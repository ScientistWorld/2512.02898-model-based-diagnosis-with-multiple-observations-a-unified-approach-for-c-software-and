# Reproduction Milestones

**Current: method_runs**

## Progress Log

### [2026-06-02 00:00] - method_runs
- Audit found that the previous synthetic circuit interface passed the injected fault map into the method as faulty-circuit semantics, which was too close to exposing diagnosis labels.
- Reworked the benchmark to store an explicit faulty circuit netlist per instance and updated the method, baseline, and evaluator to consume the faulty netlist without using the ground-truth fault list.
- Fresh container verification is pending for the repaired interface.

### [2026-06-02 00:00] - core_claim
- Implemented CFaults' Boolean-circuit multiple-observation diagnosis as a unified partial MaxSAT problem with one replicated circuit per failing observation and shared health variables per original gate.
- Ran the packaged pipeline in scheduler job `565b7133-b46`; the job completed successfully and wrote method outputs plus `scoring/scores.json`.
- On the scaled synthetic circuit benchmark, CFaults returned valid minimum-cardinality diagnoses for all 27 instances, while the one-observation voting baseline localized only 3 of 27 instances.

### [2026-06-02 00:00] - method_runs
- The CFaults circuit method executes end-to-end through `scripts/reproduce.sh` inside the container.
- The evaluation pipeline reads output artifacts and validates diagnoses without importing `method/`.

## Stop Justification
- Not stopped: a repaired benchmark/method interface has been prepared and needs a fresh job before restoring `core_claim`.
