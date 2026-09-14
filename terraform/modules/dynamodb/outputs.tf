output "table_name" {
  description = "The name of the DynamoDB table."
  value       = aws_dynamodb_table.this.name
}

output "table_arn" {
  description = "ARN of the DynamoDB table."
  value       = aws_dynamodb_table.this.arn
}
