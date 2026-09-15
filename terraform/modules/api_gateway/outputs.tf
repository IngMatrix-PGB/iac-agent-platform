output "api_id" {
  description = "ID of the HTTP API."
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "The default endpoint (invoke URL prefix) for the HTTP API."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "execution_arn" {
  description = <<-EOT
    The API's execution ARN (arn:aws:execute-api:region:account:api-id),
    used by a composition layer (Batch 20) to build a narrowly-scoped
    `aws_lambda_permission.source_arn` for exactly this API's stage and
    route — never a hardcoded or synthesized ARN.
  EOT
  value       = aws_apigatewayv2_api.this.execution_arn
}
