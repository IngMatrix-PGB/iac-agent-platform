# Test case 8: visibility_timeout_seconds above the AWS/module maximum.
# Expected: `terraform plan` fails the module's variable validation.
name                       = "order-events"
visibility_timeout_seconds = 99999
