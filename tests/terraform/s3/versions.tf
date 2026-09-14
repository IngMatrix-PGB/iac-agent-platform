# Root test fixture — NOT part of the reusable module, and not a
# production composition. Its only job is to exercise the trusted S3
# module end-to-end (fmt/validate/plan) without a real AWS account.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
