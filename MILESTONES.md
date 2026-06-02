# Reproduction Milestones

**Current: core_claim**

<!-- Milestone levels (update "Current" above as you progress):
  none             — just started, no meaningful progress yet
  method_runs      — the paper's method executes end-to-end without errors
  core_claim       — minimum experiment supports the paper's central claim
  core_claim_plus  — core claim reproduced on additional settings
  secondary_claims — secondary results or contributions reproduced
  majority         — more than half of reported results reproduced
  near_complete    — most results reproduced, only minor gaps remain
  full             — all reported results reproduced
-->

## Progress Log

### [2026-06-02 10:55] - none
- Read the paper and identified the Boolean-circuit CFaults result as the most direct reusable reproduction target.
- Extracted the core algorithm: replicate the faulty circuit per observation, share one health variable per gate, encode guarded gate semantics as hard clauses, and solve an unweighted partial MaxSAT objective over healthy-gate soft clauses.

### [2026-06-02 10:55] - method_runs
- Implemented the paper's actual multiple-observation diagnosis algorithm for Boolean circuits in `method/cfaults_circuit.py`.
- Built a reusable synthetic circuit benchmark in `data/circuit_benchmark.py` and a BugAssist-style one-observation voting baseline in `baseline/bugassist_vote_circuit.py`.
- Ran `scripts/reproduce.sh` locally: data generation, baseline, method, and evaluator all execute end-to-end.

### [2026-06-02 10:55] - core_claim
- Evaluated 27 scaled circuit-diagnosis instances across three observation counts and three injected fault counts.
- CFaults produced valid minimum-cardinality diagnoses for all 27 instances; the one-observation voting baseline localized only 3 of 27, showing that unified multi-observation reasoning is necessary on this benchmark.
- The reproduction uses a scaled synthetic circuit benchmark instead of the paper's full augmented ISCAS85 suite, but preserves the paper's MaxSAT computation and objective.

## Stop Justification
- Not stopped; the current submission verifies the packaged environment on a CPU test node.
