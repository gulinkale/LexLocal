# FOUNDRY-002 — Implement the Foundry Local runtime and model adapter boundary

## Ticket objective

Establish the minimum local-model boundary that resolves the approved chat and
embedding aliases, exposes exact safe resolved identity and compatibility state,
owns Foundry Local lifecycle, persists the schema-supported identity metadata,
and fails closed without exposing Foundry SDK types to Application or introducing
any cloud fallback.

## Repository evidence / current state

- `foundry-local-sdk>=1.2.3` is the current dependency. FOUNDRY-001 recorded SDK
  1.2.3 on Apple Silicon and proved cached, network-denied chat inference with
  alias `qwen2.5-0.5b`, resolved ID
  `qwen2.5-0.5b-instruct-generic-gpu:4`, and
  `WebGpuExecutionProvider`.
- FOUNDRY-001 is M0 validation, not production architecture. Its
  `FoundryLocalAdapter` initializes the SDK, resolves one chat alias, optionally
  prepares/downloads it, loads, streams, validates non-empty output, and unloads.
- Unit fakes already prove successful chat lifecycle, uncached/missing model
  failure, load/inference failure, cleanup, and cached-only behavior. They do not
  cover embedding capability, compatibility classification, Application ports,
  persistence, or Bootstrap process ownership.
- The opt-in `foundry_smoke` test runs only with
  `LEXLOCAL_RUN_FOUNDRY_SMOKE=1`, requires a cached model, and never prepares or
  downloads one. Normal pytest skips it.
- The installed SDK exposes catalog `get_model(alias)`, exact model/variant ID,
  integer version, provider/model/task/capability metadata, runtime device and
  execution provider, cache/load state, load/unload, chat client, and embedding
  client. Embedding responses expose vectors through SDK/OpenAI-compatible types;
  these types must be converted inside Infrastructure.
- SDK capability strings and candidate catalog identities are not verified release
  guarantees. Capability-specific client acquisition plus a minimal health request
  is the reliable compatibility proof; missing metadata/client/output fails closed.
- The approved requested aliases already exist in architecture and the release
  manifest: chat `qwen3-4b`, embedding `qwen3-embedding-0.6b`. Both remain
  candidates until catalog and health validation resolve them. FOUNDRY-002 must not
  substitute another alias silently.
- `local_models` already stores stable ID, `CHAT`/`EMBEDDING` purpose, provider,
  requested alias, resolved ID, optional version/dimensions/manifest fingerprint,
  and creation time. No migration is required.
- `LocalModelId` already exists as a nominal Domain UUID. No local-model aggregate,
  repository, Application capability port, or model settings currently exist.
- Bootstrap is the manual composition root. Application-to-Infrastructure imports
  are already forbidden by the architecture suite.

## Reuse vs replacement decisions

### Reuse unchanged

- `LocalModelId`, the existing `local_models` schema, SQLite connection factory,
  migration runner, and Unit of Work transaction behavior.
- Foundry SDK 1.2.3 dependency floor and the `foundry_smoke` marker/configuration.
- FOUNDRY-001 evidence, sanitized diagnostics rules, fixed synthetic prompt, and
  explicit operator-only online preparation workflow.
- Existing layer-boundary AST helpers and Bootstrap manual-composition pattern.

### Adapt

- Evolve `infrastructure/foundry/local_adapter.py` from a one-shot chat validation
  helper into the concrete Application-port implementation. Reuse its SDK
  initialization, streaming-content collection, metadata extraction, and `finally`
  cleanup patterns while removing SDK-shaped public results and unsanitized
  exception propagation.
- Update the validation CLI and opt-in smoke test to exercise the new concrete
  boundary. The CLI alone may retain an explicit preparation/download operation;
  normal Bootstrap composition remains cached-only and fail-closed.
- Extend the existing UoW with the minimal local-model repository needed to record
  the exact resolved chat and embedding identities atomically.

### Replace

- Replace `FoundryInferenceResult` as an application-facing concept with
  Application-owned SDK-free model identity, readiness, chat result, and embedding
  result contracts.
- Replace infrastructure-local public `FoundryLocalError` behavior with sanitized
  Application-owned failure types; SDK/native exceptions remain chained only
  internally and never expose paths, prompts, output, or runtime state.

### Validation evidence only

- `qwen2.5-0.5b` remains the FOUNDRY-001 smoke alias. It is not a default chat
  model and does not replace either approved FOUNDRY-002 candidate.
- Recorded M0 hardware/results do not establish release compatibility for the chat
  or embedding candidate.

## Frozen architecture decisions

1. Application owns one shared `LocalModelRuntime` lifecycle/catalog contract and
   two capability-specific ports: `ChatInferenceProvider` and
   `EmbeddingProvider`. Chat strings and embedding vectors have different contracts;
   combining them into a generic `infer(Any) -> Any` API is prohibited.
2. Application-owned frozen values represent only stable, obtainable facts:
   `LocalModelId`, requested alias, exact resolved model ID, optional catalog
   version, `CHAT`/`EMBEDDING` capability, execution provider, optional embedding
   dimensions, and readiness. No SDK model/client/response type crosses the port.
3. SDK initialization, catalog lookup, variant selection, cache/load state,
   capability-client acquisition, request/response conversion, health calls,
   load/unload, and SDK exception translation belong exclusively to
   `infrastructure/foundry/`.
4. Bootstrap reads the two exact approved aliases from `AppSettings`, initializes
   one concrete runtime for the process, resolves both aliases explicitly, performs
   capability health checks, records both resolved identities in one UoW, composes
   the two capability ports, and guarantees runtime close/unload at process exit or
   failed composition.
5. Normal application composition never prepares execution providers, downloads a
   model, substitutes an alias, configures a remote endpoint, or calls a cloud API.
   Both requested candidates must already be locally available and compatible.
6. FOUNDRY-001's validation CLI remains the only explicit online preparation path.
   It is operator-invoked evidence tooling, not an Application fallback.
7. Compatibility is decided in Infrastructure before a provider becomes available:
   exact alias resolution, cache availability, usable resolved identity/version and
   execution provider, successful load, capability-specific client acquisition, and
   a minimal synthetic health result. Embeddings additionally require a non-empty,
   finite vector with a stable positive dimension.
8. Catalog task/capability metadata may strengthen diagnostics but is not trusted as
   the sole compatibility proof because SDK/catalog values are not frozen. A failed
   capability client or health request is incompatible and cannot be bypassed.
9. The initial health check loads one model at a time and unloads it after the check.
   Later inference may reuse a loaded handle within the single process-owned runtime,
   but all loaded handles are unloaded by explicit `close()` and after failures.
   QThread scheduling, idle timers, cancellation workers, and memory-pressure policy
   belong to later workflow/presentation tickets.
10. Exact schema-supported identity is persisted without a migration. Execution
    provider and readiness remain observable runtime metadata because the current
    table has no corresponding columns. `manifest_fingerprint` stays null until a
    verified release-manifest workflow owns it.
11. Missing aliases, uncached models, incompatible capability, invalid embedding
    shape/content, load/health/inference failures, identity conflicts, and cleanup
    failures use sanitized typed failures. There is no fallback to another local
    alias or any remote provider.
12. Model prompts/results are sensitive operational data. They are returned only to
    the calling Application operation and are never included in status objects,
    exceptions, diagnostics, logs, persistence metadata, or test failure messages.

## Scope IN

- Application-owned local-model identity/readiness values, errors, shared lifecycle
  contract, chat port, embedding port, and minimal resolved-model repository.
- Exact chat/embedding alias settings using the already approved candidate values.
- Foundry Local SDK initialization, catalog resolution, cached-only availability,
  compatibility/health validation, load/reuse/unload, and SDK conversion.
- SDK-free chat text and embedding-vector outputs with strict validation.
- Persistence of exact schema-supported model identity/compatibility metadata using
  the existing table and UoW.
- Bootstrap process-lifetime composition and cleanup for both capabilities.
- Fake lifecycle/failure tests, architecture guards, and the existing opt-in real
  local-runtime smoke path.

## Scope OUT

- RAG, retrieval, ingestion, PDF/OCR, chunking, indexing, vector persistence/search,
  prompts for legal workflows, chat history, analysis generation, or UI.
- Cloud, Azure, OpenAI service, HTTP endpoint, remote inference, or fallback logic.
  The SDK's local OpenAI-compatible response classes do not authorize remote use.
- Automatic model substitution, release-model selection experiments, benchmarking,
  model download UI, background QThread workers, idle unloading, cancellation, or
  memory-pressure orchestration.
- Production encryption, key lifecycle, source storage, migration/schema changes,
  or release-manifest verification/pinning.
- Generic provider framework, plugin discovery, registry, DI container, service
  locator, generic AI request/result types, or hypothetical non-Foundry providers.

## Layer/file ownership

| Layer | Expected ownership | Immediate reason |
|---|---|---|
| Application ports | `application/ports/local_models.py` | SDK-free lifecycle, capability, identity, persistence, and failure contracts consumed by Bootstrap and future local workflows. |
| Bootstrap settings | `bootstrap/settings.py` | Load the two explicit requested aliases without selecting or importing SDK types. |
| Infrastructure Foundry | `infrastructure/foundry/local_adapter.py` | Own all SDK objects, catalog/client conversion, compatibility checks, health, and loaded handles. |
| Infrastructure persistence | `infrastructure/persistence/sqlite_local_model_repository.py`, existing SQLite UoW | Persist the exact resolved record inside the existing transaction boundary. |
| Bootstrap composition | `bootstrap/foundry.py`, minimal `bootstrap/application.py` wiring | Initialize one runtime, resolve/health-check both models, persist identity, expose capability ports, and close at process exit. |
| Tests | focused Application contract, Infrastructure fake, persistence, Bootstrap, architecture, and opt-in smoke tests | Prove behavior and dependency direction without requiring real hardware in normal CI. |

No Domain model aggregate is added. `LocalModelId` is reused; runtime compatibility
and provider lifecycle are Application/Infrastructure concerns.

## Runtime/model lifecycle

1. Settings load non-empty chat and embedding requested aliases; defaults are exactly
   `qwen3-4b` and `qwen3-embedding-0.6b`.
2. Bootstrap creates one SDK configuration/manager and one concrete runtime.
3. The runtime resolves each alias independently to one exact local catalog model.
4. Resolution rejects missing, uncached, identity-less, provider-less, or wrong
   capability candidates without trying another alias.
5. Health validation serially loads the candidate, obtains the capability client,
   runs a fixed anonymous synthetic request, validates its result, and unloads it.
6. Bootstrap assigns stable `LocalModelId` values, stages both resolved records in
   one existing UoW transaction, and commits only after both capabilities pass.
   A matching existing record is reused; conflicting identity/compatibility data
   fails closed rather than being silently overwritten.
7. The composed chat and embedding providers reference the process runtime and exact
   resolved identities. They may load/reuse only those identities; catalog re-resolution
   or alias substitution during inference is forbidden.
8. Bootstrap calls `close()` in a `finally` path on normal shutdown and failed
   composition. Close attempts every loaded-handle unload and is idempotent; a
   sanitized cleanup failure is reported without concealing an earlier primary
   failure.

## Alias resolution + resolved identity semantics

- Requested aliases are configuration, preserved exactly after existing settings
  whitespace validation; Application never derives an alias from installed models.
- `qwen3-4b` is the chat candidate and `qwen3-embedding-0.6b` is the embedding
  candidate. Neither is silently replaced by the FOUNDRY-001 smoke alias.
- Resolved identity is the SDK model/variant `id`, not the requested alias or display
  name. Catalog integer `version` is represented as a safe string when available.
- Capability is explicit `CHAT` or `EMBEDDING`; model IDs cannot be reused across
  purposes merely because their text matches.
- Execution provider is exposed as sanitized compatibility metadata. Cache paths,
  model URIs, license text, prompt templates, and native state are not exposed.
- Embedding dimension is observed from the validated health vector and persisted.
  Subsequent embedding responses must match it exactly and contain only finite
  numeric values. Chat has no dimensions value.
- Readiness is published only after successful compatibility health validation.
  Failure is represented by typed failure, not a partially ready provider.

## Compatibility/fail-closed semantics

- A missing alias raises `LocalModelUnavailable`.
- An uncached model or absent local execution provider raises
  `LocalModelUnavailable`; production composition never downloads it.
- A model that cannot supply the required capability client or valid health output
  raises `LocalModelIncompatible`.
- SDK initialization, load, inference, and unload failures translate to
  `LocalModelRuntimeError` or capability-specific `LocalModelInferenceError`.
- Stored record conflicts or invalid mappings raise sanitized
  `LocalModelPersistenceError`.
- Bootstrap publishes no partial composition and commits no one-model record when
  either capability fails.
- No error handler retries with a different alias, remote endpoint, or cloud SDK.

## Error/sanitization rules

- Application-owned errors contain stable category text only. They do not contain
  prompts, assistant output, embedding values, SDK exception strings, model/cache
  paths, URIs, environment values, or native object representations.
- Requested alias, resolved model ID/version, capability, execution provider,
  readiness, and embedding dimensions are approved observable diagnostics after
  validation. They are kept separate from inference content.
- Infrastructure raises sanitized errors with `from None` at the public boundary;
  internal logging, if needed, records exception class/category only.
- Health and fake fixtures use anonymous synthetic text. The real smoke test retains
  its fixed non-sensitive sentence and never prints response content.

## Test strategy

- Application contracts: immutable SDK-free model metadata, capability/readiness
  validation, minimal port/repository shape, and sanitized error hierarchy.
- Settings: exact chat/embedding defaults, explicit environment values, empty/invalid
  rejection, and no endpoint/cloud setting.
- Infrastructure fake SDK: initialization, exact alias lookup, resolved metadata,
  uncached/missing/incompatible models, serial health load/unload, valid/invalid
  embeddings, successful chat, load/inference failures, unload on all applicable
  paths, idempotent close, and no alternate lookup.
- Persistence: migrated temporary DB round-trip for both purposes, exact IDs/version/
  dimensions, nullable chat dimensions, matching-record reuse, conflict/corrupt-row
  sanitization, and no repository-owned commit/rollback.
- Bootstrap: one shared runtime, two capability ports, atomic two-record commit,
  cleanup after success/failure, missing/incompatible fail-closed behavior, safe
  observable identity, and no cloud fallback.
- Architecture: Application/Domain contain no `foundry_local_sdk`, SDK/OpenAI response,
  concrete Infrastructure, or Bootstrap imports; only Bootstrap composes the concrete
  adapter.
- Real smoke: retain strict opt-in marker/environment gate, cached-only behavior,
  synthetic prompt, meaningful output assertion, and cleanup. Normal pytest must
  collect and skip it without hardware/network work.

## Overengineering risks

- A generic AI/provider registry is unnecessary: Foundry Local is the sole approved
  runtime and cloud fallback is forbidden.
- One generic inference port would erase the materially different chat and embedding
  validation contracts. Separate capability ports share one lifecycle boundary.
- Separate manager objects per capability would duplicate SDK initialization and
  weaken lifecycle ownership. One runtime owns two exact handles.
- Persisting every SDK metadata field would leak unstable/native details and require
  schema changes. Store only existing schema fields and expose the small safe runtime
  status.
- QThread workers, queues, cancellation, warm-idle policy, download UX, RAG, and
  prompt resources have no immediate FOUNDRY-002 consumer and remain out of scope.

## Implementation steps

## 1. Define Application contracts and alias settings ✅

### Purpose

Freeze the SDK-free identity, readiness, lifecycle, capability, persistence, error,
and requested-alias contracts before adapting Infrastructure.

### Exact expected files

- `src/lexlocal/application/ports/local_models.py`
- `src/lexlocal/application/ports/unit_of_work.py`
- `src/lexlocal/bootstrap/settings.py`
- `tests/unit/application/ports/test_local_models.py`
- `tests/unit/bootstrap/test_settings.py`

### Do

- Add the minimal frozen values and typed errors described above.
- Define one shared runtime lifecycle port, separate chat/embedding ports, and a
  minimal resolved-model repository contract.
- Add exact chat/embedding alias settings with approved candidate defaults.
- Prove contracts contain no SDK/native/OpenAI response types.

### Do not

- Do not import Infrastructure, implement SDK calls, add a generic provider API, add
  endpoint/cloud settings, or create Domain model generation behavior.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_local_models.py tests/unit/bootstrap/test_settings.py -v
uv run ruff check src/lexlocal/application/ports/local_models.py src/lexlocal/application/ports/unit_of_work.py src/lexlocal/bootstrap/settings.py tests/unit/application/ports/test_local_models.py tests/unit/bootstrap/test_settings.py
uv run mypy src
git diff --check
```

### Step completion condition

Application owns a minimal typed SDK-free boundary for both capabilities and settings
resolve only the two explicit requested aliases.

## 2. Adapt the concrete Foundry Local runtime and capability providers ✅

### Purpose

Implement SDK initialization, exact catalog resolution, compatibility health,
load/reuse/unload, chat conversion, and embedding conversion behind Step 1 ports.

### Exact expected files

- `src/lexlocal/infrastructure/foundry/local_adapter.py`
- `src/lexlocal/infrastructure/foundry/__init__.py`
- `tests/unit/infrastructure/foundry/test_local_adapter.py`
- `scripts/validate_foundry_local.py`
- `tests/unit/scripts/test_validate_foundry_local.py`
- `tests/integration/foundry/test_foundry_local_smoke.py`

### Do

- Retain explicit FOUNDRY-001 preparation CLI behavior while making normal adapter
  resolution cached-only and fail-closed.
- Convert every SDK request/response and exception inside Infrastructure.
- Prove chat and embedding success, exact safe metadata, missing/uncached/incompatible
  rejection, dimension/finite validation, lifecycle reuse, and cleanup failures.
- Keep the real smoke explicitly opt-in, cached-only, synthetic, and unloaded.

### Do not

- Do not expose SDK types, log content/vectors, substitute aliases, add remote clients,
  implement RAG, or add background execution machinery.

### Focused validation

```bash
uv run pytest tests/unit/infrastructure/foundry/test_local_adapter.py tests/unit/scripts/test_validate_foundry_local.py -v
uv run pytest tests/integration/foundry/test_foundry_local_smoke.py -v
uv run ruff check src/lexlocal/infrastructure/foundry scripts/validate_foundry_local.py tests/unit/infrastructure/foundry tests/unit/scripts/test_validate_foundry_local.py tests/integration/foundry/test_foundry_local_smoke.py
uv run mypy src
git diff --check
```

### Step completion condition

Both capabilities and every lifecycle/failure path operate behind SDK-free ports;
normal tests require no runtime/model/network and the real smoke remains opt-in.

## 3. Persist exact resolved model records through the existing UoW ✅

### Purpose

Map validated chat and embedding identities to the existing `local_models` table
without giving Infrastructure transaction ownership or changing the schema.

### Exact expected files

- `src/lexlocal/infrastructure/persistence/sqlite_local_model_repository.py`
- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py`
- `tests/integration/persistence/test_sqlite_local_model_repository.py`
- `tests/integration/persistence/test_local_model_transactions.py`
- `tests/integration/persistence/test_sqlite_unit_of_work.py`

### Do

- Implement only record/matching-read operations required by composition.
- Persist exact purpose/provider/requested alias/resolved ID/version/dimensions/time,
  reuse an exact existing record, and reject conflicting or corrupt records.
- Bind the repository to the active UoW connection and prove atomic rollback/reuse.

### Do not

- Do not migrate schema, persist SDK objects/runtime paths/readiness, commit or open a
  second connection, add generic CRUD, or implement model deletion/download state.

### Focused validation

```bash
uv run pytest tests/integration/persistence/test_sqlite_local_model_repository.py tests/integration/persistence/test_local_model_transactions.py tests/integration/persistence/test_sqlite_unit_of_work.py -v
uv run ruff check src/lexlocal/infrastructure/persistence/sqlite_local_model_repository.py src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py tests/integration/persistence/test_sqlite_local_model_repository.py tests/integration/persistence/test_local_model_transactions.py tests/integration/persistence/test_sqlite_unit_of_work.py
uv run mypy src
git diff --check
```

### Step completion condition

Both validated identities round-trip exactly and atomically through the existing
schema/UoW with sanitized conflict/mapping failures.

## 4. Compose and test the process-lifetime local-model boundary ✅

### Purpose

Make Bootstrap the sole owner of SDK initialization, two-model resolution/health,
atomic identity recording, provider exposure, and shutdown cleanup.

### Exact expected files

- `src/lexlocal/bootstrap/foundry.py`
- `src/lexlocal/bootstrap/application.py`
- `tests/unit/bootstrap/test_foundry.py`
- `tests/unit/bootstrap/test_application.py`
- `tests/integration/foundry/test_foundry_composition.py`

### Do

- Compose one runtime, exact configured aliases, separate capability providers, and
  safe observable statuses.
- Commit neither record until both models are ready; close on every failure and after
  the application event loop.
- Prove missing/incompatible/load/health/persistence failures publish no partial
  composition and never attempt another alias or provider.

### Do not

- Do not initialize in Application, add cloud fallback, start downloads, add a DI
  container, run model work on the GUI thread beyond startup health, or implement
  downstream chat/embedding workflows.

### Focused validation

```bash
uv run pytest tests/unit/bootstrap/test_foundry.py tests/unit/bootstrap/test_application.py tests/integration/foundry/test_foundry_composition.py -v
uv run ruff check src/lexlocal/bootstrap/foundry.py src/lexlocal/bootstrap/application.py tests/unit/bootstrap/test_foundry.py tests/unit/bootstrap/test_application.py tests/integration/foundry/test_foundry_composition.py
uv run mypy src
git diff --check
```

### Step completion condition

Bootstrap exposes two ready SDK-free capabilities with exact identities from one
local runtime and always closes them without partial persistence or fallback.

## 5. Run architecture, quality, and strict scope audits ✅

### Purpose

Validate all FOUNDRY-002 requirements together and prove that SDK coupling, sensitive
output, cloud fallback, and later AI workflows did not enter forbidden layers.

### Exact expected files

- `tests/architecture/test_layer_boundaries.py` only if existing import rules need a
  representative Foundry-specific regression fixture
- `docs/FOUNDRY-002.md`
- Earlier-step files only for a genuine owning defect

### Do

- Run focused Foundry/Application/persistence/Bootstrap tests, architecture tests,
  full pytest, Ruff, mypy, and whitespace checks with actual counts.
- Audit every diff hunk, public abstraction, error/log path, alias, lifecycle path,
  opt-in smoke boundary, and cloud-fallback absence.
- Confirm resolved identities are observable without prompt/output/vector exposure.

### Do not

- Do not weaken checks, run/download a real model implicitly, add later workflows,
  or refactor unrelated code to obtain green gates.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_local_models.py tests/unit/infrastructure/foundry tests/unit/bootstrap/test_foundry.py tests/integration/persistence/test_sqlite_local_model_repository.py tests/integration/persistence/test_local_model_transactions.py tests/integration/foundry/test_foundry_composition.py -v
uv run pytest tests/architecture -v
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```

The real smoke remains skipped unless a human explicitly opts in with the documented
cached-model environment gate.

### Step completion condition

All requirements have executable evidence; Application/Domain have no SDK coupling,
the staged scope contains no cloud/later-ticket work, and all required gates pass.

### Recorded validation

- Focused FOUNDRY-002 suite: 69 passed.
- Architecture suite: 19 passed.
- Full suite: 1089 passed, 1 explicitly opt-in Foundry smoke skipped.
- Ruff, mypy (39 source files), and `git diff --check`: passed.
- Architecture, lifecycle, persistence, security, cloud/fallback, and strict scope
  audits: clean.

## 6. Audit Git state for human review ✅

### Purpose

Prepare only the completed FOUNDRY-002 diff for explicit human review without
committing, pushing, or creating a PR automatically.

### Exact expected files

- Only files proven to belong to FOUNDRY-002

### Do

- Inspect branch, status, every tracked/untracked hunk, staged/unstaged stats,
  generated files, dependencies, aliases, sensitive data, and whitespace.
- Stage only the approved ticket files after Step 5 passes and report proposed
  commit/PR metadata plus actual validation evidence.

### Do not

- Do not mix WORKSPACE-001 or other pre-existing changes, commit, push, create a PR,
  or mark human review complete without explicit approval.

### Focused validation

```bash
git status --short
git diff --stat
git diff
git diff --check
git diff --cached --stat
git diff --cached
git diff --cached --check
```

### Step completion condition

The exact FOUNDRY-002 file set is staged, scope/security audited, and stopped at the
explicit human-review boundary.

## Final Definition of Done

- [x] Application and Domain import no Foundry SDK/OpenAI response or concrete
  Infrastructure types.
- [x] One process-owned local runtime resolves the exact configured chat and
  embedding aliases without substitution or cloud fallback.
- [x] Exact requested alias, resolved ID/version, capability, execution provider,
  readiness, and embedding dimensions are safely observable where applicable.
- [x] Both capability health checks fail closed for missing, uncached, incompatible,
  invalid-output, load, inference, or cleanup failures.
- [x] Chat and embedding operations return SDK-free validated results and never expose
  prompts, response content, or vectors through diagnostics/errors.
- [x] Exact schema-supported identities persist atomically through the existing UoW;
  no migration or partial one-model record is introduced.
- [x] Fake-adapter tests cover successful lifecycle and all required failure/cleanup
  paths without hardware or network.
- [x] The real Foundry Local smoke test remains explicitly opt-in, cached-only,
  synthetic, meaningful-output checked, and unloaded.
- [x] Bootstrap alone owns concrete composition and process cleanup.
- [x] No cloud/remote endpoint, automatic download, RAG/retrieval/ingestion/UI, generic
  provider framework, or unrelated work enters FOUNDRY-002.
- [x] Focused, architecture, full pytest, Ruff, mypy, and diff gates pass with actual
  evidence.
- [x] Final staged diff is scope-clean and explicitly human-reviewed.

## Current position

**FOUNDRY-002 ✅ COMPLETE. Ready for delivery.** All focused, architecture, full
quality, lifecycle, persistence, security, cloud/fallback, strict scope, and
staged-diff gates pass; explicit human staged-diff review is approved.

Next: **Authorized commit and PR delivery.**
