# Experiment Overview

All experiments are measured on the same hidden ISCAS85-derived test instances, and identically on the public train split.

- The evaluator runs each method itself, instance by instance.
- Each instance has a fixed work budget: instructions counted over the method's whole process tree, so the result does not depend on machine speed.
- An instance counts as localised only if the method reports exactly the complete set of minimum-cardinality diagnoses within that budget.

## iscas85_localisation

The central question of the paper's circuit study: on how many faulty circuits does a method find all minimum diagnoses within the limit?

- **Instances:** the base tier, five mid-size ISCAS85 circuits with 3, 5 or 7 injected faults and 10 to 50 failing observations.
- **Measure:** the share of instances successfully localised, the paper's own reported measure.
- **Partial credit:** mean recall of the minimum-diagnosis sets, for a method that runs out of budget mid-way.

## diagnosis_quality

The constraint side of the paper's claim.

- A method must return only genuine minimum diagnoses: explanations consistent with every observation, of the smallest size, each reported once.
- One-observation-at-a-time aggregation tends to violate this.
- The experiment counts the instances, over both tiers, on which a method reported anything else. Such instances also earn nothing in the other experiments, so the constraint cannot be traded for coverage.

## observation_scaling

Whether coverage holds up as the number of failing observations grows from 10 to 50, mirroring the per-observation-count rows of the paper's circuit table. Each bucket is a distinct set of base-tier instances.

## fault_scaling

Whether coverage holds up as the number of injected faults grows from 3 to 5 to 7. More faults mean larger diagnoses and many more of them, which is where exhaustive candidate search stops working and enumeration cost dominates.

## scale_stress

Where the paper's method falls short: scale.

- **Instances:** the two largest ISCAS85 circuits (2.3k and 3.5k gates), with 3, 5 or 7 faults and 10, 30 or 50 observations.
- **Same rules:** budget and scoring are identical to the main experiment.
- **Why it matters:** the formulas are largest here and many instances have hundreds of minimum diagnoses.

## runtime_profile

How much work a method needs, mirroring the paper's CPU-time comparison (its cactus plot).

- **Measure:** the share of all instances localised within one half, one quarter and one eighth of the budget.
- **Read from the same run:** each diagnosis is credited at the work at which it was written.
- **What it rewards:** a method that localises the same instances with less work scores higher here, even when both finish within the full budget.
