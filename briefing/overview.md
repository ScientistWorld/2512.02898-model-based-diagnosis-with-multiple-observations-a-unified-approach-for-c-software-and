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
- This gym (scaled ISCAS85, hidden test, ~10 CPU-s per instance): the reproduced CFaults localises 97.3% of the base-tier instances (c432-c1908) and 67.4% of the scale-stress tier (c2670-c7552), with no unsound output; HSD localises 100% / 90.7% and is faster on every instance both solve; a BugAssist-style per-observation voting baseline localises 10.7% / 2.3% and reports non-diagnoses on 43% of instances.
