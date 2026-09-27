# Name rules mirror EcrResourceSpec: AWS CreateRepository's published
# regex, length 2-256. A leading digit is accepted because the regex
# accepts it.

variable "name" {
  description = "ECR repository name. Callers supply the exact final name."
  type        = string

  validation {
    condition     = length(var.name) >= 2 && length(var.name) <= 256
    error_message = "name must be between 2 and 256 characters."
  }

  validation {
    condition     = can(regex("^[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*(\\/[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*)*$", var.name))
    error_message = "name must match the ECR repository name pattern."
  }
}

variable "image_tag_mutability" {
  description = "MUTABLE or IMMUTABLE. Exclusion-filter modes are not supported."
  type        = string
  default     = "IMMUTABLE"

  validation {
    condition     = contains(["MUTABLE", "IMMUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be MUTABLE or IMMUTABLE."
  }
}

variable "scan_on_push" {
  description = "Whether images are scanned on push."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to the repository. Passed through as-is."
  type        = map(string)
  default     = {}
}
