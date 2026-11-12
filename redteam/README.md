# Scoring audit

Run `bash redteam/run_all.sh` in the supplied gym container as a CPU job.
Each scenario also has an independent `run.sh`; reuse scenarios require the
freshly generated `reference_seed_0` outputs first.
The nonminimal-padding shortcut also reuses the genuine `trained_tiebreak` run.

`harness.py` makes an isolated workspace containing only scientist-visible
source/data. Honest variants use the original joint MaxSAT method; shortcut
variants mutate only their own output artifacts, public data, or public train
scores. No method reads hidden evaluation, hidden score snapshots, the paper,
or the audit's ranking configuration. Hidden evaluation is copied in after the
method and public evaluation finish, and runs as a separate foreground process
with `bash scripts/evaluate_test.sh`, no arguments or evaluation overrides.
No process is started in the background or survives between phases.

Only the auditing harness reads/restores hidden evaluator files. This models
the stipulated restoration boundary without changing the real workspace.
All cases run in one scheduler container; they use clean directories and new
processes rather than rebuilding a container per case. There is no dependence
on process persistence or Python-environment modification.

`summary.json` reports normalized improvements over the freshly rerun reference.
Normalization uses the population standard deviation across this audit's
attempts (including HSD), because the distribution of future ranked attempts is
not yet known. Experiment weights and absolute coefficient values are used;
directions come only from `higher_is_better`. Exact ties and coordinate-wise
dominance are also identified because they survive changes in normalization.
Complete per-run hidden scores and method outputs are saved in each folder.

Generated scratch workspaces and verbose logs are ignored by this directory's
`.gitignore`. Small score, provenance, and result JSON files are intentional
audit evidence and tracked.

`python redteam/check_evidence.py` checks the saved JSON evidence without
rerunning any method or solver and writes `checks.json`.
