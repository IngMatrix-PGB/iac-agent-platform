# Batch 12.5 — scenario B: standard queue, 77-character primary name
# (one character past the derived-DLQ-name boundary). DLQ enabled, so
# the derived "<name>-dlq" name is 81 characters — exceeds the SQS
# 80-character limit. Expected: plan fails on the module's
# lifecycle.precondition.
name = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789abcde"
