# Trusted API Gateway (HTTP API) module (Phase 2, Batch 20).
#
# Owns exactly the API itself and its one managed stage — never a
# route, integration, or Lambda permission, all of which are
# relationships a composition owns (see
# iac_agent.compositions.api_lambda), mirroring exactly how this
# project's Lambda module never owns an SQS event source mapping.
#
# protocol_type is hardcoded to "HTTP" — there is no variable that can
# produce a WEBSOCKET API from this module.

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  description   = var.description
  tags          = var.tags
}

# A single managed "$default" stage with auto_deploy enabled — the
# smallest deterministic stage model for Phase 2. No dev/staging/prod
# stage management; every route this platform generates is
# automatically live on this one stage.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags
}
