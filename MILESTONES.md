# Reproduction Milestones

**Current: core_claim**

## Progress Log

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

## Stop Justification
- Completed at milestone `core_claim`.
