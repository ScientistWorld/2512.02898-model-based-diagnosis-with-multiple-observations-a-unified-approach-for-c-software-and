# Overview

- **Paper ID:** 2512.02898
- **Title:** Model-Based Diagnosis with Multiple Observations: A Unified Approach for C Software and Boolean Circuits
- **Domain:** Formal methods / Boolean circuit fault localisation
- **TL;DR:** The paper introduces CFaults, a MaxSAT-based model-diagnosis tool that localises faults from multiple observations, with the reproduction focused on its Boolean-circuit benchmark.

## Short Summary

The paper studies exact fault localisation for systems with multiple failing observations. On Boolean circuits, the task is to diagnose injected faults in augmented ISCAS85 circuits from failing input-output examples. CFaults encodes all observations together and searches for minimum diagnoses, then compares against HSD and HSD-CM. The reported circuit result is competitive coverage but slower runtime than HSD.

## Key Results

- Augmented ISCAS85 contains 12,147 faulty circuit instances with 10-50 failing observations and 1-50 injected faults.
- CFaults localises 8,969 circuits (73.84%) within 1800 seconds.
- HSD localises 9,735 circuits (80.14%), so CFaults is about 6 percentage points lower while preserving minimum-diagnosis quality.
- This gym (scaled ISCAS85, hidden test, ~10 CPU-s per instance): the reproduced CFaults localises 97.3% of the base-tier instances (c432-c1908) and 67.4% of the scale-stress tier (c2670-c7552), with no unsound output; HSD localises 100% / 90.7% and is faster on every instance both solve; a BugAssist-style per-observation voting baseline localises 10.7% / 2.3% and reports non-diagnoses on 43% of instances.

---

# Problem Definition

## Research Question

Given a faulty combinational Boolean circuit and a set of failing input/output observations, find **every minimum-cardinality diagnosis**: every smallest set of gates which, if declared faulty, makes the circuit consistent with *all* observations at once. Each benchmark instance can contain one or several injected faults, and the observations must be explained jointly: a faulty gate is the same gate in every observation.

The benchmark is built from the ISCAS85 combinational circuits (the circuit benchmark of the paper). C-program fault localisation, which the paper also studies, is out of scope here.

## Formal setting

- A circuit has primary inputs, primary outputs and gates (AND, NAND, OR, NOR with two or more inputs; XOR with two inputs; NOT; BUF), listed in topological order. Signal names are obfuscated and the gate order is shuffled, so instances cannot be matched to the public netlists by name.
- An observation is one primary-input vector together with the *expected* (correct-design) value of every primary output. On each observation the faulty circuit disagrees with at least one expected output.
- Fault model (weak fault model, as in model-based diagnosis): a gate declared faulty may output any value, independently in each observation; every other gate computes its function. A set of gates D is a **diagnosis** if, with the gates in D faulty, there is an assignment to the circuit's wires that satisfies every gate outside D and reproduces the inputs and expected outputs of every observation.
- A **minimum-cardinality diagnosis** is a diagnosis of the smallest possible size k*. Instances usually have several (up to a few thousand) minimum diagnoses; the injected fault set is one explanation but is not necessarily minimum, and it is not the target.

## Why It Matters

Formula-based fault localisation gives exact, verifiable explanations of failures, but its cost grows quickly with circuit size, the number of observations and the number of faults. Methods that reason about observations one at a time can return explanations that are not consistent with all failures, or redundant non-minimal ones. A useful method returns only valid minimum diagnoses, all of them, quickly enough to scale to larger circuits and more observations.

## Success Criteria

An instance counts as **localised** when the method reports, within the per-instance CPU budget, exactly the complete set of minimum-cardinality diagnoses and nothing else: every reported diagnosis must be a diagnosis for all observations, of minimum size, well formed and reported once. Coverage is measured on smaller circuits (c432 to c1908) and on larger ones (c2670 to c7552), across 10 to 50 observations and 1, 3 or 5 injected faults. Reporting anything that is not a minimum diagnosis fails the instance, and is tracked as a constraint violation.

---

# Paper's Method

## Key Contribution

CFaults formulates fault localisation for C programs and Boolean circuits as model-based diagnosis with multiple observations. For the circuit benchmark, its core contribution is to explain all failing input-output observations in one optimisation problem and return only minimum diagnoses for the gates/components of the circuit.

## Approach

For Boolean circuits, CFaults first replicates the faulty circuit once per failing observation. Each replica receives fresh variables for that observation's inputs, outputs, and internal gates, while corresponding gates across replicas share a common health/relaxation variable. This shared health variable represents whether the original circuit component is considered active or faulty across all observations.

The replicated and instrumented circuit is encoded as an unweighted partial MaxSAT instance. Hard clauses encode the circuit replicas and the failing input-output observations. Soft unit clauses prefer every circuit component to remain healthy. Solving the MaxSAT instance minimises the number of disabled components, so the false health variables identify a minimum-cardinality diagnosis that is consistent with all observations at once.

The paper contrasts this with HSD, which reasons through multiple per-observation oracle calls and hitting sets. CFaults instead uses a unified MaxSAT formulation for all observations, then enumerates optimal solutions when multiple minimum diagnoses exist (Algorithm 5): after each optimum, a blocking clause over the disabled health variables is added to the hard clauses and the MaxSAT oracle (RC2Stratified from PySAT, as in the paper) is called again, until the optimum cost increases. As in the authors' public CFaults tool, one oracle is kept for the whole enumeration and each blocking clause is added to it incrementally (`method/cfaults_circuit.py`).

## Main Claims

The primary circuit-side claim is that this unified diagnosis formulation remains competitive on Boolean circuits with multiple faults and multiple failing observations, even though HSD remains faster and localises more circuits overall.

The paper reports that on augmented ISCAS85, CFaults localises 8,969 of 12,147 faulty circuits (73.84%) within 1800 seconds, compared with 9,735 (80.14%) for HSD and 9,678 (79.67%) for HSD-CM. The gap is about 6 percentage points overall and is smaller for the 10- and 20-observation groups.

The broader claim is that jointly reasoning over observations avoids redundant or inconsistent aggregation behaviour seen in some one-observation-at-a-time diagnosis workflows, while still producing subset-minimal diagnoses.

---

# Evaluation

## How a method is run

A method is a command registered in `checkpoints/<name>/solver.json`:

```json
{"command": ["python", "method/my_solver.py", "--instance", "{instance}", "--output", "{output}"]}
```

The evaluator itself runs the command once per instance, in a fresh process started from the repository root, after replacing `{instance}` with a JSON file holding the instance (`id`, `circuit` with `inputs`, `outputs` and topologically ordered `gates`, and `observations` with `inputs` and `expected_outputs`) and `{output}` with the path to write. The method writes one diagnosis per line as a JSON list of gate names (JSON Lines), and should flush each line as soon as it is found: lines already written when the budget runs out still earn partial credit. Nothing else the method writes (validity flags, counters, timings) is read.

- **Budget.** Each instance gets a nominal 10 CPU-seconds, scaled by a machine-speed factor that the evaluator measures with a fixed workload at the start of every evaluation (clamped to [0.67, 1.5]). The budget covers the CPU time of the **whole process tree** the method starts: threads, subprocesses, and detached or orphaned workers all count, and the whole tree is stopped when it reaches the budget. Memory is limited to 8 GB per process, and a wall-clock guard of twice the budget plus 10 s stops processes that sleep or block.
- **Hidden test.** `bash scripts/evaluate_test.sh` (no arguments) runs every method registered on disk on 118 hidden instances that only the evaluator holds. While method code runs, the hidden-test directory is unreadable; a method that changes its permissions, owner, location or contents is scored as a failed run.
- **Public train split.** `bash scripts/evaluate_train.sh` (or `scripts/evaluate.sh`) applies the identical protocol to the 96 public instances in `data/iscas85_train/` (instances in `instances.jsonl`, exact answers in `ground_truth.json`).

Both splits come from the same generator: an ISCAS85 netlist, 1, 3 or 5 random gate-type changes as faults, and 10 to 50 random input vectors on which the faulty circuit's outputs differ from the correct design. Exact answers were computed offline by exhaustive enumeration and independently checked. The **base tier** (c432, c499, c880, c1355 and c1908: 160 to 880 gates; 1, 3 or 5 faults; 10, 20, 30, 40 or 50 observations) has 75 instances in each split. The **scale-stress tier** (c2670, c3540, c5315 and c7552: 1.2k to 3.5k gates; 3 or 5 faults; 10, 30 or 50 observations; up to about 6,000 minimum diagnoses per instance) has 43 hidden and 21 public instances.

## Scoring an instance

- **Localised**: the reported lines are exactly the complete set of minimum-cardinality diagnoses, and the tree stayed within the budget.
- **Recall**: the fraction of the instance's minimum diagnoses that were reported.
- **Unsound**: any reported line is not a minimum diagnosis. This covers diagnoses inconsistent with some observation, larger than the minimum, malformed, naming unknown gates, or repeated. An unsound instance scores 0 on localisation and recall. Exceeding the budget also scores 0.
- **Failed run**: a method that produces no output on any instance, or that tampers with the hidden test, receives the worst value of every metric.

## Metrics and experiments

| Experiment | Ranked metrics (better direction) | Weight |
|---|---|---:|
| `iscas85_localisation` (base tier) | `localized_rate` ↑ (coef. 1.0), `min_diagnosis_recall` ↑ (0.5) | 0.25 |
| `diagnosis_quality` (both tiers) | `unsound_output_rate` ↓ (1.0) | 0.15 |
| `observation_scaling` (base tier) | `localized_rate_obs{10,20,30,40,50}` ↑ (0.2 each) | 0.10 |
| `fault_scaling` (base tier) | `localized_rate_f1` ↑ (0.2), `localized_rate_f3` ↑ (0.4), `localized_rate_f5` ↑ (0.4) | 0.10 |
| `scale_stress` (stress tier) | `localized_rate_stress` ↑ (1.0), `min_diagnosis_recall_stress` ↑ (0.5) | 0.40 |

Every other field (counts, CPU seconds, injected-fault overlap of the first diagnosis, statuses) is audit-only. A method is ranked against the reference by summing, over the ranked metrics, weight × |coefficient| × its improvement in the better direction, with each improvement divided by that metric's spread across the attempts being compared.

## Reference and baselines (hidden test / public train)

| Method | Base `localized_rate` | Stress `localized_rate_stress` | `unsound_output_rate` |
|---|---:|---:|---:|
| Reference (the paper's method) | 97.3 / 96.0 | 67.4 / 66.7 | 0.0 / 0.0 |
| HSD baseline (hitting-set dualisation, the paper's circuit competitor) | 100.0 / 100.0 | 90.7 / 76.2 | 0.0 / 0.0 |
| BugAssist-style per-observation voting baseline | 10.7 / 9.3 | 2.3 / 0.0 | 43.2 / 44.8 |

The baselines' outputs are stored with each evaluator and scored like any method; registrations named `hsd` or `bugassist_vote` are ignored. Because the budget depends on the measured machine speed, repeated runs of the same method differ by a few points on the stress tier: three runs of the reference spanned 65.1 to 67.4%.

In the paper (augmented ISCAS85, 12,147 instances, 1800 s per circuit), the method localises 73.84% and HSD 80.14%. HSD is faster on circuits, and the paper's method returns only minimal diagnoses, unlike per-observation aggregation. Those numbers are context only; the gym's instances and budget are scaled down.

---

# Reproduction Log

### Iteration 1: gpt-5.5
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 12m | **GPU**: 0.0h
- **Jobs**: 1 total (1 completed, 0 failed)

<details>
<summary>Progress Log</summary>

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

### [2026-06-02 11:00] - core_claim
- Scheduler job `565b7133-b46` ran `scripts/run.sh` successfully in the compute container with exit code 0.
- The packaged reproduction completed in 56 seconds on a CPU test node and wrote the expected `scoring/scores.json` structure.
- Verified that the container path reproduces the same CFaults result: 27 / 27 valid minimum-cardinality diagnoses on the scaled benchmark.

</details>

### Iteration 2: gpt-5.5
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 5m | **GPU**: 0.0h
- **Jobs**: 2 total (2 completed, 0 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 11:06] - core_claim
- Scheduler job `2147c6a7-240` completed successfully after the faulty-circuit interface repair.
- The repaired pipeline ran through `scripts/reproduce.sh` inside the container with PySAT RC2 and regenerated `scoring/scores.json`.
- CFaults localised 27 / 27 scaled synthetic circuit instances with 0 invalid and 0 non-minimal diagnoses; the one-observation voting baseline localised 0 / 27.

### [2026-06-02 00:00] - method_runs
- Audit found that the previous synthetic circuit interface passed the injected fault map into the method as faulty-circuit semantics, which was too close to exposing diagnosis labels.
- Reworked the benchmark to store an explicit faulty circuit netlist per instance and updated the method, baseline, and evaluator to consume the faulty netlist without using the ground-truth fault list.
- Submitted CPU test job `2147c6a7-240` for fresh container verification.

### [2026-06-02 00:00] - core_claim
- Implemented CFaults' Boolean-circuit multiple-observation diagnosis as a unified partial MaxSAT problem with one replicated circuit per failing observation and shared health variables per original gate.
- Ran the packaged pipeline in scheduler job `565b7133-b46`; the job completed successfully and wrote method outputs plus `scoring/scores.json`.
- On the scaled synthetic circuit benchmark, CFaults returned valid minimum-cardinality diagnoses for all 27 instances, while the one-observation voting baseline localized only 3 of 27 instances.

### [2026-06-02 00:00] - method_runs
- The CFaults circuit method executes end-to-end through `scripts/reproduce.sh` inside the container.
- The evaluation pipeline reads output artifacts and validates diagnoses without importing `method/`.

</details>

### Iteration 3: gpt-5.5
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 7m | **GPU**: 0.0h
- **Jobs**: 3 total (3 completed, 0 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 4: gpt-5.5 (designer_stage_1)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 6m | **GPU**: 0.0h
- **Jobs**: 3 total (3 completed, 0 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 5: gpt-5.5 (designer_stage_2)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 4m | **GPU**: 0.0h
- **Jobs**: 3 total (3 completed, 0 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 6: gpt-5.5 (designer_stage_3)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 6m | **GPU**: 0.0h
- **Jobs**: 5 total (5 completed, 0 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 7: gpt-5.5 (packager)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 2m | **GPU**: 0.0h
- **Jobs**: 5 total (5 completed, 0 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 8: gpt-5.5 (verifier)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 7m | **GPU**: 0.0h
- **Jobs**: 6 total (6 completed, 0 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 12:05] - method_runs
- Patched the top-level reusable evaluator to emit the selected-fault overlap, output-completeness, and diagnosis-volume metrics already expected by `reference.json`.
- Reset the active milestone to `method_runs` pending a fresh packaged CPU validation job, because `scoring/scores.json` must be regenerated after the evaluator change.
- Updated `scripts/run.sh` to run the full reproduce/evaluate/validate pipeline in the compute container.

### [2026-06-02 12:28] - method_runs
- Final verification found a critical Boolean-gate encoding bug: the CNF clauses for binary gates did not match the data generator's circuit semantics.
- Corrected `AND`, `OR`, `NAND`, and `NOR` encodings in method, baseline, and evaluator code.
- Verified the corrected encodings by truth table locally; fresh packaged scoring is pending a CPU test job before `core_claim` can be restored.

### [2026-06-02 12:49] - core_claim
- CPU job `e9807e81-d04` completed successfully after the Boolean-gate repair and regenerated root, train, and test score artifacts.
- Restored `core_claim`: the corrected CFaults implementation localizes all 27 scaled synthetic circuit instances, and every counted diagnosis is valid, minimum-cardinality, and consistent with all observations.
- Verified the final scoring contract with `python validate.py --compare`; all checks passed.

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 9: gpt-5.5 (verifier)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 10m | **GPU**: 0.0h
- **Jobs**: 8 total (7 completed, 1 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 12:05] - method_runs
- Patched the top-level reusable evaluator to emit the selected-fault overlap, output-completeness, and diagnosis-volume metrics already expected by `reference.json`.
- Reset the active milestone to `method_runs` pending a fresh packaged CPU validation job, because `scoring/scores.json` must be regenerated after the evaluator change.
- Updated `scripts/run.sh` to run the full reproduce/evaluate/validate pipeline in the compute container.

### [2026-06-02 12:28] - method_runs
- Final verification found a critical Boolean-gate encoding bug: the CNF clauses for binary gates did not match the data generator's circuit semantics.
- Corrected `AND`, `OR`, `NAND`, and `NOR` encodings in method, baseline, and evaluator code.
- Verified the corrected encodings by truth table locally; fresh packaged scoring is pending a CPU test job before `core_claim` can be restored.

### [2026-06-02 12:49] - core_claim
- CPU job `e9807e81-d04` completed successfully after the Boolean-gate repair and regenerated root, train, and test score artifacts.
- Restored `core_claim`: the corrected CFaults implementation localizes all 27 scaled synthetic circuit instances, and every counted diagnosis is valid, minimum-cardinality, and consistent with all observations.
- Verified the final scoring contract with `python validate.py --compare`; all checks passed.

### [2026-06-02 12:52] - core_claim
- Fixed `reference.json` for the gym-only runtime-efficiency proxy: the paper does not report diagnosis-output volume, so the reference now labels the value as a corrected scaled-gym reference from job `e9807e81-d04`.
- Re-ran both `python validate.py` and `python validate.py --compare`; all checks passed.

### [2026-06-02 12:07] - core_claim
- CPU job `f183bdd9-60a` ran the expanded CFaults/HSD pipeline but failed validation because `avg_reported_diagnoses_per_instance` tied across methods on the train slice.
- Replaced the runtime-efficiency primary metric with `avg_solver_oracle_calls_per_instance`, added explicit solver-oracle-call fields to CFaults and HSD outputs, and kept diagnosis-output volume as audit-only.
- Local `python validate.py --compare` now passes; a packaged CPU rerun is pending to regenerate the score artifacts from scratch.

### [2026-06-02 12:14] - core_claim
- CPU job `d04c15ff-130` completed successfully after the runtime-efficiency scoring repair.
- Regenerated CFaults/HSD root, train, and test score artifacts with explicit solver-oracle-call metrics.
- `python validate.py --compare` passes for scoring, train/test consistency, output-reading evaluation, import separation, and shared-path checks.

### [2026-06-02 11:56] - core_claim
- Added an HSD-style circuit baseline that follows the paper's multiple-observation hitting-set dualisation comparison path.
- Wired the HSD artifact into the reusable root, train, and test evaluators while keeping BugAssist voting as an unscored sanity baseline.
- Kept the milestone at `core_claim` because the expanded scored comparison still needs a packaged CPU verification job.

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 10: gpt-6.1-sol (redteam)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 12m | **GPU**: 0.0h
- **Jobs**: 8 total (7 completed, 1 failed)

<details>
<summary>Progress Log</summary>

### [2026-06-02 12:05] - method_runs
- Patched the top-level reusable evaluator to emit the selected-fault overlap, output-completeness, and diagnosis-volume metrics already expected by `reference.json`.
- Reset the active milestone to `method_runs` pending a fresh packaged CPU validation job, because `scoring/scores.json` must be regenerated after the evaluator change.
- Updated `scripts/run.sh` to run the full reproduce/evaluate/validate pipeline in the compute container.

### [2026-06-02 12:28] - method_runs
- Final verification found a critical Boolean-gate encoding bug: the CNF clauses for binary gates did not match the data generator's circuit semantics.
- Corrected `AND`, `OR`, `NAND`, and `NOR` encodings in method, baseline, and evaluator code.
- Verified the corrected encodings by truth table locally; fresh packaged scoring is pending a CPU test job before `core_claim` can be restored.

### [2026-06-02 12:49] - core_claim
- CPU job `e9807e81-d04` completed successfully after the Boolean-gate repair and regenerated root, train, and test score artifacts.
- Restored `core_claim`: the corrected CFaults implementation localizes all 27 scaled synthetic circuit instances, and every counted diagnosis is valid, minimum-cardinality, and consistent with all observations.
- Verified the final scoring contract with `python validate.py --compare`; all checks passed.

### [2026-06-02 12:52] - core_claim
- Fixed `reference.json` for the gym-only runtime-efficiency proxy: the paper does not report diagnosis-output volume, so the reference now labels the value as a corrected scaled-gym reference from job `e9807e81-d04`.
- Re-ran both `python validate.py` and `python validate.py --compare`; all checks passed.

### [2026-06-02 12:07] - core_claim
- CPU job `f183bdd9-60a` ran the expanded CFaults/HSD pipeline but failed validation because `avg_reported_diagnoses_per_instance` tied across methods on the train slice.
- Replaced the runtime-efficiency primary metric with `avg_solver_oracle_calls_per_instance`, added explicit solver-oracle-call fields to CFaults and HSD outputs, and kept diagnosis-output volume as audit-only.
- Local `python validate.py --compare` now passes; a packaged CPU rerun is pending to regenerate the score artifacts from scratch.

### [2026-06-02 12:14] - core_claim
- CPU job `d04c15ff-130` completed successfully after the runtime-efficiency scoring repair.
- Regenerated CFaults/HSD root, train, and test score artifacts with explicit solver-oracle-call metrics.
- `python validate.py --compare` passes for scoring, train/test consistency, output-reading evaluation, import separation, and shared-path checks.

### [2026-06-02 11:56] - core_claim
- Added an HSD-style circuit baseline that follows the paper's multiple-observation hitting-set dualisation comparison path.
- Wired the HSD artifact into the reusable root, train, and test evaluators while keeping BugAssist voting as an unscored sanity baseline.
- Kept the milestone at `core_claim` because the expanded scored comparison still needs a packaged CPU verification job.

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>

### Iteration 11: claude-opus-5-5 (hardener)
- **Milestone**: `core_claim` | **Status**: done
- **Working time**: 31m | **GPU**: 0.0h
- **Jobs**: 14 total (12 completed, 1 failed)

<details>
<summary>Progress Log</summary>

### [2026-11-13 00:30] - core_claim
- Hardening iteration 11 (part 2): the reproduced CFaults circuit method (unified multi-observation MaxSAT, RC2Stratified, incremental Algorithm 5 enumeration) localises 97.3% of the hidden base-tier and 67.4% of the hidden scale-stress ISCAS85 instances with no unsound output; HSD 100% / 90.7% and faster, per-observation voting 10.7% / 2.3% with 43% unsound, matching the paper's circuit claims in direction.
- Closed CPU-escape, chmod-and-read and evaluator-memory loopholes; every shortcut now ranks below the reference (HARDENING.md).

### [2026-06-02 12:05] - method_runs
- Patched the top-level reusable evaluator to emit the selected-fault overlap, output-completeness, and diagnosis-volume metrics already expected by `reference.json`.
- Reset the active milestone to `method_runs` pending a fresh packaged CPU validation job, because `scoring/scores.json` must be regenerated after the evaluator change.
- Updated `scripts/run.sh` to run the full reproduce/evaluate/validate pipeline in the compute container.

### [2026-06-02 12:28] - method_runs
- Final verification found a critical Boolean-gate encoding bug: the CNF clauses for binary gates did not match the data generator's circuit semantics.
- Corrected `AND`, `OR`, `NAND`, and `NOR` encodings in method, baseline, and evaluator code.
- Verified the corrected encodings by truth table locally; fresh packaged scoring is pending a CPU test job before `core_claim` can be restored.

### [2026-06-02 12:49] - core_claim
- CPU job `e9807e81-d04` completed successfully after the Boolean-gate repair and regenerated root, train, and test score artifacts.
- Restored `core_claim`: the corrected CFaults implementation localizes all 27 scaled synthetic circuit instances, and every counted diagnosis is valid, minimum-cardinality, and consistent with all observations.
- Verified the final scoring contract with `python validate.py --compare`; all checks passed.

### [2026-06-02 12:52] - core_claim
- Fixed `reference.json` for the gym-only runtime-efficiency proxy: the paper does not report diagnosis-output volume, so the reference now labels the value as a corrected scaled-gym reference from job `e9807e81-d04`.
- Re-ran both `python validate.py` and `python validate.py --compare`; all checks passed.

### [2026-06-02 12:07] - core_claim
- CPU job `f183bdd9-60a` ran the expanded CFaults/HSD pipeline but failed validation because `avg_reported_diagnoses_per_instance` tied across methods on the train slice.
- Replaced the runtime-efficiency primary metric with `avg_solver_oracle_calls_per_instance`, added explicit solver-oracle-call fields to CFaults and HSD outputs, and kept diagnosis-output volume as audit-only.
- Local `python validate.py --compare` now passes; a packaged CPU rerun is pending to regenerate the score artifacts from scratch.

### [2026-06-02 12:14] - core_claim
- CPU job `d04c15ff-130` completed successfully after the runtime-efficiency scoring repair.
- Regenerated CFaults/HSD root, train, and test score artifacts with explicit solver-oracle-call metrics.
- `python validate.py --compare` passes for scoring, train/test consistency, output-reading evaluation, import separation, and shared-path checks.

### [2026-06-02 11:56] - core_claim
- Added an HSD-style circuit baseline that follows the paper's multiple-observation hitting-set dualisation comparison path.
- Wired the HSD artifact into the reusable root, train, and test evaluators while keeping BugAssist voting as an unscored sanity baseline.
- Kept the milestone at `core_claim` because the expanded scored comparison still needs a packaged CPU verification job.

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

</details>


---

# Reproduction Milestones

**Current: core_claim**

## Stop Justification
- Completed at milestone `core_claim`.
