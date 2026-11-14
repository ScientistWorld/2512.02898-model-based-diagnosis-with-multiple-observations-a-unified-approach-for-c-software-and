# Problem Definition

## Research Question

Given a faulty combinational Boolean circuit and a set of failing input/output observations, find **every minimum-cardinality diagnosis**: every smallest set of gates which, if declared faulty, makes the circuit consistent with *all* observations at once. Each benchmark instance can contain one or several injected faults, and the observations must be explained jointly: a faulty gate is the same gate in every observation.

The benchmark is built from the ISCAS85 combinational circuits (the circuit benchmark of the paper). C-program fault localisation, which the paper also studies, is out of scope here.

## Formal setting

- A circuit has primary inputs, primary outputs and gates (AND, NAND, OR, NOR with two or more inputs; XOR with two inputs; NOT; BUF), listed in topological order. Signal names are obfuscated and the gate order is shuffled, so instances cannot be matched to the public netlists by name.
- An observation is one primary-input vector together with the *expected* (correct-design) value of every primary output. On each observation the faulty circuit disagrees with at least one expected output.
- Fault model (weak fault model, as in model-based diagnosis): a gate declared faulty may output any value, independently in each observation; every other gate computes its function. A set of gates D is a **diagnosis** if, with the gates in D faulty, there is an assignment to the circuit's wires that satisfies every gate outside D and reproduces the inputs and expected outputs of every observation.
- A **minimum-cardinality diagnosis** is a diagnosis of the smallest possible size k*. Instances usually have several (up to 4,000) minimum diagnoses; the injected fault set is one explanation but is not necessarily minimum, and it is not the target.

## Why It Matters

Formula-based fault localisation gives exact, verifiable explanations of failures, but its cost grows quickly with circuit size, the number of observations and the number of faults. Methods that reason about observations one at a time can return explanations that are not consistent with all failures, or redundant non-minimal ones. A useful method returns only valid minimum diagnoses, all of them, quickly enough to scale to larger circuits and more observations.

## Success Criteria

An instance counts as **localised** when the method reports, within the per-instance work budget, exactly the complete set of minimum-cardinality diagnoses and nothing else: every reported diagnosis must be a diagnosis for all observations, of minimum size, well formed and reported once. Coverage is measured on mid-size circuits (c880 to c3540) and on the two largest ones (c5315 and c7552), across 10 to 50 observations and 3, 5 or 7 injected faults, and also at fractions of the budget (how much work a method needs). Reporting anything that is not a minimum diagnosis fails the instance, and is tracked as a constraint violation.
