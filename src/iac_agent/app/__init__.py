"""Application composition root (Batch 15).

This is the one place Phase 1's individually-tested components
(renderer, Terraform runner, Checkov adapter, GitHub adapter, SQLite
checkpointer, LangGraph workflow) are wired together into something a
future FastAPI/CLI layer can call without constructing any of that
complexity itself.

``iac_agent.app.config`` — typed, non-secret configuration plus
explicit environment loaders. ``iac_agent.app.composition`` — builds
the real adapters and the compiled graph. ``iac_agent.app.service`` —
the small `Phase1Application` service (`submit`/`resume`/`get_state`)
and its bounded `WorkflowView` result type.
"""
