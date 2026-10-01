# Batch 35 — capability-scoped runtime dependency decoupling

## 1. Problem statement

The operator HTTP process refuses to start unless GitHub publication settings and OpenAI interpreter settings are both present. That happens in `_lifespan` before the server accepts connections. List, detail, and reject do not call either provider. A `state.db` that already holds an `awaiting_approval` checkpoint is therefore unreadable when `GITHUB_OWNER` or `OPENAI_API_KEY` is missing.

Batch 35 separates state-plane availability from those two capabilities. The process stays one FastAPI application and one `state.db`. A missing optional capability is detected before the operation that would mutate the checkpoint. Partial configuration fails startup. Complete absence does not.

## 2. Repository evidence

Discovery ran against `origin/main` at `e8dfd9d127e3a33d707f762e908c688f240fa289`, the merge of pull request 18. Batch 34 is in the tree: `src/iac_agent/api/operator_auth.py`, the operator-secret load in `src/iac_agent/api/app.py`, and `docs/superpowers/specs/2026-09-29-batch34-design.md`.

`_lifespan` in `src/iac_agent/api/app.py` loads, in order, the operator secret, `load_application_config_from_env()`, `load_github_token_from_env()`, interpreter config, and `load_openai_api_key_from_env()`, then calls `create_intent_interpreter()` and `open_intent_application()`. `test_lifespan_still_requires_github_after_the_operator_secret` locks the GitHub requirement: with the operator secret set and `GITHUB_OWNER` unset, `TestClient` raises `MissingConfigurationError` and no request is served.

`GitHubSourceControl.__init__` stores the token and a `UrllibHttpTransport`. It does not call the network. `OpenAIIntentInterpreter` constructs `openai.OpenAI(...)` and does not call the network until `interpret()`. An unreachable host does not block startup. Missing configuration does.

`IacApplication.list_requests()` and `read()` use `request_index` and `graph.get_state()`. `IntentResolutionService.submit()` calls `interpret()` before `IacApplication.submit()`. `_route_after_approval_gate` enters `source_control` only when status is `APPROVED`. Reject ends at `REJECTED`. `decide_approval()` resumes only from `AWAITING_APPROVAL`. `_error_update()` writes `WorkflowStatus.ERROR` when `publish_change` raises `SourceControlError`, which consumes the interrupt. The checkpoint field `pull_request` makes a second publish of an already stored result a no-op.

`build_iac_workflow()` requires a `SourceControlPort` argument. `IntentResolutionService` requires an `IntentInterpreterPort` argument. `ApplicationConfig` has no operator-secret field. `request_index` columns are `request_id` and `created_at`. `src/iac_agent/domain/approval.py` stores no approver. `TerraformRunner` has `init`, `validate`, `plan`, and `fmt`. `RequestResponse.terraform_apply` is `not_executed`. Compose publishes `127.0.0.1:8000:8000`.

## 3. Current eager startup graph

```
serve()
  create_app(ui_dist)
    lifespan, when holder is None:
      IAC_AGENT_OPERATOR_SECRET          required, no default
      GITHUB_OWNER / REPOSITORY /
        COMMIT_AUTHOR_NAME / EMAIL       required, no default
      GITHUB_TOKEN                       required, no default
      IAC_AGENT_LLM_PROVIDER / MODEL     required, no default
      OPENAI_API_KEY                     required, no default
      OpenAIIntentInterpreter            client object, no API call
      open_intent_application
        GitHubSourceControl              token stored, no HTTP
        SQLite checkpointer              state.db
        compiled graph                   TerraformRunner, CheckovAdapter
        observability                    off, unless langfuse was requested
        request_index                    second connection, same file
      yield
    HTTP accepts connections
```

`/health` returns `{"status":"ok"}` and does not read the holder. `/ready` is 200 when `app.state.holder` is set and 503 otherwise. Today a ready holder means the whole graph above succeeded, including both credentials.

## 4. Selected architecture

Keep one process and one `state.db`. Startup always requires the operator secret and a usable state plane. GitHub publication and intent interpretation are optional capabilities with explicit presence.

The API checks that presence before any mutating call. That check is the only normal control path.

`build_iac_workflow()` cannot be compiled without a `SourceControlPort`. When publication is absent, composition installs `UnavailableSourceControl` so the graph can exist. That object is a backstop. Approve returns HTTP 503 before `application.resume()`, so normal API execution does not enter `source_control` and does not call the backstop.

`IntentResolutionService` is constructed only when interpretation is configured, and it receives the real `OpenAIIntentInterpreter`. When interpretation is absent, `intent_service` is `None`. Submit returns HTTP 503 before any call on that service. There is no unconfigured interpreter object. A null interpreter would be a second policy next to the route check, and composition does not need one if submit never reaches the service.

```
                FastAPI
                   |
             State Plane
                   |
                SQLite
             /     |     \
           list  detail  reject

    submit  -> intent interpreter     gated before submit()
    approve -> source control         gated before resume()
```

Reject follows the existing resume path. It does not consult the source-control capability.

## 5. State-plane boundary

The state plane is the SQLite checkpointer and `request_index` on `state_db_path`, plus the compiled graph that can read and resume checkpoints.

Paths keep today's defaults. `IAC_AGENT_WORKSPACE_ROOT` defaults to `artifacts`. `IAC_AGENT_STATE_DB` defaults to `<workspace_root>/state.db`. Those defaults are not GitHub configuration and not OpenAI configuration.

Lifespan opens the checkpointer and the index before it yields. If either open fails, startup fails and HTTP does not accept connections. `/ready` is then unreachable, which matches a state plane that did not open.

`ApplicationConfig` stays free of secrets. GitHub owner, repository, and commit identity are loaded only when publication is configured. When publication is absent, the graph still receives `base_branch="main"` because `build_sqs_workflow()` requires that argument. That string is the existing default parameter. It does not record a GitHub repository and it is not evidence that publication is configured.

## 6. Capability model

Presence is a closed enum on the composition holder:

```
class CapabilityPresence(StrEnum):
    CONFIGURED = "configured"
    ABSENT = "absent"

@dataclass(frozen=True)
class RuntimeCapabilities:
    intent_interpretation: CapabilityPresence
    source_control_publishing: CapabilityPresence
```

`IntentApplication` carries `capabilities: RuntimeCapabilities` and `intent_service: IntentResolutionService | None`. Production lifespan sets both from the environment classification below. The UI does not supply them. They are not stored in the checkpoint or `request_index`. They contain no secret values and no "reachable" bit.

There is no plugin registry, service locator, dependency-injection framework, or role. Invalid or partial configuration never becomes a presence value. It raises `MissingConfigurationError` during startup.

Route handlers read `holder.capabilities` directly. They do not infer availability from a caught exception.

An injected test holder that omits `capabilities` fails closed: submit and approve return `capability_unavailable` rather than assuming the capability exists. Health and readiness tests that never call those routes are unchanged.

## 7. Interpreter capability

`intent_interpretation` is `configured` only when `IAC_AGENT_LLM_PROVIDER`, `IAC_AGENT_LLM_MODEL`, and `OPENAI_API_KEY` are all supplied and the provider value is `openai`.

Composition then calls `create_intent_interpreter()` and builds `IntentResolutionService` with that object, as today.

`intent_interpretation` is `absent` when all three variables are omitted. `intent_service` is `None`. No OpenAI client is constructed.

## 8. Source-control capability

`source_control_publishing` is `configured` only when `GITHUB_OWNER`, `GITHUB_REPOSITORY`, `GITHUB_COMMIT_AUTHOR_NAME`, `GITHUB_COMMIT_AUTHOR_EMAIL`, and `GITHUB_TOKEN` are all supplied. Composition then builds `GitHubSourceControl` with `SecretStr.get_secret_value()` at that constructor, as today. `GITHUB_BASE_BRANCH` uses the supplied value, or `main` when omitted.

`source_control_publishing` is `absent` when all five variables are omitted. `GITHUB_BASE_BRANCH` does not change that result when it is omitted or set to `main`, which is the value in `.env.example`. Composition passes `UnavailableSourceControl` into `build_sqs_workflow()`.

`UnavailableSourceControl.publish_change` raises `SourceControlError` with a fixed message that source-control publishing is not configured. The message contains no token, header, owner, repository, or path. The object stores no credential.

This backstop is not the approve gate. The approve route returns 503 before `application.resume()`. A test of the route must show the checkpoint is still `awaiting_approval` and that `publish_change` was not called. A separate unit test may call the backstop directly and assert the safe message. Reaching the backstop from the API is a defect. If an internal caller resumes anyway, the existing `source_control` node still catches `SourceControlError` and applies `_error_update()`. That path is not the operator contract.

## 9. Complete, absent, and partial configuration

A variable is supplied when it is present and `strip()` is non-empty. It is omitted when it is missing, empty, or whitespace-only. Whitespace-only is omitted so a blank secret is not treated as a real credential. Omission of every member of a group is absence. A mixture is partial and fails startup.

### GitHub publication group

Members: `GITHUB_OWNER`, `GITHUB_REPOSITORY`, `GITHUB_COMMIT_AUTHOR_NAME`, `GITHUB_COMMIT_AUTHOR_EMAIL`, `GITHUB_TOKEN`.

`GITHUB_BASE_BRANCH` is outside the group because it already has a default.

| Inputs | Result |
|---|---|
| All five members omitted. `GITHUB_BASE_BRANCH` omitted, empty, whitespace-only, or `main` | `source_control_publishing = absent`. Process may start. `.env.example` is this row: empty members and `GITHUB_BASE_BRANCH=main`. |
| All five members supplied. `GITHUB_BASE_BRANCH` omitted or `main` | `source_control_publishing = configured`. Branch is `main`. |
| All five members supplied. `GITHUB_BASE_BRANCH` is some other non-blank value | `source_control_publishing = configured`. Branch is that value. |
| All five members supplied. `GITHUB_BASE_BRANCH` is present and blank or whitespace-only | Invalid. Startup `MissingConfigurationError` names `GITHUB_BASE_BRANCH` and includes no secret. The default is not substituted for an explicit blank. |
| Some of the five supplied and some omitted | Partial. Startup `MissingConfigurationError` names each omitted member. No values. HTTP does not start. The backstop is not installed. |
| All five omitted, and `GITHUB_BASE_BRANCH` is supplied as a value other than `main` | Partial. Startup fails. The message names `GITHUB_BASE_BRANCH` and the omitted members. A non-default branch without the publication group is an incomplete attempt. `main` is excluded because it is the code default and the example file. |

A supplied but wrong owner or repository is configured. This batch does not probe GitHub to validate it. Later `publish_change` failure keeps the current workflow error behavior.

### Intent interpretation group

Members: `IAC_AGENT_LLM_PROVIDER`, `IAC_AGENT_LLM_MODEL`, `OPENAI_API_KEY`.

| Inputs | Result |
|---|---|
| All three omitted | `intent_interpretation = absent`. Process may start. No interpreter object. |
| All three supplied, provider is `openai` | `intent_interpretation = configured`. |
| All three supplied, provider is any other string | Invalid. Startup `MissingConfigurationError` using the existing unsupported-provider text. The provider string may appear. The API key must not. This is not absence. |
| Some supplied and some omitted | Startup `MissingConfigurationError` naming each omitted variable. No values. HTTP does not start. |

### What this replaces

The discovery sentence "if any required GitHub variable is missing, install the unconfigured port" is withdrawn. A half-set is an operator mistake. Startup fails. Only a completely omitted group is absence.

### Observability

`IAC_AGENT_OBSERVABILITY` stays on its own path in `build_observability()`. Unset, empty, `off`, and `noop` remain off. `langfuse` with a missing `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` still fails startup. Any other value still fails startup. Those keys are not part of `RuntimeCapabilities`.

The operator secret is not part of either capability group. It is checked first. Missing, empty, or whitespace-only `IAC_AGENT_OPERATOR_SECRET` still fails startup with the existing message, and the value is not in the message.

## 10. Submit precondition

`POST /api/v1/requests` keeps today's authentication as the first line.

After the body and request id are valid, the handler reads the checkpoint for `request_exists`, as today. That read does not create a checkpoint or an index row.

If the id is new and `intent_interpretation` is `absent`, the handler returns HTTP 503 `capability_unavailable` and does not call `intent_service`, `interpret()`, `IacApplication.submit()`, or `graph.invoke()`.

If the capability is `configured`, submit proceeds as today: interpret, resolve, then invoke. Interpreter failures still occur before `IacApplication.submit()`, so they still do not insert `request_index`.

Message when interpretation is absent:

```
Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY.
```

## 11. Approve precondition

`POST /api/v1/requests/{request_id}/approval` keeps authentication, request-id validation, body parsing, `application.read()`, not-found, and `decide_approval()` in that order. The read is not a mutation.

When `decide_approval()` returns `resume` and the decision is `approve`:

- If `source_control_publishing` is `absent`, return HTTP 503 `capability_unavailable` and do not call `application.resume()`.
- If it is `configured`, call `application.resume()` as today.

The checkpoint stays `awaiting_approval` in the absent case. A following authenticated GET shows that status. `source_control` does not run. `UnavailableSourceControl.publish_change` is not called.

`return_current` and `conflict` stay as they are. They do not consult the capability and they do not resume. A repeated approve of an already published request still returns the current view when GitHub is configured. When publication is absent, a request cannot have reached `pr_created` through this process; the absent check applies only to a `resume` of `approve`.

Message when publication is absent:

```
Source-control publishing is not configured. Set GITHUB_OWNER, GITHUB_REPOSITORY, GITHUB_COMMIT_AUTHOR_NAME, GITHUB_COMMIT_AUTHOR_EMAIL, and GITHUB_TOKEN.
```

## 12. Reject behavior

`reject` does not read `source_control_publishing`. From `awaiting_approval`, `decide_approval()` returns `resume`, and `application.resume()` runs. The graph sets `REJECTED` and `_route_after_approval_gate` ends. `source_control` is not entered. This holds when the GitHub group is entirely omitted.

## 13. Read behavior

`GET /api/v1/requests` and `GET /api/v1/requests/{request_id}` require authentication and the state plane. They call `list_requests()` and `read()`. They do not read `RuntimeCapabilities`. They succeed when both capabilities are absent, including against a `state.db` created by an earlier fully configured process.

## 14. `/health` semantics

`GET /health` means the process is alive. The body stays `{"status":"ok"}`. The route stays anonymous. It does not read the holder, the capabilities, or the database. The Docker `HEALTHCHECK` stays an unauthenticated call to `http://127.0.0.1:8000/health`.

## 15. `/ready` semantics

`GET /ready` means the local state plane is operational: the lifespan yielded and `app.state.holder` is set, which means the checkpointer and `request_index` opened.

Ready does not mean OpenAI is configured, OpenAI is reachable, GitHub is configured, GitHub is reachable, submit can interpret, or approve can publish. The handler performs no network I/O and does not branch on `RuntimeCapabilities`.

The anonymous body stays `{"status":"ready"}` or `{"status":"not_ready"}` with 503. `docs/api.md` must state this when the implementation lands, so a ready probe is not read as a credential probe.

## 16. Configuration absence versus runtime provider failure

| Situation | Contract |
|---|---|
| Interpreter group omitted | Submit returns 503 `capability_unavailable` before `interpret()`. No request state is created. |
| Interpreter group configured, and the API call later fails | Existing `IntentInterpreterError` mapping in `routes.py` (`intent_provider_unavailable`, timeout, refusal, malformed payload, unsupported schema). |
| Publication group omitted | Approve of `awaiting_approval` returns 503 `capability_unavailable` before `resume()`. Status stays `awaiting_approval`. |
| Publication group configured, and `publish_change` later fails | Existing `source_control` handling, including `_error_update()` and the `pull_request` replay guard. |

Batch 35 does not change the window in which GitHub has accepted a pull request and the checkpoint has not yet stored `pull_request`.

## 17. HTTP 503 `capability_unavailable` contract

The body uses the existing error envelope and no extra fields:

```
{
  "error": "capability_unavailable",
  "message": "<safe configuration message>"
}
```

Status is 503. Messages may name environment variables. They must not contain secret values, bearer credentials, the `GITHUB_TOKEN` value, the `OPENAI_API_KEY` value, checkpoint internals, or workspace paths.

Successful `RequestResponse` and `RequestListItem` bodies gain no fields. Capability presence is not a workflow status.

## 18. State and persistence invariants

- No checkpoint schema change.
- No `request_index` schema change. Columns remain `request_id` and `created_at`.
- The checkpoint remains workflow authority. The index remains discovery.
- No `approved_by`, actor, or principal.
- Capability presence is runtime composition state only. It is not written to SQLite.

## 19. Security invariants

Authentication on `/api/v1/requests` stays the first line of each handler, before lookup and before the capability check. A missing capability must not reveal whether an unauthenticated caller would have been allowed further; the 401 body stays the Batch 34 body.

Capability metadata has no secrets. `UnavailableSourceControl` has no token attribute. Startup errors for partial configuration name variables and omit values. The same rule as `load_operator_secret_from_env()` applies to `OPENAI_API_KEY` and `GITHUB_TOKEN`.

The process can serve reads and reject without those two secrets in the environment. When a group is configured, the secret is still a `SecretStr` until the adapter constructor, and it is still absent from `ApplicationConfig`.

`/health`, `/ready`, and static files stay anonymous. Compose publication stays `127.0.0.1:8000:8000`. This batch does not authorize a reachable bind.

## 20. Batch 34 invariants

- `IAC_AGENT_OPERATOR_SECRET` is mandatory at startup.
- Missing, empty, and whitespace-only values still fail startup with the existing message.
- Every `/api/v1/requests` route stays authenticated.
- The browser secret stays in React memory. Reload clears it.
- No `localStorage`, `sessionStorage`, IndexedDB, or cookie storage is added.
- Loopback publication stays `127.0.0.1:8000:8000`.
- No public deployment is authorized.

## 21. Testing strategy

Deterministic tests only. No live GitHub or OpenAI calls.

- Missing, empty, and whitespace-only operator secret still fail startup, and the value is absent from the message.
- All GitHub and OpenAI variables omitted, operator secret present: `TestClient` starts; anonymous `/health` and `/ready` succeed; bearer list and detail against a seeded `state.db` succeed.
- `test_lifespan_still_requires_github_after_the_operator_secret` is replaced by that startup test plus the partial-configuration tests. It is not deleted without those successors.
- One supplied GitHub member and the others omitted: startup `MissingConfigurationError` names an omitted member and does not contain a token value. The five members omitted with `GITHUB_BASE_BRANCH=main` still starts. The five omitted with `GITHUB_BASE_BRANCH` set to a value other than `main` fails startup. The five supplied with a blank `GITHUB_BASE_BRANCH` fails startup and does not echo a token. Same shape for a mixed OpenAI group, including a whitespace-only `OPENAI_API_KEY` beside a supplied provider.
- All three interpreter variables supplied with provider `openai`: submit still reaches the interpreter.
- Unsupported `IAC_AGENT_LLM_PROVIDER` with model and key supplied: startup fails and the key is absent from the message.
- New request id, interpreter absent: 503 `capability_unavailable`, and the checkpoint and index do not gain that id.
- Existing id, interpreter absent: `request_exists` 409, unchanged.
- Seeded `awaiting_approval`, publication absent, `approve`: 503, and a following GET is still `awaiting_approval`. The source-control port's `publish_change` is not called.
- Same seed, `reject`, publication absent: status becomes `rejected`.
- Publication configured and `publish_change` raises: existing error behavior, asserted by the current source-control tests, which stay.
- Fully configured fresh-process test still creates, restarts, lists, and approves.
- `UnavailableSourceControl.publish_change` raises `SourceControlError` whose text has no credential.
- `IAC_AGENT_OBSERVABILITY=langfuse` with a missing key still fails startup.
- Success DTO tests and `request_index` schema tests stay as they are.

## 22. Explicit non-goals

- RBAC, users, tenants, durable identity, `approved_by`.
- TLS, ingress, a remote bind, or any change to Compose publication.
- A second process or a second database.
- Terraform apply or destroy.
- Folding Langfuse into `RuntimeCapabilities`.
- Redesigning publish failure, interrupt recovery, or the post-accept checkpoint window.
- Successful DTO expansion.
- Persisting capability presence.
- An unconfigured `IntentInterpreterPort`.

## 23. Risks

`/ready` will be green when approve would return 503. That is the intended split. `docs/api.md` has to say so, or operators will read ready as "publication will work."

`UnavailableSourceControl` can still persist `WorkflowStatus.ERROR` if something calls `resume()` despite the route gate. The route test is the acceptance proof that approve does not do that. The backstop test only proves the port refuses to publish.

Injected holders used by route tests must grow `capabilities`. Omitting the attribute fails closed, so those tests will need an explicit `configured` value when they submit or approve. That is test wiring, not a production default.

Classifying whitespace-only as omitted changes today's `if not token` check, which treats `"   "` as present. The new rule is the one in section 9. A whitespace-only token beside real owner settings is partial and fails startup.

## 24. Migration and compatibility

A fully configured environment keeps current submit, approve, reject, list, and detail behavior. Startup still fails when the operator secret is missing or when a capability group is partial. Startup now succeeds when a capability group is entirely omitted, and the corresponding operation returns 503 instead of the process failing to boot.

Implementation updates `docs/api.md` and the Batch 35 note in `docs/roadmap.md` to match sections 14, 15, and 17. No data migration. Existing `state.db` files stay readable.
