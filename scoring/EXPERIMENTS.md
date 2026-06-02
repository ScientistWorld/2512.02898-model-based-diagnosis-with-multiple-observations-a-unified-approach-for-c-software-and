# Experiment Overview

## iscas85_localisation

Tests the central benchmark question: how many faulty Boolean-circuit instances can be diagnosed successfully under the paper's main augmented ISCAS85 setting. This experiment establishes overall task coverage across the full set of generated circuit faults and failing observations.

## diagnosis_quality

Tests whether counted successes are real diagnoses rather than merely plausible fault hints. The purpose is to ensure that a method's reported components explain every failing observation for the circuit and meet the required minimality standard.

## observation_scaling

Tests whether performance remains robust as the number of failing observations increases. This separates methods that work only on small observation sets from methods that can handle the multi-observation setting emphasized by the paper.

## runtime_efficiency

Tests whether diagnoses are obtained within the benchmark timeout without producing an impractically large set of candidate diagnoses. Wall-clock runtime is not a scored gym metric because hardware varies across agents; scored metrics use timeout/memory outcomes and output-volume proxies.
