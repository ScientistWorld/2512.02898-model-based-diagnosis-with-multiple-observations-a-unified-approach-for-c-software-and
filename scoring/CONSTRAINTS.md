# Scientist Constraints

## Data

- Develop on the public train split in `data/iscas85_train/` (96 instances with exact answers in `ground_truth.json`) and the public ISCAS85 netlists fetched by `scripts/download.sh`. The hidden test has 118 instances from the same generator with a different, secret seed; it lives only with the hidden-test evaluator.
- Do not tune to individual train instances. Hidden instances differ from train ones in faults, observations, signal names and gate order.

## Interface

- Register the method as `checkpoints/<name>/solver.json` with a `command` containing `{instance}` and `{output}`. The evaluator runs it once per instance from the repository root, and the method writes one JSON list of gate names per line.
- Write only minimum-cardinality diagnoses, each once, and flush as you go. Any other line makes the instance unsound and worth 0. Self-reported fields (validity flags, counters, timings) are ignored.
- The method receives only the faulty netlist and the observations. It must not read, list, chmod, move or otherwise touch `eval/test/`: any change to that directory while the method runs marks the whole run as failed. It must also not read the evaluator's memory or files, or write to `scoring/`.

## Resources

- The per-instance budget is CPU time of the whole process tree: nominal 10 CPU-s, scaled by the evaluator's machine-speed calibration. Parallel workers, subprocesses and detached or orphaned processes all count, and the whole tree is killed when the budget is reached. Memory is limited to 8 GB per process. A wall-clock guard stops processes that block or sleep.
- Every method, including the reference and the baselines, runs under the same rules. Do not change the budget, the instances, the evaluators or the stored baseline outputs.

## Diagnosis validity

- An instance counts only if the full set of minimum-cardinality diagnoses is reported. A superset of a diagnosis, a diagnosis valid for some observations but not all, a ranked list of candidates, or the injected fault set when it is not minimum all fail the instance.
- The fault model is the weak fault model: a faulty gate's output is unconstrained, independently in each observation, and the faulty gate set is shared by all observations.

## Compliance Checklist

- [x] Method registered through `checkpoints/<name>/solver.json`; scored by `scripts/evaluate_test.sh` with no arguments
- [x] Only minimum-cardinality diagnoses consistent with all observations are reported
- [x] No access to `eval/test/`, the evaluator's process, or stored baseline outputs
- [x] All computation counted within the per-instance CPU budget of the process tree
- [x] Same instances, budget and scoring for the method and every baseline
