#!/usr/bin/env python3
"""Hidden-test evaluator for multi-observation circuit diagnosis.

Run with no arguments (``bash scripts/evaluate_test.sh``).  It

1. loads the hidden ISCAS85-derived test instances and their exact answers
   (the complete set of minimum-cardinality diagnoses) from ``eval/test/``;
2. calibrates the per-instance CPU budget to the speed of this machine with a
   fixed, evaluator-owned workload;
3. discovers every method registered on disk (``checkpoints/*/solver.json``)
   and runs it on each hidden instance in a fresh temporary directory, under
   the CPU budget, giving it only the faulty netlist and the observations;
4. scores the raw diagnoses the method wrote.  Nothing the method reports
   about itself (validity flags, work counters, timings) is read.

The CPU budget covers every process the method starts: the evaluator is a
child subreaper and samples the CPU time of the whole process tree from
/proc, so detached or auto-reaped workers are counted (and killed) too.
While method code runs, ``eval/test`` is unreadable and the evaluator's own
memory is not readable by other processes; a method that changes the
permissions, owner, location or contents of ``eval/test`` is recorded as
tampering and its whole run is scored as failed.

The evaluator is deliberately a single self-contained file: it imports only
the standard library (and PySAT for the calibration workload), never code
from ``data/``, ``method/`` or ``baseline/``.

Baselines (HSD, BugAssist-style voting) are evaluator-owned: their raw
outputs on the hidden instances are stored in ``eval/test/baseline_outputs``
and on-disk registrations using those names are ignored.  The proposed
method key (``cfaults``) is always reported; if it is not registered, or it
produces no output at all, it receives the worst value of every metric.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

SLICE = "test"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
BENCHMARK_FILE = HERE / "hidden_benchmark.json"
CONFIG_FILE = HERE / "config.json"
BASELINE_DIR = HERE / "baseline_outputs"
RUNS_DIR = HERE / "runs"
DEFAULT_OUT = REPO_ROOT / "scoring" / "scores_test.json"

OBSERVATION_BUCKETS = (10, 20, 30, 40, 50)
FAULT_BUCKETS = (1, 3, 5)
DIR_ALIASES = {"cfaults_circuit": "cfaults", "hsd_circuit": "hsd"}
RESERVED_KEYS = ("hsd", "bugassist_vote")
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MEMORY_LIMIT_BYTES = 8 * 1024 ** 3
POLL_SECONDS = 0.02
PR_SET_DUMPABLE = 4
PR_SET_CHILD_SUBREAPER = 36
try:
    CLK_TCK = float(os.sysconf("SC_CLK_TCK"))
except (ValueError, OSError, AttributeError):
    CLK_TCK = 100.0


def over_budget(cpu_seconds: float, cpu_limit: float) -> bool:
    """The single budget rule: measured CPU of the whole process tree."""
    return cpu_seconds > 1.1 * cpu_limit + 1.0


def _prctl(option: int, value: int) -> bool:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(option, value, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return default


def load_benchmark() -> tuple[list[dict], dict[str, dict]]:
    data = json.loads(BENCHMARK_FILE.read_text())
    instances = data["instances"]
    truth = data["ground_truth"]
    for inst in instances:
        if inst["id"] not in truth:
            raise RuntimeError(f"no ground truth for {inst['id']}")
    return instances, truth


def public_view(instance: dict) -> dict:
    return {"id": instance["id"], "circuit": instance["circuit"], "observations": instance["observations"]}


# --------------------------------------------------------------------------
# Machine-speed calibration (evaluator-owned workload)
# --------------------------------------------------------------------------


def _guarded(op: str, out: int, ins: list[int], h: int) -> list[list[int]]:
    g = -h
    if op == "BUF":
        return [[g, -out, ins[0]], [g, out, -ins[0]]]
    if op == "NOT":
        return [[g, -out, -ins[0]], [g, out, ins[0]]]
    if op == "AND":
        return [[g, out, *[-x for x in ins]], *[[g, -out, x] for x in ins]]
    if op == "NAND":
        return [[g, -out, *[-x for x in ins]], *[[g, out, x] for x in ins]]
    if op == "OR":
        return [[g, -out, *ins], *[[g, out, -x] for x in ins]]
    if op == "NOR":
        return [[g, out, *ins], *[[g, -out, -x] for x in ins]]
    if op == "XOR":
        a, b = ins
        return [[g, -a, -b, -out], [g, -a, b, out], [g, a, -b, out], [g, a, b, -out]]
    raise ValueError(op)


def _calibration_once(instances: list[dict]) -> float:
    from pysat.examples.rc2 import RC2  # imported (and cached) before timing starts
    from pysat.formula import WCNF

    start = time.process_time()
    for inst in instances:
        circuit = inst["circuit"]
        nv = 0
        health = {}
        for gate in circuit["gates"]:
            nv += 1
            health[gate["name"]] = nv
        wcnf = WCNF()
        for obs in inst["observations"]:
            var = {}
            for name in circuit["inputs"]:
                nv += 1
                var[name] = nv
                wcnf.append([nv if obs["inputs"][name] else -nv])
            for gate in circuit["gates"]:
                nv += 1
                var[gate["name"]] = nv
            for gate in circuit["gates"]:
                for clause in _guarded(gate["op"], var[gate["name"]], [var[x] for x in gate["inputs"]], health[gate["name"]]):
                    wcnf.append(clause)
            for name, value in obs["expected_outputs"].items():
                wcnf.append([var[name] if value else -var[name]])
        for h in health.values():
            wcnf.append([h], weight=1)
        with RC2(wcnf) as rc2:
            rc2.compute()
    return time.process_time() - start


def measure_calibration(instances: list[dict], ids: list[str], repeats: int = 5) -> float | None:
    """Fastest of several runs of a fixed workload: robust to transient interference."""
    chosen = [inst for inst in instances if inst["id"] in set(ids)]
    if not chosen:
        return None
    try:
        import gc

        import pysat.examples.rc2  # noqa: F401  warm import outside the timed region
        _calibration_once(chosen[:1])  # warm-up
        gc.collect()
        times = [_calibration_once(chosen) for _ in range(repeats)]
    except Exception:  # PySAT missing or broken: fall back to the nominal budget
        return None
    return min(times)


def cpu_budget(config: dict, instances: list[dict]) -> dict:
    nominal = float(config["cpu_limit_seconds"])
    calib = config.get("calibration", {})
    ref = calib.get("reference_cpu_seconds")
    measured = measure_calibration(instances, calib.get("instance_ids", [])) if ref else None
    if measured and ref:
        factor = min(max(measured / float(ref), 0.67), 1.5)
    else:
        factor = 1.0
    return {
        "nominal_cpu_limit_seconds": nominal,
        "calibration_reference_cpu_seconds": ref,
        "calibration_measured_cpu_seconds": measured,
        "speed_factor": factor,
        "cpu_limit_seconds": nominal * factor,
    }


# --------------------------------------------------------------------------
# Running a method on one instance
# --------------------------------------------------------------------------


def _parse_output(raw: bytes) -> tuple[list, bool]:
    truncated = len(raw) > MAX_OUTPUT_BYTES
    raw = raw[:MAX_OUTPUT_BYTES]
    lines = raw.split(b"\n")
    complete = lines[:-1]  # the last fragment is unterminated (or empty)
    parsed = []
    for line in complete:
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            parsed.append({"__malformed__": True})
    return parsed, truncated


def _read_stat(pid: int):
    """(ppid, own user+system CPU seconds, start time) of a process, or None."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_bytes()
        rest = raw[raw.rindex(b")") + 2:].split()
        return int(rest[1]), (int(rest[11]) + int(rest[12])) / CLK_TCK, int(rest[19])
    except (OSError, ValueError, IndexError):
        return None


class ProcessTree:
    """Every process a method starts, however it detaches, and its CPU time.

    The evaluator is a child subreaper, so processes orphaned inside the tree
    are re-parented to it (not to init) and stay in the tree.  Membership is
    found by following parent links in /proc; each member's own CPU time is
    sampled at every poll and the last sample is kept after it exits, so CPU
    spent in detached or auto-reaped workers is counted.
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


_TREE: ProcessTree | None = None


def run_command_on_instance(command: list[str], instance: dict, cpu_limit: float) -> dict:
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
    soft = max(1, int(math.ceil(cpu_limit)))
    wall_limit = 2.0 * cpu_limit + 10.0

    def limit_child() -> None:
        os.setsid()
        try:
            hard_cap = resource.getrlimit(resource.RLIMIT_CPU)[1]
            hard = soft + 1 if hard_cap == resource.RLIM_INFINITY else min(soft + 1, hard_cap)
            resource.setrlimit(resource.RLIMIT_CPU, (min(soft, hard), hard))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # no core files from killed methods
        except (ValueError, OSError):
            pass

    record = {"id": instance["id"], "status": "ok", "cpu_seconds": 0.0, "wall_seconds": 0.0}
    start = time.monotonic()
    try:
        with err_path.open("wb") as err:
            proc = subprocess.Popen(
                argv,
                cwd=str(REPO_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
                preexec_fn=limit_child,
            )
            state = {"root_status": None, "root_cpu": 0.0, "orphan_cpu": 0.0}
            stopped = None
            while True:
                tree.poll()
                _reap(proc.pid, state)
                if state["root_status"] is not None:
                    break
                if tree.cpu_seconds() > soft:
                    stopped = "cpu_limit"  # the whole tree used the per-process CPU allowance
                    break
                if time.monotonic() - start > wall_limit:
                    stopped = "wall_limit"
                    break
                time.sleep(POLL_SECONDS)
            _kill_tree(tree, proc.pid, state)  # stray helpers of the method, however detached
            if state["root_status"] is None:
                try:
                    _, status, usage = os.wait4(proc.pid, 0)
                    state["root_status"], state["root_cpu"] = status, usage.ru_utime + usage.ru_stime
                except ChildProcessError:
                    state["root_status"] = 0
            proc.returncode = 0  # already reaped with wait4
        status = state["root_status"]
        record["wall_seconds"] = time.monotonic() - start
        record["cpu_seconds"] = max(state["root_cpu"] + state["orphan_cpu"], tree.cpu_seconds())
        record["tree_processes"] = len(tree.cpu)
        if stopped:
            record["status"] = stopped
        elif os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            record["status"] = "cpu_limit" if sig in (signal.SIGXCPU, signal.SIGKILL) else f"signal_{sig}"
        elif os.WEXITSTATUS(status) != 0:
            record["status"] = f"exit_{os.WEXITSTATUS(status)}"
    except (OSError, subprocess.SubprocessError) as exc:
        record["status"] = "launch_error"
        record["error"] = str(exc)[:500]
    raw = out_path.read_bytes() if out_path.exists() else b""
    record["diagnoses"], record["truncated"] = _parse_output(raw)
    try:
        record["stderr_tail"] = err_path.read_bytes()[-1500:].decode(errors="replace")
    except OSError:
        record["stderr_tail"] = ""
    shutil.rmtree(tmp, ignore_errors=True)
    return record


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


class HiddenDataGuard:
    """Make eval/test unreadable while third-party method code runs.

    Method code runs as the same user, so it could chmod the directory back.
    Any change to the directory's permissions, owner, inode or contents changes
    its (inode, device, mode, ctime) fingerprint, which no unprivileged process
    can restore; ``tampered()`` is checked after every method process.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.mode = None
        self.fingerprint = None

    def _fingerprint(self):
        try:
            st = os.stat(self.path)
            return (st.st_ino, st.st_dev, st.st_mode & 0o7777, st.st_ctime_ns, st.st_uid, st.st_gid)
        except OSError:
            return None

    def _lock(self) -> None:
        try:
            os.chmod(self.path, 0)
        except OSError:
            pass
        self.fingerprint = self._fingerprint()

    def tampered(self) -> bool:
        """True if the directory changed since it was locked; it is then locked again."""
        if self.mode is None:
            return False
        if self._fingerprint() == self.fingerprint:
            return False
        self._lock()
        return True

    def __enter__(self):
        try:
            self.mode = self.path.stat().st_mode & 0o7777
            self._lock()
        except OSError:
            self.mode = None
        self._old = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                self._old[sig] = signal.signal(sig, self._restore_and_exit)
            except (ValueError, OSError):
                pass
        return self

    def _restore_and_exit(self, signum, frame):
        self.restore()
        raise SystemExit(128 + signum)

    def restore(self) -> None:
        if self.mode is not None:
            try:
                os.chmod(self.path, self.mode)
            except OSError:
                pass
            self.mode = None

    def __exit__(self, *exc):
        self.restore()
        for sig, old in self._old.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError):
                pass
        return False


def run_method(command: list[str] | None, instances: list[dict], cpu_limit: float, log_name: str,
               guard: HiddenDataGuard | None = None) -> list[dict]:
    records = []
    tampered = False
    for idx, inst in enumerate(instances):
        if command is None or tampered:
            records.append({"id": inst["id"], "status": "tampered" if tampered else "not_registered",
                            "cpu_seconds": 0.0, "wall_seconds": 0.0, "diagnoses": [], "truncated": False})
            continue
        rec = run_command_on_instance(command, inst, cpu_limit)
        if guard is not None and guard.tampered():
            # The method touched the hidden directory: its whole run is failed.
            tampered = True
            rec = {"id": inst["id"], "status": "tampered", "cpu_seconds": rec["cpu_seconds"],
                   "wall_seconds": rec["wall_seconds"], "diagnoses": [], "truncated": False}
        records.append(rec)
        print(f"[{SLICE}] {log_name} {idx + 1}/{len(instances)} {rec['status']} cpu={rec['cpu_seconds']:.2f}s "
              f"lines={len(rec['diagnoses'])}", file=sys.stderr, flush=True)
    return records


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def score_instance(record: dict, inst: dict, truth_entry: dict, cpu_limit: float) -> dict:
    truth = {frozenset(d) for d in truth_entry["diagnoses"]}
    optimum = int(truth_entry["optimum"])
    gate_names = {g["name"] for g in inst["circuit"]["gates"]}
    kinds: Counter = Counter()
    seen: set[frozenset] = set()
    sound = 0
    first = None
    for diag in record.get("diagnoses", []):
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
    over_limit = bool(record.get("truncated")) or over_budget(float(record.get("cpu_seconds", 0.0)), cpu_limit)
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
        "lines": len(record.get("diagnoses", [])),
        "true_count": len(truth),
    }


def worst_values() -> dict:
    out = {
        "iscas85_localisation": {"localized_rate": 0.0, "min_diagnosis_recall": 0.0},
        "diagnosis_quality": {"unsound_output_rate": 100.0},
        "observation_scaling": {f"localized_rate_obs{m}": 0.0 for m in OBSERVATION_BUCKETS},
        "fault_scaling": {f"localized_rate_f{k}": 0.0 for k in FAULT_BUCKETS},
        "scale_stress": {"localized_rate_stress": 0.0, "min_diagnosis_recall_stress": 0.0},
    }
    return out


def aggregate(records: list[dict], instances: list[dict], truth: dict, cpu_limit: float) -> dict:
    by_id = {r["id"]: r for r in records}
    rows = []
    for inst in instances:
        rec = by_id.get(inst["id"], {"id": inst["id"], "status": "missing", "diagnoses": []})
        row = score_instance(rec, inst, truth[inst["id"]], cpu_limit)
        row["observation_count"] = inst["observation_count"]
        row["fault_count"] = inst["fault_count"]
        row["tier"] = inst.get("tier", "base")
        rows.append(row)
    all_rows = rows
    produced_any = any(r["lines"] > 0 for r in all_rows)
    kinds = Counter()
    for r in all_rows:
        kinds.update(r["kinds"])
    stress = [r for r in all_rows if r["tier"] == "stress"]
    rows = [r for r in all_rows if r["tier"] == "base"]  # main/observation/fault experiments: base tier
    n = len(rows)

    def rate(flag_rows, key):
        return 100.0 * sum(1 for r in flag_rows if r[key]) / max(1, len(flag_rows))

    loc = {
        "localized_rate": rate(rows, "localized"),
        "min_diagnosis_recall": 100.0 * sum(r["recall"] for r in rows) / max(1, n),
        "localized_count": sum(1 for r in rows if r["localized"]),
        "total_instances": n,
        "cpu_limit_count": sum(1 for r in rows if r["status"] in ("cpu_limit", "wall_limit")),
        "error_count": sum(1 for r in rows if r["status"] not in ("ok", "cpu_limit", "wall_limit")),
        "selected_fault_f1": 100.0 * sum(r["selected_fault_f1"] for r in rows) / max(1, n),
        "exact_fault_set_rate": rate(rows, "exact"),
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
        "cpu_limit_count_stress": sum(1 for r in stress if r["status"] in ("cpu_limit", "wall_limit")),
    }
    for k in sorted({r["fault_count"] for r in stress}):
        bucket = [r for r in stress if r["fault_count"] == k]
        scale[f"localized_rate_stress_f{k}"] = rate(bucket, "localized")
    result = {
        "iscas85_localisation": loc,
        "diagnosis_quality": quality,
        "observation_scaling": obs,
        "fault_scaling": faults,
        "scale_stress": scale,
    }
    tampered = any(r.get("status") == "tampered" for r in records)
    if tampered or not produced_any:
        # A run that produced nothing at all, or that touched the hidden test
        # directory, is a failed run: worst value of every metric.
        for exp, metrics in worst_values().items():
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
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (RUNS_DIR / f"{name}.json").write_text(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    # Build-time helpers used once when the gym is packaged; never needed for scoring.
    parser.add_argument("--calibrate-only", action="store_true")
    parser.add_argument("--store-baseline", default=None, help="run a baseline command and store its raw outputs")
    parser.add_argument("--command-json", default=None)
    args = parser.parse_args()

    # The answers are held in this process's memory while method code runs:
    # make it non-dumpable so other processes of the same user cannot read it
    # (/proc/<pid>/mem), and adopt every orphan the method leaves behind.
    _prctl(PR_SET_DUMPABLE, 0)
    _prctl(PR_SET_CHILD_SUBREAPER, 1)

    instances, truth = load_benchmark()
    config = json.loads(CONFIG_FILE.read_text())

    if args.calibrate_only:
        ids = config.get("calibration", {}).get("instance_ids", [])
        print(json.dumps({"cpu_seconds": measure_calibration(instances, ids, repeats=7)}))
        return

    budget = cpu_budget(config, instances)
    cpu_limit = budget["cpu_limit_seconds"]
    print(f"[{SLICE}] cpu budget per instance: {json.dumps(budget)}", file=sys.stderr, flush=True)

    if args.store_baseline:
        command = valid_registration({"command": json.loads(args.command_json)})
        with HiddenDataGuard(HERE) as guard:
            records = run_method(command, instances, cpu_limit, args.store_baseline, guard)
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        (BASELINE_DIR / f"{args.store_baseline}.json").write_text(
            json.dumps({"method": args.store_baseline, "budget": budget, "records": records}, sort_keys=True) + "\n"
        )
        return

    registered = discover_methods(REPO_ROOT / "checkpoints")
    for required in config.get("required_methods", ["cfaults"]):
        registered.setdefault(required, None)

    per_method: dict[str, dict] = {}
    run_payloads: dict[str, dict] = {}
    with HiddenDataGuard(HERE) as guard:
        for key, command in sorted(registered.items()):
            records = run_method(command, instances, cpu_limit, key, guard)
            per_method[key] = aggregate(records, instances, truth, cpu_limit)
            run_payloads[key] = {"method": key, "budget": budget, "command": command, "records": records}
    for key, payload in run_payloads.items():
        save_runs(key, payload)

    for key in RESERVED_KEYS:
        stored = load_json(BASELINE_DIR / f"{key}.json")
        if stored is None:
            continue
        stored_limit = float(stored.get("budget", {}).get("cpu_limit_seconds", cpu_limit))
        per_method[key] = aggregate(stored.get("records", []), instances, truth, stored_limit)

    extra = {
        "_evaluation": {
            "slice": SLICE,
            "instance_count": len(instances),
            "budget": budget,
            "methods_run": sorted(registered),
            "baselines_from": "eval/test/baseline_outputs (evaluator-owned, fixed)",
        }
    }
    scores = write_scores(per_method, args.out, extra)
    print(json.dumps(scores["experiments"]["iscas85_localisation"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
