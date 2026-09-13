output "queue_arn" {
  value = module.queue.queue_arn
}

output "queue_url" {
  value = module.queue.queue_url
}

output "dlq_arn" {
  value = module.queue.dlq_arn
}

output "dlq_url" {
  value = module.queue.dlq_url
}
