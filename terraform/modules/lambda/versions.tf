# Same baseline as the trusted SQS/S3/DynamoDB modules. No additional
# Terraform provider was introduced for this module — the deployment
# package is a trusted, checked-in fixture file referenced directly via
# `filebase64sha256()` and `${path.module}`, not the `archive_file` data
# source from the separate `hashicorp/archive` provider, so this module
# still requires only the `aws` provider already in use everywhere else.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Provider major version 6.x is the current stable line (same
      # constraint already verified and pinned by the trusted SQS/S3/
      # DynamoDB modules). `aws_lambda_function`, `aws_iam_role`,
      # `aws_iam_role_policy`, `aws_cloudwatch_log_group`, and the
      # `aws_iam_policy_document` data source were all verified
      # empirically against this provider version before writing
      # main.tf.
      version = "~> 6.0"
    }
  }
}
