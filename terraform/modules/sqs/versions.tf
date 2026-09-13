# Minimum tested with lifecycle.precondition blocks (available since 1.2)
# and the endswith() built-in function (added in Terraform 1.3.0, confirmed
# against the upstream CHANGELOG). Empirically exercised locally against
# Terraform 1.16.1 as part of Batch 3's credential-free planning spike.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Provider major version 6.x is the current stable line (verified
      # against the Terraform Registry at implementation time; 5.x is no
      # longer the latest). Pinned to the 6.x major so patch/minor
      # upgrades are picked up automatically but a breaking major upgrade
      # requires a deliberate constraint change here.
      version = "~> 6.0"
    }
  }
}
