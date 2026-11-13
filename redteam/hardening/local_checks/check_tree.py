import importlib.util, json, os, sys, time, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("ev", "eval/test/evaluate_circuit_outputs.py")
ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
ev._prctl(ev.PR_SET_CHILD_SUBREAPER, 1)
inst = {"id": "x", "circuit": {"inputs": [], "outputs": [], "gates": []}, "observations": []}
d = Path(tempfile.mkdtemp())
spin = "import time\nt=time.process_time()\nwhile time.process_time()-t<%s: pass\n"
progs = {
 "honest_0.5s": spin % 0.5 + "open(__import__('sys').argv[1],'w').write('[\"a\"]\\n')",
 "detached_escape_2x1.5s": r'''
import os, sys, time, signal
signal.signal(signal.SIGCHLD, signal.SIG_IGN)
for i in range(2):
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            t = time.process_time()
            while time.process_time() - t < 1.5: pass
            open(sys.argv[1] + f".{i}", "w").write("x"); os._exit(0)
        os._exit(0)
while not all(os.path.exists(sys.argv[1] + f".{i}") for i in range(2)): time.sleep(0.01)
open(sys.argv[1], "w").write('["a"]\n'); os._exit(0)
''',
 "joined_pool_4x1s": r'''
import sys, time
from multiprocessing import Pool
def f(_):
    t = time.process_time()
    while time.process_time() - t < 1.0: pass
    return 1
if __name__ == "__main__":
    with Pool(4) as p: p.map(f, range(4))
    open(sys.argv[1], "w").write('["a"]\n')
''',
 "lingering_daemon": r'''
import os, sys, time
if os.fork() == 0:
    os.setsid()
    while True: time.sleep(0.1)
open(sys.argv[1], "w").write('["a"]\n')
''',
}
for name, code in progs.items():
    p = d / f"{name}.py"; p.write_text(code)
    rec = ev.run_command_on_instance([sys.executable, str(p), "{output}", "{instance}"], inst, 2.0)
    print(f"{name:26s} status={rec['status']:10s} cpu={rec['cpu_seconds']:.2f} wall={rec['wall_seconds']:.2f} procs={rec['tree_processes']} lines={len(rec['diagnoses'])} over={ev.over_budget(rec['cpu_seconds'], 2.0)}")
# make sure nothing lingers
time.sleep(0.3)
import subprocess
print(subprocess.run(["pgrep", "-f", str(d)], capture_output=True, text=True).stdout or "no leftover processes")
