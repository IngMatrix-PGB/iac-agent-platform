# ADR: Defer a centralized resource registry / catalog

**Status:** Deferred  
**Date:** 2026-09-27  
**Evidence:** Batch 27, ECR repository vertical slice

## Context

Adding a resource type touches several explicit registration points
(dispatch, policy, Checkov, module map, display name, checkpoint
allowlist, CLI). Batch 27 added ECR to measure whether that friction
justifies a centralized registry or catalog.

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

## Alternatives

- **Explicit dispatch and registration (current)** — **KEPT.** Most
  omissions fail loudly; the two silent ones have dedicated tests.
- **Centralized registry / catalog** — **DEFERRED.** Relocates the same
  boundaries without removing the two silent-failure paths.

## Consequences

- Adding a resource keeps touching each registration point by hand.
- The two silent-failure boundaries depend on their dedicated tests;
  a new silent boundary needs its own test.
- No registry abstraction to maintain until a trigger below is met.

## Reconsider when

- the resource or composition count increases materially;
- adding a resource requires repeated semantic metadata;
- registration omissions escape tests;
- plugin-like extensibility becomes a requirement.

Until one of those is true, keep explicit dispatch.
