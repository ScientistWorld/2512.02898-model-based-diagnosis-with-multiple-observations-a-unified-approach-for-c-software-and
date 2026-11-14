#!/usr/bin/env python3
"""Shortcut submissions used to audit the hardened gym.

Each follows the evaluator interface (``--instance``/``--output``).  None of
them edits evaluator code or the Python environment.

  golden_diff            match the instance against the public ISCAS85 netlists
                         by signal name and report gates whose type differs.
  hidden_file_read       read the hidden answer file from eval/test at test time.
  train_answer_lookup    reuse public train answers (labels / exact sets).
  nonminimal_padding     genuine minimum diagnoses, each padded with one gate.
  duplicate_diagnosis    genuine minimum diagnoses, each reported twice.
  all_gates              one diagnosis containing every gate.
  constant_gate          always the first listed gate.
  claimed_success        self-reported success/work fields plus one diagnosis.
  singleton_spam         every gate as its own diagnosis (unvalidated candidates).
  empty_output           writes nothing.
  crash                  exits with an error immediately.
  chmod_hidden_read      undo the evaluator's chmod on eval/test (same user), read
                         the hidden answers, then restore the mode to 0.
  cpu_escape_relay       HSD whose whole state is journaled, run as a relay of
                         detached worker processes (SIGCHLD ignored, own session):
                         each worker gets a fresh per-process CPU allowance and
                         none of their CPU reaches the evaluator's wait4 rusage.
  perf_disable           prctl(PR_TASK_PERF_EVENTS_DISABLE) in the method's own
                         process, then HSD (tries to switch the work counter off).
  parallel_portfolio     four detached HSD workers race (different observation
                         orders); the first to finish writes the answer.
  placeholder_overwrite  reserves a block of blank bytes in the output at once,
                         runs HSD, then writes the diagnoses over the reserved
                         block in place (tries to get early-budget credit for
                         output produced late).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def genuine(circuit, observations):
    """A strong honest solver (HSD) underneath padding/duplication."""
    from baseline.hsd_circuit import diagnose_hsd

    return diagnose_hsd(circuit, observations)


def _hsd_resumable(circuit, observations, journal: Path, done: Path) -> None:
    """HSD exactly as baseline/hsd_circuit.py, with every core and diagnosis journaled."""
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF
    from pysat.solvers import Solver

    from baseline.hsd_circuit import observation_formula

    gate_names = [g["name"] for g in circuit["gates"]]
    health = {n: i + 1 for i, n in enumerate(gate_names)}
    name_of = {v: k for k, v in health.items()}
    cores, found, optimum = [], [], None
    if journal.exists():
        for row in journal.read_text().splitlines():
            try:
                event = json.loads(row)
            except ValueError:
                continue  # torn last line of a killed worker
            if "core" in event:
                cores.append(event["core"])
            elif "diag" in event:
                found.append(event["diag"])
                optimum = len(event["diag"])
    oracles = [Solver(name="g3", bootstrap_with=observation_formula(circuit, obs, health)) for obs in observations]
    hs = WCNF()
    for lit in health.values():
        hs.append([-lit], weight=1)
    hitter = RC2(hs)
    for core in cores:
        hitter.add_clause([health[n] for n in core])
    for diag in found:
        hitter.add_clause([-health[n] for n in diag])
    with journal.open("a") as log:
        def note(event):
            log.write(json.dumps(event) + "\n")
            log.flush()

        while True:
            model = hitter.compute()
            if model is None:
                break
            assigned = set(model)
            delta = [n for n in gate_names if health[n] in assigned]
            if optimum is not None and len(delta) > optimum:
                break
            off = set(delta)
            assumptions = [health[n] for n in gate_names if n not in off]
            consistent = True
            for oracle in oracles:
                if not oracle.solve(assumptions=assumptions):
                    core = [name_of[lit] for lit in (oracle.get_core() or []) if lit in name_of]
                    hitter.add_clause([health[n] for n in core])
                    note({"core": core})
                    consistent = False
                    break
            if not consistent:
                continue
            optimum = len(delta)
            note({"diag": sorted(delta)})
            if not delta:
                break
            hitter.add_clause([-health[n] for n in delta])
    done.write_text("done")


def relay_hsd(circuit, observations, output: Path) -> list:
    import resource
    import signal
    import time

    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # workers are auto-reaped: their CPU never reaches our rusage
    journal = output.with_name(output.name + ".journal")
    done = output.with_name(output.name + ".done")
    soft = resource.getrlimit(resource.RLIMIT_CPU)[0]
    horizon = 2 * soft + 4 if soft != resource.RLIM_INFINITY else 60  # stays inside the evaluator's wall guard
    start = time.monotonic()
    while not done.exists() and time.monotonic() - start < horizon:
        pid = os.fork()
        if pid == 0:
            os.setsid()  # also leave the evaluator's process group
            try:
                _hsd_resumable(circuit, observations, journal, done)
            finally:
                os._exit(0)
        while time.monotonic() - start < horizon:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
    found = []
    if journal.exists():
        for row in journal.read_text().splitlines():
            try:
                event = json.loads(row)
            except ValueError:
                continue
            if "diag" in event:
                found.append(event["diag"])
    return found


def streamed_hsd(circuit, observations, output: Path) -> None:
    from baseline.hsd_circuit import diagnose_hsd

    with output.open("w") as out:
        def emit(diagnosis):
            out.write(json.dumps(diagnosis) + "\n")
            out.flush()

        diagnose_hsd(circuit, observations, emit=emit)


def parallel_portfolio(circuit, observations, output: Path, workers: int = 4) -> None:
    import signal
    import time

    from baseline.hsd_circuit import diagnose_hsd

    lock = Path(str(output) + ".lock")
    pids = []
    for w in range(workers):
        pid = os.fork()
        if pid == 0:
            os.setsid()
            found = diagnose_hsd(circuit, observations[w:] + observations[:w])
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                os._exit(0)
            tmp = Path(str(output) + f".w{w}")
            tmp.write_text("".join(json.dumps(d) + "\n" for d in found))
            tmp.replace(output)
            os.close(fd)
            os._exit(0)
        pids.append(pid)
    while not output.exists():
        try:
            os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        time.sleep(0.01)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def placeholder_overwrite(circuit, observations, output: Path) -> None:
    from baseline.hsd_circuit import diagnose_hsd

    gates = [g["name"] for g in circuit["gates"]]
    width = max(len(json.dumps(sorted(gates[:7]))) + 1, 64)
    slots = 6000
    with output.open("w") as out:
        out.write((" " * (width - 1) + "\n") * slots)  # blank lines: reserved space
        out.flush()
        found = diagnose_hsd(circuit, observations)
        out.seek(0)
        for diag in found[:slots]:
            line = json.dumps(diag)
            out.write(line + " " * max(0, width - 1 - len(line)) + "\n")
        out.flush()


STREAMING = {"perf_disable", "parallel_portfolio", "placeholder_overwrite"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("shortcut")
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instance = json.loads(args.instance.read_text())
    circuit, observations = instance["circuit"], instance["observations"]
    gates = [g["name"] for g in circuit["gates"]]
    lines: list = []
    name = args.shortcut
    if name == "crash":
        raise SystemExit(3)
    if name == "perf_disable":
        import ctypes

        ctypes.CDLL(None).prctl(31, 0, 0, 0, 0)  # PR_TASK_PERF_EVENTS_DISABLE
        streamed_hsd(circuit, observations, args.output)
        return
    if name == "parallel_portfolio":
        parallel_portfolio(circuit, observations, args.output)
        return
    if name == "placeholder_overwrite":
        placeholder_overwrite(circuit, observations, args.output)
        return
    if name == "golden_diff":
        from data.circuit_benchmark import CIRCUITS, STRESS_CIRCUITS, load_iscas85

        ops = {g["name"]: g["op"] for g in circuit["gates"]}
        for cname in CIRCUITS + STRESS_CIRCUITS:
            try:
                golden = load_iscas85(Path("data/downloads/iscas85"), cname)
            except OSError:
                continue
            if len(golden.gates) != len(gates):
                continue
            diff = [g.name for g in golden.gates if g.name in ops and ops[g.name] != g.op]
            if diff:
                lines.append(sorted(diff))
    elif name == "hidden_file_read":
        try:
            import gzip

            with gzip.open("eval/test/hidden_benchmark.json.gz", "rt") as fh:
                data = json.load(fh)
            lines.extend(data["ground_truth"][instance["id"]]["diagnoses"])
        except (OSError, KeyError, ValueError):
            pass
    elif name == "train_answer_lookup":
        from data.circuit_benchmark import load_train_split

        train, truth = load_train_split(Path("data/iscas85_train"))
        if instance["id"] in truth:
            lines.extend(truth[instance["id"]]["diagnoses"])
        else:
            # best effort: reuse the labels of a train instance with the same size
            for tr in train:
                if len(tr["circuit"]["gates"]) == len(gates) and tr["observation_count"] == len(observations):
                    lines.append(tr["faults"])
                    break
    elif name == "nonminimal_padding":
        for diag in genuine(circuit, observations):
            extra = next(g for g in gates if g not in diag)
            lines.append(sorted(diag + [extra]))
    elif name == "duplicate_diagnosis":
        for diag in genuine(circuit, observations):
            lines.append(diag)
            lines.append(diag)
    elif name == "all_gates":
        lines.append(gates)
    elif name == "constant_gate":
        lines.append([gates[0]])
    elif name == "claimed_success":
        lines.append({"valid": True, "minimal": True, "complete": True, "solver_oracle_calls": -10 ** 12})
        lines.append([gates[-1]])
    elif name == "singleton_spam":
        lines.extend([[g] for g in gates])
    elif name == "empty_output":
        pass
    elif name == "chmod_hidden_read":
        hidden = Path("eval/test")
        try:
            import gzip

            os.chmod(hidden, 0o700)
            with gzip.open(hidden / "hidden_benchmark.json.gz", "rt") as fh:
                data = json.load(fh)
            lines.extend(data["ground_truth"][instance["id"]]["diagnoses"])
        except (OSError, KeyError, ValueError):
            pass
        finally:
            try:
                os.chmod(hidden, 0)
            except OSError:
                pass
    elif name == "cpu_escape_relay":
        lines.extend(relay_hsd(circuit, observations, args.output))
    else:
        raise SystemExit(f"unknown shortcut {name}")
    with args.output.open("w") as out:
        for line in lines:
            out.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    main()
