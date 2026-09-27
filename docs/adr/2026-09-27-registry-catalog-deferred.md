# Registry / catalog

**Status:** Deferred  
**Date:** 2026-09-27  
**Evidence:** Batch 27, ECR repository vertical slice

## Decision

Deferred. A centralized registry or catalog is not justified by the
Batch 27 evidence. This is not a permanent rejection.

## Evidence

Batch 27 measured extension friction while adding ECR. The production
changes were explicit dispatch and registration boundaries: a
`ResourceType` member, union and `match` arms, policy and Checkov
entries, a module-directory map, a display name, a checkpoint
allowlist, and CLI presentation.

A centralized registry would primarily relocate those boundaries. It
would not eliminate the remaining silent-failure boundaries:

- omitting a checkpoint allowlist entry round-trips the spec as a
  `dict` and does not raise;
- omitting an ECR branch in `_component_lines` returns `[]` and does
  not raise.

Those two are covered by dedicated tests. Missing an explicit
dispatch arm, a Checkov profile, or a display-name registration fails
loudly, through `ValueError`, `KeyError`, or the same existing
fail-closed behavior.

## Reconsider when

- the resource or composition count increases materially;
- adding a resource requires repeated semantic metadata;
- registration omissions escape tests;
- plugin-like extensibility becomes a requirement.

Until one of those is true, keep explicit dispatch.
