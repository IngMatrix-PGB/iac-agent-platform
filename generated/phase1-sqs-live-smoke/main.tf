# GENERATED FILE — do not edit by hand.
# Produced deterministically by TerraformCompositionRenderer from a
# validated SQSResourceSpec. Regenerate instead of modifying.

provider "aws" {
  region = "us-east-1"

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

module "queue" {
  source = "../../terraform/modules/sqs"

  name                       = "iac-agent-phase1-demo"
  fifo                       = false
  visibility_timeout_seconds = 30
  message_retention_seconds  = 345600
  delay_seconds              = 0
  kms_key_id                 = null
  dlq_enabled                = true
  max_receive_count          = 5
  tags = {
    "ManagedBy" = "iac-agent-platform"
    "Purpose"   = "phase1-live-smoke"
  }
}
