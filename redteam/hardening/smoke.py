#!/usr/bin/env python3
"""Fail-fast cross-check run at the start of the hardening job.

On a few small instances every exact solver (reference CFaults, HSD baseline,
incremental and SAT-enumeration variants, brute force) must return exactly the
ground-truth set produced by the packaging-time enumerator, and the evaluator's
sandboxed runner must work end to end.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data.circuit_benchmark import load_iscas85, make_instance  # noqa: E402
from method.cfaults_circuit import diagnose  # noqa: E402
from baseline.hsd_circuit import diagnose_hsd  # noqa: E402
from baseline.bugassist_vote_circuit import diagnose_vote  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


builder = load_module("builder", ROOT / "eval/test/build_hidden_benchmark.py")
variants = load_module("variants", ROOT / "redteam/hardening/audit_variants.py")
test_eval = load_module("test_eval", ROOT / "eval/test/evaluate_circuit_outputs.py")


def as_set(diags):
    return {frozenset(d) for d in diags}


def main() -> None:
    import pysat

    print("pysat", getattr(pysat, "__version__", "?"), flush=True)
    bench = ROOT / "data/downloads/iscas85"
    cases = [("c432", 1, 10), ("c432", 2, 10), ("c499", 3, 20), ("c880", 3, 10)]
    failures = []
    for name, k, m in cases:
        golden = load_iscas85(bench, name)
        inst = make_instance(golden, "smoke", "smoke-seed", k, m, 0)
        assert inst is not None
        t = time.time()
        truth = builder.exact_answer(inst)
        builder.verify_answer(inst, truth, __import__("random").Random(0))
        gt = as_set(truth["diagnoses"])
        line = f"{name} f{k} o{m}: k*={truth['optimum']} #min={len(gt)} gt={time.time() - t:.2f}s"
        circuit, obs = inst["circuit"], inst["observations"]
        results = {}
        t = time.time(); results["cfaults"] = as_set(diagnose(circuit, obs)); line += f" cfaults={time.time() - t:.2f}s"
        t = time.time(); results["hsd"] = as_set(diagnose_hsd(circuit, obs)); line += f" hsd={time.time() - t:.2f}s"
        for var in ("fresh_solver", "lazy_observations", "satenum"):
            got = []
            t = time.time(); getattr(variants, var)(circuit, obs, got.append); line += f" {var}={time.time() - t:.2f}s"
            results[var] = as_set(got)
            if len(got) != len(results[var]):
                failures.append(f"{line}: {var} emitted duplicates")
        if name == "c432" and k <= 2:
            got = []
            t = time.time(); variants.brute_force(circuit, obs, got.append); line += f" brute={time.time() - t:.2f}s"
            results["brute_force"] = as_set(got)
        vote = diagnose_vote(circuit, obs)
        line += f" vote_sound={frozenset(vote) in gt}"
        print(line, flush=True)
        for key, got in results.items():
            if got != gt:
                msg = f"{name} f{k} o{m}: {key} disagrees with ground truth ({len(got)} vs {len(gt)})"
                if key == "lazy_observations":
                    print("WARNING (experimental audit variant):", msg, flush=True)
                else:
                    failures.append(msg)
        # sandboxed runner end to end on the reference command
        command = ["python", "method/cfaults_circuit.py", "--instance", "{instance}", "--output", "{output}"]
        record = test_eval.run_command_on_instance(command, inst, 30.0)
        scored = test_eval.score_instance(record, inst, truth, 30.0)
        print(f"   runner: status={record['status']} cpu={record['cpu_seconds']:.2f} localized={scored['localized']}", flush=True)
        if not scored["localized"]:
            failures.append(f"{name} f{k} o{m}: runner/scorer did not credit the reference ({record.get('stderr_tail', '')[-300:]})")
    # CPU limit enforcement: a busy loop must be stopped near the limit
    with tempfile.TemporaryDirectory() as tmp:
        spin = Path(tmp) / "spin.py"
        spin.write_text("import sys\nopen(sys.argv[2],'w').write('[\"x\"]\\n')\nwhile True: pass\n")
        rec = test_eval.run_command_on_instance(["python", str(spin), "{instance}", "{output}"], inst, 2.0)
        print(f"   spin: status={rec['status']} cpu={rec['cpu_seconds']:.2f} wall={rec['wall_seconds']:.2f} lines={len(rec['diagnoses'])}")
        if rec["status"] not in ("cpu_limit", "wall_limit") or rec["cpu_seconds"] > 4.5:
            failures.append("cpu limit not enforced")
    if failures:
        print("SMOKE FAILURES:\n" + "\n".join(failures), flush=True)
        raise SystemExit(1)
    print("smoke OK", flush=True)


if __name__ == "__main__":
    main()
