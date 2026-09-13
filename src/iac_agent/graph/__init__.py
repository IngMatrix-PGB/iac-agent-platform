"""LangGraph orchestration of the deterministic Phase 1 SQS pipeline.

The graph calls existing, already-proven components — it does not
reimplement contract validation, Terraform rendering/execution, plan
classification, platform policy, Checkov normalization, or security-gate
precedence. No LLM, message history, persistence, or human-in-the-loop
logic exists in this package yet.
"""
