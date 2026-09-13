# Test case 9: contradictory DLQ configuration (dlq_enabled = true but
# max_receive_count left null instead of a valid 1-1000 value).
# Expected: `terraform plan` fails the module's lifecycle.precondition.
name              = "order-events"
dlq_enabled       = true
max_receive_count = null
