output "queue_arn" {
  description = "ARN of the primary SQS queue."
  value       = aws_sqs_queue.this.arn
}

output "queue_url" {
  description = "URL of the primary SQS queue."
  value       = aws_sqs_queue.this.url
}

output "dlq_arn" {
  description = "ARN of the dead-letter queue, or null when dlq_enabled = false."
  value       = var.dlq_enabled ? aws_sqs_queue.dlq[0].arn : null
}

output "dlq_url" {
  description = "URL of the dead-letter queue, or null when dlq_enabled = false."
  value       = var.dlq_enabled ? aws_sqs_queue.dlq[0].url : null
}
