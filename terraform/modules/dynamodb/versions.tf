# Same baseline as the trusted SQS/S3 modules — lifecycle.precondition
# blocks (available since 1.2) are the only Terraform >= 1.2 feature
# any trusted module relies on, kept at the same >= 1.5.0 floor for
# consistency.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Provider major version 6.x is the current stable line (same
      # constraint already verified and pinned by the trusted SQS/S3
      # modules) — a breaking major upgrade requires a deliberate
      # constraint change here. `aws_dynamodb_table`'s exact schema
      # (deletion_protection_enabled, server_side_encryption.kms_key_arn,
      # point_in_time_recovery block) was verified empirically against
      # this provider version before writing main.tf.
      version = "~> 6.0"
    }
  }
}
