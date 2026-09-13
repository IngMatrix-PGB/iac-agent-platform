# Root test fixture for the trusted SQS module.
#
# This is deliberately NOT a production/live composition — it exists
# only so the module can be exercised with `terraform validate`/`plan`
# under test conditions. The Terraform composer (a later batch) owns
# generated production compositions; this fixture is hand-authored and
# lives under tests/.
#
# The AWS provider is configured ONLY here, never inside the module
# itself, and is deliberately set up to require no real AWS account —
# see docs/terraform-credential-free-plan.md for the verified evidence.
# Credentials are supplied only via environment variables at invocation
# time (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY), never written here.
provider "aws" {
  region = var.aws_region

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

module "queue" {
  source = "../../../terraform/modules/sqs"

  name                       = var.name
  fifo                       = var.fifo
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  delay_seconds              = var.delay_seconds
  kms_key_id                 = var.kms_key_id
  dlq_enabled                = var.dlq_enabled
  max_receive_count          = var.max_receive_count
  tags                       = var.tags
}
