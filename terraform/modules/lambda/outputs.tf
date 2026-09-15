output "function_name" {
  description = "The name of the Lambda function."
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "ARN of the Lambda function."
  value       = aws_lambda_function.this.arn
}

output "execution_role_arn" {
  description = "ARN of the Lambda function's IAM execution role."
  value       = aws_iam_role.this.arn
}

output "execution_role_name" {
  description = <<-EOT
    Name of the Lambda function's IAM execution role (aws_iam_role's own
    `id` attribute, which for this resource type equals its `name`).
    Exposed so a composition layer (Batch 19) can attach additional,
    narrowly-scoped `aws_iam_role_policy` resources to this exact role
    without this module needing to know anything about what those
    policies grant — this module's own baseline permissions are
    unaffected either way.
  EOT
  value       = aws_iam_role.this.id
}

output "log_group_name" {
  description = "Name of the function's CloudWatch Logs log group."
  value       = aws_cloudwatch_log_group.this.name
}
