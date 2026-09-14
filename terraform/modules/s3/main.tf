# Trusted S3 module.
#
# Security invariant: there is no variable and no code path in this
# module that can produce an unencrypted bucket, a bucket with public
# access unblocked, or a bucket reachable over plain HTTP. Those three
# properties are unconditional here — mirroring exactly how the
# trusted SQS module has no "encryption_enabled" toggle at all. Only
# `versioning` is a genuine caller-controlled option, since disabling
# it is a legitimate (if not recommended) choice surfaced as a WARN by
# a later policy layer, not rejected here.

locals {
  use_kms = var.kms_key_id != null
}

resource "aws_s3_bucket" "this" {
  bucket = var.name
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = var.versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = local.use_kms ? "aws:kms" : "AES256"
      kms_master_key_id = local.use_kms ? var.kms_key_id : null
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.this.id

  # Deterministic JSON via jsonencode() — never LLM-produced, never
  # hand-interpolated string concatenation.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.this.arn,
          "${aws_s3_bucket.this.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })

  # Applying a bucket policy while public access is still unblocked
  # can conflict; the public access block must land first.
  depends_on = [aws_s3_bucket_public_access_block.this]
}
