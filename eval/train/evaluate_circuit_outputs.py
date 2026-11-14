#!/usr/bin/env python3
"""Train-split evaluator for multi-observation circuit diagnosis.

Run with no arguments (``bash scripts/evaluate_train.sh``).  It mirrors the
hidden test exactly, on the public training split:

1. loads the public ISCAS85-derived training instances and their exact
   answers (the complete set of minimum-cardinality diagnoses) from
   ``data/iscas85_train/``;
2. discovers every method registered on disk (``checkpoints/*/solver.json``)
   and runs it on each training instance in a fresh temporary directory,
   giving it only the faulty netlist and the observations;
3. counts the method's work as user-space instructions retired, with a
   hardware counter (Linux perf_event) that the evaluator opens and owns and
   that is inherited by every thread and process the method starts, however
   it detaches.  The method is stopped when the count reaches the fixed
   per-instance instruction budget, and only diagnoses that were already in
   the output file at a moment when the count was within budget are credited;
4. scores the raw diagnoses the method wrote.  Nothing the method reports
   about itself (validity flags, work counters, timings) is read.

Instruction counts do not depend on machine speed or load, so reruns are
exact: methods run with PYTHONHASHSEED=0 and with address-space
randomisation off.  If the kernel offers no hardware instruction counter,
the evaluator falls back to the CPU time of the process tree converted with
a fixed rate, and records ``accounting: cpu_fallback``.

The evaluator is deliberately a single self-contained file: it imports only
the standard library, never code from ``data/``, ``method/`` or ``baseline/``.

Baselines (HSD, BugAssist-style voting) are evaluator-owned: their raw
outputs on the training instances are stored in ``eval/train/baseline_outputs``
and on-disk registrations using those names are ignored.  The proposed
method key (``cfaults``) is always reported; if it is not registered, or it
produces no output at all, it receives the worst value of every metric.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import gzip
import json
import os
import platform
import resource
import shutil
import signal
import struct
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

SLICE = "train"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
TRAIN_DIR = REPO_ROOT / "data" / "iscas85_train"
CONFIG_FILE = HERE / "config.json"
BASELINE_DIR = HERE / "baseline_outputs"
RUNS_DIR = HERE / "runs"
DEFAULT_OUT = REPO_ROOT / "scoring" / "scores_train.json"

OBSERVATION_BUCKETS = (10, 20, 30, 40, 50)
FAULT_BUCKETS = (3, 5, 7)
DIR_ALIASES = {"cfaults_circuit": "cfaults", "hsd_circuit": "hsd"}
RESERVED_KEYS = ("hsd", "bugassist_vote")
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MEMORY_LIMIT_BYTES = 8 * 1024 ** 3
POLL_SECONDS = 0.01
PR_SET_DUMPABLE = 4
PR_SET_CHILD_SUBREAPER = 36
try:
    CLK_TCK = float(os.sysconf("SC_CLK_TCK"))
except (ValueError, OSError, AttributeError):
    CLK_TCK = 100.0


_LIBC = None
ADDR_NO_RANDOMIZE = 0x0040000


def _libc():
    global _LIBC
    if _LIBC is None:
        _LIBC = ctypes.CDLL(None, use_errno=True)
    return _LIBC


def _no_aslr() -> None:
    """Turn off address-space randomisation for this process and its descendants.

    CPython's behaviour depends on object addresses in places (e.g. its method
    cache), so with randomised addresses the same program retires a slightly
    different number of instructions on every run; without, counts are exact.
    """
    try:
        libc = _libc()
        current = libc.personality(ctypes.c_ulong(0xFFFFFFFF))
        if current != -1:
            libc.personality(ctypes.c_ulong(current | ADDR_NO_RANDOMIZE))
    except (OSError, AttributeError):
        pass


def _prctl(option: int, value: int) -> bool:
    try:
        return _libc().prctl(option, value, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_json(path: Path, default=None):
    path = Path(path)
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(path.read_text())
    except (OSError, ValueError, EOFError):
        return default


def dump_json_gz(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".part")
    with gzip.GzipFile(tmp, "wb", mtime=0) as fh:
        fh.write(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    tmp.replace(path)


def load_benchmark() -> tuple[list[dict], dict[str, dict]]:
    path = TRAIN_DIR / "instances.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        instances = [json.loads(line) for line in fh if line.strip()]
    truth = load_json(TRAIN_DIR / "ground_truth.json.gz")
    if truth is None:
        raise RuntimeError(f"cannot read {TRAIN_DIR / 'ground_truth.json.gz'}")
    for inst in instances:
        if inst["id"] not in truth:
            raise RuntimeError(f"no ground truth for {inst['id']}")
    return instances, truth


def public_view(instance: dict) -> dict:
    return {"id": instance["id"], "circuit": instance["circuit"], "observations": instance["observations"]}


# --------------------------------------------------------------------------
# Work accounting: hardware instruction counter (perf_event), inherited
# --------------------------------------------------------------------------

PERF_TYPE_HARDWARE = 0
PERF_COUNT_HW_INSTRUCTIONS = 1
PERF_FORMAT_TOTAL_TIME_ENABLED = 1
PERF_FORMAT_TOTAL_TIME_RUNNING = 2
PERF_FLAG_FD_CLOEXEC = 8
_ATTR_DISABLED = 1 << 0
_ATTR_INHERIT = 1 << 1
_ATTR_EXCLUDE_KERNEL = 1 << 5
_ATTR_EXCLUDE_HV = 1 << 6
_ATTR_ENABLE_ON_EXEC = 1 << 12
_PERF_EVENT_OPEN_NR = {"x86_64": 298, "amd64": 298, "aarch64": 241, "arm64": 241}


class _PerfAttr(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("config", ctypes.c_uint64),
        ("sample_period", ctypes.c_uint64), ("sample_type", ctypes.c_uint64), ("read_format", ctypes.c_uint64),
        ("flags", ctypes.c_uint64), ("wakeup_events", ctypes.c_uint32), ("bp_type", ctypes.c_uint32),
        ("config1", ctypes.c_uint64),
    ]


def open_instruction_counter(pid: int) -> int:
    """Counter of user-space instructions retired by ``pid`` and every task it creates later.

    The counter is created disabled and is enabled by the kernel at the
    task's next exec (the method's command).  The evaluator owns it, so the
    method cannot disable or reset it (PR_TASK_PERF_EVENTS_DISABLE only
    affects counters the caller created), and ``inherit`` gives every thread
    and descendant process a child counter that is summed into this one,
    whether the descendant detaches, changes session or is re-parented.
    """
    nr = _PERF_EVENT_OPEN_NR.get(platform.machine().lower())
    if nr is None:
        raise OSError(errno.ENOSYS, "perf_event_open: unsupported architecture")
    attr = _PerfAttr()
    attr.type = PERF_TYPE_HARDWARE
    attr.size = ctypes.sizeof(_PerfAttr)
    attr.config = PERF_COUNT_HW_INSTRUCTIONS
    attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING
    attr.flags = _ATTR_DISABLED | _ATTR_INHERIT | _ATTR_EXCLUDE_KERNEL | _ATTR_EXCLUDE_HV | _ATTR_ENABLE_ON_EXEC
    libc = _libc()
    libc.syscall.restype = ctypes.c_long
    fd = libc.syscall(ctypes.c_long(nr), ctypes.byref(attr), ctypes.c_int(pid), ctypes.c_int(-1),
                      ctypes.c_int(-1), ctypes.c_ulong(PERF_FLAG_FD_CLOEXEC))
    if fd < 0:
        err = ctypes.get_errno()
        raise OSError(err, f"perf_event_open: {os.strerror(err)}")
    return int(fd)


def read_instruction_counter(fd: int) -> tuple[int, bool]:
    """(count, scaled): ``scaled`` if the kernel multiplexed the counter (estimate)."""
    value, enabled, running = struct.unpack("QQQ", os.read(fd, 24))
    if running and enabled and running < enabled:
        return int(value * enabled / running), True
    return int(value), False


# --------------------------------------------------------------------------
# Running a method on one instance
# --------------------------------------------------------------------------

# /bin/sh waits on fd 3 until the evaluator has attached the counter, then
# becomes the method's command (exec), which enables the counter.
_GATE_SCRIPT = 'read _ <&3 || exit 125; exec 3<&-; exec "$@"'


def _read_stat(pid: int):
    """(ppid, own user+system CPU seconds, start time) of a process, or None."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_bytes()
        rest = raw[raw.rindex(b")") + 2:].split()
        return int(rest[1]), (int(rest[11]) + int(rest[12])) / CLK_TCK, int(rest[19])
    except (OSError, ValueError, IndexError):
        return None


class ProcessTree:
    """Every process a method starts, however it detaches (used to stop them all).

    The evaluator is a child subreaper, so processes orphaned inside the tree
    are re-parented to it (not to init) and stay in the tree.  Membership is
    found by following parent links in /proc; each member's own CPU time is
    sampled at every poll (audit, and the fallback accounting).
    """

    def __init__(self) -> None:
        self.me = os.getpid()
        self.others: dict[int, int] = {}  # pid -> ppid for processes outside the tree
        self.reset()

    def reset(self) -> None:
        self.members: dict[int, int] = {}  # live members: pid -> start time
        self.cpu: dict[tuple[int, int], float] = {}

    def poll(self) -> None:
        try:
            listing = {int(p) for p in os.listdir("/proc") if p.isdigit()}
        except OSError:
            return
        for pid in [p for p in self.others if p not in listing]:
            del self.others[pid]
        fresh = {}
        for pid in listing:
            if pid == self.me or pid in self.members:
                continue
            if pid in self.others and self.others[pid] in listing:
                continue  # outside the tree and its parent is unchanged
            st = _read_stat(pid)
            if st is not None:
                fresh[pid] = st
        added = set()
        changed = True
        while changed:
            changed = False
            for pid, (ppid, cpu, start) in list(fresh.items()):
                if ppid == self.me or ppid in self.members:
                    self.members[pid] = start
                    self.cpu[(pid, start)] = max(self.cpu.get((pid, start), 0.0), cpu)
                    self.others.pop(pid, None)
                    added.add(pid)
                    del fresh[pid]
                    changed = True
        for pid, (ppid, _, _) in fresh.items():
            self.others[pid] = ppid
        for pid, start in list(self.members.items()):
            if pid in added:
                continue
            st = _read_stat(pid) if pid in listing else None
            if st is None or st[2] != start:
                del self.members[pid]
                continue
            self.cpu[(pid, start)] = max(self.cpu.get((pid, start), 0.0), st[1])

    def cpu_seconds(self) -> float:
        return sum(self.cpu.values())


def _reap(root_pid: int, state: dict) -> None:
    """Reap every exited child of the evaluator (the method and adopted orphans)."""
    while True:
        try:
            pid, status, usage = os.wait4(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if not pid:
            return
        cpu = usage.ru_utime + usage.ru_stime
        if pid == root_pid:
            state["root_status"] = status
            state["root_cpu"] = cpu
        else:
            state["orphan_cpu"] += cpu


def _kill_tree(tree: ProcessTree, root_pid: int, state: dict) -> None:
    try:
        os.killpg(root_pid, signal.SIGKILL)
    except OSError:
        pass
    for _ in range(300):
        tree.poll()
        live = list(tree.members)
        if not live and state.get("root_status") is not None:
            break
        for pid in live:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        _reap(root_pid, state)
        time.sleep(0.01)
    _reap(root_pid, state)


def _high_dup(fd: int) -> int:
    return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 64)


def _spawn(argv: list[str], err_fd: int, env: dict, cpu_cap_seconds: int, use_counter: bool):
    """Start ``argv`` behind a /bin/sh gate; attach the counter before it runs.

    Returns (pid, counter_fd or None, counter_error or None).  The counter is
    attached only after the child has exec-ed /bin/sh: a fresh image that
    holds none of the evaluator's memory.
    """
    _libc()  # loaded before the fork
    gate_r, gate_w = os.pipe()
    exec_r, exec_w = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.setsid()
            _no_aslr()
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_cap_seconds, cpu_cap_seconds + 1))
            except (ValueError, OSError):
                pass
            for res, value in ((resource.RLIMIT_AS, MEMORY_LIMIT_BYTES), (resource.RLIMIT_CORE, 0)):
                try:
                    resource.setrlimit(res, (value, value))
                except (ValueError, OSError):
                    pass
            os.chdir(REPO_ROOT)
            null = _high_dup(os.open(os.devnull, os.O_RDWR))
            g, x, e = _high_dup(gate_r), _high_dup(exec_w), _high_dup(err_fd)
            os.dup2(null, 0)
            os.dup2(null, 1)
            os.dup2(e, 2)
            os.dup2(g, 3)  # inheritable: the gate
            os.dup2(x, 4, inheritable=False)  # closed by the exec: tells the evaluator /bin/sh is running
            try:
                maxfd = os.sysconf("SC_OPEN_MAX")
            except (ValueError, OSError):
                maxfd = 65536
            os.closerange(5, max(maxfd, 5))
            os.execve("/bin/sh", ["sh", "-c", _GATE_SCRIPT, "sh", *argv], env)
        except BaseException:
            pass
        os._exit(127)
    os.close(gate_r)
    os.close(exec_w)
    while True:
        try:
            os.read(exec_r, 1)  # EOF once /bin/sh runs (or the child died)
            break
        except InterruptedError:
            continue
    os.close(exec_r)
    counter, error = None, None
    if use_counter:
        try:
            counter = open_instruction_counter(pid)
        except OSError as exc:
            error = str(exc)[:200]
    try:
        os.write(gate_w, b"go\n")
    except OSError:
        pass
    os.close(gate_w)
    return pid, counter, error


class OutputObserver:
    """What the method has written, as observed by the evaluator while it runs.

    Every observation is kept (committed) only if the counted work, read
    *after* the observation, is within the budget, so every committed byte was
    in the file at a moment when the method's work was within budget.  A file
    of up to FULL_READ_BYTES is re-read whole at every poll: if the method
    rewrote what was already committed (truncate and rewrite, replace,
    in-place edit), observation restarts from the new content and the earlier
    trace is dropped.  Larger files are read append-only.
    """

    FULL_READ_BYTES = 4 * 1024 * 1024

    def __init__(self, path: Path) -> None:
        self.path = path
        self.buf = bytearray()
        self.lines = 0  # newline count in buf
        self.ino = None
        self.trace: list[list[int]] = []  # [count, complete lines] whenever the committed line count grows
        self.truncated = False
        self.rewritten = False
        self.pending = None

    def observe(self) -> None:
        self.pending = None
        try:
            with open(self.path, "rb") as fh:
                st = os.fstat(fh.fileno())
                size = min(st.st_size, MAX_OUTPUT_BYTES)
                n = len(self.buf)
                same_file = st.st_ino == self.ino
                if size <= self.FULL_READ_BYTES:
                    data = fh.read(size)
                    if same_file and len(data) >= n and data[:n] == self.buf:
                        restart, chunk = False, data[n:]
                    else:
                        restart, chunk = True, data
                elif same_file and size >= n:
                    fh.seek(n)
                    restart, chunk = False, fh.read(size - n)
                else:
                    restart, chunk = True, fh.read(size)
        except OSError:
            return
        self.pending = (restart, st.st_ino, chunk, st.st_size > MAX_OUTPUT_BYTES)

    def commit(self, count: int) -> None:
        if self.pending is None:
            return
        restart, ino, chunk, over = self.pending
        self.pending = None
        self.ino = ino
        if restart:
            if self.buf:
                self.rewritten = True
            self.buf = bytearray()
            self.lines = 0
            self.trace = []
        if chunk:
            self.buf += chunk
            self.lines += chunk.count(b"\n")
        if over:
            self.truncated = True
        if self.lines and (not self.trace or self.trace[-1][1] != self.lines):
            self.trace.append([int(count), self.lines])


def _parse_committed(buf: bytes, trace: list[list[int]]) -> tuple[list, list[list[int]]]:
    """Complete (newline-terminated) non-blank lines, and the trace in those units."""
    parts = bytes(buf).split(b"\n")[:-1]
    parsed: list = []
    prefix = [0]
    for line in parts:
        if line.strip():
            try:
                parsed.append(json.loads(line))
            except (ValueError, UnicodeDecodeError):
                parsed.append({"__malformed__": True})
        prefix.append(len(parsed))
    line_trace: list[list[int]] = []
    for count, n in trace:
        k = prefix[min(n, len(parts))]
        if not line_trace or line_trace[-1][1] != k:
            line_trace.append([int(count), k])
    return parsed, line_trace


_TREE: ProcessTree | None = None


def run_command_on_instance(command: list[str], instance: dict, run: dict) -> dict:
    """Run one method on one instance under the instruction budget ``run['cap']``."""
    global _TREE
    if _TREE is None:
        _TREE = ProcessTree()
    tree = _TREE
    tree.reset()
    tmp = Path(tempfile.mkdtemp(prefix="diag_eval_"))
    inst_path = tmp / "instance.json"
    out_path = tmp / "diagnoses.jsonl"
    err_path = tmp / "stderr.log"
    inst_path.write_text(json.dumps(public_view(instance)))
    argv = [str(a).replace("{instance}", str(inst_path)).replace("{output}", str(out_path)) for a in command]
    cap = int(run["cap"])
    wall_limit = float(run["wall_limit_seconds"])
    rate = float(run["fallback_instructions_per_cpu_second"])
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"  # deterministic hashing: exact reruns of Python methods
    observer = OutputObserver(out_path)
    record = {"id": instance["id"], "status": "ok", "instructions": 0, "cpu_seconds": 0.0, "wall_seconds": 0.0}
    state = {"root_status": None, "root_cpu": 0.0, "orphan_cpu": 0.0}
    counter = None
    scaled = False
    start = time.monotonic()
    try:
        with err_path.open("wb") as err:
            pid, counter, counter_error = _spawn(argv, err.fileno(), env, int(wall_limit) + 5, run["accounting"] == "perf")
        use_perf = counter is not None
        record["accounting"] = "perf" if use_perf else "cpu_fallback"
        if counter_error:
            record["counter_error"] = counter_error

        def count() -> int:
            nonlocal scaled
            if use_perf:
                value, was_scaled = read_instruction_counter(counter)
                scaled = scaled or was_scaled
                return value
            return int(max(tree.cpu_seconds(), state["root_cpu"] + state["orphan_cpu"]) * rate)

        stopped = None
        while True:
            tree.poll()
            _reap(pid, state)
            observer.observe()
            work = count()  # read after the output: every observed byte was written with at most this much work
            if work > cap:
                stopped = "budget"
                break
            observer.commit(work)
            if state["root_status"] is not None:
                break
            if time.monotonic() - start > wall_limit:
                stopped = "wall_limit"
                break
            if tree.cpu_seconds() > wall_limit:
                stopped = "cpu_guard"
                break
            time.sleep(POLL_SECONDS)
        _kill_tree(tree, pid, state)  # whatever the method left running, however detached
        if state["root_status"] is None:
            try:
                _, status, usage = os.wait4(pid, 0)
                state["root_status"], state["root_cpu"] = status, usage.ru_utime + usage.ru_stime
            except ChildProcessError:
                state["root_status"] = 0
        if stopped is None:  # the command exited: observe the final output
            observer.observe()
            work = count()
            if work <= cap:
                observer.commit(work)
            else:
                stopped = "budget"
        record["instructions"] = int(count())
        status = state["root_status"]
        record["wall_seconds"] = time.monotonic() - start
        record["cpu_seconds"] = max(state["root_cpu"] + state["orphan_cpu"], tree.cpu_seconds())
        record["tree_processes"] = len(tree.cpu)
        if stopped:
            record["status"] = stopped
        elif os.WIFSIGNALED(status):
            record["status"] = f"signal_{os.WTERMSIG(status)}"
        elif os.WEXITSTATUS(status) != 0:
            record["status"] = f"exit_{os.WEXITSTATUS(status)}"
    except OSError as exc:
        record["status"] = "launch_error"
        record["error"] = str(exc)[:500]
    finally:
        if counter is not None:
            try:
                os.close(counter)
            except OSError:
                pass
    record["diagnoses"], record["line_trace"] = _parse_committed(observer.buf, observer.trace)
    record["truncated"] = observer.truncated
    record["rewritten"] = observer.rewritten
    record["counter_scaled"] = scaled
    try:
        record["stderr_tail"] = err_path.read_bytes()[-1500:].decode(errors="replace")
    except OSError:
        record["stderr_tail"] = ""
    shutil.rmtree(tmp, ignore_errors=True)
    return record


def detect_accounting() -> tuple[str, str | None]:
    """'perf' if a hardware instruction counter can be attached to a child and counts, else 'cpu_fallback'."""
    try:
        with open(os.devnull, "wb") as err:
            pid, counter, error = _spawn(["true"], err.fileno(), dict(os.environ), 10, True)
        os.waitpid(pid, 0)
    except OSError as exc:
        return "cpu_fallback", str(exc)[:200]
    if counter is None:
        return "cpu_fallback", error
    try:
        value, _ = read_instruction_counter(counter)
    finally:
        os.close(counter)
    if value <= 0:
        return "cpu_fallback", "instruction counter attached but counted nothing"
    return "perf", None


def valid_registration(spec) -> list[str] | None:
    if not isinstance(spec, dict):
        return None
    command = spec.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        return None
    joined = " ".join(command)
    if "{instance}" not in joined or "{output}" not in joined:
        return None
    return command


def discover_methods(result_root: Path) -> dict[str, list[str] | None]:
    found: dict[str, list[str] | None] = {}
    for path in sorted(Path(result_root).glob("*/solver.json")):
        key = DIR_ALIASES.get(path.parent.name, path.parent.name)
        if key.startswith("_") or key in RESERVED_KEYS:
            continue  # baselines are evaluator-owned
        found[key] = valid_registration(load_json(path))
    return found


def run_method(command: list[str] | None, instances: list[dict], run: dict, log_name: str) -> list[dict]:
    records = []
    for idx, inst in enumerate(instances):
        if command is None:
            records.append({"id": inst["id"], "status": "not_registered", "instructions": 0, "cpu_seconds": 0.0,
                            "wall_seconds": 0.0, "diagnoses": [], "line_trace": [], "truncated": False})
            continue
        rec = run_command_on_instance(command, inst, run)
        records.append(rec)
        print(f"[{SLICE}] {log_name} {idx + 1}/{len(instances)} {rec['status']} "
              f"instr={rec['instructions'] / 1e9:.2f}G cpu={rec['cpu_seconds']:.2f}s lines={len(rec['diagnoses'])}",
              file=sys.stderr, flush=True)
    return records


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def credited_lines(record: dict, budget: float) -> list:
    """Lines that were in the output file at a moment when the counted work was <= budget."""
    n = 0
    for count, k in record.get("line_trace") or []:
        if count <= budget and k > n:
            n = k
    return list(record.get("diagnoses") or [])[:n]


def score_instance(record: dict, inst: dict, truth_entry: dict, budget: float) -> dict:
    truth = {frozenset(d) for d in truth_entry["diagnoses"]}
    optimum = int(truth_entry["optimum"])
    gate_names = {g["name"] for g in inst["circuit"]["gates"]}
    kinds: Counter = Counter()
    seen: set[frozenset] = set()
    sound = 0
    first = None
    lines = credited_lines(record, budget)
    for diag in lines:
        if not isinstance(diag, list) or not all(isinstance(x, str) for x in diag):
            kinds["malformed"] += 1
            continue
        if len(set(diag)) != len(diag) or any(x not in gate_names for x in diag):
            kinds["malformed"] += 1
            continue
        fdiag = frozenset(diag)
        if first is None:
            first = fdiag
        if fdiag in seen:
            kinds["duplicate"] += 1
            continue
        seen.add(fdiag)
        if fdiag in truth:
            sound += 1
        elif len(fdiag) > optimum:
            kinds["not_minimum"] += 1
        else:
            kinds["invalid"] += 1
    over_limit = bool(record.get("truncated"))
    if over_limit:
        kinds["over_limit"] += 1
    unsound = sum(v for k, v in kinds.items() if k != "over_limit") > 0
    credited = not unsound and not over_limit
    localized = credited and sound == len(truth)
    recall = (sound / len(truth)) if credited else 0.0
    injected = set(inst["faults"])
    f1 = 0.0
    exact = False
    if credited and first is not None and first in truth:
        tp = len(first & injected)
        prec = tp / len(first) if first else 0.0
        rec = tp / len(injected) if injected else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        exact = set(first) == injected
    return {
        "localized": localized,
        "recall": recall,
        "unsound": unsound,
        "sound_nonempty": credited and sound > 0,
        "kinds": dict(kinds),
        "selected_fault_f1": f1,
        "exact": exact,
        "status": record.get("status", "missing"),
        "cpu_seconds": float(record.get("cpu_seconds", 0.0)),
        "instructions": float(record.get("instructions", 0.0)),
        "lines": len(lines),
        "true_count": len(truth),
    }


def worst_values(fractions: dict[str, float]) -> dict:
    return {
        "iscas85_localisation": {"localized_rate": 0.0, "min_diagnosis_recall": 0.0},
        "diagnosis_quality": {"unsound_output_rate": 100.0},
        "observation_scaling": {f"localized_rate_obs{m}": 0.0 for m in OBSERVATION_BUCKETS},
        "fault_scaling": {f"localized_rate_f{k}": 0.0 for k in FAULT_BUCKETS},
        "scale_stress": {"localized_rate_stress": 0.0, "min_diagnosis_recall_stress": 0.0},
        "runtime_profile": {f"localized_rate_{name}": 0.0 for name in fractions},
    }


def aggregate(records: list[dict], instances: list[dict], truth: dict, budget: float,
              fractions: dict[str, float]) -> dict:
    by_id = {r["id"]: r for r in records}
    rows = []
    for inst in instances:
        rec = by_id.get(inst["id"], {"id": inst["id"], "status": "missing", "diagnoses": [], "line_trace": []})
        row = score_instance(rec, inst, truth[inst["id"]], budget)
        row["profile"] = {name: score_instance(rec, inst, truth[inst["id"]], frac * budget)["localized"]
                          for name, frac in fractions.items()}
        row["observation_count"] = inst["observation_count"]
        row["fault_count"] = inst["fault_count"]
        row["tier"] = inst.get("tier", "base")
        rows.append(row)
    all_rows = rows
    produced_any = any(len(by_id.get(inst["id"], {}).get("diagnoses") or []) > 0 for inst in instances)
    kinds = Counter()
    for r in all_rows:
        kinds.update(r["kinds"])
    stress = [r for r in all_rows if r["tier"] == "stress"]
    rows = [r for r in all_rows if r["tier"] == "base"]  # main/observation/fault experiments: base tier
    n = len(rows)
    stopped = ("budget", "wall_limit", "cpu_guard")

    def rate(flag_rows, key):
        return 100.0 * sum(1 for r in flag_rows if r[key]) / max(1, len(flag_rows))

    loc = {
        "localized_rate": rate(rows, "localized"),
        "min_diagnosis_recall": 100.0 * sum(r["recall"] for r in rows) / max(1, n),
        "localized_count": sum(1 for r in rows if r["localized"]),
        "total_instances": n,
        "budget_stop_count": sum(1 for r in rows if r["status"] in stopped),
        "error_count": sum(1 for r in rows if r["status"] not in ("ok",) + stopped),
        "selected_fault_f1": 100.0 * sum(r["selected_fault_f1"] for r in rows) / max(1, n),
        "exact_fault_set_rate": rate(rows, "exact"),
        "audit_mean_giga_instructions": sum(r["instructions"] for r in rows) / max(1, n) / 1e9,
        "audit_avg_cpu_seconds": sum(r["cpu_seconds"] for r in rows) / max(1, n),
    }
    quality = {  # constraint over every instance (both tiers)
        "unsound_output_rate": rate(all_rows, "unsound"),
        "sound_output_rate": rate(all_rows, "sound_nonempty"),
        "unsound_count": sum(1 for r in all_rows if r["unsound"]),
        "invalid_count": kinds.get("invalid", 0),
        "not_minimum_count": kinds.get("not_minimum", 0),
        "malformed_count": kinds.get("malformed", 0),
        "duplicate_count": kinds.get("duplicate", 0),
        "over_limit_count": kinds.get("over_limit", 0),
    }
    obs = {}
    for m in OBSERVATION_BUCKETS:
        bucket = [r for r in rows if r["observation_count"] == m]
        obs[f"localized_rate_obs{m}"] = rate(bucket, "localized")
        obs[f"min_diagnosis_recall_obs{m}"] = 100.0 * sum(r["recall"] for r in bucket) / max(1, len(bucket))
        obs[f"localized_count_obs{m}"] = sum(1 for r in bucket if r["localized"])
    faults = {}
    for k in FAULT_BUCKETS:
        bucket = [r for r in rows if r["fault_count"] == k]
        faults[f"localized_rate_f{k}"] = rate(bucket, "localized")
        faults[f"min_diagnosis_recall_f{k}"] = 100.0 * sum(r["recall"] for r in bucket) / max(1, len(bucket))
        faults[f"localized_count_f{k}"] = sum(1 for r in bucket if r["localized"])
    scale = {
        "localized_rate_stress": rate(stress, "localized"),
        "min_diagnosis_recall_stress": 100.0 * sum(r["recall"] for r in stress) / max(1, len(stress)),
        "localized_count_stress": sum(1 for r in stress if r["localized"]),
        "total_instances_stress": len(stress),
        "budget_stop_count_stress": sum(1 for r in stress if r["status"] in stopped),
    }
    for k in sorted({r["fault_count"] for r in stress}):
        bucket = [r for r in stress if r["fault_count"] == k]
        scale[f"localized_rate_stress_f{k}"] = rate(bucket, "localized")
    profile = {}
    for name in fractions:
        profile[f"localized_rate_{name}"] = 100.0 * sum(1 for r in all_rows if r["profile"][name]) / max(1, len(all_rows))
        profile[f"localized_count_{name}"] = sum(1 for r in all_rows if r["profile"][name])
    profile["localized_rate_full_budget"] = rate(all_rows, "localized")
    profile["total_instances_all"] = len(all_rows)
    result = {
        "iscas85_localisation": loc,
        "diagnosis_quality": quality,
        "observation_scaling": obs,
        "fault_scaling": faults,
        "scale_stress": scale,
        "runtime_profile": profile,
    }
    tampered = any(r.get("status") == "tampered" for r in records)
    if tampered or not produced_any:
        # A run that produced nothing at all is a failed run: worst value of every metric.
        for exp, metrics in worst_values(fractions).items():
            result[exp].update(metrics)
        result["iscas85_localisation"]["failed_run"] = 1
    else:
        result["iscas85_localisation"]["failed_run"] = 0
    result["iscas85_localisation"]["tamper_detected"] = int(tampered)
    return result


def write_scores(per_method: dict[str, dict], out: Path, extra: dict) -> dict:
    experiments: dict[str, dict] = {}
    for method, result in sorted(per_method.items()):
        for exp, metrics in result.items():
            experiments.setdefault(exp, {"results": {}})["results"][method] = metrics
    scores = {"experiments": experiments, **extra}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")
    return scores


def save_runs(name: str, payload: dict) -> None:
    try:
        dump_json_gz(RUNS_DIR / f"{name}.json.gz", payload)
    except OSError:
        pass


def run_settings(config: dict, accounting: str) -> dict:
    budget = int(float(config["instruction_budget"]))
    return {
        "instruction_budget": budget,
        "cap": budget,
        "budget_fractions": {k: float(v) for k, v in config["budget_fractions"].items()},
        "wall_limit_seconds": float(config["wall_limit_seconds"]),
        "fallback_instructions_per_cpu_second": float(config["fallback_instructions_per_cpu_second"]),
        "accounting": accounting,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    # Build-time and development helpers; never needed for scoring.
    parser.add_argument("--store-baseline", default=None, help="run a baseline command and store its raw outputs")
    parser.add_argument("--command-json", default=None)
    parser.add_argument("--rescore", action="store_true",
                        help="score the raw outputs saved in eval/train/runs instead of running the methods")
    parser.add_argument("--instruction-cap", type=float, default=None,
                        help="run methods up to this many instructions per instance (budget probe); "
                             "scores are still computed at the configured budget when it is lower")
    parser.add_argument("--methods", default=None, help="comma-separated subset of registered methods")
    parser.add_argument("--runs-name", default=None, help="save raw outputs as runs/<name>.json.gz (single method)")
    args = parser.parse_args()

    _prctl(PR_SET_CHILD_SUBREAPER, 1)  # adopt every orphan the method leaves behind

    config = json.loads(CONFIG_FILE.read_text())
    accounting, accounting_note = ("rescore", None) if args.rescore else detect_accounting()
    run = run_settings(config, accounting)
    if args.instruction_cap:
        run["cap"] = int(args.instruction_cap)
    budget, fractions = min(run["instruction_budget"], run["cap"]), run["budget_fractions"]
    print(f"[{SLICE}] accounting={accounting} {accounting_note or ''} budget={budget / 1e9:.1f}G "
          f"cap={run['cap'] / 1e9:.1f}G instructions per instance", file=sys.stderr, flush=True)
    instances, truth = load_benchmark()

    if args.store_baseline:
        command = valid_registration({"command": json.loads(args.command_json)})
        records = run_method(command, instances, run, args.store_baseline)
        dump_json_gz(BASELINE_DIR / f"{args.store_baseline}.json.gz",
                     {"method": args.store_baseline, "run": run, "records": records})
        return

    registered = discover_methods(REPO_ROOT / "checkpoints")
    for required in config.get("required_methods", ["cfaults"]):
        registered.setdefault(required, None)
    if args.methods:
        wanted = {m.strip() for m in args.methods.split(",") if m.strip()}
        registered = {k: v for k, v in registered.items() if k in wanted}

    per_method: dict[str, dict] = {}
    run_payloads: dict[str, dict] = {}
    for key, command in sorted(registered.items()):
        if args.rescore:
            saved = load_json(RUNS_DIR / f"{key}.json.gz") or {}
            per_method[key] = aggregate(saved.get("records", []), instances, truth, budget, fractions)
            continue
        records = run_method(command, instances, run, key)
        per_method[key] = aggregate(records, instances, truth, budget, fractions)
        run_payloads[key] = {"method": key, "run": run, "command": command, "records": records}
    for key, payload in run_payloads.items():
        save_runs(args.runs_name if (args.runs_name and len(run_payloads) == 1) else key, payload)

    for key in RESERVED_KEYS:
        stored = load_json(BASELINE_DIR / f"{key}.json.gz")
        if stored is None:
            continue
        stored_cap = float(stored.get("run", {}).get("cap", budget))
        per_method[key] = aggregate(stored.get("records", []), instances, truth, min(budget, stored_cap), fractions)

    extra = {
        "_evaluation": {
            "slice": SLICE,
            "instance_count": len(instances),
            "budget": {"instruction_budget": budget, "budget_fractions": fractions,
                       "wall_limit_seconds": run["wall_limit_seconds"], "accounting": accounting,
                       "unit": "user-space instructions retired by the method's whole process tree"},
            "methods_run": sorted(registered),
            "baselines_from": "eval/train/baseline_outputs (evaluator-owned, fixed)",
        }
    }
    scores = write_scores(per_method, args.out, extra)
    print(json.dumps(scores["experiments"]["iscas85_localisation"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
