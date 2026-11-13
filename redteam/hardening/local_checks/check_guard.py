import importlib.util, os, sys, tempfile, subprocess
from pathlib import Path
spec = importlib.util.spec_from_file_location("ev", "eval/test/evaluate_circuit_outputs.py")
ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
d = Path(tempfile.mkdtemp()); hidden = d / "hidden"; hidden.mkdir(); (hidden / "a.json").write_text("secret")
for name, code in {
    "plain_read": f"open('{hidden}/a.json').read()",
    "chmod_read_restore": f"import os; os.chmod('{hidden}', 0o700); open('{hidden}/a.json').read(); os.chmod('{hidden}', 0)",
    "rename_replace": f"import os; os.rename('{hidden}', '{hidden}.x'); os.mkdir('{hidden}'); os.chmod('{hidden}', 0)",
    "nothing": "pass",
}.items():
    with ev.HiddenDataGuard(hidden) as g:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        print(f"{name:20s} rc={r.returncode} tampered={g.tampered()} {r.stderr.strip().splitlines()[-1][:60] if r.stderr else ''}")
    if Path(f"{hidden}.x").exists():
        os.chmod(f"{hidden}.x", 0o700); os.rmdir(hidden); os.rename(f"{hidden}.x", hidden)
print(oct(hidden.stat().st_mode & 0o777), (hidden / "a.json").read_text())
