# Hardening report (iteration 11)

**Verdict.** Better results now score higher and worse results lower. Every shortcut in `REDTEAM.md`, and the three more found in this iteration, now ranks below the reference. The one exception is the CPU-escape relay: after its fix it still ranks +0.356, slightly above honest HSD (+0.327), and that gap is explained by calibration noise, not escaped CPU. The reference is the paper's own circuit procedure (unified multi-observation MaxSAT, RC2Stratified, Algorithm 5 enumeration with one incremental oracle, as in the authors' `oracle.py`).

The test runs on real ISCAS85 circuits, with hidden instances and answers held only in `eval/test/`. The evaluator runs each method itself under a per-instance CPU budget that covers the method's whole process tree.

The remaining noise source is the machine-speed calibration of that budget (see *Not fixed*).

`REDTEAM.md` audited the earlier synthetic gym: one 25-gate adder, injected-fault F1 as the objective, answers in public `data/`, self-reported work counters. This iteration had two parts:

- **Part 1** (earlier session, commits `f3cc0a5` to `b06717a`): rebuilt the benchmark, evaluator and baselines.
- **Part 2** (this session, commits `5b00b43` onward): closed three more loopholes (process-tree CPU escape, chmod-and-read of the hidden answers, reading the evaluator's memory), fixed the audit harness, re-checked the calibration, and reran everything through the final evaluator.

All "after" numbers below come from CPU jobs `9deb4bfa-925` and `6e39e4c0-442`. Every case ran through **`bash scripts/evaluate_test.sh` with no arguments**, in a fresh copy of the workspace ([harness](redteam/hardening/harness.py), [summary](redteam/hardening/summary.txt), [summary.json](redteam/hardening/summary.json), per-case scores in `redteam/hardening/results/<case>/`).

Rank formula ([summarize.py](redteam/hardening/summarize.py)): Σ weight × |coefficient| × (value − reference), signed by `higher_is_better`, divided by the population SD of that metric. The SD is taken over every case scored by the final evaluator plus the two evaluator-owned baselines. Cases scored by the *previous* evaluator (`__before`) are reported but kept out of that SD cohort.

## What changed

**Part 1 (benchmark and protocol), summarised from its commits:**

- **Benchmark.** The synthetic 3-bit adder (27 instances, labels in `data/`) is replaced by ISCAS85 circuits with injected gate-type faults. Signals are renamed and gates reordered.
  - Base tier: c432, c499, c880, c1355, c1908; 1, 3 or 5 faults; 10 to 50 observations.
  - Scale-stress tier: c2670, c3540, c5315, c7552; 3 or 5 faults; 10, 30 or 50 observations.
  - Public train split: 96 instances (public seed). Hidden test: 118 instances (secret seed, in `eval/test/build_hidden_benchmark.py`).
  - Exact answers (the complete set of minimum-cardinality diagnoses) were computed offline and independently re-verified.
- **Objective.** The paper's measure replaces injected-fault F1: an instance is localised if the complete set of minimum diagnoses is reported, and nothing else, within the budget. Any non-minimum, inconsistent, malformed or duplicate line makes the instance unsound and worth 0, and `unsound_output_rate` is a ranked constraint (weight 0.15).
- **Evaluator runs the method.** Each registered method (`checkpoints/*/solver.json`, all discovered) runs once per hidden instance in a fresh process, under a calibrated CPU budget. Nothing it reports about itself is read.
  - The required key `cfaults` and any method with no output get the worst value of every metric.
  - Baselines (HSD, BugAssist-style voting) are evaluator-owned outputs in `eval/test/baseline_outputs/`. On-disk registrations named after them are ignored.
- **Reference.** Restored to the paper's incremental enumeration: one RC2Stratified oracle, with blocking clauses added via `add_clause`. Previously a fresh solver was built for every optimum.
- **HSD baseline.** Now uses an incremental MaxSAT minimum-hitting-set solver instead of combination enumeration.
- **Headroom tier.** The scale-stress tier was added with weight 0.40, because the base tier is near-saturated for strong methods.

**Part 2 (this session):**

1. **Process-tree CPU budget** (`eval/{test,train}/evaluate_circuit_outputs.py`). The evaluator only counted CPU through `wait4` on the method's root process. A worker that was detached, double-forked, auto-reaped (SIGCHLD ignored) or moved to its own session was invisible: a detached worker's 0.6 s showed up as 0.01 s. Each such worker also got a fresh per-process `RLIMIT_CPU`, so a method could use roughly cores × wall-limit CPU per instance.
   - The evaluator is now a child subreaper and samples every descendant's CPU from `/proc` every 20 ms. It stops the whole tree at the per-process ceiling `ceil(budget)` and records max(polled tree CPU, reaped rusage). Every leftover descendant is killed, and method processes cannot write core files.
   - Container smoke check: 2 detached workers × 1.5 s were counted as 3.10 s at a 5 s budget, and stopped at 2.03 s at a 2 s budget.
2. **Tamper detection on `eval/test`.** The hidden directory is chmod-ed to 0 while method code runs. But the method runs as the same user, so it could chmod it back, read the answers, and restore mode 0.
   - The guard now fingerprints the directory (inode, device, mode, ctime, owner) after locking it and checks it after every method process. Any change, which no unprivileged process can undo since ctime always moves, records `tamper_detected = 1`, stops that method, and scores its whole run as failed.
3. **Non-dumpable evaluator.** The evaluator holds the answers in memory while methods run. A same-user child could read `/proc/<ppid>/mem`: in a local test a planted string was found in the parent's memory. With `PR_SET_DUMPABLE=0` the same read gets *Permission denied*. Local evidence for this fix and the two above: [local_checks/output.txt](redteam/hardening/local_checks/output.txt).
4. **Audit harness.** Interrupted (preempted) hidden-test runs left case workspaces with `eval/test` at mode 0. That made four cases of the earlier job fail with `PermissionError` (brute force, HSD as the method, the previous reference, reference seed 2). Workspaces are now unlocked before removal, and all four ran.
5. **Calibration check.** I first "aligned" the train calibration reference to the test one from three alternating measurements. That rule was driven by one fast outlier sample and pushed the official train run to the clamp floor (factor 0.67: a 6.7 s budget, reference 89.3% / 47.6%).
   - Three back-to-back same-node train/test pairs give workload ratios of 0.80, 0.81 and 0.85, matching the original build-time references (0.83).
   - So the original train reference was restored and the alignment phase dropped (evidence in `eval/train/config.json` → `alignment_check`), and the train side was rerun. Reference: train 96.0% / 66.7%, test 97.3% / 67.4%.
6. `scoring/reference.json`: `results` now hold the official hidden-test run instead of placeholder zeros. The paper's numbers stay under `_paper_reported`, and the audit field `tamper_detected` is declared.
7. All of `briefing/` and `scoring/*.md` rewritten to describe the final gym; they still described the synthetic benchmark, solver-call counts and F1.

Weights are unchanged from part 1: base localisation 0.25, constraint 0.15, observation scaling 0.10, fault scaling 0.10, scale-stress 0.40. Stress carries the most weight because it is the only tier where strong methods still differ: HSD and the reference are at or near 100% on the base tier.

## Do better results score higher?

Yes. Ranks before are from `REDTEAM.md` (old synthetic gym, F1 objective, its own cohort); ranks after are on the final hidden test. Base and stress values are base-tier `localized_rate` and stress-tier `localized_rate_stress`.

| Variant | Before (REDTEAM) | After: rank | After: base % | After: stress % |
|---|---:|---:|---:|---:|
| Reference (paper's procedure), official run | 0 (F1 44.1) | **0** | 97.3 | 67.4 |
| Reference, repeat runs (PYTHONHASHSEED 1, 2) | 0, 0 | −0.040, −0.013 | 97.3, 96.0 | 65.1, 67.4 |
| HSD as the submitted method (better on circuits per the paper) | +0.863 | **+0.327** | 100 | 83.7 |
| HSD, evaluator-owned baseline run | (not ranked) | +0.433 | 100 | 90.7 |
| Lazy observation addition (CFaults-family variant) | — | −0.032 | 97.3 | 65.1 |
| Optimum by MaxSAT, then SAT enumeration under a cardinality bound | — | −0.185 | 97.3 | 55.8 |
| Previous gym reference: fresh MaxSAT solver per optimum | — (was the reference) | **−1.003** | 70.7 | 27.9 |
| Weaker: CFaults returning only the first optimum | — | −2.306 | 12.0 | 2.3 |
| Weaker: CFaults on the first observation only | −0.306 | **−2.759** | 8.0 | 0.0 (unsound 94.9%) |
| BugAssist-style voting baseline | — | −2.479 | 10.7 | 2.3 (unsound 43.2%) |

- **HSD vs reference.** HSD-as-method beats the reference with 9 instances won and 0 lost (paired sign test p = 0.004). That is 8× the reference's rank spread across three runs (0.040).
- **Restoring the paper's incremental enumeration** separates the previous fresh-solver reference from today's by 1.0 rank: 37 instances won, 0 lost, p = 1.5e-11. In `REDTEAM.md` this speed improvement tied at 0, because the scored "work" counted solver calls.
- **Ablations** fall far below the reference. Per-observation diagnosis also produces unsound output, the failure the paper attributes to per-observation aggregation.
- **Not distinguishable:** lazy observation addition ties the reference within noise (0 won, 1 lost). The SAT-enumeration alternative is worse (0/5).

## Major shortcuts: fix and score before → after

Before is the `REDTEAM.md` rank on the old gym, or for part-2 findings the previous evaluator on the final hidden test (`__before` cases). After is the final evaluator.

| Shortcut | Fix | Before | After |
|---|---|---:|---:|
| Copy public injected-fault labels / train answers | Hidden instances and answers only in `eval/test/`; the target is the full minimum-diagnosis set, not labels | +2.193 | −2.876 (`train_answer_lookup`) |
| Diff against the public golden netlist | Signals renamed, gates reordered; target is the minimum set | +2.193 | −2.876 (`golden_diff`) |
| Relabel public ground truth / shrink the public manifest | Instances, answers and test size fixed inside `eval/test/` | +2.190 / +1.700 | closed by construction (public `data/` is no longer read by the hidden test; not rerun) |
| Pad each diagnosis with an extra gate (non-minimal) | Non-minimum line makes the instance unsound and worth 0; ranked constraint | +0.810 | −2.827 |
| Duplicate each diagnosis | Duplicates are unsound | 0 (tie) | −2.824 |
| Report zero or negative solver work | Self-reported fields ignored; CPU measured by the evaluator | +0.003 / +0.411 | −2.876 (`claimed_success`) |
| Clear train keys so the hidden test scores nothing | Evaluator discovers every registration on disk; `cfaults` always reported; no output → worst values | 0 (skip) | −2.876 (`empty_output`, `unregistered`) |
| Register a method after public evaluation | Same: discovered and scored | 0 (skip) | −2.876 (`late_method`) |
| Replace the stored baseline artefact | Baselines stored inside `eval/test/`; registrations named `hsd`/`bugassist_vote` ignored | 0 | −2.876 (baselines unchanged) |
| Pre-write `scores_test.json` | Overwritten by the hidden test | 0 | −2.876 |
| Exhaustive candidate search (brute force) | Real ISCAS85 scale, multi-fault, stress tier | +0.819 | −1.787 (base 44.0%, stress 11.6%) |
| **chmod `eval/test` back, read the answers, restore mode 0** (part 2) | Directory fingerprint checked after every method process → failed run | +0.564 (100% / 100%) | **−2.876** (`tamper_detected` = 1) |
| **CPU escape: HSD relayed across detached, auto-reaped workers in their own sessions** (part 2) | Subreaper + `/proc` tree accounting; tree stopped at `ceil(budget)` | +0.531 (stress 97.7%; root CPU ≤ 0.22 s) | **+0.356** (stress 88.4%; max tree CPU 12.05 s at ceiling 12) |
| **Read the evaluator's memory via `/proc/<ppid>/mem`** (part 2) | Evaluator non-dumpable | local test: planted string found | local test: Permission denied (not run as a full case) |
| Plain read of the hidden file | Directory unreadable while methods run | — | −2.876 |
| All gates / constant gate / every gate as a singleton | Unsound | −0.967 / −1.465 / — | −2.876 |

The relay after the fix is honest HSD with restart overhead, and the evidence shows its remaining edge is calibration, not escaped CPU:

- Its per-instance CPU matches honest HSD's (median ratio 0.98).
- It won exactly two instances that honest HSD lost. Those needed 9.9 and 10.7 CPU-s: inside the relay run's calibrated budget (11.14 s, factor 1.11) but beyond the HSD-as-method run's (9.35 s, factor 0.94).
- The evaluator-owned HSD run with factor 1.42 scored higher still (+0.433).

## Shortcuts left, and why

- **Submitting the provided HSD baseline as a method** scores +0.33 to +0.43. HSD is the paper's own circuit competitor and is better on circuits in the paper too (80.14% vs 73.84%), so this is an honest stronger method, not a scoring flaw. It is already reported as an evaluator-owned baseline, and `DIRECTION.md` marks resubmitting it unchanged as out of bounds. Left to the grader.
- **Very short-lived workers.** A worker that lives under one 20 ms poll and is auto-reaped can still hide its CPU. Exploiting this needs thousands of forks per second of work and is plainly evasive. Left to the grader.
- **Structural matching to the public netlists** (graph isomorphism despite renaming) could recover the injected gates. That only bounds k*: the complete set of minimum diagnoses still has to be enumerated, and injected sets are often not minimum. Not run.
- **Git history.** `eval/test/` is tracked in this repository, so a hidden-test workspace that shipped `.git` history would expose the answers through git objects. Keeping that history away from scientists and method processes is the infrastructure's job (the hidden test restores `eval/test/` into a fresh container).
- **Privileged access** (root, ptrace with CAP_SYS_PTRACE) is out of scope.

## Reference score before and after

- **Before:** the synthetic gym's reference scored selected-fault F1 44.10, with 100% minimum-diagnosis coverage that saturated the old constraint. On the final hidden test, the previous gym reference (fresh solver per optimum) localises 70.7% base / 27.9% stress (rank −1.003).
- **After:** the paper's procedure localises 97.33% base / 67.44% stress, recall 99.24 / 76.52, unsound 0%. That is at a calibrated budget of 9.09 CPU-s per instance (speed factor 0.909), from `scoring/scores_test.json`. Train: 96.0 / 66.67.
- **In the paper's direction:**
  - HSD localises more (100 / 90.7) and is faster on every one of the 102 instances both solve (median 0.42 s vs 0.77 s; totals 66 vs 191 CPU-s).
  - The reference returns only minimum diagnoses, while per-observation voting reports non-diagnoses on 43% of instances.
  - On the stress tier the reference's coverage falls as observations grow (80% → 60% → 61.5% at 10 → 30 → 50 observations). The paper reports 81.6 → 68.7.
  - The paper's overall gap to HSD is 6.3 points. Here it is 2.7 on the base tier and 23 on the larger circuits.

## Headroom check

- **Ranked metrics where the reference sits at the bound:** `localized_rate_obs10/20/30/50` (100), `localized_rate_f1` (100), and the constraint `unsound_output_rate` (0; a constraint is meant to sit at its bound).
- **Not at the bound:** `localized_rate` 97.3, `min_diagnosis_recall` 99.2, `localized_rate_obs40` 86.7, `localized_rate_f3`/`f5` 96, and above all the scale-stress tier (67.4 / 76.5), which part 1 added and weighted 0.40.
- **A better method scores higher:** HSD-as-method +0.327 (stress 83.7%) and the HSD baseline +0.433 (90.7%), and neither reaches the bound.
- **Brute force fails, and the simple baseline sits clearly below:** brute force localises 11.6% of the stress tier (−1.787); BugAssist voting ranks −2.479.

## Noise

| Source | Size |
|---|---|
| Reference, three runs | rank spread 0.040; base 96.0–97.3; stress 65.1–67.4 |
| HSD, two runs (as method, as baseline) | stress 83.7 vs 90.7 (+0.327 vs +0.433) |
| Calibration factor across job segments and nodes | 0.77 to 1.50 |
| Per-instance budget tracking of real speed | within ~15–20% (seed 0 → 2: CPU ratio 1.37, factor ratio 1.50; HSD runs: 1.30 vs 1.52) |
| One calibration measurement on one node | varies up to ~25% within a minute |

Without calibration the budget error would be up to ~37%: the same reference ran 1.37× slower on one node. The paper's effects (reference vs per-observation voting: ~2.5 rank) and the better variant (+0.33) are well above this noise; small improvements of a few hundredths are not distinguishable.

## Not fixed

- **Calibration noise.** Budget-sensitive methods (HSD) can shift about 0.1 rank between runs. A more robust scheme was not built in this iteration because it needs a full rerun of every case: calibration repeated during the run, with post-hoc crediting of time-stamped output prefixes.
- **The base tier is close to saturated:** the reference is at 100% in four of five observation buckets and HSD at 100% everywhere. The paper's decline with more observations is visible only on the stress tier, which the observation-scaling metrics do not cover.
- **Scale.** Not reproduced: 12,147 instances, 1800 s per circuit, up to 50 faults, c6288, and HSD-CM. The C-program half of the paper is out of scope.
- **Lazy observation addition**, the one CFaults-family improvement tried, ties the reference. The demonstrated "better" method is HSD, the paper's competitor.
