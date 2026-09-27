"""Optional Langfuse sink. The SDK is imported only inside a function."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import SecretStr

from iac_agent.observability.models import (
    GenerationTelemetry,
    ResolutionTelemetry,
    WorkflowTelemetry,
)

_DEFAULT_BASE_URL = "https://cloud.langfuse.com"


class LangfuseObservability:
    """Emit allowlisted telemetry through an injected trace client.

    The client is either `SdkTraceClient` around the real SDK or a fake
    in tests. This class does not read domain objects and does not catch
    client failures.
    """

    def __init__(self, client) -> None:
        self._client = client

    def record_generation(self, event: GenerationTelemetry) -> None:
        usage: dict[str, int] = {}
        if event.input_tokens is not None:
            usage["input"] = event.input_tokens
        if event.output_tokens is not None:
            usage["output"] = event.output_tokens
        self._emit(
            event.request_id,
            name="intent.interpret",
            as_type="generation",
            metadata={
                "request_id": event.request_id,
                "provider": event.provider,
                "prompt_version": event.prompt_version,
                "latency_ms": event.latency_ms,
                "attempt_count": event.attempt_count,
                "outcome_category": event.outcome_category,
            },
            model=event.model,
            usage=usage or None,
        )

    def record_resolution(self, event: ResolutionTelemetry) -> None:
        self._emit(
            event.request_id,
            name="intent.resolve",
            as_type="event",
            metadata={
                "request_id": event.request_id,
                "outcome": event.outcome,
                "workload_type": event.workload_type,
                "interaction_pattern": event.interaction_pattern,
                "capabilities": list(event.capabilities),
                "user_provided_hints": list(event.user_provided_hints),
                "matched_pattern": event.matched_pattern,
                "resolved_type": event.resolved_type,
                "clarification_reason": event.clarification_reason,
                "unsupported_reason": event.unsupported_reason,
            },
        )

    def record_workflow(self, event: WorkflowTelemetry) -> None:
        self._emit(
            event.request_id,
            name=f"workflow.{event.kind}",
            as_type="event",
            metadata={
                "request_id": event.request_id,
                "kind": event.kind,
                "workflow_status": event.workflow_status,
                "current_stage": event.current_stage,
                "security_status": event.security_status,
                "add_count": event.add_count,
                "change_count": event.change_count,
                "destroy_count": event.destroy_count,
                "destructive_change_detected": event.destructive_change_detected,
                "findings": [
                    {
                        "policy_id": finding.policy_id,
                        "status": finding.status,
                        "severity": finding.severity,
                    }
                    for finding in event.findings
                ],
                "approval_decision": event.approval_decision,
                "error_stage": event.error_stage,
                "error_type": event.error_type,
                "published": event.published,
            },
        )

    def flush(self) -> None:
        self._client.flush()

    def _emit(
        self,
        request_id: str,
        *,
        name: str,
        as_type: str,
        metadata: Mapping,
        model: str | None = None,
        usage: Mapping[str, int] | None = None,
    ) -> None:
        trace_id = self._client.create_trace_id(seed=request_id)
        payload = {
            "trace_id": trace_id,
            "name": name,
            "as_type": as_type,
            "metadata": dict(metadata),
        }
        if model is not None:
            payload["model"] = model
        if usage:
            payload["usage"] = dict(usage)
        self._client.emit(**payload)


class SdkTraceClient:
    """Translate the platform client surface onto Langfuse SDK v4.

    `create_trace_id(seed=request_id)` is deterministic in that SDK.
    Observations are attached with `trace_context`, not an in-memory
    span stack. Prompt and completion arguments are never forwarded.
    """

    def __init__(self, sdk) -> None:
        self._sdk = sdk

    def create_trace_id(self, *, seed: str) -> str:
        return self._sdk.create_trace_id(seed=seed)

    def emit(
        self,
        *,
        trace_id: str,
        name: str,
        as_type: str,
        metadata: Mapping,
        model: str | None = None,
        usage: Mapping[str, int] | None = None,
    ) -> None:
        kwargs: dict = {
            "as_type": as_type,
            "name": name,
            "metadata": dict(metadata),
            "trace_context": {"trace_id": trace_id},
        }
        if model is not None:
            kwargs["model"] = model
        with self._sdk.start_as_current_observation(**kwargs) as observation:
            if usage:
                observation.update(usage_details=dict(usage))

    def flush(self) -> None:
        self._sdk.flush()


def build_langfuse_observability(env: Mapping[str, str]) -> LangfuseObservability:
    """Construct the real client. Imported only when langfuse mode is selected."""
    from langfuse import Langfuse

    public_key = SecretStr(env["LANGFUSE_PUBLIC_KEY"])
    secret_key = SecretStr(env["LANGFUSE_SECRET_KEY"])
    base_url = env.get("LANGFUSE_BASE_URL") or _DEFAULT_BASE_URL
    sdk = Langfuse(
        public_key=public_key.get_secret_value(),
        secret_key=secret_key.get_secret_value(),
        base_url=base_url,
    )
    return LangfuseObservability(SdkTraceClient(sdk))
