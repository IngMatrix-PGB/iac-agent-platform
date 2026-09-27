# Trusted ECR module.
#
# Security invariant: encryption_type is hardcoded to AES256. There is
# no variable that can select KMS, and no kms_key argument. Scanning
# and tag mutability are caller-controlled and default to the secure
# values. force_delete, lifecycle policy, and repository policy are
# absent on purpose.

resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = var.image_tag_mutability

  image_scanning_configuration {
    scan_on_push = var.scan_on_push
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = var.tags
}
