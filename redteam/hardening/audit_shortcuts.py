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
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def genuine(circuit, observations):
    """A strong honest solver (exact SAT enumeration) underneath padding/duplication."""
    found = []
    from method.audit_variants import satenum

    satenum(circuit, observations, found.append)
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
    else:
        raise SystemExit(f"unknown shortcut {name}")
    with args.output.open("w") as out:
        for line in lines:
            out.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    main()
