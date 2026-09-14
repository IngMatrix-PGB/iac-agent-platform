"""SQLite-backed durable LangGraph checkpoint persistence.

This is the only place in this project that imports ``sqlite3`` or
``langgraph.checkpoint.sqlite``. Domain, provider, security, and policy
code must never import from this package or from those modules
directly — they depend only on the generic, backend-agnostic
``BaseCheckpointSaver`` abstraction that ``iac_agent.graph.workflow``
accepts.
"""
