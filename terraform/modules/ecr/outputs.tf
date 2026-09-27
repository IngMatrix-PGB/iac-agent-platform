output "arn" {
  description = "ARN of the ECR repository."
  value       = aws_ecr_repository.this.arn
}

output "repository_url" {
  description = "URL of the ECR repository."
  value       = aws_ecr_repository.this.repository_url
}

output "registry_id" {
  description = "Registry ID of the ECR repository."
  value       = aws_ecr_repository.this.registry_id
}
