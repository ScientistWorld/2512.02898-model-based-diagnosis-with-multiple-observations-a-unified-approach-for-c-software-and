#!/usr/bin/env python3
"""Synthetic Boolean-circuit diagnosis benchmark for CFaults reproduction.

The original paper evaluates on ISCAS85 circuits with injected gate faults.
This module builds a small, tracked substitute benchmark that preserves the
same problem structure: a golden combinational circuit, a faulty variant, and
multiple failing input-output observations.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


OPS = {"AND", "OR", "XOR", "NAND", "NOR", "NOT", "BUF"}
BINARY_OPS = ("AND", "OR", "XOR", "NAND", "NOR")
UNARY_OPS = ("NOT", "BUF")


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
    gates: tuple[Gate, ...]


def eval_op(op: str, values: list[bool]) -> bool:
    if op == "AND":
        return all(values)
    if op == "OR":
        return any(values)
    if op == "XOR":
        out = False
        for value in values:
            out ^= value
        return out
    if op == "NAND":
        return not all(values)
    if op == "NOR":
        return not any(values)
    if op == "NOT":
        return not values[0]
    if op == "BUF":
        return values[0]
    raise ValueError(f"unknown op {op}")


def evaluate(circuit: Circuit, assignment: dict[str, bool]) -> dict[str, bool]:
    values = dict(assignment)
    for gate in circuit.gates:
        values[gate.name] = eval_op(gate.op, [values[name] for name in gate.inputs])
    return {name: values[name] for name in circuit.outputs}


def circuit_to_json(circuit: Circuit) -> dict:
    return {
        "name": circuit.name,
        "inputs": list(circuit.inputs),
        "outputs": list(circuit.outputs),
        "gates": [{"name": g.name, "op": g.op, "inputs": list(g.inputs)} for g in circuit.gates],
    }


def circuit_from_json(data: dict) -> Circuit:
    gates = tuple(Gate(g["name"], g["op"], tuple(g["inputs"])) for g in data["gates"])
    for gate in gates:
        if gate.op not in OPS:
            raise ValueError(f"unsupported gate op {gate.op}")
    return Circuit(data["name"], tuple(data["inputs"]), tuple(data["outputs"]), gates)


def build_adder_logic() -> Circuit:
    """Three full adders plus parity/control outputs, all gate-level."""
    gates: list[Gate] = []

    def add_gate(name: str, op: str, inputs: Iterable[str]) -> str:
        gates.append(Gate(name, op, tuple(inputs)))
        return name

    carry = "cin"
    sums = []
    for idx in range(3):
        a = f"a{idx}"
        b = f"b{idx}"
        axb = add_gate(f"g{idx}_axb", "XOR", [a, b])
        sums.append(add_gate(f"g{idx}_sum", "XOR", [axb, carry]))
        maj1 = add_gate(f"g{idx}_ab", "AND", [a, b])
        maj2 = add_gate(f"g{idx}_ac", "AND", [a, carry])
        maj3 = add_gate(f"g{idx}_bc", "AND", [b, carry])
        tmp = add_gate(f"g{idx}_carry_tmp", "OR", [maj1, maj2])
        carry = add_gate(f"g{idx}_carry", "OR", [tmp, maj3])
    p01 = add_gate("g_parity_01", "XOR", [sums[0], sums[1]])
    parity = add_gate("g_parity", "XOR", [p01, sums[2]])
    any_ab = add_gate("g_any_ab", "OR", ["a0", "b0"])
    ctrl = add_gate("g_ctrl", "AND", [any_ab, carry])
    return Circuit(
        "three_bit_adder_logic",
        ("a0", "a1", "a2", "b0", "b1", "b2", "cin"),
        (sums[0], sums[1], sums[2], carry, parity, ctrl),
        tuple(gates),
    )


def all_inputs(names: tuple[str, ...]) -> list[dict[str, bool]]:
    rows = []
    for mask in range(1 << len(names)):
        rows.append({name: bool((mask >> i) & 1) for i, name in enumerate(names)})
    return rows


def mutate_gate_op(gate: Gate, rng: random.Random) -> str:
    candidates = UNARY_OPS if len(gate.inputs) == 1 else BINARY_OPS
    choices = [op for op in candidates if op != gate.op]
    return rng.choice(choices)


def mutate_circuit(circuit: Circuit, rng: random.Random, fault_count: int) -> tuple[Circuit, dict[str, dict[str, str]]]:
    selected = set(rng.sample([gate.name for gate in circuit.gates], fault_count))
    mutations: dict[str, dict[str, str]] = {}
    mutated_gates: list[Gate] = []
    for gate in circuit.gates:
        if gate.name in selected:
            new_op = mutate_gate_op(gate, rng)
            mutations[gate.name] = {"from": gate.op, "to": new_op}
            mutated_gates.append(Gate(gate.name, new_op, gate.inputs))
        else:
            mutated_gates.append(gate)
    return Circuit(f"{circuit.name}_faulty", circuit.inputs, circuit.outputs, tuple(mutated_gates)), mutations


def make_instance(
    circuit: Circuit,
    rng: random.Random,
    fault_count: int,
    observation_count: int,
    index: int,
) -> dict:
    faulty_circuit, mutations = mutate_circuit(circuit, rng, fault_count)
    candidates = []
    for assignment in all_inputs(circuit.inputs):
        golden = evaluate(circuit, assignment)
        faulty = evaluate(faulty_circuit, assignment)
        if golden != faulty:
            candidates.append({"inputs": assignment, "expected_outputs": golden, "faulty_outputs": faulty})
    if len(candidates) < observation_count:
        raise RuntimeError("not enough failing observations for generated fault set")
    rng.shuffle(candidates)
    return {
        "id": f"{circuit.name}_f{fault_count}_o{observation_count}_{index:03d}",
        "fault_count": fault_count,
        "observation_count": observation_count,
        "faults": sorted(mutations),
        "fault_mutations": mutations,
        "faulty_circuit": circuit_to_json(faulty_circuit),
        "observations": candidates[:observation_count],
    }


def generate_benchmark(out_dir: Path, seed: int, instances_per_setting: int) -> None:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    circuit = build_adder_logic()
    (out_dir / "circuits").mkdir(exist_ok=True)
    (out_dir / "instances").mkdir(exist_ok=True)
    (out_dir / "circuits" / f"{circuit.name}.json").write_text(json.dumps(circuit_to_json(circuit), indent=2) + "\n")
    manifest = {
        "name": "synthetic_cfaults_circuit",
        "circuit": f"circuits/{circuit.name}.json",
        "deviation": "Small synthetic substitute for ISCAS85; same gate-mutation observation task.",
        "instances": [],
    }
    for fault_count in (1, 2, 3):
        for observation_count in (4, 8, 16):
            made = 0
            attempts = 0
            while made < instances_per_setting:
                attempts += 1
                instance = make_instance(circuit, rng, fault_count, observation_count, made)
                if attempts > 500:
                    raise RuntimeError("failed to generate enough benchmark instances")
                rel = f"instances/{instance['id']}.json"
                (out_dir / rel).write_text(json.dumps(instance, indent=2, sort_keys=True) + "\n")
                manifest["instances"].append({"path": rel, "fault_count": fault_count, "observation_count": observation_count})
                made += 1
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/synthetic_circuits"))
    parser.add_argument("--seed", type=int, default=251202898)
    parser.add_argument("--instances-per-setting", type=int, default=3)
    args = parser.parse_args()
    generate_benchmark(args.out, args.seed, args.instances_per_setting)


if __name__ == "__main__":
    main()
