# Model-Based Diagnosis with Multiple Observations: A Unified Approach for C Software and Boolean Circuits

| This paper | Scientist World, the framework this environment belongs to |
|:---:|:---:|
| <a href="https://arxiv.org/abs/2512.02898"><img alt="This paper on arXiv" src="https://img.shields.io/badge/arXiv-2512.02898-b31b1b?logo=arxiv&logoColor=white"></a> | <a href="https://arxiv.org/abs/2611.08478"><img alt="Scientist World on arXiv" src="https://img.shields.io/badge/arXiv-2611.08478-b31b1b?logo=arxiv&logoColor=white"></a> <a href="https://github.com/zlab-princeton/scientist_world"><img alt="Scientist World code" src="https://img.shields.io/badge/Code-Scientist_World-181717?logo=github&logoColor=white"></a> <a href="https://github.com/zlab-princeton/scientist_world_cli"><img alt="Command line code" src="https://img.shields.io/badge/Code-Command_line-181717?logo=github&logoColor=white"></a> |

| | |
|---|---|
| **Paper ID** | [2512.02898](https://arxiv.org/abs/2512.02898) |
| **Domain** | Formal methods / Boolean circuit fault localisation |
| **TL;DR** | The paper introduces CFaults, a MaxSAT-based model-diagnosis tool that localises faults from multiple observations, with the reproduction focused on its Boolean-circuit benchmark. |

## Summary

The paper studies exact fault localisation for systems with multiple failing observations. On Boolean circuits, the task is to diagnose injected faults in augmented ISCAS85 circuits from failing input-output examples. CFaults encodes all observations together and searches for minimum diagnoses, then compares against HSD and HSD-CM. The reported circuit result is competitive coverage but slower runtime than HSD.

## Problem

Given a faulty combinational Boolean circuit and a set of failing input-output observations, identify a smallest set of circuit components whose behaviour can explain all observed failures. The target setting is multi-fault circuit diagnosis: each benchmark instance may contain one or many injected faults, and the observations must be explained jointly rather than one at a time.

The reproduction should focus on the Boolean-circuit side of the paper. C-program fault localisation is useful context but is outside the primary benchmark scope here.

## The paper's method

CFaults formulates fault localisation for C programs and Boolean circuits as model-based diagnosis with multiple observations. For the circuit benchmark, its core contribution is to explain all failing input-output observations in one optimisation problem and return only minimum diagnoses for the gates/components of the circuit.

## Key results of the paper

- Augmented ISCAS85 contains 12,147 faulty circuit instances with 10-50 failing observations and 1-50 injected faults.
- CFaults localises 8,969 circuits (73.84%) within 1800 seconds.
- HSD localises 9,735 circuits (80.14%), so CFaults is about 6 percentage points lower while preserving minimum-diagnosis quality.

## Run it

```bash
pip install sciworld
sw research 2512.02898 --mode innovate --agent claude-code
sw evaluate 2512.02898
```

## More

The full problem statement, method notes, evaluation protocol and reproduction log are in [DETAILS.md](DETAILS.md).

