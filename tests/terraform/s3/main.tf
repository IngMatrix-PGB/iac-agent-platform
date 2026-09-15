# Root test fixture for the trusted S3 module — mirrors
# tests/terraform/sqs/main.tf exactly (see docs/terraform-credential-free-plan.md
# for the credential-free provider configuration this reuses verbatim).
provider "aws" {
  region = var.aws_region

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

module "bucket" {
  source = "../../../terraform/modules/s3"

  name       = var.name
  kms_key_id = var.kms_key_id
  versioning = var.versioning
  tags       = var.tags
}
