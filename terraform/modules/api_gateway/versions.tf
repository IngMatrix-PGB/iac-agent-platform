# Same baseline as every other trusted module in this project.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Provider major version 6.x is the current stable line (same
      # constraint already verified and pinned by every other trusted
      # module) — a breaking major upgrade requires a deliberate
      # constraint change here. `aws_apigatewayv2_api`/`aws_apigatewayv2_
      # stage`'s exact schemas were verified empirically against this
      # provider version (via `terraform providers schema -json`)
      # before writing main.tf.
      version = "~> 6.0"
    }
  }
}
