# Reproduction Milestones

**Current: core_claim**

## Progress Log

### [2026-06-02 00:00] - core_claim
- Implemented CFaults' Boolean-circuit multiple-observation diagnosis as a unified partial MaxSAT problem with one replicated circuit per failing observation and shared health variables per original gate.
- Ran the packaged pipeline in scheduler job `565b7133-b46`; the job completed successfully and wrote method outputs plus `scoring/scores.json`.
- On the scaled synthetic circuit benchmark, CFaults returned valid minimum-cardinality diagnoses for all 27 instances, while the one-observation voting baseline localized only 3 of 27 instances.

### [2026-06-02 00:00] - method_runs
- The CFaults circuit method executes end-to-end through `scripts/reproduce.sh` inside the container.
- The evaluation pipeline reads output artifacts and validates diagnoses without importing `method/`.

## Stop Justification
- Completed at milestone `core_claim` on a scaled synthetic Boolean-circuit benchmark. Higher milestones would require expanding to augmented ISCAS85 and adding HSD/HSD-CM reproductions.
