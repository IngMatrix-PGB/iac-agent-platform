"""Deterministic platform security/policy evaluation.

Every policy here is plain Python: no Checkov, no LangChain/LangGraph,
no AWS SDK, no Terraform execution, no LLM. Policies consume only the
already-established typed facts (SQSResourceSpec, PlanSummary) — never
raw Terraform plan JSON.
"""
