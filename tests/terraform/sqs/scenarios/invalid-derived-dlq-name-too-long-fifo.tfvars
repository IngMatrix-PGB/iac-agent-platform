# Batch 12.5 — scenario E: FIFO queue, 77-character primary name
# (72-character base + ".fifo"), one character past the derived-DLQ-
# name boundary. DLQ enabled, so the derived "<base>-dlq.fifo" name is
# 81 characters — exceeds the SQS 80-character limit. Expected: plan
# fails on the module's lifecycle.precondition.
name = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789.fifo"
fifo = true
