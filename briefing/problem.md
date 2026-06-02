# Problem Definition

## Research Question

Given a faulty combinational Boolean circuit and a set of failing input-output observations, identify a smallest set of circuit components whose behaviour can explain all observed failures. The target setting is multi-fault circuit diagnosis: each benchmark instance may contain one or many injected faults, and the observations must be explained jointly rather than one at a time.

The reproduction should focus on the Boolean-circuit side of the paper. C-program fault localisation is useful context but is outside the primary benchmark scope here.

## Why It Matters

Circuit debugging is expensive when failures arise from multiple interacting faults. A useful diagnostic system should narrow the search to a small, valid set of gates/components while scaling to standard circuit benchmarks and many failing observations.

## Success Criteria

A successful system returns valid minimum diagnoses for many faulty ISCAS85-derived circuit instances within the evaluation timeout. Its diagnoses must be consistent with every failing observation for the instance and must be minimum-cardinality or otherwise demonstrably subset-minimal under the benchmark fault model. Runtime and timeout behaviour matter because exact circuit diagnosis can become impractical even when the returned diagnoses are correct.
