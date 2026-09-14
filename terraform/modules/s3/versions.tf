# Same baseline as the trusted SQS module (terraform/modules/sqs) —
# lifecycle.precondition blocks (available since 1.2) are the only
# Terraform >= 1.2 feature this module relies on, kept at the same
# >= 1.5.0 floor for consistency across trusted modules.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Provider major version 6.x is the current stable line (same
      # constraint already verified and pinned by the trusted SQS
      # module) — a breaking major upgrade requires a deliberate
      # constraint change here.
      version = "~> 6.0"
    }
  }
}
