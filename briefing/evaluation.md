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
