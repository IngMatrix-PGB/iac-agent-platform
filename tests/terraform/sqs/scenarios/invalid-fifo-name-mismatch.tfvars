# Test case 7: fifo = true without a ".fifo" name suffix.
# Expected: `terraform plan` fails the module's lifecycle.precondition.
name = "order-processing"
fifo = true
