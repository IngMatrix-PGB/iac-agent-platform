# Batch 12.5 — scenario D: FIFO queue, 76-character primary name
# (71-character base + ".fifo"), the longest FIFO primary name whose
# derived "<base>-dlq.fifo" DLQ name stays at exactly 80 characters.
# DLQ enabled. Expected: plan succeeds.
name = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz012345678.fifo"
fifo = true
