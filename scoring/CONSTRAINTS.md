# Scientist Constraints

## Data

- Develop on the public train split in `data/iscas85_train/` (78 instances in `instances.jsonl.gz`, exact answers in `ground_truth.json.gz`) and the public ISCAS85 netlists fetched by `scripts/download.sh`.
- The hidden test has 158 instances from the same generator with a different, secret seed. It lives only with the hidden-test evaluator.
- Do not tune to individual train instances. Hidden instances differ from train ones in faults, observations, signal names and gate order.

## Interface

- Register the method as `checkpoints/<name>/solver.json` with a `command` containing `{instance}` and `{output}`. The evaluator runs it once per instance from the repository root, and the method writes one JSON list of gate names per line.
- Write only minimum-cardinality diagnoses, each once. Write append-only and flush as you go. Any other line makes the instance unsound and worth 0. Self-reported fields (validity flags, counters, timings) are ignored.
- The method receives only the faulty netlist and the observations.
- It must not read, list, chmod, move or otherwise touch `eval/test/`: any change to that directory while the method runs marks the whole run as failed.
- It must also not read, signal or interfere with the evaluator's process or files, or write to `scoring/`.

## Resources

- **Budget.** Each instance's budget is 3x10^10 user-space instructions retired by the method's whole process tree, counted by the evaluator with a hardware counter. Threads, subprocesses and detached or re-parented workers all count.
- **Stopping and crediting.** The tree is stopped when the budget is reached, or when the registered command's process exits. Only lines that were in the output file while the count was within budget are credited.
- **Reproducibility.** Methods run with `PYTHONHASHSEED=0` and address-space randomisation off, so deterministic methods count the same work on every run and on any evaluation node.
- **Other limits.** Memory is limited to 8 GB per process. A 240 s wall-clock guard stops processes that block or sleep. Output beyond 64 MB is not credited.
- **Same rules for all.** Every method, including the reference and the baselines, runs under the same rules. Do not change the budget, the instances, the evaluators or the stored baseline outputs.

## Diagnosis validity

- An instance counts only if the full set of minimum-cardinality diagnoses is reported. Each of these fails the instance:
  - a superset of a diagnosis;
  - a diagnosis valid for some observations but not all;
  - a ranked list of candidates;
  - the injected fault set, when it is not minimum.
- The fault model is the weak fault model: a faulty gate's output is unconstrained, independently in each observation, and the faulty gate set is shared by all observations.

## Compliance Checklist

- [x] Method registered through `checkpoints/<name>/solver.json`; scored by `scripts/evaluate_test.sh` with no arguments
- [x] Only minimum-cardinality diagnoses consistent with all observations are reported
- [x] No access to `eval/test/`, the evaluator's process, or stored baseline outputs
- [x] All computation done by the method's own process tree, within the counted per-instance budget
- [x] Same instances, budget and scoring for the method and every baseline
