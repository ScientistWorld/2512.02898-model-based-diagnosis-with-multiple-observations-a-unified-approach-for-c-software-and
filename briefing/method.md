# Paper's Method

## Key Contribution

CFaults formulates fault localisation for C programs and Boolean circuits as model-based diagnosis with multiple observations. For the circuit benchmark, its core contribution is to explain all failing input-output observations in one optimisation problem and return only minimum diagnoses for the gates/components of the circuit.

## Approach

For Boolean circuits, CFaults first replicates the faulty circuit once per failing observation. Each replica receives fresh variables for that observation's inputs, outputs, and internal gates, while corresponding gates across replicas share a common health/relaxation variable. This shared health variable represents whether the original circuit component is considered active or faulty across all observations.

The replicated and instrumented circuit is encoded as an unweighted partial MaxSAT instance. Hard clauses encode the circuit replicas and the failing input-output observations. Soft unit clauses prefer every circuit component to remain healthy. Solving the MaxSAT instance minimises the number of disabled components, so the false health variables identify a minimum-cardinality diagnosis that is consistent with all observations at once.

The paper contrasts this with HSD, which reasons through multiple per-observation oracle calls and hitting sets. CFaults instead uses a unified MaxSAT formulation for all observations, then enumerates optimal solutions when multiple minimum diagnoses exist (Algorithm 5): after each optimum, a blocking clause over the disabled health variables is added to the hard clauses and the MaxSAT oracle (RC2Stratified from PySAT, as in the paper) is called again, until the optimum cost increases. As in the authors' public CFaults tool, one oracle is kept for the whole enumeration and each blocking clause is added to it incrementally (`method/cfaults_circuit.py`).

## Main Claims

The primary circuit-side claim is that this unified diagnosis formulation remains competitive on Boolean circuits with multiple faults and multiple failing observations, even though HSD remains faster and localises more circuits overall.

The paper reports that on augmented ISCAS85, CFaults localises 8,969 of 12,147 faulty circuits (73.84%) within 1800 seconds, compared with 9,735 (80.14%) for HSD and 9,678 (79.67%) for HSD-CM. The gap is about 6 percentage points overall and is smaller for the 10- and 20-observation groups.

The broader claim is that jointly reasoning over observations avoids redundant or inconsistent aggregation behaviour seen in some one-observation-at-a-time diagnosis workflows, while still producing subset-minimal diagnoses.
