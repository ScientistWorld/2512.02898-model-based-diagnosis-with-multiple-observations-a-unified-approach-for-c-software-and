# Research Direction

## Research Problem

Exact fault localisation for Boolean circuits with multiple failing observations and multiple faults: enumerate every minimum-cardinality diagnosis that explains all observations jointly, quickly enough to scale to larger circuits, more observations and more faults. The measured quantity is the share of instances fully localised within a fixed CPU budget, with every reported diagnosis required to be a genuine minimum diagnosis.

## Core Contribution

The paper's circuit-side contribution is a formula-based diagnosis workflow that reasons about all failing observations jointly, rather than one at a time, and returns only minimal diagnoses. On the smaller ISCAS85 circuits, strong methods already localise nearly every instance at this budget. The open part is the larger circuits (1.2k to 3.5k gates), where many instances have hundreds to thousands of minimum diagnoses and the reference localises about two thirds.

## Approach Scope

Scientists may change the diagnosis encoding, solver choice and configuration, search and enumeration strategy, observation handling (for example adding observations lazily), decomposition, symmetry or dominance reasoning, circuit preprocessing, and incremental reuse of solver state. They may use SAT, MaxSAT, implicit hitting sets, constraint programming, or hybrid exact search, as long as the output is the exact set of minimum diagnoses. Learned components such as orderings, heuristics or solver configurations fitted on the public train split are allowed if the final output is still exact.

## Out of Bounds

- Returning anything other than minimum-cardinality diagnoses valid for all observations, such as rankings, supersets or single-observation explanations.
- Using CPU outside the counted budget, for example detached workers, other processes, or work done before the instance arrives that depends on hidden instances.
- Reading or touching the hidden test, the evaluator, its process, or stored baseline outputs; writing scores.
- Re-submitting a provided baseline unchanged as a new method. HSD is already scored as an evaluator-owned baseline.
