#!/usr/bin/env python3
"""Summarise the hardened-gym audit: ranks, paired comparisons, rerun exactness.

rank = sum over ranked metrics of
       weight(experiment) * |coefficient| * direction * (value - reference) / sd
where direction comes from ``higher_is_better`` only, ``sd`` is the population
standard deviation of that metric over the audit cohort (every case run here
plus the evaluator-owned baselines), and missing values are skipped.
The reference is the official run in ``scoring/scores_test.json``.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import math
import shutil
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARD = ROOT / "redteam" / "hardening"
RESULTS = HARD / "results"


def load(path: Path):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt") as fh:
            return json.load(fh)
    return json.loads(path.read_text())


def get(scores: dict, exp: str, metric: str, method: str = "cfaults"):
    return scores.get("experiments", {}).get(exp, {}).get("results", {}).get(method, {}).get(metric)


def sign_test_p(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main() -> None:
    reference_cfg = load(ROOT / "scoring" / "reference.json")["experiments"]
    metrics = [(e, m, ex["weight"] * abs(md["coefficient"]), md["higher_is_better"])
               for e, ex in reference_cfg.items() for m, md in ex["metrics"].items() if md["coefficient"] != 0]
    main_scores = load(ROOT / "scoring" / "scores_test.json")
    ref_dir = RESULTS / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scoring" / "scores_test.json", ref_dir / "scores_test.json")
    if (ROOT / "eval" / "test" / "runs" / "cfaults.json.gz").exists():
        (ref_dir / "runs").mkdir(exist_ok=True)
        shutil.copy2(ROOT / "eval" / "test" / "runs" / "cfaults.json.gz", ref_dir / "runs" / "cfaults.json.gz")

    cases = {p.parent.name: load(p) for p in sorted(RESULTS.glob("*/scores_test.json"))}
    entries = {name: (scores, "cfaults") for name, scores in cases.items()}
    entries["baseline_hsd"] = (main_scores, "hsd")
    entries["baseline_bugassist_vote"] = (main_scores, "bugassist_vote")
    if "late_method_shortcut" in cases:
        entries["late_method_shortcut[late_method]"] = (cases["late_method_shortcut"], "late_method")

    sds = {}
    for e, m, w, high in metrics:
        vals = [get(s, e, m, k) for s, k in entries.values()]
        vals = [v for v in vals if isinstance(v, (int, float))]
        sds[f"{e}/{m}"] = statistics.pstdev(vals) if len(vals) > 1 else 0.0

    spec = importlib.util.spec_from_file_location("test_eval", ROOT / "eval/test/evaluate_circuit_outputs.py")
    test_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(test_eval)
    instances, truth = test_eval.load_benchmark()
    budget = float(main_scores["_evaluation"]["budget"]["instruction_budget"])

    def records_of(case: str, key: str = "cfaults"):
        path = RESULTS / case / "runs" / f"{key}.json.gz"
        if case.startswith("baseline_"):
            path = ROOT / "eval" / "test" / "baseline_outputs" / f"{case[len('baseline_'):]}.json.gz"
        if not path.exists():
            return None
        return {r["id"]: r for r in load(path)["records"]}

    def per_instance(case: str, key: str = "cfaults"):
        recs = records_of(case, key)
        if recs is None:
            return None
        return {inst["id"]: test_eval.score_instance(recs.get(inst["id"], {"diagnoses": []}), inst, truth[inst["id"]], budget)
                for inst in instances}

    ref_flags = per_instance("reference")
    rows = {}
    for name, (scores, key) in entries.items():
        rank, contributions, missing = 0.0, {}, []
        for e, m, w, high in metrics:
            v, r = get(scores, e, m, key), get(main_scores, e, m, "cfaults")
            if v is None or r is None:
                missing.append(f"{e}/{m}")
                continue
            sd = sds[f"{e}/{m}"]
            c = w * (v - r) * (1 if high else -1) / sd if sd else 0.0
            contributions[f"{e}/{m}"] = c
            rank += c
        row = {
            "rank_vs_reference": rank,
            "localized_rate": get(scores, "iscas85_localisation", "localized_rate", key),
            "min_diagnosis_recall": get(scores, "iscas85_localisation", "min_diagnosis_recall", key),
            "unsound_output_rate": get(scores, "diagnosis_quality", "unsound_output_rate", key),
            "localized_rate_f7": get(scores, "fault_scaling", "localized_rate_f7", key),
            "localized_rate_stress": get(scores, "scale_stress", "localized_rate_stress", key),
            "min_diagnosis_recall_stress": get(scores, "scale_stress", "min_diagnosis_recall_stress", key),
            "localized_rate_quarter_budget": get(scores, "runtime_profile", "localized_rate_quarter_budget", key),
            "failed_run": get(scores, "iscas85_localisation", "failed_run", key),
            "tamper_detected": get(scores, "iscas85_localisation", "tamper_detected", key),
            "missing_ranked_metrics": missing,
            "contributions": contributions,
        }
        case_dir = name if (name in cases or name.startswith("baseline_")) else None
        if case_dir and ref_flags is not None and name != "reference":
            flags = per_instance(case_dir, key)
            if flags is not None:
                wins = sum(1 for i in flags if flags[i]["localized"] and not ref_flags[i]["localized"])
                losses = sum(1 for i in flags if ref_flags[i]["localized"] and not flags[i]["localized"])
                rec_diff = [flags[i]["recall"] - ref_flags[i]["recall"] for i in flags]
                row["paired_vs_reference"] = {
                    "instances_localized_only_by_case": wins,
                    "instances_localized_only_by_reference": losses,
                    "sign_test_p": sign_test_p(wins, losses),
                    "mean_recall_difference_pct": 100.0 * sum(rec_diff) / max(1, len(rec_diff)),
                }
        rows[name] = row

    exactness = None
    a, b = records_of("reference"), records_of("reference_repeat")
    if a and b:
        diffs = []
        for i, ra in a.items():
            rb = b.get(i)
            if rb and ra.get("status") == "ok" and rb.get("status") == "ok" and ra["instructions"]:
                diffs.append(abs(ra["instructions"] - rb["instructions"]) / ra["instructions"])
        repeat_flags = per_instance("reference_repeat")
        flips = sum(1 for i in ref_flags if ref_flags[i]["localized"] != repeat_flags[i]["localized"])
        exactness = {"instances_compared": len(diffs), "max_relative_instruction_difference": max(diffs) if diffs else None,
                     "median_relative_instruction_difference": statistics.median(diffs) if diffs else None,
                     "localized_flips": flips,
                     "rank_difference": rows.get("reference_repeat", {}).get("rank_vs_reference")}
    train = load(ROOT / "scoring" / "scores_train.json")
    doc = {
        "rank_convention": "sum(weight*|coefficient|*direction*(value-reference)/population_sd_over_audit_cohort); missing skipped; "
                           "cohort = every audit case plus the evaluator-owned baselines",
        "cohort": sorted(entries),
        "reference": "scoring/scores_test.json (official reference run, cfaults)",
        "budget": main_scores.get("_evaluation", {}).get("budget"),
        "metric_sd": sds,
        "rerun_exactness": exactness,
        "reference_train_vs_test": {
            f"{e}/{m}": {"train": get(train, e, m), "test": get(main_scores, e, m)} for e, m, _, _ in metrics
        },
        "runs": rows,
    }
    (HARD / "summary.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(f"{'case':40s} {'rank':>7s} {'loc%':>6s} {'rec%':>6s} {'uns%':>6s} {'f7%':>6s} {'str%':>6s} {'q-bud%':>6s} paired(w/l,p)")
    for name, r in sorted(rows.items(), key=lambda kv: -kv[1]["rank_vs_reference"]):
        p = r.get("paired_vs_reference")
        ptxt = f"{p['instances_localized_only_by_case']}/{p['instances_localized_only_by_reference']},{p['sign_test_p']:.3g}" if p else ""
        fmt = lambda v: f"{v:6.1f}" if isinstance(v, (int, float)) else "     -"
        print(f"{name:40s} {r['rank_vs_reference']:7.3f} {fmt(r['localized_rate'])} {fmt(r['min_diagnosis_recall'])} "
              f"{fmt(r['unsound_output_rate'])} {fmt(r['localized_rate_f7'])} {fmt(r['localized_rate_stress'])} "
              f"{fmt(r['localized_rate_quarter_budget'])} {ptxt}")
    print("rerun exactness:", json.dumps(exactness))


if __name__ == "__main__":
    main()
