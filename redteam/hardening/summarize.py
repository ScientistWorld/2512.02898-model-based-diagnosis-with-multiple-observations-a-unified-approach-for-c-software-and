#!/usr/bin/env python3
"""Summarise the hardened-gym audit: ranks, seed spread, paired comparisons.

rank = sum over ranked metrics of
       weight(experiment) * |coefficient| * direction * (value - reference) / sd
where direction comes from ``higher_is_better`` only, ``sd`` is the population
standard deviation of that metric over the audit cohort (every case run here
plus the evaluator-owned baselines), and missing values are skipped.
The reference is the official run in ``scoring/scores_test.json``.
"""

from __future__ import annotations

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
    return json.loads(Path(path).read_text())


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
    ref_dir = RESULTS / "reference_seed_0"
    ref_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scoring" / "scores_test.json", ref_dir / "scores_test.json")
    if (ROOT / "eval" / "test" / "runs").exists():
        shutil.copytree(ROOT / "eval" / "test" / "runs", ref_dir / "runs", dirs_exist_ok=True)

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

    test_eval = None
    spec = importlib.util.spec_from_file_location("test_eval", ROOT / "eval/test/evaluate_circuit_outputs.py")
    test_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(test_eval)
    instances, truth = test_eval.load_benchmark()

    def per_instance(case: str, key: str = "cfaults"):
        path = RESULTS / case / "runs" / f"{key}.json"
        if not path.exists():
            return None
        payload = load(path)
        limit = float(payload["budget"]["cpu_limit_seconds"])
        by_id = {r["id"]: r for r in payload["records"]}
        flags = {}
        for inst in instances:
            rec = by_id.get(inst["id"], {"id": inst["id"], "diagnoses": []})
            flags[inst["id"]] = test_eval.score_instance(rec, inst, truth[inst["id"]], limit)
        return flags

    ref_flags = per_instance("reference_seed_0")
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
            "localized_rate_f5": get(scores, "fault_scaling", "localized_rate_f5", key),
            "selected_fault_f1_audit": get(scores, "iscas85_localisation", "selected_fault_f1", key),
            "failed_run": get(scores, "iscas85_localisation", "failed_run", key),
            "missing_ranked_metrics": missing,
            "contributions": contributions,
        }
        case_dir = name if name in cases else None
        if case_dir and ref_flags is not None:
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

    seeds = [n for n in ("reference_seed_0", "reference_seed_1", "reference_seed_2") if n in rows]
    spread = {}
    for e, m, _, _ in metrics:
        vals = [get(cases[s], e, m) for s in seeds]
        vals = [v for v in vals if v is not None]
        if vals:
            spread[f"{e}/{m}"] = max(vals) - min(vals)
    spread["rank_vs_reference"] = (max(rows[s]["rank_vs_reference"] for s in seeds) -
                                   min(rows[s]["rank_vs_reference"] for s in seeds)) if seeds else None
    train = load(ROOT / "scoring" / "scores_train.json")
    doc = {
        "rank_convention": "sum(weight*|coefficient|*direction*(value-reference)/population_sd_over_audit_cohort); missing skipped",
        "reference": "scoring/scores_test.json (official reference run, cfaults)",
        "budget": main_scores.get("_evaluation", {}).get("budget"),
        "metric_sd": sds,
        "seed_spread": spread,
        "reference_train_vs_test": {
            f"{e}/{m}": {"train": get(train, e, m), "test": get(main_scores, e, m)} for e, m, _, _ in metrics
        },
        "runs": rows,
    }
    (HARD / "summary.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(f"{'case':42s} {'rank':>8s} {'loc%':>6s} {'recall%':>8s} {'unsound%':>8s} {'f5%':>6s} paired(w/l,p)")
    for name, r in sorted(rows.items(), key=lambda kv: -kv[1]["rank_vs_reference"]):
        p = r.get("paired_vs_reference")
        ptxt = f"{p['instances_localized_only_by_case']}/{p['instances_localized_only_by_reference']},{p['sign_test_p']:.3g}" if p else ""
        fmt = lambda v: f"{v:6.1f}" if isinstance(v, (int, float)) else "     -"
        print(f"{name:42s} {r['rank_vs_reference']:8.3f} {fmt(r['localized_rate'])} {fmt(r['min_diagnosis_recall']):>8s} "
              f"{fmt(r['unsound_output_rate']):>8s} {fmt(r['localized_rate_f5'])} {ptxt}")
    print("seed spread:", json.dumps(spread))


if __name__ == "__main__":
    main()
