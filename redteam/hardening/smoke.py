#!/usr/bin/env python3
"""Fail-fast cross-check run at the start of the hardening job (a few minutes).

1. Work accounting: the evaluator's hardware instruction counter is available
   in this container, counts a deterministic program identically twice,
   counts short-lived and detached descendants, and cannot be switched off by
   the method (PR_TASK_PERF_EVENTS_DISABLE).
2. Solvers: on a few small instances of the new grid every exact solver
   (reference CFaults, HSD baseline, the audit variants) returns exactly the
   ground-truth set produced by the packaging-time enumerator.
3. The evaluator's runner credits the reference end to end and stops a busy
   loop at the instruction budget.
"""

from __future__ import annotations

import importlib.util
import os
import random
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


def run(command, inst, cap, wall=60.0, accounting="perf"):
    settings = {"cap": int(cap), "wall_limit_seconds": wall, "fallback_instructions_per_cpu_second": 5e9,
                "accounting": accounting}
    return test_eval.run_command_on_instance(command, inst, settings)


def main() -> None:
    import pysat

    print("pysat", getattr(pysat, "__version__", "?"), flush=True)
    test_eval._prctl(test_eval.PR_SET_CHILD_SUBREAPER, 1)
    failures, warnings = [], []
    accounting, note = test_eval.detect_accounting()
    print(f"accounting: {accounting} {note or ''}", flush=True)
    if accounting != "perf":
        failures.append(f"hardware instruction counter unavailable: {note}")

    bench = ROOT / "data/downloads/iscas85"
    golden = load_iscas85(bench, "c880")
    inst = make_instance(golden, "smoke", "smoke-seed", 3, 10, 0)
    truth = builder.exact_answer(inst)
    builder.verify_answer(inst, truth, random.Random(0))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        loop = tmp / "loop.py"
        loop.write_text("import sys\ndef f(n):\n    s = 0\n    for i in range(n): s += i\n    return s\n"
                        "f(3000000)\nopen(sys.argv[1], 'w').write('[]\\n')\n")
        counts = [run(["python", str(loop), "{output}", "{instance}"], inst, 1e12)["instructions"] for _ in range(3)]
        print(f"deterministic program: {counts}", flush=True)
        if accounting == "perf" and (max(counts) - min(counts)) > 0.002 * max(counts):
            failures.append(f"instruction counts not reproducible: {counts}")
        many = tmp / "many.py"
        many.write_text(
            "import os, sys, signal\nsignal.signal(signal.SIGCHLD, signal.SIG_IGN)\n"
            "def f(n):\n    s = 0\n    for i in range(n): s += i\n    return s\n"
            "for _ in range(200):\n    if os.fork() == 0:\n        os.setsid(); f(100000); os._exit(0)\n"
            "import time; time.sleep(0.5)\nopen(sys.argv[1], 'w').write('[]\\n')\n")
        loop1 = tmp / "loop1.py"
        loop1.write_text("import sys\ndef f(n):\n    s = 0\n    for i in range(n): s += i\n    return s\n"
                         "f(100000)\nopen(sys.argv[1], 'w').write('[]\\n')\n")
        empty = tmp / "empty.py"
        empty.write_text("import sys\nopen(sys.argv[1], 'w').write('[]\\n')\n")
        base = run(["python", str(empty), "{output}", "{instance}"], inst, 1e12)["instructions"]
        work = run(["python", str(loop1), "{output}", "{instance}"], inst, 1e12)["instructions"] - base
        rec = run(["python", str(many), "{output}", "{instance}"], inst, 1e12)
        print(f"200 short-lived detached workers: {rec['instructions'] / 1e9:.2f}G counted; "
              f"interpreter start-up {base / 1e9:.3f}G, one worker's work {work / 1e9:.4f}G", flush=True)
        if accounting == "perf" and rec["instructions"] < base + 0.9 * 200 * work:
            failures.append("short-lived detached workers not counted")
        dis = tmp / "disable.py"
        dis.write_text("import ctypes, sys\nctypes.CDLL(None).prctl(31, 0, 0, 0, 0)\n" + loop.read_text().split("import sys\n", 1)[1])
        got = run(["python", str(dis), "{output}", "{instance}"], inst, 1e12)["instructions"]
        print(f"PR_TASK_PERF_EVENTS_DISABLE then same program: {got}", flush=True)
        if accounting == "perf" and got < 0.9 * min(counts):
            failures.append("method could disable the counter")
        spin = tmp / "spin.py"
        spin.write_text("import sys\nopen(sys.argv[1],'w').write('[\"x\"]\\n')\nwhile True: pass\n")
        t = time.time()
        rec = run(["python", str(spin), "{output}", "{instance}"], inst, 5e9)
        print(f"busy loop at 5G budget: status={rec['status']} instr={rec['instructions'] / 1e9:.2f}G "
              f"wall={time.time() - t:.2f}s", flush=True)
        if rec["status"] != "budget":
            failures.append(f"budget not enforced: {rec['status']}")

    cases = [("c880", 3, 10), ("c1355", 5, 20), ("c1908", 3, 30), ("c880", 7, 10)]
    for name, k, m in cases:
        inst = make_instance(load_iscas85(bench, name), "smoke", "smoke-seed", k, m, 0)
        assert inst is not None
        t = time.time()
        truth = builder.exact_answer(inst, cpu_budget=60.0, max_diagnoses=20000)
        if truth["status"] != "complete":
            print(f"{name} f{k} o{m}: ground truth {truth['status']}, skipped", flush=True)
            continue
        builder.verify_answer(inst, truth, random.Random(0))
        gt = as_set(truth["diagnoses"])
        line = f"{name} f{k} o{m}: k*={truth['optimum']} #min={len(gt)} gt={time.time() - t:.2f}s"
        circuit, obs = inst["circuit"], inst["observations"]
        results = {}
        t = time.time(); results["cfaults"] = as_set(diagnose(circuit, obs)); line += f" cfaults={time.time() - t:.2f}s"
        t = time.time(); results["hsd"] = as_set(diagnose_hsd(circuit, obs)); line += f" hsd={time.time() - t:.2f}s"
        slow_variants = ("fresh_solver", "lazy_observations") if k <= 3 else ()
        for var in ("lean", "exhaust_minz") + slow_variants:
            got = []
            t = time.time(); getattr(variants, var)(circuit, obs, got.append); line += f" {var}={time.time() - t:.2f}s"
            results[var] = as_set(got)
            if len(got) != len(results[var]):
                failures.append(f"{line}: {var} emitted duplicates")
        got = []
        variants.lean(circuit, obs, got.append, adapt=True, exhaust=True, minz=True)
        results["lean_exhaust_minz"] = as_set(got)
        vote = diagnose_vote(circuit, obs)
        line += f" vote_sound={frozenset(vote) in gt}"
        print(line, flush=True)
        for key, got in results.items():
            if got != gt:
                msg = f"{name} f{k} o{m}: {key} disagrees with ground truth ({len(got)} vs {len(gt)})"
                (failures if key in ("cfaults", "hsd") else warnings).append(msg)
        command = ["python", "method/cfaults_circuit.py", "--instance", "{instance}", "--output", "{output}"]
        record = run(command, inst, 1e12)
        scored = test_eval.score_instance(record, inst, truth, 1e12)
        print(f"   runner: status={record['status']} instr={record['instructions'] / 1e9:.2f}G "
              f"cpu={record['cpu_seconds']:.2f}s rate={record['instructions'] / max(record['cpu_seconds'], 1e-3) / 1e9:.2f}G/s "
              f"localized={scored['localized']}", flush=True)
        if not scored["localized"]:
            failures.append(f"{name} f{k} o{m}: runner/scorer did not credit the reference "
                            f"({record.get('stderr_tail', '')[-300:]})")
    # parallel speed-up of this node (informational: how many cases can run at once)
    with tempfile.TemporaryDirectory() as tmp:
        prog = Path(tmp) / "busy.py"
        prog.write_text("s = 0\nfor i in range(20000000): s += i\n")
        import subprocess

        t = time.time(); subprocess.run([sys.executable, str(prog)]); one = time.time() - t
        t = time.time()
        procs = [subprocess.Popen([sys.executable, str(prog)]) for _ in range(os.cpu_count() or 1)]
        for p in procs:
            p.wait()
        many = time.time() - t
        print(f"parallel check: 1 process {one:.2f}s, {len(procs)} processes {many:.2f}s", flush=True)
    if warnings:
        print("SMOKE WARNINGS (audit variants):\n" + "\n".join(warnings), flush=True)
    if failures:
        print("SMOKE FAILURES:\n" + "\n".join(failures), flush=True)
        raise SystemExit(1)
    print("smoke OK", flush=True)


if __name__ == "__main__":
    main()
