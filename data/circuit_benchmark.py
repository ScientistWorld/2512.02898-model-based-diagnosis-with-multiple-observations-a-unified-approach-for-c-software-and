#!/usr/bin/env python3
"""ISCAS85 multi-observation circuit-diagnosis benchmark (public utilities).

The paper evaluates fault localisation on the ISCAS85 combinational circuits
with injected faults and 10-50 failing input/output observations.  This module
rebuilds that benchmark at reduced scale:

* golden netlists are the public ISCAS85 ``.bench`` files fetched by
  ``scripts/download.sh`` into ``data/downloads/iscas85``;
* a fault is a gate-type change (e.g. NAND -> NOR) at a uniformly chosen gate;
* an observation is a random primary-input vector on which the faulty circuit's
  outputs differ from the golden circuit's outputs, recorded together with the
  golden (expected) outputs;
* every signal is renamed and the gate list is put in a random topological
  order, so instances cannot be matched to the public netlists by name.

A diagnosis method only ever receives ``public_view(instance)``: the faulty
netlist and the observations.  Injected-fault labels never reach a method.

Command line (regenerates the public training split, deterministic):

    python data/circuit_benchmark.py --bench-dir data/downloads/iscas85 \
        --out data/iscas85_train
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

OPS = ("AND", "NAND", "OR", "NOR", "XOR", "NOT", "BUF")
MULTI_INPUT_OPS = ("AND", "NAND", "OR", "NOR")
TWO_INPUT_OPS = ("AND", "NAND", "OR", "NOR", "XOR")
UNARY_OPS = ("NOT", "BUF")

# Benchmark grid (scaled version of the paper's 10 circuits x {1..50 faults}
# x {10,20,30,40,50 observations}).
# Base tier: the five smaller ISCAS85 circuits, full observation grid.
CIRCUITS = ("c432", "c499", "c880", "c1355", "c1908")
FAULT_COUNTS = (1, 3, 5)
OBSERVATION_COUNTS = (10, 20, 30, 40, 50)
# Scale-stress tier: the larger ISCAS85 circuits (1.2k-3.5k gates), multi-fault.
STRESS_CIRCUITS = ("c2670", "c3540", "c5315", "c7552")
STRESS_FAULT_COUNTS = (3, 5)
STRESS_OBSERVATION_COUNTS = (10, 30, 50)
TRAIN_SEED = "cfaults-iscas85-public-train-v2"

ISCAS85_URL = "https://pld.ttu.ee/~maksim/benchmarks/iscas85/bench/{name}.bench"
ISCAS85_SHA256 = {
    "c432": "c3a37ac6850aa737",
    "c499": "a7a6a6c48c2b7c66",
    "c880": "6c8940cdbd4b59e3",
    "c1355": "21cf62a376a0fde9",
    "c1908": "948e4c168d412bb5",
    "c2670": "f9cea6f6734725b8",
    "c3540": "57c629ae6bbb9cd2",
    "c5315": "5da6e65f5df89a39",
    "c7552": "209d2aa40b31abec",
}


@dataclass(frozen=True)
class Gate:
    name: str
    op: str
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class Circuit:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    gates: tuple[Gate, ...]  # topologically ordered


# --------------------------------------------------------------------------
# Netlists
# --------------------------------------------------------------------------


def _normalise_op(op: str) -> str:
    op = op.upper()
    if op in ("BUFF", "BUF"):
        return "BUF"
    if op not in OPS:
        raise ValueError(f"unsupported gate type {op}")
    return op


def topological_gates(inputs: Iterable[str], gates: Iterable[Gate], rng: random.Random | None = None) -> tuple[Gate, ...]:
    """Kahn's algorithm; with ``rng`` the order among ready gates is random."""
    gates = list(gates)
    known = set(inputs)
    by_name = {g.name: g for g in gates}
    if len(by_name) != len(gates):
        raise ValueError("duplicate gate names")
    pending = {g.name: sum(1 for x in set(g.inputs) if x not in known) for g in gates}
    users: dict[str, list[str]] = {}
    for g in gates:
        for x in set(g.inputs):
            if x not in known:
                if x not in by_name:
                    raise ValueError(f"gate {g.name} reads undefined signal {x}")
                users.setdefault(x, []).append(g.name)
    ready = sorted(name for name, n in pending.items() if n == 0)
    order: list[Gate] = []
    while ready:
        idx = rng.randrange(len(ready)) if rng is not None else 0
        name = ready.pop(idx)
        order.append(by_name[name])
        for user in users.get(name, []):
            pending[user] -= 1
            if pending[user] == 0:
                if rng is None:
                    # keep deterministic sorted insertion
                    ready.append(user)
                    ready.sort()
                else:
                    ready.append(user)
    if len(order) != len(gates):
        raise ValueError("netlist is cyclic")
    return tuple(order)


def parse_bench(text: str, name: str) -> Circuit:
    inputs: list[str] = []
    outputs: list[str] = []
    gates: list[Gate] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"INPUT\s*\(\s*(\S+?)\s*\)", line, flags=re.I)
        if m:
            inputs.append(m.group(1))
            continue
        m = re.fullmatch(r"OUTPUT\s*\(\s*(\S+?)\s*\)", line, flags=re.I)
        if m:
            if m.group(1) not in outputs:
                outputs.append(m.group(1))
            continue
        m = re.fullmatch(r"(\S+)\s*=\s*(\w+)\s*\((.*)\)", line)
        if not m:
            raise ValueError(f"cannot parse line: {raw!r}")
        args = tuple(x.strip() for x in m.group(3).split(",") if x.strip())
        op = _normalise_op(m.group(2))
        if op in UNARY_OPS and len(args) != 1:
            raise ValueError(f"{op} gate {m.group(1)} needs one input")
        if op not in UNARY_OPS and len(args) < 2:
            # degenerate one-input AND/OR: model as buffer / inverter
            op = "BUF" if op in ("AND", "OR") else "NOT"
        if op == "XOR" and len(args) != 2:
            raise ValueError("only two-input XOR gates are supported")
        gates.append(Gate(m.group(1), op, args))
    ordered = topological_gates(inputs, gates)
    return Circuit(name, tuple(inputs), tuple(outputs), ordered)


def load_iscas85(bench_dir: Path, name: str) -> Circuit:
    return parse_bench((Path(bench_dir) / f"{name}.bench").read_text(), name)


def circuit_to_json(circuit: Circuit) -> dict:
    return {
        "name": circuit.name,
        "inputs": list(circuit.inputs),
        "outputs": list(circuit.outputs),
        "gates": [{"name": g.name, "op": g.op, "inputs": list(g.inputs)} for g in circuit.gates],
    }


def circuit_from_json(data: dict) -> Circuit:
    gates = tuple(Gate(g["name"], _normalise_op(g["op"]), tuple(g["inputs"])) for g in data["gates"])
    return Circuit(data.get("name", "circuit"), tuple(data["inputs"]), tuple(data["outputs"]), gates)


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------


def eval_op(op: str, values: list[bool]) -> bool:
    if op == "AND":
        return all(values)
    if op == "NAND":
        return not all(values)
    if op == "OR":
        return any(values)
    if op == "NOR":
        return not any(values)
    if op == "XOR":
        out = False
        for value in values:
            out ^= bool(value)
        return out
    if op == "NOT":
        return not values[0]
    if op == "BUF":
        return bool(values[0])
    raise ValueError(f"unknown op {op}")


def evaluate(circuit: Circuit, assignment: dict[str, bool]) -> dict[str, bool]:
    values = dict(assignment)
    for gate in circuit.gates:
        values[gate.name] = eval_op(gate.op, [values[name] for name in gate.inputs])
    return {name: values[name] for name in circuit.outputs}


def eval_op_words(op: str, words: list[int], mask: int) -> int:
    """Bit-parallel gate evaluation: every bit position is one input vector."""
    if op in ("AND", "NAND"):
        acc = mask
        for w in words:
            acc &= w
        return acc if op == "AND" else (~acc) & mask
    if op in ("OR", "NOR"):
        acc = 0
        for w in words:
            acc |= w
        return acc if op == "OR" else (~acc) & mask
    if op == "XOR":
        acc = 0
        for w in words:
            acc ^= w
        return acc
    if op == "NOT":
        return (~words[0]) & mask
    if op == "BUF":
        return words[0]
    raise ValueError(f"unknown op {op}")


def simulate_words(circuit: Circuit, input_words: dict[str, int], width: int, forced: dict[str, int] | None = None) -> dict[str, int]:
    mask = (1 << width) - 1
    values = dict(input_words)
    forced = forced or {}
    for gate in circuit.gates:
        if gate.name in forced:
            values[gate.name] = forced[gate.name] & mask
        else:
            values[gate.name] = eval_op_words(gate.op, [values[x] for x in gate.inputs], mask)
    return values


def diagnosis_semantically_valid(circuit: Circuit, observations: list[dict], diagnosis: Iterable[str]) -> bool:
    """Exact check, independent of any CNF encoding.

    A diagnosis is valid iff for every observation some assignment of free
    output values to the diagnosed gates makes the circuit produce the
    expected outputs.  All 2^k assignments are simulated at once with
    bit-parallel words of width 2^k.
    """
    diag = list(dict.fromkeys(diagnosis))
    gate_names = {g.name for g in circuit.gates}
    if any(name not in gate_names for name in diag):
        return False
    k = len(diag)
    width = 1 << k
    mask = (1 << width) - 1
    forced = {}
    for j, name in enumerate(diag):
        word = 0
        for combo in range(width):
            if (combo >> j) & 1:
                word |= 1 << combo
        forced[name] = word
    for obs in observations:
        words = {name: (mask if value else 0) for name, value in obs["inputs"].items()}
        values = simulate_words(circuit, words, width, forced)
        ok = mask
        for name, expected in obs["expected_outputs"].items():
            ok &= values[name] if expected else (~values[name]) & mask
            if not ok:
                return False
        if not ok:
            return False
    return True


# --------------------------------------------------------------------------
# Instance generation
# --------------------------------------------------------------------------


def stable_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:32], 16)


def mutation_choices(gate: Gate) -> list[str]:
    if len(gate.inputs) == 1:
        pool = UNARY_OPS
    elif len(gate.inputs) == 2:
        pool = TWO_INPUT_OPS
    else:
        pool = MULTI_INPUT_OPS
    return [op for op in pool if op != gate.op]


def mutate_circuit(circuit: Circuit, rng: random.Random, fault_count: int) -> tuple[Circuit, dict[str, dict[str, str]]]:
    selected = set(rng.sample([g.name for g in circuit.gates], fault_count))
    mutations: dict[str, dict[str, str]] = {}
    gates = []
    for gate in circuit.gates:
        if gate.name in selected:
            new_op = rng.choice(mutation_choices(gate))
            mutations[gate.name] = {"from": gate.op, "to": new_op}
            gates.append(Gate(gate.name, new_op, gate.inputs))
        else:
            gates.append(gate)
    return Circuit(circuit.name, circuit.inputs, circuit.outputs, tuple(gates)), mutations


def find_failing_observations(
    golden: Circuit,
    faulty: Circuit,
    rng: random.Random,
    count: int,
    max_vectors: int = 1 << 16,
    width: int = 1024,
) -> list[dict] | None:
    seen: set[tuple[bool, ...]] = set()
    found: list[dict] = []
    drawn = 0
    while drawn < max_vectors and len(found) < count:
        words = {name: rng.getrandbits(width) for name in golden.inputs}
        g = simulate_words(golden, words, width)
        f = simulate_words(faulty, words, width)
        diff = 0
        for out in golden.outputs:
            diff |= g[out] ^ f[out]
        drawn += width
        bit = 0
        while diff and len(found) < count:
            if diff & 1:
                key = tuple(bool((words[name] >> bit) & 1) for name in golden.inputs)
                if key not in seen:
                    seen.add(key)
                    found.append(
                        {
                            "inputs": {name: bool((words[name] >> bit) & 1) for name in golden.inputs},
                            "expected_outputs": {out: bool((g[out] >> bit) & 1) for out in golden.outputs},
                        }
                    )
            diff >>= 1
            bit += 1
    return found if len(found) >= count else None


def obfuscate(circuit: Circuit, observations: list[dict], faults: Iterable[str], rng: random.Random) -> tuple[Circuit, list[dict], list[str], dict[str, str]]:
    """Rename every signal and randomise the (topological) gate order."""
    in_names = list(circuit.inputs)
    gate_names = [g.name for g in circuit.gates]
    rng.shuffle(in_names)
    rng.shuffle(gate_names)
    rename = {name: f"i{j}" for j, name in enumerate(in_names)}
    rename.update({name: f"g{j}" for j, name in enumerate(gate_names)})
    gates = [Gate(rename[g.name], g.op, tuple(rename[x] for x in g.inputs)) for g in circuit.gates]
    inputs = [rename[x] for x in circuit.inputs]
    rng.shuffle(inputs)
    outputs = [rename[x] for x in circuit.outputs]
    rng.shuffle(outputs)
    ordered = topological_gates(inputs, gates, rng)
    new_circuit = Circuit("circuit", tuple(inputs), tuple(outputs), ordered)
    new_obs = []
    for obs in observations:
        new_obs.append(
            {
                "inputs": {rename[k]: v for k, v in sorted(obs["inputs"].items(), key=lambda kv: rename[kv[0]])},
                "expected_outputs": {rename[k]: obs["expected_outputs"][k] for k in circuit.outputs},
            }
        )
    return new_circuit, new_obs, sorted(rename[f] for f in faults), rename


def make_instance(golden: Circuit, split: str, seed_text: str, fault_count: int, observation_count: int, attempt: int,
                  tier: str = "base") -> dict | None:
    """Deterministic candidate instance for one grid cell and attempt index."""
    rng = random.Random(stable_seed(seed_text, golden.name, fault_count, observation_count, attempt))
    faulty, mutations = mutate_circuit(golden, rng, fault_count)
    observations = find_failing_observations(golden, faulty, rng, observation_count)
    if observations is None:
        return None
    rng.shuffle(observations)
    circuit, obs, faults, rename = obfuscate(faulty, observations, mutations, rng)
    public_id = "inst_" + hashlib.sha256(f"{seed_text}|{golden.name}|{fault_count}|{observation_count}|{attempt}".encode()).hexdigest()[:16]
    return {
        "id": public_id,
        "split": split,
        "tier": tier,
        "source_circuit": golden.name,
        "fault_count": fault_count,
        "observation_count": observation_count,
        "attempt": attempt,
        "faults": faults,
        "fault_mutations": {rename[name]: change for name, change in sorted(mutations.items())},
        "circuit": circuit_to_json(circuit),
        "observations": obs,
    }


def public_view(instance: dict) -> dict:
    """The only part of an instance a diagnosis method is given."""
    return {"id": instance["id"], "circuit": instance["circuit"], "observations": instance["observations"]}


def grid() -> list[tuple[str, int, int]]:
    return [(c, k, m) for c in CIRCUITS for k in FAULT_COUNTS for m in OBSERVATION_COUNTS]


def stress_grid() -> list[tuple[str, int, int]]:
    return [(c, k, m) for c in STRESS_CIRCUITS for k in STRESS_FAULT_COUNTS for m in STRESS_OBSERVATION_COUNTS]


def cell_key(tier: str, circuit: str, k: int, m: int) -> str:
    return f"{circuit}|{k}|{m}" if tier == "base" else f"{tier}|{circuit}|{k}|{m}"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def generate_split(bench_dir: Path, split: str, seed_text: str, accepted: dict[str, int] | None = None) -> list[dict]:
    """Generate one instance per grid cell (base tier, then scale-stress tier).

    ``accepted`` maps a cell key (see ``cell_key``) to the attempt index that
    was accepted when the split was built (an attempt is rejected only if no
    failing observations exist or the exact answer is too large to enumerate
    offline); stress cells absent from ``accepted`` were skipped.
    """
    circuits = {name: load_iscas85(bench_dir, name) for name in CIRCUITS + STRESS_CIRCUITS}
    rows = []
    cells = [("base", *c) for c in grid()] + [("stress", *c) for c in stress_grid()]
    for tier, circuit_name, k, m in cells:
        key = cell_key(tier, circuit_name, k, m)
        if accepted is not None and key not in accepted:
            continue
        attempt = (accepted or {}).get(key, 0)
        while True:
            inst = make_instance(circuits[circuit_name], split, seed_text, k, m, attempt, tier)
            if inst is not None:
                break
            attempt += 1
        rows.append(inst)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bench-dir", type=Path, default=Path("data/downloads/iscas85"))
    parser.add_argument("--out", type=Path, default=Path("data/iscas85_train"))
    args = parser.parse_args()
    manifest_path = args.out / "manifest.json"
    accepted = json.loads(manifest_path.read_text()).get("accepted_attempts") if manifest_path.exists() else None
    rows = generate_split(args.bench_dir, "train", TRAIN_SEED, accepted)
    write_jsonl(args.out / "instances.jsonl", rows)
    print(f"wrote {len(rows)} training instances to {args.out / 'instances.jsonl'}")


if __name__ == "__main__":
    main()
