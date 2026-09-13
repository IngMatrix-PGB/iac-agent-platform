# Root fixture inputs — mirror the trusted module's variables 1:1 so
# each named scenario file under scenarios/ can drive the module through
# `terraform plan -var-file=scenarios/<name>.tfvars` without editing
# this fixture. Defaults reproduce the "standard queue, DLQ enabled"
# scenario.

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "order-events"
}

variable "fifo" {
  type    = bool
  default = false
}

variable "visibility_timeout_seconds" {
  type    = number
  default = 30
}

variable "message_retention_seconds" {
  type    = number
  default = 345600
}

variable "delay_seconds" {
  type    = number
  default = 0
}

variable "kms_key_id" {
  type    = string
  default = null
}

variable "dlq_enabled" {
  type    = bool
  default = true
}

variable "max_receive_count" {
  type    = number
  default = 5
}

variable "tags" {
  type    = map(string)
  default = {}
}
