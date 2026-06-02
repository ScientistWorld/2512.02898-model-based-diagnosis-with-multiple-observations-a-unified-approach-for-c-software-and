# Research Direction

## Research Problem

This benchmark is about exact or validation-backed fault localisation for Boolean circuits with multiple failing observations. The scientific question is how to identify small, correct sets of faulty circuit components in the presence of multiple injected faults while scaling to standard benchmark circuits and many observations.

## Core Contribution

The paper's circuit-side contribution is a formula-based diagnosis workflow that reasons about all failing observations jointly and returns minimal diagnoses for faulty gates/components. Future improvements should remain in this family of circuit diagnosis methods: they should improve how multi-observation circuit fault localisation is encoded, searched, decomposed, validated, or optimised.

## Approach Scope

Scientists may change the diagnosis encoding, solver strategy, search order, decomposition scheme, observation handling, blocking/enumeration strategy, validation oracle, or preprocessing of the circuit formula. They may use SAT, MaxSAT, hitting-set, constraint-programming, or hybrid exact-search techniques as long as the system still returns validated circuit-component diagnoses for all observations.

## Out of Bounds

- Switching to a different task such as fault-type classification, output prediction, or test generation without producing validated diagnoses.
- Reporting successes from diagnoses that explain only one failing observation or a subset of observations.
- Using a learned ranker as the final answer unless the selected diagnosis is independently validated and minimal under the benchmark criterion.
- Replacing the ISCAS85 benchmark with easier synthetic circuits for the main score.
- Counting oversized supersets of faulty components as successful localisations.
