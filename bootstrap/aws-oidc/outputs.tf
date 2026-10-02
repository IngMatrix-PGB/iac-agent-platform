output "iac_plan_role_arn" {
  value       = aws_iam_role.iac_plan_role.arn
  description = "Non-secret. Consumed by iac-agent-platform's CI as the AWS_PLAN_ROLE_ARN repository variable — the only configuration iac-agent-platform ever needs from this bootstrap plane."
}

output "github_oidc_provider_arn" {
  value       = data.aws_iam_openid_connect_provider.github_actions.arn
  description = "Non-secret. The existing account-level GitHub OIDC provider. This module does not create it."
}
