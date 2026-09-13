# Test case 2: standard queue with DLQ disabled.
# max_receive_count must be explicit null — the module precondition
# rejects a non-null value when dlq_enabled = false.
name              = "order-events-no-dlq"
dlq_enabled       = false
max_receive_count = null
