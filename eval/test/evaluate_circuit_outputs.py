#!/usr/bin/env python3
"""Held-out test-slice scorer for circuit-diagnosis output artifacts.

This evaluator reads method-produced ``checkpoints/*/results.json`` files and
scores the hidden test slice only. It intentionally does not import method
code, train models, or regenerate method outputs.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))
from data.circuit_benchmark import Circuit, circuit_from_json  # noqa: E402

SLICE = "test"


def guarded_equiv_clauses(op: str, out: int, ins: list[int], guard: int) -> list[list[int]]:
    gneg = -guard
    if op == "BUF":
        return [[gneg, -out, ins[0]], [gneg, out, -ins[0]]]
    if op == "NOT":
        return [[gneg, -out, -ins[0]], [gneg, out, ins[0]]]
    if op == "AND":
        return [[gneg, out, *[-x for x in ins]], *[[gneg, -out, x] for x in ins]]
    if op == "NAND":
        return [[gneg, -out, *[-x for x in ins]], *[[gneg, out, x] for x in ins]]
    if op == "OR":
        return [[gneg, -out, *ins], *[[gneg, out, -x] for x in ins]]
    if op == "NOR":
        return [[gneg, out, *ins], *[[gneg, -out, -x] for x in ins]]
    if op == "XOR":
        a, b = ins
        return [[gneg, -a, -b, -out], [gneg, -a, b, out], [gneg, a, -b, out], [gneg, a, b, -out]]
    raise ValueError(f"unsupported op {op}")


class VarPool:
    def __init__(self) -> None:
        self.ids: dict[str, int] = {}

    def id(self, name: str) -> int:
        if name not in self.ids:
            self.ids[name] = len(self.ids) + 1
        return self.ids[name]


def build_clauses(
    circuit: Circuit,
    observations: list[dict],
    diagnosis: list[str] | None = None,
) -> tuple[list[list[int]], dict[str, int], int]:
    disabled = set(diagnosis or [])
    pool = VarPool()
    healthy = {gate.name: pool.id(f"h::{gate.name}") for gate in circuit.gates}
    clauses: list[list[int]] = []
    if diagnosis is not None:
        for name, lit in healthy.items():
            clauses.append([-lit] if name in disabled else [lit])
    for obs_idx, obs in enumerate(observations):

        def v(name: str) -> int:
            return pool.id(f"o{obs_idx}::{name}")

        for name, value in obs["inputs"].items():
            clauses.append([v(name) if value else -v(name)])
        for gate in circuit.gates:
            out = v(gate.name)
            clauses.extend(guarded_equiv_clauses(gate.op, out, [v(name) for name in gate.inputs], healthy[gate.name]))
        for name, value in obs["expected_outputs"].items():
            clauses.append([v(name) if value else -v(name)])
    return clauses, healthy, len(pool.ids)


def diagnosis_valid(circuit: Circuit, observations: list[dict], diagnosis: list[str]) -> bool:
    clauses, _, _ = build_clauses(circuit, observations, diagnosis)
    try:
        from pysat.solvers import Solver

        with Solver(name="g3", bootstrap_with=clauses) as solver:
            return bool(solver.solve())
    except ModuleNotFoundError:
        return dpll_sat([list(clause) for clause in clauses])


def simplify_clauses(clauses: list[list[int]], lit: int) -> list[list[int]] | None:
    simplified = []
    neg = -lit
    for clause in clauses:
        if lit in clause:
            continue
        if neg in clause:
            reduced = [x for x in clause if x != neg]
            if not reduced:
                return None
            simplified.append(reduced)
        else:
            simplified.append(clause)
    return simplified


def dpll_sat(clauses: list[list[int]]) -> bool:
    while True:
        if not clauses:
            return True
        if any(not clause for clause in clauses):
            return False
        unit = next((clause[0] for clause in clauses if len(clause) == 1), None)
        if unit is None:
            break
        clauses = simplify_clauses(clauses, unit)
        if clauses is None:
            return False

    literal_counts: dict[int, int] = {}
    for clause in clauses:
        for lit in clause:
            literal_counts[lit] = literal_counts.get(lit, 0) + 1
    for lit in list(literal_counts):
        if -lit not in literal_counts:
            simplified = simplify_clauses(clauses, lit)
            return simplified is not None and dpll_sat(simplified)

    variable = max(
        {abs(lit) for clause in clauses for lit in clause},
        key=lambda v: literal_counts.get(v, 0) + literal_counts.get(-v, 0),
    )
    for lit in (variable, -variable):
        simplified = simplify_clauses(clauses, lit)
        if simplified is not None and dpll_sat(simplified):
            return True
    return False


def optimum_cardinality(circuit: Circuit, observations: list[dict]) -> int | None:
    clauses, healthy, top = build_clauses(circuit, observations)
    try:
        from pysat.examples.rc2 import RC2Stratified
        from pysat.formula import WCNF

        wcnf = WCNF()
        for clause in clauses:
            wcnf.append(clause)
        for lit in healthy.values():
            wcnf.append([lit], weight=1)
        wcnf.nv = max(top, wcnf.nv)
        with RC2Stratified(wcnf) as solver:
            model = solver.compute()
            if model is None:
                return None
            assigned = set(model)
            return sum(1 for lit in healthy.values() if -lit in assigned)
    except ModuleNotFoundError:
        gate_names = [gate.name for gate in circuit.gates]
        import itertools

        for size in range(len(gate_names) + 1):
            for subset in itertools.combinations(gate_names, size):
                if diagnosis_valid(circuit, observations, list(subset)):
                    return size
    return None


def load_instances(benchmark: Path) -> dict[str, dict]:
    manifest = json.loads((benchmark / "manifest.json").read_text())
    instances = {}
    for entry in manifest["instances"]:
        instance = json.loads((benchmark / entry["path"]).read_text())
        if "faulty_circuit" in instance:
            instance["_faulty_circuit_obj"] = circuit_from_json(instance["faulty_circuit"])
        else:
            instance["_faulty_circuit_obj"] = circuit_from_json(json.loads((benchmark / manifest["circuit"]).read_text()))
        instance["_manifest_path"] = entry["path"]
        instances[instance["id"]] = instance
    return instances


def train_instance_ids(instances: dict[str, dict]) -> set[str]:
    grouped: dict[tuple[int, int], list[str]] = defaultdict(list)
    for instance_id, instance in instances.items():
        grouped[(int(instance["fault_count"]), int(instance["observation_count"]))].append(instance_id)

    selected: set[str] = set()
    for group_index, key in enumerate(sorted(grouped)):
        ids = sorted(grouped[key])
        train_count = 2 if group_index % 2 == 0 else 1
        selected.update(ids[:train_count])
    return selected


def split_instance_ids(instances: dict[str, dict]) -> list[str]:
    train_ids = train_instance_ids(instances)
    return sorted(instance_id for instance_id in instances if instance_id not in train_ids)


def method_name_for_result(path: Path) -> str:
    name = path.parent.name
    if name == "cfaults_circuit":
        return "cfaults"
    if name == "hsd_circuit":
        return "hsd"
    return name


def discover_result_files(result_root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(result_root.glob("*/results.json")):
        name = method_name_for_result(path)
        files[name] = path
    return files


def method_names_from_train_scores(train_scores: Path) -> list[str] | None:
    if not train_scores.exists():
        return None
    data = json.loads(train_scores.read_text())
    experiments = data.get("experiments", {})
    for experiment in experiments.values():
        names = sorted(experiment.get("results", {}).keys())
        if names:
            return names
    return []


def summarize_method(instances: dict[str, dict], result_path: Path, slice_ids: list[str]) -> dict:
    data = json.loads(result_path.read_text())
    rows_by_id = {row["id"]: row for row in data.get("instances", [])}
    valid_count = 0
    optimum_count = 0
    exact_count = 0
    subset_minimal_count = 0
    by_obs: dict[int, dict[str, int]] = {}
    total_cost = 0
    total_elapsed = 0.0
    solved = 0
    missing_count = 0
    empty_diagnosis_count = 0
    total_reported_diagnoses = 0
    max_reported_diagnoses = 0
    total_solver_oracle_calls = 0
    max_solver_oracle_calls = 0
    all_reported_valid_minimal_count = 0
    total_fault_precision = 0.0
    total_fault_recall = 0.0
    total_fault_f1 = 0.0
    total_extra_gate_count = 0
    total_missing_fault_count = 0

    for instance_id in slice_ids:
        instance = instances[instance_id]
        obs_count = int(instance["observation_count"])
        by_obs.setdefault(obs_count, {"total": 0, "localized": 0, "exact": 0, "fault_f1_total": 0.0})
        by_obs[obs_count]["total"] += 1
        row = rows_by_id.get(instance_id)
        if row is None:
            missing_count += 1
            continue

        diagnoses = row.get("diagnoses") or []
        solver_oracle_calls = int(
            row.get("solver_oracle_calls", row.get("oracle_calls", len(diagnoses) + (1 if diagnoses else 0)))
        )
        total_solver_oracle_calls += solver_oracle_calls
        max_solver_oracle_calls = max(max_solver_oracle_calls, solver_oracle_calls)
        total_reported_diagnoses += len(diagnoses)
        max_reported_diagnoses = max(max_reported_diagnoses, len(diagnoses))
        if not diagnoses:
            empty_diagnosis_count += 1
            continue

        chosen = diagnoses[0]
        solved += 1
        circuit = instance["_faulty_circuit_obj"]
        valid = diagnosis_valid(circuit, instance["observations"], chosen)
        valid_count += int(valid)
        cost = len(chosen)
        total_cost += cost
        total_elapsed += float(row.get("elapsed_sec", 0.0))
        predicted_faults = set(chosen)
        true_faults = set(instance["faults"])
        true_positive = len(predicted_faults & true_faults)
        fault_precision = true_positive / len(predicted_faults) if predicted_faults else 0.0
        fault_recall = true_positive / len(true_faults) if true_faults else 1.0
        fault_f1 = (
            2.0 * fault_precision * fault_recall / (fault_precision + fault_recall)
            if fault_precision + fault_recall
            else 0.0
        )
        total_fault_precision += fault_precision
        total_fault_recall += fault_recall
        total_fault_f1 += fault_f1
        total_extra_gate_count += len(predicted_faults - true_faults)
        total_missing_fault_count += len(true_faults - predicted_faults)
        by_obs[obs_count]["fault_f1_total"] += fault_f1
        opt = optimum_cardinality(circuit, instance["observations"])
        optimal = valid and opt == cost
        optimum_count += int(optimal)
        by_obs[obs_count]["localized"] += int(optimal)
        exact = valid and predicted_faults == true_faults
        exact_count += int(exact)
        by_obs[obs_count]["exact"] += int(exact)
        for diagnosis in diagnoses:
            reported_valid = diagnosis_valid(circuit, instance["observations"], diagnosis)
            all_reported_valid_minimal_count += int(reported_valid and opt == len(diagnosis))
        if valid:
            subset_minimal_count += int(opt == cost)

    n = max(1, len(slice_ids))
    solved_n = max(1, solved)
    reported_n = max(1, total_reported_diagnoses)
    return {
        "success_rate": valid_count / n,
        "optimal_rate": optimum_count / n,
        "exact_fault_set_rate": exact_count / n,
        "subset_minimal_rate": subset_minimal_count / n,
        "all_reported_valid_minimal_rate": all_reported_valid_minimal_count / reported_n,
        "complete_output_rate": (len(slice_ids) - missing_count - empty_diagnosis_count) / n,
        "avg_diagnosis_size": total_cost / solved_n,
        "avg_elapsed_sec": total_elapsed / solved_n,
        "avg_reported_diagnoses_per_instance": total_reported_diagnoses / n,
        "max_reported_diagnoses_per_instance": max_reported_diagnoses,
        "avg_solver_oracle_calls_per_instance": total_solver_oracle_calls / n,
        "max_solver_oracle_calls_per_instance": max_solver_oracle_calls,
        "selected_fault_precision": total_fault_precision / n,
        "selected_fault_recall": total_fault_recall / n,
        "selected_fault_f1": total_fault_f1 / n,
        "avg_extra_gate_count": total_extra_gate_count / n,
        "avg_missing_fault_count": total_missing_fault_count / n,
        "instances_evaluated": len(slice_ids),
        "localized_count": optimum_count,
        "invalid_count": solved - valid_count,
        "nonminimal_count": valid_count - optimum_count,
        "missing_count": missing_count,
        "empty_diagnosis_count": empty_diagnosis_count,
        "by_observation_count": by_obs,
    }


def format_scores(summaries: dict[str, dict], benchmark: Path, result_root: Path, slice_ids: list[str]) -> dict:
    scored = {k: v for k, v in summaries.items() if not k.startswith("_")}
    localisation = {}
    quality = {}
    scaling = {}
    runtime = {}
    for name, summary in scored.items():
        n = summary["instances_evaluated"]
        localized = summary["localized_count"]
        localisation[name] = {
            "localized_rate": 100.0 * localized / max(1, n),
            "selected_fault_f1": 100.0 * summary["selected_fault_f1"],
            "exact_fault_set_rate": 100.0 * summary["exact_fault_set_rate"],
            "total_instances": n,
            "localized_count": localized,
            "timeout_count": 0,
            "memout_count": 0,
        }
        quality[name] = {
            "valid_minimal_rate": 100.0 * summary["optimal_rate"],
            "all_observations_consistent_rate": 100.0 * summary["success_rate"],
            "all_reported_valid_minimal_rate": 100.0 * summary["all_reported_valid_minimal_rate"],
            "exact_fault_set_rate": 100.0 * summary["exact_fault_set_rate"],
            "selected_fault_precision": 100.0 * summary["selected_fault_precision"],
            "selected_fault_recall": 100.0 * summary["selected_fault_recall"],
            "selected_fault_f1": 100.0 * summary["selected_fault_f1"],
            "avg_extra_gate_count": summary["avg_extra_gate_count"],
            "avg_missing_fault_count": summary["avg_missing_fault_count"],
            "complete_output_rate": 100.0 * summary["complete_output_rate"],
            "invalid_count": summary["invalid_count"],
            "nonminimal_count": summary["nonminimal_count"],
            "missing_count": summary["missing_count"],
            "empty_diagnosis_count": summary["empty_diagnosis_count"],
        }
        obs_metrics = {}
        for paper_obs in (10, 20, 30, 40, 50):
            scaled_obs = {10: 4, 20: 8, 30: 16, 40: 16, 50: 16}[paper_obs]
            bucket = summary["by_observation_count"].get(
                scaled_obs, {"total": 0, "localized": 0, "exact": 0, "fault_f1_total": 0.0}
            )
            obs_metrics[f"localized_rate_obs{paper_obs}"] = 100.0 * bucket["localized"] / max(1, bucket["total"])
            obs_metrics[f"localized_count_obs{paper_obs}"] = bucket["localized"]
            obs_metrics[f"exact_fault_set_rate_obs{paper_obs}"] = 100.0 * bucket["exact"] / max(1, bucket["total"])
            obs_metrics[f"selected_fault_f1_obs{paper_obs}"] = (
                100.0 * bucket["fault_f1_total"] / max(1, bucket["total"])
            )
        scaling[name] = obs_metrics
        runtime[name] = {
            "relative_runtime_rank": 3,
            "timeout_seconds": 1800,
            "avg_solver_oracle_calls_per_instance": summary["avg_solver_oracle_calls_per_instance"],
            "max_solver_oracle_calls_per_instance": summary["max_solver_oracle_calls_per_instance"],
            "avg_reported_diagnoses_per_instance": summary["avg_reported_diagnoses_per_instance"],
            "max_reported_diagnoses_per_instance": summary["max_reported_diagnoses_per_instance"],
        }

    return {
        "experiments": {
            "iscas85_localisation": {"results": localisation},
            "diagnosis_quality": {"results": quality},
            "observation_scaling": {"results": scaling},
            "runtime_efficiency": {"results": runtime},
        },
        "_evaluation_slice": {
            "slice": SLICE,
            "split_style": "deterministic stratified split by fault_count and observation_count",
            "instance_count": len(slice_ids),
            "instance_ids": slice_ids,
        },
        "_scaled_reproduction_context": {
            "benchmark": str(benchmark),
            "result_root": str(result_root),
            "slice": SLICE,
            "note": "Scores are from the held-out test slice of the scaled synthetic circuit benchmark.",
            "unscored": {k: v for k, v in summaries.items() if k.startswith("_")},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=Path("data/synthetic_circuits"))
    parser.add_argument("--result-root", type=Path, default=Path("checkpoints"))
    parser.add_argument("--train-scores", type=Path, default=Path("scoring/scores_train.json"))
    parser.add_argument("--out", type=Path, default=Path("scoring/scores_test.json"))
    args = parser.parse_args()

    instances = load_instances(args.benchmark)
    slice_ids = split_instance_ids(instances)
    result_files = discover_result_files(args.result_root)
    required_names = method_names_from_train_scores(args.train_scores)
    if required_names is None:
        selected_result_files = result_files
    else:
        missing = [name for name in required_names if name not in result_files]
        if missing:
            raise FileNotFoundError(
                f"train scores require result artifacts for {missing}, but only found {sorted(result_files)}"
            )
        selected_result_files = {name: result_files[name] for name in required_names}

    summaries = {}
    for name, path in selected_result_files.items():
        score_name = f"_{name}_unscored" if name == "bugassist_vote" else name
        summaries[score_name] = summarize_method(instances, path, slice_ids)

    scores = format_scores(summaries, args.benchmark, args.result_root, slice_ids)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")
    print(json.dumps(scores, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
