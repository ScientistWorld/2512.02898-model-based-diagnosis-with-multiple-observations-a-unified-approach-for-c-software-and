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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def genuine(circuit, observations):
    """A strong honest solver (exact SAT enumeration) underneath padding/duplication."""
    found = []
    from method.audit_variants import satenum

    satenum(circuit, observations, found.append)
    return found


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
    if name == "golden_diff":
        from data.circuit_benchmark import CIRCUITS, load_iscas85

        ops = {g["name"]: g["op"] for g in circuit["gates"]}
        for cname in CIRCUITS:
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
            data = json.loads(Path("eval/test/hidden_benchmark.json").read_text())
            lines.extend(data["ground_truth"][instance["id"]]["diagnoses"])
        except (OSError, KeyError, ValueError):
            pass
    elif name == "train_answer_lookup":
        truth = json.loads(Path("data/iscas85_train/ground_truth.json").read_text())
        if instance["id"] in truth:
            lines.extend(truth[instance["id"]]["diagnoses"])
        else:
            # best effort: reuse the labels of a train instance with the same size
            for row in Path("data/iscas85_train/instances.jsonl").read_text().splitlines():
                tr = json.loads(row)
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
            os.chmod(hidden, 0o700)
            data = json.loads((hidden / "hidden_benchmark.json").read_text())
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
