# Research Direction

## Research Problem

Exact fault localisation for Boolean circuits with multiple failing observations and multiple faults: enumerate every minimum-cardinality diagnosis that explains all observations jointly, with as little work as possible, so that it scales to larger circuits, more observations and more faults. The measured quantity is the share of instances fully localised within a fixed per-instance work budget (and at fractions of it). Every reported diagnosis must be a genuine minimum diagnosis.

## Core Contribution

The paper's circuit-side contribution is a formula-based diagnosis workflow that reasons about all failing observations jointly, rather than one at a time, and returns only minimal diagnoses.

At this gym's budget, the reference localises half of the base tier (c880 to c3540, 3 to 7 faults) and about 40% of the two largest circuits. Its coverage drops sharply with more observations (68% at 10, 28% at 50) and more faults (74% at 3, 29% at 7). The provided HSD baseline localises about 78% / 68%. Many instances have hundreds to a few thousand minimum diagnoses, so both finding the minimum cardinality and enumerating all optima cheaply matter.

## Approach Scope

Scientists may change any of the following:

- the diagnosis encoding;
- the solver choice and configuration;
- the search and enumeration strategy;
- observation handling (for example adding observations lazily);
- decomposition, symmetry or dominance reasoning;
- circuit preprocessing;
- incremental reuse of solver state;
- the efficiency of the implementation itself.

They may use SAT, MaxSAT, implicit hitting sets, constraint programming, or hybrid exact search, as long as the output is the exact set of minimum diagnoses. Learned components such as orderings, heuristics or solver configurations fitted on the public train split are allowed if the final output is still exact.

## Out of Bounds

- Returning anything other than minimum-cardinality diagnoses valid for all observations, such as rankings, supersets or single-observation explanations.
- Doing work outside the counted process tree: for example handing work to processes the method did not start, or doing work before the instance arrives that depends on hidden instances.
- Reading or touching the hidden test, the evaluator, its process, or stored baseline outputs; writing scores.
- Re-submitting a provided baseline, or a variant from the audit material in `redteam/`, unchanged as a new method. HSD is already scored as an evaluator-owned baseline.
