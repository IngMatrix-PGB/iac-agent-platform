"""Deterministic evaluation harness for the Phase 1 SQS vertical slice.

Evals are versioned behavioral scenarios (input -> expected behavior),
not unit tests with a new name: the test suite under ``tests/`` verifies
this eval framework itself; the scenarios under ``evals/datasets/``
verify actual product behavior against a golden dataset. The entire
deterministic suite runs with no LLM, network, or paid API calls.
"""
