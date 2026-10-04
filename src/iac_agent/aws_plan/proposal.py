"""Decode a proposal only when it is byte-identical to the SQS renderer."""

from __future__ import annotations

import json

from pydantic import ValidationError

from iac_agent.providers.aws.sqs.contract import DlqSpec, EncryptionSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import (
    DEFAULT_MODULE_SOURCE,
    TerraformCompositionRenderer,
)
from iac_agent.providers.aws.terraform_render import (
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

_HEADER = (
    "# GENERATED FILE — do not edit by hand.\n"
    "# Produced deterministically by TerraformCompositionRenderer from a\n"
    "# validated SQSResourceSpec. Regenerate instead of modifying.\n\n"
)

_SCALAR_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("source", "  source = "),
    ("name", "  name                       = "),
    ("fifo", "  fifo                       = "),
    ("visibility_timeout_seconds", "  visibility_timeout_seconds = "),
    ("message_retention_seconds", "  message_retention_seconds  = "),
    ("delay_seconds", "  delay_seconds              = "),
    ("kms_key_id", "  kms_key_id                 = "),
    ("dlq_enabled", "  dlq_enabled                = "),
    ("max_receive_count", "  max_receive_count          = "),
)

_STRING_ATTRIBUTES = frozenset({"source", "name"})
_BOOL_ATTRIBUTES = frozenset({"fifo", "dlq_enabled"})
_INT_ATTRIBUTES = frozenset(
    {"visibility_timeout_seconds", "message_retention_seconds", "delay_seconds"}
)
_OPTIONAL_STRING_ATTRIBUTES = frozenset({"kms_key_id"})
_OPTIONAL_INT_ATTRIBUTES = frozenset({"max_receive_count"})


class ProposalRejected(ValueError):
    """The proposal is not canonical SQS renderer output."""


def decode_sqs_proposal(main_tf: str, versions_tf: str) -> SQSResourceSpec:
    if versions_tf != render_versions_tf():
        raise ProposalRejected("versions.tf is not the trusted renderer output")

    prefix = _HEADER + render_provider_block() + "\n"
    if not main_tf.startswith(prefix):
        raise ProposalRejected("main.tf header or provider block is not renderer output")

    values = _parse_module(main_tf[len(prefix) :])
    if values["source"] != DEFAULT_MODULE_SOURCE:
        raise ProposalRejected("module source is not the trusted SQS module")

    try:
        spec = SQSResourceSpec(
            name=values["name"],
            fifo=values["fifo"],
            visibility_timeout_seconds=values["visibility_timeout_seconds"],
            message_retention_seconds=values["message_retention_seconds"],
            delay_seconds=values["delay_seconds"],
            encryption=EncryptionSpec(kms_key_id=values["kms_key_id"]),
            dlq=DlqSpec(
                enabled=values["dlq_enabled"],
                max_receive_count=values["max_receive_count"],
            ),
            tags=values["tags"],
        )
    except ValidationError as exc:
        raise ProposalRejected("decoded values are not a valid SQSResourceSpec") from exc

    rendered = TerraformCompositionRenderer().render(spec)
    if rendered.files["main.tf"] != main_tf or rendered.files["versions.tf"] != versions_tf:
        raise ProposalRejected("proposal bytes are not the trusted renderer output")
    return spec


def _parse_module(text: str) -> dict[str, object]:
    opener = 'module "queue" {\n'
    if not text.startswith(opener):
        raise ProposalRejected("main.tf is not a single module \"queue\" block")
    rest = text[len(opener) :]
    values: dict[str, object] = {}
    for name, prefix in _SCALAR_ATTRIBUTES:
        if not rest.startswith(prefix):
            raise ProposalRejected(f"attribute {name} is missing or out of renderer order")
        rest = rest[len(prefix) :]
        newline = rest.find("\n")
        if newline < 0:
            raise ProposalRejected(f"attribute {name} is not a single renderer line")
        values[name] = _parse_scalar(name, rest[:newline])
        rest = rest[newline + 1 :]
        if name == "source":
            if not rest.startswith("\n"):
                raise ProposalRejected("module source is not followed by the renderer blank line")
            rest = rest[1:]
    values["tags"], rest = _parse_tags(rest)
    if rest != "}\n":
        raise ProposalRejected("module block has trailing content")
    return values


def _parse_scalar(name: str, token: str) -> object:
    if name in _STRING_ATTRIBUTES:
        return _decode_hcl_string(token)
    if name in _BOOL_ATTRIBUTES:
        if token == "true":
            return True
        if token == "false":
            return False
        raise ProposalRejected(f"attribute {name} is not a renderer boolean")
    if name in _INT_ATTRIBUTES:
        return _decode_integer(token, name)
    if name in _OPTIONAL_STRING_ATTRIBUTES:
        if token == "null":
            return None
        return _decode_hcl_string(token)
    if name in _OPTIONAL_INT_ATTRIBUTES:
        if token == "null":
            return None
        return _decode_integer(token, name)
    raise ProposalRejected(f"attribute {name} is not part of the SQS renderer")


def _parse_tags(rest: str) -> tuple[dict[str, str], str]:
    empty = "  tags                       = {}\n"
    if rest.startswith(empty):
        return {}, rest[len(empty) :]
    multiline = "  tags = "
    if not rest.startswith(multiline):
        raise ProposalRejected("tags are not in the renderer layout")
    value_and_tail = rest[len(multiline) :]
    closing = "\n  }\n"
    end = value_and_tail.find(closing)
    if end < 0 or not value_and_tail.startswith("{"):
        raise ProposalRejected("tags are not in the renderer layout")
    value = value_and_tail[: end + len("\n  }")]
    tail = value_and_tail[end + len(closing) :]
    tags = _decode_tag_map(value)
    if hcl_tags(tags) != value:
        raise ProposalRejected("tags are not the canonical renderer map")
    return tags, tail


def _decode_tag_map(value: str) -> dict[str, str]:
    if not value.startswith("{\n") or not value.endswith("\n  }"):
        raise ProposalRejected("tags are not the canonical renderer map")
    body = value[len("{\n") : -len("\n  }")]
    tags: dict[str, str] = {}
    for line in body.split("\n"):
        if " = " not in line:
            raise ProposalRejected("tags are not the canonical renderer map")
        key_token, value_token = line.split(" = ", 1)
        if not key_token.startswith("    "):
            raise ProposalRejected("tags are not the canonical renderer map")
        key = _decode_hcl_string(key_token.strip())
        tags[key] = _decode_hcl_string(value_token.strip())
    return tags


def _decode_integer(token: str, name: str) -> int:
    if not token.isdigit():
        raise ProposalRejected(f"attribute {name} is not a renderer integer")
    value = int(token)
    if str(value) != token:
        raise ProposalRejected(f"attribute {name} is not a renderer integer")
    return value


def _decode_hcl_string(token: str) -> str:
    if _has_unescaped_template(token):
        raise ProposalRejected("string contains an unescaped template marker")
    if len(token) < 2 or not token.startswith('"') or not token.endswith('"'):
        raise ProposalRejected("value is not a renderer string literal")
    normalized = token.replace("$${", "${").replace("%%{", "%{")
    try:
        value = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ProposalRejected("value is not a renderer string literal") from exc
    if not isinstance(value, str) or hcl_string(value) != token:
        raise ProposalRejected("value is not a renderer string literal")
    return value


def _has_unescaped_template(token: str) -> bool:
    index = 0
    while index < len(token):
        if token.startswith("$${", index) or token.startswith("%%{", index):
            index += 3
            continue
        if token.startswith("${", index) or token.startswith("%{", index):
            return True
        index += 1
    return False
