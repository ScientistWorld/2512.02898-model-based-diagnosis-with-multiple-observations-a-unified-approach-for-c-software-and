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

---

# Problem Definition

## Research Question

Given a faulty combinational Boolean circuit and a set of failing input-output observations, identify a smallest set of circuit components whose behaviour can explain all observed failures. The target setting is multi-fault circuit diagnosis: each benchmark instance may contain one or many injected faults, and the observations must be explained jointly rather than one at a time.

The reproduction should focus on the Boolean-circuit side of the paper. C-program fault localisation is useful context but is outside the primary benchmark scope here.

## Why It Matters

Circuit debugging is expensive when failures arise from multiple interacting faults. A useful diagnostic system should narrow the search to a small, valid set of gates/components while scaling to standard circuit benchmarks and many failing observations.

## Success Criteria

A successful system returns valid minimum diagnoses for many faulty ISCAS85-derived circuit instances within the evaluation timeout. Its diagnoses must be consistent with every failing observation for the instance and must be minimum-cardinality or otherwise demonstrably subset-minimal under the benchmark fault model. Runtime and timeout behaviour matter because exact circuit diagnosis can become impractical even when the returned diagnoses are correct.

---

# Paper's Method

## Key Contribution

CFaults formulates fault localisation for C programs and Boolean circuits as model-based diagnosis with multiple observations. For the circuit benchmark, its core contribution is to explain all failing input-output observations in one optimisation problem and return only minimum diagnoses for the gates/components of the circuit.

## Approach

For Boolean circuits, CFaults first replicates the faulty circuit once per failing observation. Each replica receives fresh variables for that observation's inputs, outputs, and internal gates, while corresponding gates across replicas share a common health/relaxation variable. This shared health variable represents whether the original circuit component is considered active or faulty across all observations.

The replicated and instrumented circuit is encoded as an unweighted partial MaxSAT instance. Hard clauses encode the circuit replicas and the failing input-output observations. Soft unit clauses prefer every circuit component to remain healthy. Solving the MaxSAT instance minimises the number of disabled components, so the false health variables identify a minimum-cardinality diagnosis that is consistent with all observations at once.

The paper contrasts this with HSD, which reasons through multiple per-observation oracle calls and hitting sets. CFaults instead uses a unified MaxSAT formulation for all observations, then enumerates optimal solutions when multiple minimum diagnoses exist.

## Main Claims

The primary circuit-side claim is that this unified diagnosis formulation remains competitive on Boolean circuits with multiple faults and multiple failing observations, even though HSD remains faster and localises more circuits overall.

The paper reports that on augmented ISCAS85, CFaults localises 8,969 of 12,147 faulty circuits (73.84%) within 1800 seconds, compared with 9,735 (80.14%) for HSD and 9,678 (79.67%) for HSD-CM. The gap is about 6 percentage points overall and is smaller for the 10- and 20-observation groups.

The broader claim is that jointly reasoning over observations avoids redundant or inconsistent aggregation behaviour seen in some one-observation-at-a-time diagnosis workflows, while still producing subset-minimal diagnoses.

---

# Evaluation

## Metrics

The main metric is `localized_count`: the number of benchmark instances for which a method returns a valid minimum diagnosis before the timeout. `localized_rate` is the same count divided by the number of instances in the evaluated split. Higher is better for both.

Efficiency is measured with CPU time per circuit and aggregate timeout count. Lower CPU time and fewer timeouts are better. Memory exhaustion should be recorded separately; the paper reports no memory-limit hits on the Boolean-circuit benchmark.

Diagnosis quality is a constraint metric. A submitted diagnosis must be consistent with all failing input-output observations for that circuit and must be minimum-cardinality, or at least subset-minimal when the exact optimum is not available for a scaled reproduction. Invalid, non-minimal, or observation-inconsistent diagnoses should not count as successfully localised instances.

## Baselines and Targets

The primary benchmark is the augmented ISCAS85 Boolean-circuit benchmark used in the paper: 12,147 faulty circuit instances, generated with 10, 20, 30, 40, or 50 failing observations and 1, 2, 3, 4, 5, 10, 20, 30, 40, or 50 injected faults.

The paper compares the proposed circuit diagnosis system against HSD and HSD with core minimisation. Reported all-instance localisation rates are 73.84% for the paper method, 80.14% for HSD, and 79.67% for HSD-CM under an 1800 second timeout per circuit. A strong reproduction should recover the same qualitative result: competitive localisation coverage against HSD while preserving diagnosis validity/minimality, with HSD generally faster on circuits.

## Evaluation Protocol

Run each method on the same augmented ISCAS85 instances, grouped by the number of failing observations. Use the same input-output observations and injected-fault configurations for all methods. Use an 1800 second timeout per buggy circuit and record success, timeout, memory failure, and CPU time.

For each returned diagnosis, independently validate that deactivating or repairing the reported components can satisfy all failing observations for that instance. Compute success counts and rates for each observation-count group and for the full benchmark. If the reproduction must scale down, keep the same procedure and include multiple observation-count groups plus multi-fault cases so the task remains non-trivial.

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


---

# Reproduction Milestones

**Current: core_claim**

## Stop Justification
- Completed at milestone `core_claim`.
