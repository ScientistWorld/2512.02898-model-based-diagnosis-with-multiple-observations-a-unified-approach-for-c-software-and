# Evaluation

## How a method is run

A method is a command registered in `checkpoints/<name>/solver.json`:

```json
{"command": ["python", "method/my_solver.py", "--instance", "{instance}", "--output", "{output}"]}
```

The evaluator itself runs the command once per instance, in a fresh process started from the repository root. It first replaces `{instance}` with a JSON file holding the instance (`id`; `circuit` with `inputs`, `outputs` and topologically ordered `gates`; `observations` with `inputs` and `expected_outputs`) and `{output}` with the path to write. The method writes one diagnosis per line as a JSON list of gate names (JSON Lines) and should flush each line as soon as it is found. Nothing else the method writes (validity flags, counters, timings) is read.

- **Budget (work, not time).** Each instance gets a budget of **3x10^10 user-space instructions retired** by the method's **whole process tree**.
  - The evaluator counts them with a hardware performance counter that it opens and owns. Every thread, subprocess and detached or re-parented worker the method starts is counted.
  - The method is stopped when the count reaches the budget. When the registered command's process exits, anything it left running is stopped too.
  - Methods run with `PYTHONHASHSEED=0` and address-space randomisation off. The count therefore does not depend on machine speed, load or chance, and reruns of a deterministic method count the same work.
  - At this budget the reference uses about 4-6 CPU-seconds per instance on the evaluation nodes. Memory is limited to 8 GB per process, a 240 s wall-clock guard stops processes that block or sleep, and output beyond 64 MB is not credited.
- **What is credited.** The evaluator watches the output file while the method runs. A line counts if it was in the file at a moment when the method's counted work was within the budget, and the work at which it appeared is recorded.
  - Write lines append-only and flush as you go: lines written before the budget runs out earn partial credit.
  - A method that rewrites lines it already wrote (truncate and rewrite, or edit in place) restarts the evaluator's observation from the new content.
- **Hidden test.** `bash scripts/evaluate_test.sh` (no arguments) runs every method registered on disk on 158 hidden instances that only the evaluator holds. While method code runs, the hidden-test directory is unreadable. A method that changes its permissions, owner, location or contents is scored as a failed run.
- **Public train split.** `bash scripts/evaluate_train.sh` (or `scripts/evaluate.sh`) applies the identical protocol to the 78 public instances in `data/iscas85_train/`. Instances are in `instances.jsonl.gz` and exact answers in `ground_truth.json.gz` (read them with `data/circuit_benchmark.py:load_train_split`).

Both splits come from the same generator. Each instance takes an ISCAS85 netlist, applies 3, 5 or 7 random gate-type changes as faults, and records 10 to 50 random input vectors on which the faulty circuit's outputs differ from the correct design. Exact answers were computed offline by complete enumeration and independently checked. Instances whose answer could not be enumerated offline (more than 4,000 minimum diagnoses, or too slow) were resampled or left out.

| Tier | Circuits | Gates | Faults | Observations | Hidden / public instances |
|---|---|---|---|---|---|
| Base | c880, c1355, c1908, c2670, c3540 | 383 to 1,669 | 3, 5, 7 | 10, 20, 30, 40, 50 | 136 / 67 |
| Scale-stress | c5315, c7552 | 2,307 to 3,512 | 3, 5, 7 | 10, 30, 50 | 22 / 11 |

## Scoring an instance

- **Localised**: the credited lines are exactly the complete set of minimum-cardinality diagnoses.
- **Recall**: the fraction of the instance's minimum diagnoses among the credited lines.
- **Unsound**: any credited line is not a minimum diagnosis. This covers diagnoses inconsistent with some observation, larger than the minimum, malformed, naming unknown gates, or repeated. An unsound instance scores 0 on localisation and recall.
- **Failed run**: a method that produces no output on any instance, or that tampers with the hidden test, receives the worst value of every metric.

## Metrics and experiments

| Experiment | Ranked metrics (better direction, coefficient) | Weight |
|---|---|---:|
| `iscas85_localisation` (base tier) | `localized_rate` ↑ (1.0), `min_diagnosis_recall` ↑ (0.5) | 0.25 |
| `diagnosis_quality` (both tiers) | `unsound_output_rate` ↓ (1.0) | 0.15 |
| `observation_scaling` (base tier) | `localized_rate_obs{10,20,30,40,50}` ↑ (0.2 each) | 0.10 |
| `fault_scaling` (base tier) | `localized_rate_f3` ↑ (0.2), `localized_rate_f5` ↑ (0.4), `localized_rate_f7` ↑ (0.4) | 0.10 |
| `scale_stress` (stress tier) | `localized_rate_stress` ↑ (1.0), `min_diagnosis_recall_stress` ↑ (0.5) | 0.25 |
| `runtime_profile` (both tiers) | `localized_rate_half_budget`, `_quarter_budget`, `_eighth_budget` ↑ (1/3 each) | 0.15 |

`runtime_profile` scores the same run at one half, one quarter and one eighth of the budget, using the work at which each line appeared. Every other field (counts, instructions, CPU seconds, injected-fault overlap of the first diagnosis, statuses) is audit-only.

A method is ranked against the reference by summing, over the ranked metrics, weight × |coefficient| × its improvement in the better direction. Each improvement is divided by that metric's spread across the attempts being compared.

## Reference and baselines (hidden test / public train)

| Method | Base `localized_rate` | Stress `localized_rate_stress` | `localized_rate_quarter_budget` | `unsound_output_rate` |
|---|---:|---:|---:|---:|
| Reference (the paper's method) | 50.0 / 40.3 | 40.9 / 45.5 | 22.8 / 19.2 | 0.0 / 0.0 |
| HSD baseline (hitting-set dualisation, the paper's circuit competitor) | 77.9 / 68.7 | 68.2 / 90.9 | 45.6 / 38.5 | 0.0 / 0.0 |
| BugAssist-style per-observation voting baseline | 0.0 / 0.0 | 4.5 / 0.0 | 0.6 / 0.0 | 54.4 / 65.4 |

The baselines' outputs are stored with each evaluator and scored like any method; registrations named `hsd` or `bugassist_vote` are ignored. The reference's coverage falls as observations grow (hidden: 67.9, 63.0, 46.4, 42.9, 28.0% at 10 to 50 observations) and as faults grow (74.0, 41.7, 28.9% at 3, 5, 7 faults). Rerunning the reference changes its instruction counts by at most 0.015% and its scores not at all. The stress tier is small (22 hidden instances), so its rates move in steps of 4.5 points.

In the paper (augmented ISCAS85, 12,147 instances, 1800 s per circuit), the method localises 73.84% and HSD 80.14%. HSD is faster on circuits, and the paper's method returns only minimal diagnoses, unlike per-observation aggregation. Those numbers are context only: the gym's instances and budget are scaled down.
