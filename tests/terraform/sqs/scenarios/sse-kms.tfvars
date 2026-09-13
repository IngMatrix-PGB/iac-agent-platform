# Test case 5: SSE-KMS with a referenced (not created) KMS key.
# "alias/aws/sqs" is AWS's own predefined default alias for SQS SSE-KMS
# (see the aws_sqs_queue provider docs) — a syntactically valid
# reference that requires no KMS lookup to plan a new resource, so it
# works identically under the credential-free provider configuration.
name       = "order-events"
kms_key_id = "alias/aws/sqs"
