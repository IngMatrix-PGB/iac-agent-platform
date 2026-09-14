# Batch 12.5 — scenario A: standard queue, 76-character primary name
# (the longest primary name whose derived "<name>-dlq" DLQ name stays
# at exactly 80 characters), DLQ enabled. Expected: plan succeeds.
name = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789abcd"
