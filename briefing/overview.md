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
- This gym (scaled ISCAS85, 158 hidden instances, a fixed budget of 3x10^10 instructions per instance counted over the method's whole process tree): the reproduced CFaults localises 50.0% of the base-tier instances (c880-c3540, 3/5/7 faults) and 40.9% of the scale-stress tier (c5315, c7552), with no unsound output, and its coverage falls as observations grow (67.9% at 10 to 28.0% at 50). HSD localises 77.9% / 68.2% with less work. A BugAssist-style per-observation voting baseline localises almost nothing and reports non-diagnoses on 54% of instances.
