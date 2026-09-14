# Batch 12.5 — scenario C: the same 77-character primary name as
# invalid-derived-dlq-name-too-long.tfvars, but with the DLQ disabled.
# No DLQ is ever created, so no derived name exists to be too long.
# Expected: plan succeeds.
name              = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789abcde"
dlq_enabled       = false
max_receive_count = null
