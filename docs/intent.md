# Architecture intent

A natural-language request is interpreted into one `ArchitectureIntent`. A deterministic resolver then maps that intent onto one existing typed infrastructure request, or it stops. The model does not choose Terraform, IAM, a security result, or an approval.

## ArchitectureIntent

`ArchitectureIntent` is the only object an interpreter is allowed to produce. It is a frozen Pydantic model. There is no open dictionary and no unbounded free-form architecture field.

The resolver reads only these three fields:

| Field | Closed values |
| --- | --- |
| `workload_type` | `api`, `worker`, `storage`, `unspecified` |
| `interaction_pattern` | `synchronous`, `asynchronous`, `unspecified` |
| `capabilities` | `http_endpoint`, `queue_processing`, `persistence`, `object_storage`, `container_registry` |

`capabilities` is a set. The interpreter cannot invent a member. `parse_intent_payload` rejects a payload whose `schema_version` is not `"1"`, and Pydantic rejects a string outside an enum.

These fields are advisory. The resolver does not read them when it chooses an architecture:

- `logical_name_hint`
- `user_provided_hints`
- `assumptions`
- `unresolved_questions`
- `confidence`

`user_provided_hints` uses a separate closed vocabulary (`sqs`, `s3`, `dynamodb`, `lambda`, `api_gateway`, `ecr`). That vocabulary is not `ResourceType`, and it is not authority.

## Resolver boundary

`ArchitectureResolver.resolve` is pure. It does not call a model, read the network, or touch the filesystem. An intent matches one allowlisted combination or it does not. There is no nearest-match fallback.

| Workload | Interaction | Capabilities | Resolved request |
| --- | --- | --- | --- |
| `api` | `synchronous` | `http_endpoint` | API Gateway → Lambda |
| `api` | `synchronous` | `http_endpoint`, `persistence` | API Gateway → Lambda → DynamoDB |
| `worker` | `asynchronous` | `queue_processing`, `persistence` | SQS → Lambda → DynamoDB |
| `storage` | any | `object_storage` | S3 bucket |
| `storage` | any | `container_registry` | ECR repository |

Storage does not consult `interaction_pattern`. Any other fully specified combination is unsupported.

## Deterministic defaults

The intent has no field for a Lambda handler, an API route, or a DynamoDB key. When the resolver builds a spec it supplies fixed values:

- Lambda handler: `app.handler`
- API route: `POST /invoke`
- DynamoDB partition key: `id` (`S`)

Resource names come from `logical_name_hint` when it is usable, otherwise from `request_id`. The model does not choose the handler, the route, or the key.

## Clarification

Clarification is a typed ask from the resolver, not a question invented by the model.

- `workload_type=unspecified` asks for `api`, `worker`, or `storage`.
- An otherwise resolvable API or worker intent with `interaction_pattern=unspecified` asks for `synchronous` or `asynchronous`.

A clarification is not submitted to the workflow and is not written to the checkpoint.

## Unsupported and other failures

A fully specified intent that is not on the allowlist is `unsupported`. A storage workload with a capability set other than the two rows above is `unsupported_capability`. Other mismatches are `unsupported_combination`. The detail string names the workload and interaction; it is not a stack trace.

Unsupported intent does not reach Terraform. Unknown schema versions and unknown enum strings fail at parse time, before resolution.

## Model versus deterministic responsibility

The interpreter's job ends at a validated `ArchitectureIntent`. The resolver's job is the allowlist above. Terraform rendering, `terraform plan`, Checkov, platform policy, human approval, and GitHub publication all happen later, on the typed request the resolver already chose.
