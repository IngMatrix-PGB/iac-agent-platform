# Root fixture inputs — mirror the trusted module's variables 1:1 so
# each named scenario file under scenarios/ can drive the module
# through `terraform plan -var-file=scenarios/<name>.tfvars` without
# editing this fixture.

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "my-example-bucket"
}

variable "kms_key_id" {
  type    = string
  default = null
}

variable "versioning" {
  type    = bool
  default = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
