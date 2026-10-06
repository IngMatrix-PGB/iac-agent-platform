# GENERATED FILE — do not edit by hand.
# Produced deterministically by S3TerraformCompositionRenderer from a
# validated S3ResourceSpec. Regenerate instead of modifying.

provider "aws" {
  region = "us-east-1"

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

module "bucket" {
  source = "../../terraform/modules/s3"

  name       = "user-uploads"
  kms_key_id = null
  versioning = true
  tags       = {}
}
