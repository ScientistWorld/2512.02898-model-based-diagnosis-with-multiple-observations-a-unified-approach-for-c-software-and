"""Can a same-user child read its parent's memory (/proc/<ppid>/mem)?  The hidden-test
evaluator holds the answers in memory while method code runs; it now sets
PR_SET_DUMPABLE=0.  Run: python3 redteam/hardening/local_checks/check_memory_read.py"""
import ctypes
import subprocess
import sys

secret = "SECRET-" + "X" * 20  # noqa: F841  (kept alive in this process's memory)
probe = r'''
import os
ppid = os.getppid()
try:
    maps = open(f"/proc/{ppid}/maps").read().splitlines()
    mem = open(f"/proc/{ppid}/mem", "rb", 0)
    found = False
    for line in maps:
        addr, perms = line.split()[:2]
        if "r" not in perms: continue
        a, b = (int(x, 16) for x in addr.split("-"))
        if b - a > 64 * 1024 * 1024: continue
        try:
            mem.seek(a); chunk = mem.read(b - a)
        except OSError: continue
        if b"SECRET-XXXX" in chunk: found = True; break
    print("secret found in parent memory:", found)
except OSError as e:
    print("blocked:", e)
'''
print("parent dumpable (default):", flush=True)
subprocess.run([sys.executable, "-c", probe])
ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 0, as the evaluator does
print("parent non-dumpable:", flush=True)
subprocess.run([sys.executable, "-c", probe])
