# Progress

> **Historical (iterations 1-9).** This note describes the earlier synthetic-circuit gym (artifact-based scoring, solver-call counts, injected-fault F1). It is superseded: the current benchmark, protocol and scores are in `briefing/`, `scoring/` and `HARDENING.md`.

## What Works

- The Boolean-circuit CFaults algorithm from the paper is implemented in `method/cfaults_circuit.py`.
- The implementation builds one replica of the circuit constraints per failing observation, shares a single health variable for each original gate across all replicas, and solves the resulting unweighted partial MaxSAT instance with PySAT RC2.
- A reusable benchmark generator in `data/circuit_benchmark.py` creates small tracked circuit-diagnosis instances with explicit faulty circuit netlists, injected gate-operator mutations, and failing observations.
- `scripts/reproduce.sh` runs the full local pipeline: generate benchmark data, run the one-observation voting baseline, run CFaults, and evaluate artifacts through `scripts/evaluate.sh`.
- `baseline/bugassist_vote_circuit.py` now implements its one-observation MaxSAT voting baseline independently of `method/`, so future method changes do not alter the baseline.
- `baseline/hsd_circuit.py` now implements an HSD-style multiple-observation circuit baseline from the paper using separate per-observation formulas, unsat cores over healthy-gate assumptions, and minimum hitting sets.
- Method and baseline artifacts now report `solver_oracle_calls`, and all evaluators score this machine-independent solver-work proxy for `runtime_efficiency`.
- `eval/evaluate_circuit_outputs.py` is method-agnostic: it reads result artifacts and independently checks diagnosis validity and cardinality without importing `method/`.
- Scheduler job `2147c6a7-240` verified the repaired packaged pipeline inside the compute container with exit code 0.
- Scheduler job `06041b2e-9e9` regenerated the final score artifact inside the packaged compute container with exit code 0.
- The top-level reusable evaluator has been aligned with the train/test scoring contract so future agents are scored on selected fault-set overlap, diagnosis validity, completeness, and solver-oracle-call efficiency.
- Scheduler job `e9807e81-d04` regenerated root, train, and test scores after the Boolean-gate CNF repair and passed `python validate.py --compare`.
- Scheduler job `d04c15ff-130` regenerated root, train, and test scores after the HSD baseline and solver-oracle-call scoring update; `python validate.py --compare` passes.

## Results

- Paper reference, augmented ISCAS85 localisation (Table 5): CFaults localizes 8,969 / 12,147 instances, or 73.84%.
- Scaled reproduction, synthetic circuit localisation: CFaults localizes 27 / 27 instances, or 100.0%.
- Scaled reproduction, selected-fault overlap: CFaults reaches 45.93 F1 on the selected minimum-cardinality diagnosis.
- Constraint metric, scaled reproduction: CFaults returns valid minimum-cardinality diagnoses for 27 / 27 instances, with 0 invalid, 0 non-minimal, and 0 observation-inconsistent outputs.
- All-observation consistency is now an explicit diagnosis-quality metric in `reference.json`, the evaluator output contract, and the regenerated `scores.json`.
- Unscored sanity baseline after the gate repair: the one-observation voting baseline localizes 15 / 27 instances and returns 12 invalid selected diagnoses, which confirms the benchmark is not solved reliably by considering observations independently.
- Container verification: job `2147c6a7-240` completed in 19.25 seconds on a CPU test node and reproduced the same 27 / 27 CFaults localisation result after the explicit faulty-circuit interface repair.
- Final score regeneration: job `06041b2e-9e9` completed in 60.03 seconds on a CPU node and wrote `scores.json` with `all_observations_consistent_rate: 100.0`.
- Final verification job `e9807e81-d04` completed in 14.81 seconds on a CPU node and wrote corrected `scores.json`, `scores_train.json`, and `scores_test.json`.
- `python validate.py --compare` passes for `reference.json`, `scores.json`, train/test artifacts, import separation, output-reading evaluation, and shared-path checks.
- `python validate.py` also passes after correcting `reference.json` so the gym-only diagnosis-output-volume proxy is not presented as a paper-reported number.
- HSD baseline expansion is implemented and wired into `scripts/reproduce.sh`, `scripts/baseline.sh`, and the root/train/test evaluators. Fresh packaged scores are pending CPU job verification before claiming a higher milestone.
- CPU job `f183bdd9-60a` successfully ran CFaults and HSD but failed validation because the runtime-efficiency primary metric tied across methods on the train slice.
- CPU job `d04c15ff-130` completed successfully after replacing the tied diagnosis-output-volume primary metric with `avg_solver_oracle_calls_per_instance`; the regenerated artifacts pass validation.

## Remaining

- Expand beyond the scaled synthetic benchmark toward the paper's augmented ISCAS85 instances.
- Add HSD-CM or a fuller ISCAS85-scale benchmark if pursuing `majority` or higher.
- Reproduce more of the paper's runtime-ranking table using machine-independent proxies or controlled solver call counts instead of wall-clock time.

## Issues

- The `python-sat[pblib,aiger]` extras attempted to build `pypblib` and failed on the login environment due to missing Python headers. Plain `python-sat` is sufficient for the implemented WCNF/RC2 workflow and installs successfully.
- A continuation audit found that the previous synthetic interface passed the injected fault map into the method as faulty-circuit semantics. This was repaired by storing an explicit faulty circuit netlist in each instance; `method/` now receives only the faulty circuit and observations, while the true fault list is retained only for evaluation summaries.
- `environment/setup.sh` installs `python-sat` for fresh compute containers.
- Continuation audit reset the working milestone to `method_runs`; job `06041b2e-9e9` refreshed the score artifact, so the milestone is restored to `core_claim`.
- The login-node Python environment does not currently have PySAT, so full local evaluation falls back to an intentionally tiny exhaustive SAT solver and is too slow for the full benchmark. The packaged container installs `python-sat`; job `e9807e81-d04` verified the corrected pipeline there.
- Final verification found that the CNF encoders for binary gates were dualized relative to `data.circuit_benchmark.eval_op`. This affected method, baseline, and evaluator code. The encoders were corrected, checked against truth tables, and validated by job `e9807e81-d04`.
- A validation audit rejected the earlier `runtime_efficiency` reference because `avg_reported_diagnoses_per_instance` was treated like a paper-reported value. The paper reports wall-clock runtime ranks, not diagnosis-output volume; `reference.json` now documents the proxy value as a corrected scaled-gym reference from job `e9807e81-d04`.
- Job `f183bdd9-60a` exposed a scoring-rubric issue: `avg_reported_diagnoses_per_instance` tied for CFaults and HSD on the train split, so it could not serve as a primary metric. The runtime-efficiency primary metric is now solver-oracle-call count, while output volume remains audit-only.

## Deviations from Paper

- Benchmark scale: the paper evaluates augmented ISCAS85 circuits with 12,147 buggy variants and observation counts 10, 20, 30, 40, and 50. This reproduction uses a tracked synthetic combinational circuit benchmark with 27 instances, observation counts 4, 8, and 16, and injected fault counts 1, 2, and 3. This keeps the problem small enough for fast reusable jobs while preserving non-trivial multi-observation diagnosis.
- Fault model subset: the paper's Boolean-circuit experiments use injected gate-level mutations on ISCAS85 circuits. This reproduction uses operator mutations on internal gates of a smaller tracked circuit. The diagnostic computation is unchanged: faulty gate semantics are guarded by shared health variables and MaxSAT minimizes relaxed gates.
- Solver library: the paper presents the approach at the MaxSAT/SMT level. This reproduction uses PySAT's WCNF and RC2 solver to implement the same unweighted partial MaxSAT objective.
