"""Cross-cutting domain models shared across providers and execution layers.

Kept intentionally small — a model only belongs here once it is
genuinely used by more than one layer (unlike SQS-specific contracts,
which stay under ``providers/aws/sqs``).
"""
