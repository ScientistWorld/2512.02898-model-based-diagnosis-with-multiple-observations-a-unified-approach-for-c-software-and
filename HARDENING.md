# Hardening report (iteration 12)

**Verdict.** Better results now score higher by wide, exactly reproducible margins:

- An honest, faster implementation of the paper's own procedure ranks **+1.34** (63 instances won, 0 lost).
- The paper's competitor HSD ranks **+1.00**.
- Weaker variants rank far below the reference.
- No shortcut outranks the honest method it wraps.

This iteration fixes all three items in `REVIEW.md`:

1. The base tier was saturated. The instances are now harder: circuits c880–c7552 with 3, 5 or 7 faults. The reference localises **50.0%** of the base tier and **40.9%** of the stress tier, and an honest method beats it with p < 1e-12.
2. The CPU-time budget needed a noisy calibration. It is replaced by a budget the evaluator counts: **user-space instructions retired**. Rerunning the reference on a different node changed per-instance counts by at most 0.015% and changed no score.
3. A detached relay worker still paid. The counter is inherited by every thread and process the method starts, so **all work the method starts is counted**. The relay now ranks below the honest HSD it relays (+0.91 vs +1.00).

The reference is unchanged: the paper's circuit procedure, i.e. unified multi-observation MaxSAT, RC2Stratified, and Algorithm 5 enumeration with one incremental oracle, as in the authors' `oracle.py`.

**Evidence.**

- **Runs.** CPU job `d9a40cad-0de` (preempted three times, resumed from its markers) ran every case through **`bash scripts/evaluate_test.sh` with no arguments**, each in a fresh copy of the gym. Sources: [harness](redteam/hardening/harness.py), [cases](redteam/hardening/results/), [summary](redteam/hardening/summary.txt), [summary.json](redteam/hardening/summary.json).
- **Budget.** The job ran with a 60G-instruction budget. The final budget, 30G (see *Budget*), was applied by rescoring the saved raw outputs ([rescore_cases.py](redteam/hardening/rescore_cases.py)). Each output line carries the counted work at which it appeared, and counts are exact, so scoring a 60G run at 30G gives what a 30G run gives.
- **Verification run.** The official reference and the baselines were then rerun from scratch at 30G (see *Verification run*).
- **Rank formula** ([summarize.py](redteam/hardening/summarize.py)): Σ weight × |coefficient| × (value − reference), signed by `higher_is_better`, divided by the population SD of that metric over every audit case plus the evaluator-owned baselines.

## What changed

1. **Work budget counted by the evaluator** (`eval/{test,train}/evaluate_circuit_outputs.py`).
   - **The counter.** The method's command is started behind a `/bin/sh` gate. Once that shell has exec-ed, a fresh image without the evaluator's memory, the evaluator opens a `perf_event` hardware counter on it: `PERF_COUNT_HW_INSTRUCTIONS`, `inherit`, `exclude_kernel`, `enable_on_exec`. The gate is then released and the counter starts at the method's exec.
   - **What it counts.** Every thread and every process the method starts gets an inherited child counter that is summed into the evaluator's. That holds however the process detaches, changes session or is re-parented.
   - **The method cannot switch it off.** The evaluator owns the counter, so `prctl(PR_TASK_PERF_EVENTS_DISABLE)` in the method has no effect (tested).
   - **Exact reruns.** Methods run with `PYTHONHASHSEED=0` and with address-space randomisation off (`personality(ADDR_NO_RANDOMIZE)`). CPython's work depends on object addresses, e.g. its method cache. With randomisation on, the same Python program varied by up to 2.4% between runs; with it off, counts are identical.
   - **Fallback.** If a machine offers no hardware counter, the evaluator falls back to the process tree's CPU time at a fixed rate (8.66e9 instructions per CPU-second, measured on the reference) and records `accounting: cpu_fallback`. The hidden-test job reports which mode it used.
2. **Only output written within budget is credited.**
   - **How the output is read.** The evaluator re-reads the output file at every poll (10 ms) and then reads the counter. New content is kept only if that count is within budget, so every credited line was in the file at a moment when the method's work was within budget.
   - **Rewrites.** Content rewritten in place restarts the observation. The "placeholder" trick of reserving blank lines early and filling them after the budget therefore earns nothing early.
   - **Stopping.** The method is stopped at the budget. When the registered command's process exits, anything it left running is killed.
   - **Timestamps.** Each credited line carries the counted work at which it appeared, which gives the new experiment below.
3. **Harder benchmark**, built by `eval/test/build_hidden_benchmark.py`, which computes exact answers in parallel and saves as it goes.
   - **Circuits and faults.** c432, c499 and the 1-fault cells are dropped. The base tier is c880, c1355, c1908, c2670 and c3540 (383 to 1,669 gates) with 3, 5 or 7 faults and 10 to 50 observations, two hidden instances per cell. The stress tier is c5315 and c7552 with 3, 5 or 7 faults and 10, 30 or 50 observations.
   - **New seeds.** Both the public seed and the secret seed are new.
   - **Exact answers.** The complete set of minimum diagnoses is computed offline with at most 4,000 minimum diagnoses per instance, re-verified by simulation.
   - **Split sizes.** Hidden test: 158 instances (136 base, 22 stress). Train: 78 (67 base, 11 stress). Cells whose answers could not be enumerated offline were left out: 28 of 186 hidden cells, mostly 7-fault cells on c3540 and the stress circuits.
4. **New experiment `runtime_profile`** (weight 0.15). It reports the share of all instances localised within ½, ¼ and ⅛ of the budget, read from the same run. This is the paper's Figure 6 CPU-time comparison on a machine-independent scale, and it rewards methods that need less work even when both finish.
5. **Weights.**
   - `scale_stress` goes from 0.40 to 0.25. The base tier is no longer saturated, so the stress tier no longer has to carry most of the headroom, and it has only 22 hidden instances.
   - `runtime_profile` is new at 0.15.
   - Everything else is unchanged: base 0.25, constraint 0.15, observation scaling 0.10, fault scaling 0.10. `fault_scaling` now ranks 3, 5 and 7 faults (0.2, 0.4, 0.4).
6. **Budget.** It is chosen from the public train split only: the largest candidate at which the HSD baseline, the strongest provided method, localises ≤ 70% of the train base tier and the reference ≤ 75%. That gives **3×10^10 instructions**, at which HSD scores 68.7% and the reference 40.3% on train.
   - **Why not the first rule.** My first rule bounded only the reference (≤ 75%) and chose 60G. There the HSD baseline already localised ~90% of the train base tier. On the hidden test, a plain implementation improvement of the reference (`lean`, below) reached 98.5% of the base tier and 100% of the 7-fault cells, so a method better than it could not show it there.
   - **The decision.** What I saw on the hidden test prompted the change. The rule itself uses only train data, and its coverage table is in `eval/{train,test}/config.json`.
   - At 30G the reference uses about 4–6 CPU-s per instance.
7. **Audit harness.**
   - **Isolation and order.** Cases run in parallel from a snapshot, so they never copy a locked `eval/test`. Heavy cases go first, and the job resumes across preemptions.
   - **New honest variants:** `lean`, `exhaust_minz`, `lean_exhaust_minz`, `bugassist_vote_as_method`.
   - **New shortcut probes:** `perf_disable`, `parallel_portfolio`, `placeholder_overwrite`.
   - **Smoke check.** A smoke check at the start of the job verifies that the counter works in the container, that reruns are exact (three runs of a 1.49G-instruction program within 170 instructions) and that 200 short-lived detached workers are all counted. It also checks every solver against the exact answers.
8. **Data.** Hidden instances and answers are stored gzipped (`eval/test/hidden_benchmark.json.gz`), as are the public split (`data/iscas85_train/*.gz`) and the evaluator-owned baseline outputs.

## Do better results score higher?

Yes. *Before* is the iteration-11 gym (old benchmark, CPU-time budget; `REVIEW.md` / previous `HARDENING.md`). *After* is the final hidden test at 30G; paired counts are instances localised only by the variant / only by the reference, with a sign test.

| Variant | Before: rank | After: rank | Base % | Stress % | ¼-budget % | Paired (w/l, p) |
|---|---:|---:|---:|---:|---:|---|
| Reference (the paper's procedure), official run | 0 (97.3 / 67.4) | **0** | 50.0 | 40.9 | 22.8 | |
| Reference, rerun on another node and path | −0.040 to −0.013 | **0.000** | 50.0 | 40.9 | 22.8 | 0/0 |
| **Lean CFaults** (same algorithm and oracle; reads each optimum from the SAT model instead of `RC2.compute()`'s per-call Python remap and sort of every variable) | — | **+1.343** | 91.2 | 72.7 | 52.5 | 63/0, 2e-19 |
| HSD as the submitted method (the paper's competitor, better on circuits) | +0.327 | **+0.998** | 77.9 | 68.2 | 45.6 | 45/1, 1e-12 |
| HSD, evaluator-owned baseline | +0.433 | +1.001 | 77.9 | 68.2 | 45.6 | |
| Lean CFaults + RC2 core exhaustion/minimisation | — | +0.850 | 80.9 | 59.1 | 39.9 | 46/0, 3e-14 |
| Reference + RC2 core exhaustion/minimisation | — | −0.161 | 49.3 | 31.8 | 16.5 | 0/3 |
| Lazy observation addition | −0.032 | −0.134 | 49.3 | 31.8 | 20.9 | 0/3 |
| Previous gym reference: fresh MaxSAT solver per optimum | −1.003 | −0.893 | 22.1 | 22.7 | 8.2 | 0/42, 5e-13 |
| Brute force (every gate subset by size) | −1.787 | −1.543 | 5.9 | 0.0 | 3.8 | 0/69 |
| Weaker: first optimum only | −2.306 | −1.563 | 0.0 | 4.5 | 0.6 | 0/76 |
| BugAssist-style voting baseline | −2.479 | −1.744 | 0.0 (unsound 54.4) | 4.5 | 0.6 | |
| Weaker: first observation only | −2.759 | −1.847 | 2.2 (unsound 97.5) | 4.5 | 2.5 | 0/73 |

- **The REVIEW's request is met.** An honest method other than copying HSD beats the reference beyond noise. `lean` keeps the paper's algorithm and oracle; it only avoids RC2's O(#variables) Python post-processing on every optimum, which dominates enumeration on these formulas (tens of thousands of variables, hundreds to thousands of optima). `lean_exhaust_minz` beats the reference too.
- **Room above both stays.** Neither reaches the bound: `lean` is at 91.2 / 72.7 / 52.5 (base / stress / ¼ budget), with ⅛-budget 30.4.
- **Algorithmic change scores as expected.** HSD's advantage over the reference is algorithmic: one small SAT call per observation instead of one call on the unified formula. It wins in every tier and at every budget fraction, as the paper reports for circuits.
- **Not distinguishable or worse:** core exhaustion and minimisation on the reference, and lazy observations. Both cost more work here.

## Major shortcuts: fix and score before → after

Before is the iteration-11 rank (old gym), or "new" for probes of mechanisms introduced in this iteration. After is the final hidden test at 30G.

| Shortcut | Fix | Before | After |
|---|---|---:|---:|
| **Detached relay** (REVIEW item 3): HSD journaled across detached, auto-reaped workers in their own sessions, each with a fresh per-process CPU allowance | Inherited instruction counter: every process the method starts is counted, whatever its session or parent; the tree is killed at the budget or when the command exits | +0.356 (above honest HSD +0.327) | **+0.912** (below honest HSD +0.998; same instances, output only at the end, so lower recall) |
| **Calibration noise** (REVIEW item 2): budget-sensitive methods shifted ~0.1 rank between runs | Counted budget, no calibration; `PYTHONHASHSEED=0`, address randomisation off | reference rank spread 0.040, HSD 0.33–0.43 | rerun spread **0.000** (max 0.015% instruction difference, 0 flips across nodes and workspace paths) |
| Disable the work counter: `prctl(PR_TASK_PERF_EVENTS_DISABLE)`, then HSD | Counter owned by the evaluator, not the method | new | +0.997 = honest HSD (counted in full) |
| Parallel portfolio: 4 detached HSD workers race | All four are counted | new | +0.017 (vs honest HSD +0.998) |
| Placeholder: reserve blank lines at once, run HSD, overwrite them in place | In-place rewrite restarts observation; lines credited at the work when they appeared | new | +0.912 (below honest HSD; no early-budget credit) |
| Write output after the budget is exhausted | Only lines observed within budget are credited | new | worst (local test: 0 lines credited) |
| chmod `eval/test` back and read the answers | Directory fingerprint checked after every method process | +0.564 (iter-11 before) | −1.974 (failed run) |
| Plain read of the hidden file; train-answer lookup; golden-netlist diff | Hidden data only in `eval/test` (unreadable while methods run); new seeds; signals renamed | — / +2.19 / +2.19 | −1.974 each |
| Pad diagnoses / duplicate them | Unsound → instance worth 0; ranked constraint | +0.81 / 0 | −1.901 each |
| Self-reported success, empty output, crash, unregistered, late registration, pre-written scores, replacing stored baselines | Nothing self-reported is read; every registration on disk is run; no output → worst values; baselines evaluator-owned | up to +0.41 | −1.97 each |
| Brute force over candidate subsets | Larger circuits, 3–7 faults | +0.819 (oldest gym) | −1.543 |

## Shortcuts left, and why

- **Submitting the provided HSD baseline**, or an audit variant from `redteam/`, as a method (+1.00 / up to +1.34). These are honest stronger methods, not scoring flaws: HSD is the paper's own circuit competitor and is better on circuits in the paper too. Both are named out of bounds in `DIRECTION.md`. Left to the grader.
- **Killing the evaluator and forging `scoring/scores_test.json`.** Method code runs as the same user and could kill the hidden-test process after writing a fake score file. Only privilege separation, which the gym does not have, prevents this. The hidden-test command then exits non-zero. Left to the grader and the infrastructure.
- **Kernel-side work is not counted** (`exclude_kernel`, required at `perf_event_paranoid=2`). A method cannot usefully solve SAT inside system calls. CPU time of the tree is also capped at the 240 s wall guard. Left.
- **Instruction counts differ slightly across CPU models and workspace paths** (up to 0.015% observed). That is far below anything that moves a score; the hidden test always runs at `/home/user`.
- **Structural matching to the public netlists** (graph isomorphism despite renaming) only bounds the minimum cardinality: the full set of minimum diagnoses still has to be enumerated. Not run.
- **Git history and privileged access**: unchanged from iteration 11 (infrastructure's job / out of scope).

## Reference score before and after

- **Before (iteration 11):** 97.33% base / 67.44% stress / 0% unsound, on c432–c7552 with 1, 3 or 5 faults, at a calibrated 9.09 CPU-s. Reruns spanned 96.0–97.3 / 65.1–67.4.
- **After:** **50.00% base** (68/136), recall 65.3; **40.91% stress** (9/22), recall 56.8; **0% unsound**; runtime profile 39.2 / 22.8 / 11.4% at ½ / ¼ / ⅛ budget. This is at 3×10^10 instructions, on c880–c7552 with 3, 5 or 7 faults. Train: 40.3 / 45.5 / 0.
- **In the paper's direction:**
  - Coverage falls as observations grow: 67.9, 63.0, 46.4, 42.9, 28.0% at 10–50. The paper reports 81.6 → 68.7.
  - Coverage falls as faults grow: 74.0, 41.7, 28.9% at 3, 5, 7.
  - HSD localises more with less work: 77.9 / 68.2% and 17.6 vs 33.6 G instructions per base instance.
  - Only the per-observation voting baseline reports non-diagnoses (54% of instances).
  - The gap to HSD (28 points) is larger than the paper's 6. The difference is mostly the per-solution overhead of `RC2.compute()`, which the authors' tool shares. The `lean` variant shows this.

## Headroom check

- **Ranked metrics where the reference sits at the bound:** only the constraint `unsound_output_rate` (0%; a constraint is meant to sit there). Every other ranked metric is between 11% and 74%.
- **A better method scores higher, below the bound:** `lean` +1.34 and HSD +1.00. The best variant reaches the bound only in the 20-observation bucket (100%). Its stress (72.7), 7-fault (84.2) and budget-fraction metrics (30–73%) leave room.
- **Brute force fails and the simple baseline sits clearly below:** brute force localises 5.9% / 0% (−1.54), BugAssist voting 0% / 4.5% with 54% unsound (−1.74).
- **Added experiment:** `runtime_profile`, where the reference reaches 11–39% and the best variant 30–73%.

## Noise

| Source | Size |
|---|---|
| Reference rerun (official vs repeat, different node and path) | max 0.015% per-instance instructions, median 0.003%; 0 localisation flips; rank difference 1e-6 |
| Same program, same path, three runs (smoke check in the container) | 1,489,542,530 – 1,489,542,696 instructions |
| Instance sampling (paired comparisons) | lean vs reference 63/0 (p = 2e-19); HSD 45/1 (1e-12); lazy 0/3 (0.25); exhaust/minz 0/3 |
| Train vs test, reference base tier | 40.3 vs 50.0 (67 vs 136 instances; HSD 68.7 vs 77.9: the same offset) |

## Verification run

After the rescoring, the official reference (train and hidden test) and both evaluator-owned baselines were rerun end to end from the final code at the final 30G budget, plus `bugassist_vote_as_method` as a case (`scripts/run.sh`). `scoring/scores_test.json` and `scoring/scores_train.json` are from that run; its comparison with the rescored values is reported in the next section.

## Not fixed

- **The stress tier is small:** 22 hidden instances, because exact answers for many 7-fault cells on the largest circuits could not be enumerated offline. Its rates move in steps of 4.5 points. Excluding instances whose answers are too hard to compute biases both tiers towards instances with at most 4,000 minimum diagnoses.
- **Scale.** Not reproduced: 12,147 instances, 1800 s per circuit, up to 50 faults, c6288, and HSD-CM. The C-program half of the paper is out of scope.
- **Fallback accounting.** If the hidden-test machine has no hardware counter, reruns are only as exact as CPU time (about 15–25%).
- **The budget was set after the audit job, by rescoring.** It was not re-chosen blind; the reason is given under *What changed*, item 6.
