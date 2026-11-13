# Experiment Overview

All experiments are measured on the same hidden ISCAS85-derived test instances (and identically on the public train split). The evaluator runs each method itself, instance by instance, under a fixed per-instance CPU budget covering the method's whole process tree. An instance counts as localised only if the method reports exactly the complete set of minimum-cardinality diagnoses within that budget.

## iscas85_localisation

The central question of the paper's circuit study: on how many faulty circuits does a method find all minimum diagnoses within the time limit? Measured on the base tier, the five smaller ISCAS85 circuits with 1, 3 or 5 injected faults and 10 to 50 failing observations. The paper's own reported measure is the share of instances successfully localised. Mean recall of the minimum-diagnosis sets gives partial credit when a method runs out of budget mid-way.

## diagnosis_quality

The constraint side of the paper's claim. A method must return only genuine minimum diagnoses: explanations consistent with every observation, of the smallest size, each reported once. One-observation-at-a-time aggregation tends to violate this. The experiment counts the instances, over both tiers, on which a method reported anything else. Such instances also earn nothing in the other experiments, so the constraint cannot be traded for coverage.

## observation_scaling

Whether coverage holds up as the number of failing observations grows from 10 to 50, mirroring the per-observation-count rows of the paper's circuit table. Each bucket is a distinct set of base-tier instances.

## fault_scaling

Whether coverage holds up as the number of injected faults grows from 1 to 3 to 5. More faults mean larger diagnoses and many more minimum diagnoses, which is where exhaustive candidate search stops working.

## scale_stress

Where the paper's method falls short: scale. The four larger ISCAS85 circuits (1.2k to 3.5k gates), with 3 or 5 faults and 10, 30 or 50 observations, often have hundreds to thousands of minimum diagnoses. At this gym's budget the reference localises about two thirds of these instances while the strongest baseline localises about 90%. The base tier is close to saturated for strong methods, so this tier carries the largest weight: it is where better methods can still separate themselves.
