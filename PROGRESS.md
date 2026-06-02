# Progress

## What Works

- The Boolean-circuit CFaults algorithm from the paper is implemented in `method/cfaults_circuit.py`.
- The implementation builds one replica of the circuit constraints per failing observation, shares a single health variable for each original gate across all replicas, and solves the resulting unweighted partial MaxSAT instance with PySAT RC2.
- A reusable benchmark generator in `data/circuit_benchmark.py` creates small tracked circuit-diagnosis instances with explicit faulty circuit netlists, injected gate-operator mutations, and failing observations.
- `scripts/reproduce.sh` runs the full local pipeline: generate benchmark data, run the one-observation voting baseline, run CFaults, and evaluate artifacts through `scripts/evaluate.sh`.
- `baseline/bugassist_vote_circuit.py` now implements its one-observation MaxSAT voting baseline independently of `method/`, so future method changes do not alter the baseline.
- `eval/evaluate_circuit_outputs.py` is method-agnostic: it reads result artifacts and independently checks diagnosis validity and cardinality without importing `method/`.
- Scheduler job `2147c6a7-240` verified the repaired packaged pipeline inside the compute container with exit code 0.

## Results

- Paper reference, augmented ISCAS85 localisation (Table 5): CFaults localizes 8,969 / 12,147 instances, or 73.84%.
- Scaled reproduction, synthetic circuit localisation: CFaults localizes 27 / 27 instances, or 100.0%.
- Constraint metric, scaled reproduction: CFaults returns valid minimum-cardinality diagnoses for 27 / 27 instances, with 0 invalid and 0 non-minimal outputs.
- All-observation consistency is now an explicit diagnosis-quality metric in `reference.json` and the evaluator output contract.
- Unscored sanity baseline: the one-observation voting baseline localizes 0 / 27 instances, which confirms the benchmark is not solved by considering observations independently.
- Container verification: job `2147c6a7-240` completed in 19.25 seconds on a CPU test node and reproduced the same 27 / 27 CFaults localisation result after the explicit faulty-circuit interface repair.
- `scoring/reference.json` contains the paper's reported comparison targets. `scoring/scores.json` is being regenerated after the continuation audit because the diagnosis-quality contract now includes an explicit all-observations consistency metric.

## Remaining

- Expand beyond the scaled synthetic benchmark toward the paper's augmented ISCAS85 instances.
- Add HSD or HSD-CM as scored baselines if pursuing `majority` or higher.
- Reproduce more of the paper's runtime-ranking table using machine-independent proxies or controlled solver call counts instead of wall-clock time.

## Issues

- The `python-sat[pblib,aiger]` extras attempted to build `pypblib` and failed on the login environment due to missing Python headers. Plain `python-sat` is sufficient for the implemented WCNF/RC2 workflow and installs successfully.
- A continuation audit found that the previous synthetic interface passed the injected fault map into the method as faulty-circuit semantics. This was repaired by storing an explicit faulty circuit netlist in each instance; `method/` now receives only the faulty circuit and observations, while the true fault list is retained only for evaluation summaries.
- Local login-node Python does not currently have PySAT installed. `environment/setup.sh` installs `python-sat` for compute jobs; local `python validate.py` and syntax checks pass, while full score regeneration is being submitted as a CPU test job.
- Continuation audit reset the working milestone to `method_runs` until the refreshed score artifact is produced by the CPU test job.

## Deviations from Paper

- Benchmark scale: the paper evaluates augmented ISCAS85 circuits with 12,147 buggy variants and observation counts 10, 20, 30, 40, and 50. This reproduction uses a tracked synthetic combinational circuit benchmark with 27 instances, observation counts 4, 8, and 16, and injected fault counts 1, 2, and 3. This keeps the problem small enough for fast reusable jobs while preserving non-trivial multi-observation diagnosis.
- Fault model subset: the paper's Boolean-circuit experiments use injected gate-level mutations on ISCAS85 circuits. This reproduction uses operator mutations on internal gates of a smaller tracked circuit. The diagnostic computation is unchanged: faulty gate semantics are guarded by shared health variables and MaxSAT minimizes relaxed gates.
- Solver library: the paper presents the approach at the MaxSAT/SMT level. This reproduction uses PySAT's WCNF and RC2 solver to implement the same unweighted partial MaxSAT objective.
