# Fixture for the provider-override merge test. This is not a published
# proposal. It carries only the credential-free AWS provider block the
# renderer emits, so the override test does not depend on a historical
# request id.

provider "aws" {
  region = "us-east-1"

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}
