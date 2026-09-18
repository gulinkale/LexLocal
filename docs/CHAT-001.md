# CHAT-001 — Generate One Grounded Answer or Explicit Non-Answer

## Status

**IN PROGRESS — STEPS 1–7 COMPLETE; HUMAN STAGED-DIFF REVIEW OPEN**

Human decisions and the implementation plan are complete. RAG-001 and RAG-002 are
available. The contracts, SQLite persistence, versioned prompt/output handling, atomic
completion orchestration, Bootstrap composition, complete technical validation, and
scope-clean staged Git audit are implemented and proven. Explicit human staged-diff
review remains open.

## Purpose

Complete one existing, committed, same-workspace QA request with exactly one of:

- a grounded assistant answer whose citations all resolve to the request's exact
  retrieval evidence; or
- an Application-authored explicit non-answer for an approved insufficient-evidence
  outcome.

CHAT-001 coordinates existing retrieval, evidence sufficiency, local generation,
citation validation, and final persistence without taking ownership of chat creation,
question creation, QA-request creation, scope creation, retrieval ranking, model
selection, or later conversational behavior.

## Prerequisites

- RAG-001 is delivered. CHAT-001 reuses its QA-only `PrepareRetrieval` and
  `StageRetrieval` boundaries.
- RAG-002 is complete and exposes its implemented Application-owned, deterministic,
  versioned evidence-sufficiency contract. CHAT-001 consumes that contract as delivered
  and does not invent an additional wrapper, DTO, method, or return shape.
- The existing local-model, security, workspace, SQLite, and Unit of Work foundations
  remain available and green.

## Repository Evidence

- The applied schema already has `chats`, immutable `chat_messages`, `qa_requests`,
  authoritative `qa_scope_versions`, `retrieval_runs`, `evidence_items`, `citations`,
  and `activity_events`.
- A QA request links one committed user question and an optional completed assistant
  answer. Its states already distinguish grounded completion, insufficient completion,
  failure, and cancellation.
- The Domain already defines `EvidenceSufficiency` with the three frozen states.
  CHAT-001 reuses that enum and the implemented RAG-002 Application contract directly.
- `qa_requests` already provides distinct `prompt_contract_version` and
  `evidence_policy_version` fields plus nullable `chat_model_id`; protected assistant
  content is stored as the immutable `chat_messages.content_ciphertext` snapshot.
- The applied schema does not yet represent the frozen RAG-002 snapshot header or one
  semantic relation per selected persisted evidence item. CHAT-001 therefore owns the
  minimal forward migration and final atomic snapshot persistence; RAG-002 remains
  persistence- and UoW-free.
- `qa_scope_versions` is the immutable exact document/version scope created before
  retrieval. CHAT-001 validates and reuses it; it does not create or mutate it.
- RAG-001 accepts an existing QA owner/scope, performs retrieval preparation outside
  the final write transaction, and stages a complete retrieval/evidence graph through
  the caller's active repository without committing or rolling back.
- Retrieval evidence already carries stable `EvidenceItemId`, rank, exact source
  provenance, protected full excerpt, and retrieval-time document/version snapshots.
  `E1`, `E2`, and similar labels are derived from rank and are not database identities.
- `ChatInferenceProvider` is an Application-owned, SDK-free boundary for one exact
  resolved local chat model and returns text for Application parsing.
- The current citation table stores `EvidenceItemId`, completed answer message,
  one-based ordinal, status, and timestamp. It has no evidence-code or text-offset
  column.
- Existing security composition permits insecure payload handling only for anonymous
  synthetic development/test fixtures and fails closed in production.

Some broader design prose describes aspirational columns such as `message_kind`,
`evidence_code`, or `citation_number`. CHAT-001 follows the applied schema: assistant
`role`, evidence rank-derived labels, and citation `ordinal`.

## Frozen Decisions

### 1. Existing QA owner and exact scope

- CHAT-001 operates only on an existing, committed QA request, its committed user
  question, and its immutable `qa_scope_versions` snapshot in the active workspace.
- It does not create chats, questions, QA requests, chat scope, or QA scope snapshots.
  CHAT-002 and CHAT-003 retain those responsibilities.
- Missing, cross-workspace, inactive, mutable, or inconsistent ownership fails closed.
- The optional retrieval narrowing already approved by RAG-001 may only narrow the QA
  snapshot; CHAT-001 does not create a parallel scope model.

### 2. Retrieval ownership

- CHAT-001 calls the existing RAG-001 preparation boundary and later stages or reuses
  its exact registration through the existing RAG-001 staging boundary.
- CHAT-001 does not call `EmbedQuery`, an embedding provider, or retrieval SQLite code
  directly. It does not repeat scope eligibility, compatibility-cohort selection,
  cosine scoring, ranking, top-K, threshold, provenance, or retry rules.
- `NoEligibleIndex`, corrupt retrieval state, ownership substitution, and other RAG
  integrity or operational failures remain failures. They are never converted into an
  insufficient-evidence outcome.

### 3. Evidence sufficiency

- RAG-002 alone owns the deterministic, versioned sufficiency policy and supplies one
  of `SUFFICIENT`, `RELATED_BUT_INSUFFICIENT`, or `INSUFFICIENT` for the exact retrieval
  through its implemented Application contract.
- CHAT-001 neither calculates nor overrides that state. Similarity, candidate count,
  evidence count, top-K, and retrieval threshold are not substitutes for sufficiency.
- The persisted QA outcome records the exact RAG-002 policy version and state.

### 3A. Historical RAG-002 verifier snapshot

- CHAT-001 owns one immutable snapshot header per completed QA retrieval, bound to the
  exact workspace, `QaRequestId`, `RetrievalRunId`, and
  `evidence_policy_version`.
- The header stores only aggregate READY/READY_WITH_WARNINGS coverage, exact counts for
  `SUPPORTS`, `RELATED_ONLY`, `CONTRADICTS`, and `IRRELEVANT`, and `repair_used`.
- CHAT-001 stores exactly one frozen semantic relation for every selected persisted
  `EvidenceItem`. Each relation is bound to the same QA/retrieval/workspace and
  references the existing evidence identity.
- Existing persisted `EvidenceRank` remains authoritative. The snapshot stores no
  second ranking.
- Non-empty successful verification requires complete relation coverage with no
  missing, duplicate, cross-retrieval, or cross-workspace record. Zero selected
  evidence requires no relation rows, four zero counts, `repair_used = false`, and the
  completed `INSUFFICIENT` outcome.
- `evidence_policy_version` is the sole persisted verifier-policy identity. Its
  immutable manifest binds the exact verifier model, verifier contract, invocation
  profile, vocabulary, aggregation, coverage, repair, and related-evidence semantics.
  Changing any bound value requires a new version.
- The snapshot stores no query, excerpt, provenance duplicate, prompt, raw verifier
  output, rationale, vector, provider data, or additional verifier-model field.
- CHAT-001 persists the complete snapshot atomically with the completed QA outcome.
  Partial, ambiguous, mismatched, or internally inconsistent snapshots fail closed.

### 4. Insufficient-evidence outcomes

- `RELATED_BUT_INSUFFICIENT` and `INSUFFICIENT` never invoke
  `ChatInferenceProvider`.
- Both persist a versioned, Application-authored explicit non-answer as a successful
  insufficient QA completion. Its stable Application resource/response-contract
  version is recorded in the existing `qa_requests.prompt_contract_version`; the exact
  rendered content is the protected historical `chat_messages.content_ciphertext`
  snapshot. `evidence_policy_version` independently records the RAG-002 policy version,
  and `chat_model_id` remains null because no answer-generation model is invoked.
  Reusing the existing contract-version field does not imply that a model prompt ran
  and does not replace the separate frozen RAG-002 snapshot.
- Both finish as `COMPLETED_INSUFFICIENT` with their exact RAG-002 evidence state and a
  linked assistant non-answer message.
- `RELATED_BUT_INSUFFICIENT` persists the policy-approved related evidence as ordered
  citations. Every item must belong to the exact retrieval. CHAT-001 follows the
  implemented RAG-002 contract and does not independently select, reorder, widen, or
  infer that related evidence.
- `INSUFFICIENT` persists zero citations.
- Non-answer wording cannot claim that similarity is confidence and cannot imply that
  the model evaluated or generated the outcome.

### 5. Grounded generation

- Only `SUFFICIENT` may invoke the chat provider.
- A successfully committed grounded answer finishes as `COMPLETED` with
  `evidence_state = SUFFICIENT`.
- CHAT-001 builds a versioned context-only prompt from the exact committed question and
  exact validated retrieval evidence. It exposes each evidence item to the model under
  the derived label `E{rank}`.
- The prompt instructs the model to use only supplied evidence, avoid unsupported
  claims, keep claims traceable, acknowledge missing information, and not provide
  authoritative legal advice.
- CHAT-001 uses the existing exact READY local `ChatInferenceProvider` and records its
  resolved `LocalModelId`. It must not initialize a second runtime, substitute a model,
  prepare/download a model during normal execution, or use a cloud/network fallback.
- Prompt bodies, evidence text, model output, and native provider objects remain absent
  from logs, errors, safe metadata, and public diagnostics.

### 6. Structured output

The versioned M1 model-output contract is logically:

```json
{
  "answer": "non-empty answer text",
  "citations": ["E1", "E2"]
}
```

- The top-level value must be an object containing exactly the two fields above;
  missing or additional top-level fields are invalid.
- `answer` must be a string containing at least one non-whitespace Unicode character.
  It is preserved exactly after contract
  validation; CHAT-001 does not silently rewrite model content.
- `citations` must be a non-empty ordered list of unique labels matching the exact
  `E{rank}` form and resolving to evidence in the exact retrieval used for generation.
- The model cannot supply authoritative evidence IDs, document names, document or
  version IDs, page numbers, source locators, paths, or evidence-sufficiency state.
- Unknown, malformed, out-of-retrieval, or duplicate citation labels invalidate the
  output. CHAT-001 never silently deduplicates or invents citations.
- Invalid initial output may receive at most one constrained repair attempt through the
  same exact local provider and evidence boundary. The repair prompt is versioned and
  contains no additional evidence. A second invalid result fails generation.
- No invalid initial or repaired output is persisted as a completed answer.

### 7. Citation validation and persistence

- Application validation resolves every `E{rank}` label to its exact persisted
  `EvidenceItemId`; all document/version/page/source provenance comes from that
  evidence, never from model text.
- One citation row is persisted for each distinct selected evidence item in the exact
  validated `citations` array order. Prose occurrence order is not inspected and does
  not affect citation order.
- Citation ordinals are one-based, contiguous, and local to the completed assistant
  answer. The same evidence item cannot produce multiple citation rows for one answer.
- CHAT-001 persists neither citation text offsets nor individual citation occurrences.
  Occurrence-level and claim-level citation mapping is outside M1.
- New answer citations begin as valid references to available evidence. Later source
  deletion/tombstone behavior remains outside CHAT-001.

### 8. Grounding guarantee

CHAT-001 guarantees:

- generation from only the exact validated retrieval evidence;
- a versioned context-only prompt;
- structured citation labels limited to that exact retrieval;
- Application validation of every cited label;
- Application-derived source provenance; and
- no general-knowledge, model-substitution, cloud, or hidden fallback path.

CHAT-001 does not claim semantic entailment validation for every sentence. Claim-level
support mapping, arbitrary fabricated-reference detection inside answer prose, and
answer-quality evaluation remain outside this ticket. Model-supplied source prose is
never treated as a real citation.

### 9. Transaction and atomicity boundary

- Retrieval preparation, RAG-002 evaluation, prompt construction, model inference,
  repair, parsing, and citation validation complete before the final write transaction.
- The already committed question and QA scope remain durable across answer failure.
  The final transaction revalidates them; it does not create them.
- One caller-owned Unit of Work must atomically:
  - revalidate the active workspace, QA state, committed question, and exact immutable
    scope;
  - stage or reuse the exact RAG retrieval run and evidence;
  - insert the complete immutable RAG-002 verifier snapshot header and exactly one
    relation for every selected persisted `EvidenceItem`, using the existing
    `EvidenceRank` as the sole authoritative order;
  - insert the protected assistant answer or Application-authored non-answer;
  - insert the complete validated citation set;
  - update the QA request with its terminal state, answer link, evidence state, model
    identity when used, the grounded prompt/output or deterministic non-answer contract
    version in `prompt_contract_version`, the separate RAG-002 policy version, effective
    retrieval top-K, safe metadata, and completion timestamp;
  - update the owning chat timestamp; and
  - insert one safe activity event.
- Application owns transaction orchestration. CHAT and RAG repositories use only the
  caller's active connection and never commit or roll back.
- A successful result is not reported until that final commit succeeds. Any write or
  commit failure rolls back the complete final graph and leaves no completed assistant
  answer or citation.

### 10. Failure, cancellation, and retry

- Model, parsing, repair, validation, citation, persistence, and unexpected failures
  produce sanitized Application errors without sensitive values or provider exception
  strings.
- After the final transaction is rolled back or was never opened, CHAT-001 may use one
  separate short Unit of Work to record `FAILED` or `CANCELLED`. Failure to record that
  state must not replace or conceal the original failure.
- Cooperative cancellation checks occur before retrieval work, before each initial or
  repair inference, immediately after each inference, and before final persistence and
  commit.
- The current provider call is not interruptible. Cancellation arriving during
  inference causes the returned output to be discarded at the next checkpoint.
- An eligible `FAILED` or `CANCELLED` request may retry from its preserved question and
  exact scope through the existing QA progression beginning at `SEARCHING`.
- A complete compatible terminal result is returned idempotently without new model
  calls, messages, citations, IDs, timestamps, or writes. Compatibility requires the
  same workspace/QA/question/scope, complete reusable RAG graph, exact sufficiency state
  and policy version, exact `prompt_contract_version`, and a complete internally
  consistent terminal graph. A grounded completion additionally requires the exact chat
  model plus its protected answer and ordered citations. A non-sufficient completion
  requires a null chat model, the exact deterministic non-answer contract version, its
  protected non-answer, and the citation shape frozen for that sufficiency state.
- Multiple answers, missing links, non-contiguous or duplicate citations, citations to
  another retrieval, mismatched model/policy/contract metadata, or any partial/corrupt
  terminal graph fails closed. CHAT-001 does not repair, replace, or append to it.
- If a prior final transaction rolled back, its transient IDs are not persistent and a
  retry may receive new injected IDs and timestamps.
- Streaming, in-flight provider interruption, cancellation-race hardening, and broader
  recovery remain CHAT-005 work.

## Human Decisions

**None outstanding for CHAT-001.**

RAG-002 owns its own contract and policy decisions. CHAT-001 reuses the implemented
RAG-002 Application contract directly and does not add a parallel sufficiency API.

## Architecture Ownership

| Layer | CHAT-001 ownership |
|---|---|
| Domain | Reuse `EvidenceSufficiency` and existing retrieval evidence/provenance. Add only nominal identities or immutable state relationships that the later implementation plan proves immediately necessary, following existing Domain-versus-Application technical-ID ownership; no provider, prompt, SQLite, or UI concern. |
| Application ports | Own minimal QA completion values, structured-output/citation contracts, cancellation, sanitized errors, and the repository boundary required for final validation and persistence. Reuse RAG-001 and local-model ports. |
| Application use case | Coordinate active workspace validation, RAG preparation, the implemented RAG-002 Application contract, non-answer or local generation, parsing/one repair, citation validation, retry checks, and caller-owned transaction finalization. |
| Infrastructure | Implement exact SQLite mapping and sensitive-payload encoding on the active UoW connection. It owns no sufficiency, prompt, citation-selection, retry, or lifecycle policy. |
| Bootstrap | Compose the existing process-owned local chat provider, RAG use cases, implemented RAG-002 Application contract, codec, UoW, cancellation, clock, and ID factories. It contains no CHAT rules. |
| Presentation | Outside CHAT-001. It displays completed DTOs and later derives presentation labels without becoming a validation or persistence authority. |

## Security and Privacy Boundaries

- Question, evidence excerpts, prompts, model output, answer text, and non-answer text are
  sensitive. Persisted message content crosses the existing `SensitivePayloadCodec`.
- Application never sees raw keys, physical paths, SQLite details, or concrete
  Infrastructure/provider objects.
- Development/test may use the existing insecure codec only with anonymous synthetic
  fixtures under its four mandatory risk warnings. Production composition must reject
  it before retrieval or generation begins.
- Error text, activity metadata, logs, assertions, and smoke output contain no question,
  prompt, answer, excerpt, citation payload, path, URI, raw key, provider-native object,
  or SDK exception text.
- The local-model smoke path is explicit and opt-in, uses the exact configured cached
  chat alias, performs no normal-runtime preparation/download, and has no network or
  cloud fallback.

## Persistence and Schema Impact

**Schema migration: REQUIRED — minimal forward RAG-002 verifier snapshot only.**

The applied schema already represents the chat message, QA terminal metadata,
retrieval/evidence graph, citation ordering, chat timestamp, and activity event. It
does not represent the frozen successful RAG-002 snapshot, so CHAT-001 owns approved
migration 005. The relevant persistence step must select its exact descriptive filename
and concrete table/column shape from repository evidence and must not rewrite an
applied migration.

The migration may add only the logical snapshot header and per-evidence relation
records frozen in Decision 3A. It must enforce exact workspace/QA/retrieval/evidence
ownership, one header per completed QA retrieval, complete unique relation coverage for
non-empty evidence, and an empty relation set for zero evidence. Ordering remains the
existing persisted `EvidenceRank`; no second rank is stored.

`qa_requests.prompt_contract_version` continues to identify the grounded output or
Application-authored non-answer contract. `evidence_policy_version` is the sole
persisted verifier-policy identity, and protected message content remains the exact
historical rendering. CHAT-001 must not add or overload `chat_model_id`,
`prompt_contract_version`, `error_metadata_json`, citations, `message_kind`,
`evidence_code`, citation offsets, claim maps, another scope/retrieval table, or
protected verifier content. Citation and single-answer uniqueness not expressed as a
dedicated database constraint remains transactionally guarded and strictly
reconstructed by the Application-owned repository contract.

## Dependency Impact

**New dependency: NONE.**

Use the Python standard library for structured-output parsing and existing repository,
security, SQLite, local-model, RAG, and UoW facilities. Do not add a schema-validation,
agent, prompt, cloud, ORM, or citation framework.

## Scope

### In scope

- One existing committed QA request and immutable exact scope.
- One RAG-001 retrieval preparation/staging path.
- The implemented RAG-002 Application contract, without a CHAT-owned parallel policy.
- Versioned Application-authored insufficient outcomes.
- Versioned context-only prompt and strict structured answer parsing.
- At most one constrained repair attempt.
- Exact evidence-label validation and ordered citation persistence.
- Atomic final answer/non-answer transaction, safe failure recording, cooperative
  cancellation, and idempotent terminal reuse.
- Anonymous synthetic fake-model, SQLite rollback, security/isolation, citation, and
  opt-in offline local-model smoke evidence.

### Out of scope

- Chat, user-question, QA-request, chat-scope, or QA-scope creation.
- Chat naming, rename/delete, mutable scope lifecycle, or historical scope management.
- RAG scoring/ranking/query embedding or RAG-002 sufficiency algorithms.
- Conversation history, summaries, follow-up resolution, or treating prior answers as
  evidence.
- Streaming UI, partial output display, provider interruption, cancellation-race or
  crash-recovery frameworks.
- Claim-level/occurrence-level citation mapping, answer entailment, general answer
  evaluation, citation opening UI, source viewer, or source deletion lifecycle.
- RAG-002 calibration implementation, CHAT-002+, later RAG work, analysis, or UI
  behavior.
- Cloud/network providers, fallback, model substitution, automatic model download,
  production crypto, schema work beyond the frozen verifier snapshot, or new
  dependencies.

## Implementation Plan

## Step 1 — Define CHAT completion contracts

### Status

**COMPLETE**

### Purpose

Define the minimum typed Application boundary for completing one existing QA request,
without implementing persistence, prompting, model inference, or RAG-002 itself.

### Expected files

Add or modify only as repository evidence requires:

- `src/lexlocal/domain/identifiers.py`
- `src/lexlocal/application/ports/chat.py`
- `tests/unit/domain/test_identifiers.py`
- `tests/unit/application/ports/test_chat.py`
- `docs/CHAT-001.md`

### Required behavior

- Inspect and import the completed RAG-002 Application contract directly. Do not wrap it
  in a parallel sufficiency interface or predefine its name or shape in this plan.
- Add only the nominal UUID identities immediately required by the applied chat,
  message, citation, and activity-event schema, following the existing identifier
  implementation.
- Define immutable, privacy-safe values for an existing QA completion target, grounded
  or insufficient terminal outcome, ordered citation registration, completed graph,
  result, exact response-contract version, and safe failure-state update.
- Define the minimum immutable CHAT-owned historical verifier-snapshot persistence
  representation required by the implemented RAG-002 handoff: one exact
  workspace/QA/retrieval/policy-bound header and one relation reference per selected
  persisted `EvidenceItem`. Reuse the existing `EvidenceRank` for validation and
  ordering; do not add a second ranking or duplicate the RAG-002 policy contract.
- Define the smallest repository Protocol needed to load/revalidate one target,
  reconstruct one terminal result, stage one complete outcome, and record a sanitized
  failure/cancellation state.
- Define the cooperative cancellation contract and a small sanitized CHAT error
  vocabulary. Preserve deterministic validation precedence for workspace/owner/scope
  mismatch before detailed identity or protected-payload evaluation.
- Express one-based contiguous citation ordinals and exact evidence ownership without
  adding evidence codes or occurrence offsets.

### Do not

- Add a Chat aggregate, intake use case, scope service, lifecycle CRUD, SQLite/UoW
  property, prompt/parser, provider call, RAG logic, or generic framework.
- Duplicate, wrap, or adapt the implemented RAG-002 result into a parallel policy DTO.

### Focused tests

- Typed identity nominal distinction, canonical UUID behavior, and immutability.
- Value construction, non-whitespace logical text requirements, terminal-state
  consistency, ordered unique evidence, contiguous citation ranks, timestamps, and
  privacy-safe representation.
- Historical verifier-snapshot header ownership, complete unique per-evidence relation
  coverage, authoritative existing-rank ordering, frozen zero-evidence shape, and no
  second ranking.
- Repository Protocol compatibility with a focused fake and no transaction ownership.
- Sanitized errors and workspace/QA/evidence substitution rejection.

### Focused validation

```bash
uv run pytest \
  tests/unit/domain/test_identifiers.py \
  tests/unit/application/ports/test_chat.py -v
uv run ruff check \
  src/lexlocal/domain/identifiers.py \
  src/lexlocal/application/ports/chat.py \
  tests/unit/domain/test_identifiers.py \
  tests/unit/application/ports/test_chat.py
uv run mypy src
uv run pytest tests/architecture -v
git diff --check
```

### Completion gate

The minimum CHAT contracts represent every frozen terminal outcome, citation invariant,
and immutable RAG-002 verifier snapshot; reuse the actual RAG-002 contract and existing
evidence rank without a parallel ranking; expose no sensitive data; leave UoW and
Infrastructure unchanged; and all focused gates pass.

### Actual evidence

- Focused Domain/Application contracts: `327 passed`.
- Ruff: PASS for all Step 1 production and test files.
- mypy: PASS across `69 source files`.
- Architecture: `19 passed`.
- `git diff --check`: PASS.
- No UoW, Infrastructure, SQLite, migration, model, or orchestration implementation was
  added.

## Step 2 — Implement SQLite completion persistence and UoW integration

### Status

**COMPLETE**

### Purpose

Implement strict reconstruction and caller-transaction staging against the existing
chat/QA/citation/activity schema plus the approved verifier snapshot migration,
together with the real UoW repository property.

### Expected files

Add:

- migration 005 under `src/lexlocal/infrastructure/persistence/sql_migrations/`, with
  its descriptive filename selected from repository state during this step
- `src/lexlocal/infrastructure/persistence/sqlite_chat_repository.py`
- `tests/integration/persistence/test_sqlite_chat_repository.py`
- `tests/integration/persistence/test_chat_transactions.py`

Modify:

- `src/lexlocal/application/ports/unit_of_work.py`
- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py`
- `tests/integration/persistence/test_migration_pipeline.py`
- `tests/integration/persistence/test_sqlite_unit_of_work.py`
- `docs/CHAT-001.md`

### Required behavior

- Add the CHAT repository to `UnitOfWork` only together with its real SQLite
  implementation. Reuse the active connection and existing payload codec; open no
  connection and commit or roll back nothing inside the repository.
- Add only the frozen RAG-002 snapshot header and per-evidence relation representation
  in migration 005. Preserve all applied migrations, existing evidence rank, and every
  existing ownership/retention relationship.
- Load and strictly validate the existing same-workspace chat, committed user question,
  QA request, immutable `qa_scope_versions`, allowed state, and protected question.
- Reconstruct a completed grounded or insufficient graph strictly, including the
  linked assistant message, exact QA terminal metadata, retrieval/evidence ownership,
  response-contract version for every completion, the grounded chat model or required
  null non-sufficient model, citations, ordinals, and timestamps.
- Encode/decode assistant and non-answer content through one deterministic existing
  `SensitivePayloadCodec` context bound to workspace and message identity. Do not
  expose payloads or codec metadata through Application results or errors.
- Stage one final graph using guarded owner/state checks: assistant message, exact
  citation rows, complete immutable RAG-002 snapshot, QA terminal update, chat
  timestamp update, and safe activity event. Validate the already staged or committed
  RAG graph; do not recreate retrieval or sufficiency logic.
- Reconstruct the snapshot strictly: one exact header, sole persisted policy version,
  aggregate coverage, four relation counts, repair-used, and exactly one relation per
  selected evidence item in authoritative persisted rank order. Enforce the frozen
  zero-evidence shape and reject missing, duplicate, cross-retrieval, cross-workspace,
  mismatched-count, ambiguous, or partial state.
- Stage `FAILED` or `CANCELLED` only when no completed answer/citation graph exists and
  the current state permits it. Never overwrite a completed result.
- Fail closed on duplicate answers, ambiguous rows, citation gaps/duplicates,
  cross-workspace or cross-retrieval evidence, corrupt ciphertext/metadata/state, and
  conflicting concurrent writes.

### Do not

- Modify any applied migration, add schema beyond the approved migration 005 snapshot
  or a dependency, generate IDs/timestamps, commit/rollback, create intake/scope rows,
  or implement prompt, model, sufficiency, retry, repair, or orchestration rules.

### Focused tests

- Existing target/question/scope reconstruction and exact codec round-trip.
- Grounded and both insufficient terminal graph round-trips.
- Migration 005 application and exact snapshot constraints without changes to any
  applied migration; non-empty complete relations and the frozen zero-evidence shape.
- Citation-array order mapped to one-based contiguous `ordinal`; no occurrence or
  duplicate rows.
- Missing/corrupt/partial/conflicting state and workspace/QA/retrieval/evidence
  substitution, with mismatch precedence before protected decode where required.
- Guarded single-answer behavior, concurrent conflict, compatible reconstruction, and
  strict no-repair behavior.
- Caller commit/rollback, rollback of the complete graph, repository transaction
  neutrality, UoW lifetime, and separate failure-state transaction behavior.
- Sanitized database/codec failures and no protected content in errors.

### Focused validation

```bash
uv run pytest \
  tests/integration/persistence/test_migration_pipeline.py \
  tests/integration/persistence/test_sqlite_chat_repository.py \
  tests/integration/persistence/test_chat_transactions.py \
  tests/integration/persistence/test_sqlite_unit_of_work.py -v
uv run ruff check \
  src/lexlocal/application/ports/unit_of_work.py \
  src/lexlocal/infrastructure/persistence/sqlite_chat_repository.py \
  src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py \
  tests/integration/persistence/test_migration_pipeline.py \
  tests/integration/persistence/test_sqlite_chat_repository.py \
  tests/integration/persistence/test_chat_transactions.py \
  tests/integration/persistence/test_sqlite_unit_of_work.py
uv run mypy src
uv run pytest tests/architecture -v
git diff --check
```

### Completion gate

The real repository strictly round-trips and atomically stages every approved terminal
graph on the caller's connection, approved migration 005 is proven to contain only the
minimal verifier-snapshot schema, all corrupt/substituted/duplicate states fail safely,
and all focused gates pass.

### Actual evidence

- Focused migration/repository/transaction/UoW suite: `61 passed`.
- RAG-001 SQLite retrieval regression: `46 passed`.
- Ruff: PASS for every Step 2 production and test file.
- mypy: PASS across `70 source files`.
- Architecture: `19 passed`.
- `git diff --check`: PASS.
- Migration 005 adds only `qa_verifier_snapshots` and
  `qa_verifier_snapshot_relations`; no applied migration or dependency changed.
- The repository uses only the caller's active connection, performs no transaction
  finalization, preserves `EvidenceRank` as the sole relation order, and fails closed
  for partial, corrupt, duplicate, cross-workspace, and cross-retrieval state.

## Step 3 — Implement versioned prompts, strict parsing, and citation validation

### Status

**COMPLETE**

### Purpose

Implement the pure Application components that build versioned context-only prompts,
parse the exact M1 output object, build constrained repair input, render versioned
non-answers, and validate citations before persistence.

### Expected files

Add:

- `src/lexlocal/application/chat.py`
- `src/lexlocal/application/prompts/chat_v1.py`
- `tests/unit/application/test_chat.py`

Modify after successful validation:

- `docs/CHAT-001.md`

### Required behavior

- Keep all prompt and Application-authored non-answer bodies in one explicitly
  versioned Application resource rather than scattering inline strings. Give each
  grounded prompt/output contract and deterministic non-answer contract a stable
  version identifier suitable for `qa_requests.prompt_contract_version`.
- Build the sufficient prompt from the exact question plus exact evidence in rank
  order, labelled only as `E{rank}`. Include the repo-supported instructions to use
  supplied evidence only, avoid unsupported claims, expose missing information, keep
  claims traceable, and avoid authoritative legal advice.
- Parse with the standard library. Require a top-level JSON object with exactly
  `answer` and `citations`; reject missing/additional keys, wrong types, malformed JSON,
  a whitespace-only answer, empty citations, malformed labels, duplicates, unknown
  labels, and evidence outside the exact retrieval.
- Preserve the exact valid answer string. Treat citations-array order as authoritative;
  do not inspect prose occurrence order, reorder, normalize, or silently deduplicate.
- Resolve labels only through the exact retrieval evidence map and construct citations
  from Application-controlled provenance.
- Build one versioned constrained repair prompt that identifies only safe contract
  requirements and reuses the same exact evidence. This step builds validation and
  repair input but does not call the provider.
- Render the two versioned Application-authored non-answer outcomes. Validate any
  policy-approved related evidence using the implemented RAG-002 contract without
  adding CHAT-owned selection or ordering policy.

### Do not

- Invoke the provider, RAG, repository, UoW, Bootstrap, or SQLite; calculate
  sufficiency; inspect arbitrary prose for factual entailment; or add a parser/schema
  dependency.

### Focused tests

- Exact prompt version, evidence labels/order/content, context-only/legal-safety rules,
  and privacy-safe representation.
- Valid strict output; non-object JSON; missing/extra keys; whitespace answer; wrong
  citation container/item types; empty, malformed, duplicate, unknown, and
  out-of-retrieval labels.
- Exact answer preservation, citations-array order, prose-order independence,
  contiguous ordinals, and Application-derived provenance.
- Repair prompt version/exact evidence confinement and no sensitive error text.
- Exact versioned related/insufficient non-answer rendering, no model-owned source or
  sufficiency metadata, related evidence validation, and zero insufficient citations.

### Focused validation

```bash
uv run pytest tests/unit/application/test_chat.py -v
uv run ruff check \
  src/lexlocal/application/chat.py \
  src/lexlocal/application/prompts/chat_v1.py \
  tests/unit/application/test_chat.py
uv run mypy src
uv run pytest tests/architecture -v
git diff --check
```

### Completion gate

Prompt, parser, repair input, non-answer rendering, and citation validation match the
frozen contracts exactly, remain pure and SDK/SQLite-free, and all focused gates pass.

### Actual evidence

- Focused prompt/parser/citation/non-answer suite: `22 passed`.
- Ruff: PASS for all Step 3 production and test files.
- mypy: PASS across `73 source files`.
- Architecture: `19 passed`.
- `git diff --check`: PASS.
- The versioned `chat-resources-v1` resource owns all grounded/repair prompt rules and
  both deterministic non-answer bodies. No provider, RAG orchestration, repository,
  UoW, SQLite, Bootstrap, dependency, or Step 4 implementation was added.

## Step 4 — Implement atomic QA completion orchestration

### Status

**COMPLETE**

### Purpose

Coordinate existing RAG, implemented RAG-002 sufficiency, local generation, strict
validation, cancellation, idempotent reuse, and final caller-owned UoW persistence.

### Expected files

Modify:

- `src/lexlocal/application/chat.py`
- `tests/unit/application/test_chat.py`

Add:

- `tests/integration/persistence/test_chat_completion_transactions.py`

Modify after successful validation:

- `docs/CHAT-001.md`

### Required behavior

- Resolve the workspace only through `ActiveWorkspaceScope`, then load the existing QA
  target and check for a complete compatible terminal result before expensive work.
- Reuse a compatible completion with no RAG, RAG-002, provider, ID/time factory, or
  write activity. Compatibility includes the exact response-contract version for all
  outcomes, the exact grounded model where applicable, and a null model for
  non-sufficient outcomes. Fail closed on partial, corrupt, ambiguous, or incompatible
  state.
- For an incomplete eligible request, call RAG-001 `PrepareRetrieval`; pass its exact
  result to the implemented RAG-002 Application contract once and consume the returned
  state/version according to that contract.
- For either non-sufficient state, never call the model. Build the matching versioned
  Application non-answer and validate the policy-approved related evidence, if any.
- For `SUFFICIENT`, build the exact prompt and call the injected exact READY
  `ChatInferenceProvider`. Parse and validate the output; on invalid output, perform no
  more than one constrained repair call and validate that result from scratch.
- Check cooperative cancellation before retrieval, before every inference, immediately
  after every inference, and before final persistence/commit. Discard output returned
  after in-flight cancellation.
- Finish retrieval, sufficiency, inference/repair, parsing, and citation validation
  before opening the final write UoW.
- In the final UoW, revalidate the QA target/scope/state, call RAG-001 `StageRetrieval`
  through that UoW's retrieval repository, stage the one complete CHAT outcome, and
  commit once. Report success only after commit.
- On model/validation/citation/cancellation/write/commit failure, preserve the original
  sanitized error, leave no completed graph, and attempt the allowed separate short
  failure-state UoW without masking that original error.
- Permit retry from eligible `FAILED`/`CANCELLED` state and new transient identities
  after rollback; never create a second completed answer for one QA request.

### Do not

- Create intake/scope, call `EmbedQuery` or providers other than the existing chat
  boundary, calculate sufficiency/ranking, hold a write transaction during inference,
  persist prompts/native output, or implement streaming/concurrency hardening.

### Focused tests

- Existing target validation; complete grounded/related/insufficient paths; exact
  RAG/RAG-002 call order and single invocation.
- No model for non-sufficient results; one initial provider call for valid output; one
  repair only; no completed result after exhausted repair or provider failure.
- No transaction during retrieval/sufficiency/inference/validation and exactly one
  final UoW commit after complete validation.
- RAG staging and CHAT graph in the same transaction; rollback on each staged write and
  commit failure with no partial answer/citations.
- Cancellation at each frozen checkpoint and in-flight cancellation output discard.
- Failure-state recording success/failure without masking the original error.
- Complete compatible retry reuse with no work/new identities and fail-closed
  partial/conflicting/corrupt state.
- Sanitized exceptions and no question/evidence/prompt/output/provider leakage.

### Focused validation

```bash
uv run pytest \
  tests/unit/application/test_chat.py \
  tests/integration/persistence/test_chat_completion_transactions.py -v
uv run ruff check \
  src/lexlocal/application/chat.py \
  tests/unit/application/test_chat.py \
  tests/integration/persistence/test_chat_completion_transactions.py
uv run mypy src
uv run pytest tests/architecture -v
git diff --check
```

### Completion gate

Every terminal path, repair/cancellation/retry rule, transaction boundary, and failure
semantic is behavior-tested; Application duplicates no RAG/RAG-002/Infrastructure
ownership; and all focused gates pass.

### Actual evidence

- Focused CHAT content/orchestration/transaction suite: `44 passed`.
- Directly affected SQLite CHAT repository/transaction regressions: `23 passed`.
- Ruff: PASS for the exact Step 4 files plus the narrow SQLite retry correction and
  its regression.
- mypy: PASS across `73 source files`.
- Architecture: `19 passed`.
- `git diff --check`: PASS.
- `CompleteChat` resolves only the active scope, checks compatible terminal reuse
  before new identities or expensive work, calls `PrepareRetrieval` and the implemented
  RAG-002 evaluator once, performs no provider work for non-sufficient outcomes, and
  permits only one constrained repair for sufficient output.
- Retrieval staging and the complete CHAT graph share one final caller-owned UoW and
  one commit. Every write/commit/cancellation injection rolls back staged completion;
  separate failure recording remains best-effort and cannot mask the original error.
- The narrow persistence correction permits a previously recorded eligible
  `FAILED`/`CANCELLED` target to retry while still rejecting missing or inconsistent
  retry metadata. No schema, dependency, Bootstrap, or Step 5 work was added.

## Step 5 — Compose and verify the synthetic CHAT vertical slice

### Status

**COMPLETE**

### Purpose

Wire existing process-lifetime components at Bootstrap and prove one anonymous
synthetic QA request completes through real SQLite, codec, RAG staging, CHAT
persistence, and caller commit/rollback.

### Expected files

Add:

- `src/lexlocal/bootstrap/chat.py`
- `tests/unit/bootstrap/test_chat.py`
- `tests/integration/test_chat_vertical_slice.py`
- `tests/integration/foundry/test_chat_local_smoke.py`

Modify only if required by existing composition conventions:

- `src/lexlocal/bootstrap/application.py`
- `docs/CHAT-001.md`

### Required behavior

- Compose the existing active scope, existing RAG application composition, implemented
  RAG-002 Application contract, existing process-owned exact READY chat provider,
  security codec, SQLite UoW, cancellation, UTC clock, and ID factories.
- Reuse the one existing local-model runtime/provider lifetime; create no alternate
  provider, registry, service locator, or hidden fallback.
- Keep all CHAT decisions in Application. Bootstrap only wires dependencies and fails
  production composition before retrieval, protected data, or model work when no
  release-safe security provider exists.
- Seed only the frozen precondition in integration tests: one existing committed
  same-workspace chat, question, QA request, immutable scope, and eligible ACTIVE
  retrieval graph. Do not introduce an intake use case.
- Prove grounded completion with exact structured citations; related non-answer with
  policy-approved related citations; insufficient non-answer with zero citations;
  compatible repeat reuse; and query/prompt/output ephemerality.
- Prove rollback and substitution/corruption/provider/cancellation failures leave no
  completed assistant result.

### Do not

- Add settings without a frozen need, implement RAG-002, create chat/intake/scope,
  initialize a second model runtime, add UI, schema beyond the approved snapshot,
  dependency, cloud/network path, or move business/validation/SQL rules into Bootstrap.

### Focused tests

- Exact wiring and provider/runtime identity with fakes at true external boundaries.
- Real anonymous synthetic SQLite/codec/RAG/CHAT path for all three sufficiency states.
- Structured generation and citation provenance, final atomic graph, retry reuse,
  rollback, workspace/scope/model substitution, cancellation, and sanitized failure.
- No model for insufficient states; no query/prompt/native response persistence; no SDK,
  SQLite, codec, or provider objects in Application results.
- Production fail-closed before retrieval/generation and no model substitution/fallback.
- Opt-in cached local CHAT prompt/output smoke behavior with no preparation, download,
  network, or cloud fallback; normal test execution skips it explicitly when disabled.

### Focused validation

```bash
uv run pytest \
  tests/unit/bootstrap/test_chat.py \
  tests/integration/test_chat_vertical_slice.py \
  tests/integration/foundry/test_chat_local_smoke.py -v
uv run ruff check \
  src/lexlocal/bootstrap/chat.py \
  tests/unit/bootstrap/test_chat.py \
  tests/integration/test_chat_vertical_slice.py \
  tests/integration/foundry/test_chat_local_smoke.py
uv run mypy src
uv run pytest tests/architecture -v
git diff --check
```

Include `src/lexlocal/bootstrap/application.py` in Ruff only if Step 5 genuinely changes
it.

### Completion gate

The synthetic vertical slice produces either one grounded cited answer or the exact
non-answer, uses one runtime and existing RAG/RAG-002 contracts, fails safely in every
required path, and all focused gates pass.

### Actual evidence

- `src/lexlocal/bootstrap/chat.py` composes the existing RAG-001 preparation/staging,
  implemented RAG-002 evaluator, exact process-owned READY chat provider, security
  codec, SQLite UoW, cancellation, UTC clock, and CHAT identity factories. Provider and
  verifier status identity is checked before the use case is exposed; no runtime or
  provider lifecycle is created here.
- The anonymous synthetic real SQLite/codec/RAG/CHAT slice proved SUFFICIENT grounded
  completion with exact citation provenance, RELATED_BUT_INSUFFICIENT with only the
  policy-approved citation, INSUFFICIENT with zero citations, and compatible terminal
  reuse without repeated embedding, verification, generation, identities, or writes.
- Provider, corrupt-vector, write, cancellation, and workspace-substitution failures
  left no completed assistant, citation, verifier-snapshot, or completion-event graph.
  Production composition failed before protected/model dependency access.
- The opt-in cached/offline CHAT smoke path uses only the exact configured chat alias,
  performs no preparation/download/fallback, and was explicitly SKIPPED in the normal
  focused run because `LEXLOCAL_RUN_CHAT001_SMOKE` was not enabled.
- Focused tests: **13 passed, 1 skipped** (the documented opt-in live smoke).
- Ruff: **PASS** for the exact Step 5 production/test files.
- mypy: **PASS — 74 source files**.
- Architecture: **19 passed**.
- `git diff --check`: **PASS**.

## Step 6 — Run security, regression, offline, quality, and strict-scope gates

### Status

**COMPLETE**

### Purpose

Run the complete technical validation matrix, audit every CHAT-001 path and invariant,
and close only technical Definition of Done items supported by actual evidence.

### Expected files

Modify only for a genuine CHAT-owned defect exposed by a gate, then:

- `docs/CHAT-001.md`

### Required audit

- Run every focused CHAT contract, parser, repository, transaction, Bootstrap, and
  vertical-slice suite; architecture; full pytest; Ruff; mypy; and diff checks.
- Verify the exact QA/scope precondition, RAG/RAG-002 reuse, three outcome paths,
  non-whitespace strict output, extra-field rejection, citation-array order, one-repair
  limit, grounding boundary, and no model call for non-sufficient states.
- Verify no transaction during retrieval/policy/model work; one atomic final commit;
  complete rollback; separate failure recording; idempotent compatible reuse; and
  fail-closed partial/conflicting state.
- Audit codec use, production fail-closed behavior, anonymous synthetic fixtures,
  sanitized errors/logs, no native provider objects, no cloud/network fallback, and no
  sensitive persisted prompt or diagnostic data.
- Verify Domain/Application/Infrastructure/Bootstrap ownership and that no intake,
  scope lifecycle, RAG-002 implementation, CHAT-002+, RAG duplication, UI, analysis,
  unapproved schema, dependency, streaming framework, or unrelated refactor entered
  the diff.
- Verify the opt-in cached local chat smoke path exists, performs no automatic
  preparation/download or cloud access, and is safely skipped when not explicitly
  enabled. Record an actual hardware-dependent result only when it was run.

### Validation

```bash
uv run pytest \
  tests/unit/application/ports/test_chat.py \
  tests/unit/application/test_chat.py \
  tests/integration/persistence/test_sqlite_chat_repository.py \
  tests/integration/persistence/test_chat_transactions.py \
  tests/integration/persistence/test_chat_completion_transactions.py \
  tests/unit/bootstrap/test_chat.py \
  tests/integration/test_chat_vertical_slice.py \
  tests/integration/foundry/test_chat_local_smoke.py -v
uv run pytest tests/architecture -v
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
git status --short
git diff --stat
git diff
```

Run the CHAT-specific opt-in local smoke command defined by Step 5 only in an explicitly
enabled, cached-model environment. Never download or contact a network to make it pass.

### Completion gate

All required technical gates pass with actual counts, the complete diff is
scope/security clean, every technical DoD item is evidenced, no prerequisite/later
ticket work leaked in, and Step 7 is next with files still unstaged.

### Actual evidence

- Focused CHAT contracts, parsing, persistence, transactions, Bootstrap, vertical
  slice, and normal smoke path: **101 passed, 1 skipped**. The sole skip was the
  documented opt-in CHAT smoke because `LEXLOCAL_RUN_CHAT001_SMOKE` was not enabled.
- Architecture: **19 passed**.
- Full suite: **1892 passed, 3 skipped**. The skips were the three explicit opt-in
  Foundry CHAT smoke, generic Foundry smoke, and RAG-002 live qualification paths.
- Ruff: **PASS** for the complete repository.
- mypy: **PASS — 74 source files**.
- `git diff --check`: **PASS**.
- The configured alias was `qwen3-4b`; the local catalog resolved
  `qwen3-4b-generic-gpu:2` with `is_cached=False`, and the normal runtime READY check
  failed closed with sanitized `LocalModelUnavailable`. Therefore the opt-in CHAT
  smoke was **NOT RUN** and is not reported as a live PASS; no preparation, download,
  network, cloud, alternate model, substitution, or fallback was attempted.
- The complete 22-path unstaged diff was audited. Every path has an immediate CHAT-001
  contract, prompt, orchestration, persistence/UoW, migration, Bootstrap, test, or
  ticket-evidence purpose. Migration 005 contains only the approved verifier snapshot
  header/relation tables; migrations 001–004 and dependency files are unchanged.
- Contract and behavior evidence proves the existing committed QA/scope precondition,
  exact RAG-001 and RAG-002 reuse, all three outcomes, strict output/citation and
  one-repair rules, no non-sufficient generation, transaction isolation/atomicity,
  rollback/failure recording/cancellation/retry, codec and production fail-closed
  behavior, sanitized privacy boundaries, one process-owned provider, and correct
  Application/Infrastructure/Bootstrap ownership. No intake, later-ticket, RAG
  redesign, UI, streaming, analysis, claim-validation, cloud, dependency, generic
  framework, debug artifact, or unrelated refactor entered the diff.

## Step 7 — Audit Git state for explicit human staged-diff review

### Status

**COMPLETE**

### Purpose

Classify the final worktree, stage only the exact CHAT-001 change set, audit every
cached hunk, and stop before delivery for explicit human review.

### Expected files

Modify only to record staged-audit evidence:

- `docs/CHAT-001.md`

### Required behavior

- Confirm Step 6 and every technical DoD item are complete before staging anything.
- Inspect branch, tracked/untracked paths, full diff/stat, and whitespace; classify each
  path as CHAT-owned, unrelated, or ambiguous.
- Stage only explicit proven CHAT-owned paths. Never use broad staging when unrelated or
  ambiguous work exists.
- Inspect the entire cached diff and confirm no missing ticket hunk, unrelated change,
  schema beyond the approved snapshot, dependency, generated artifact, local
  environment data, secret, real document, sensitive fixture, debug residue, or
  later-ticket work.
- Record staged path count and cached-check evidence. Keep explicit human review open.

### Validation

```bash
git branch --show-current
git status --short
git diff --stat
git diff
git diff --check
git diff --cached --stat
git diff --cached
git diff --cached --check
```

### Completion gate

The exact scope-clean CHAT-001 diff is staged, cached checks pass, no unexplained ticket
hunk remains unstaged, and explicit human staged-diff approval is the only remaining
gate. Do not commit, push, create a PR, merge, or mark human review complete.

### Actual evidence

- Branch: `feature/chat-001-grounded-answer`.
- All **22** changed paths were classified as CHAT-001-owned; unrelated and ambiguous
  paths: **none**. Each path was staged explicitly by name without broad staging.
- Cached diff: **22 files changed, 8415 insertions, 2 deletions**.
- `git diff --cached --check`: **PASS**. No CHAT-001 path or hunk remains unstaged.
- Every cached file and hunk was audited. The set contains only immediate CHAT-001
  contract/identity, versioned prompt/non-answer, orchestration, UoW/repository,
  migration 005, Bootstrap, focused-test, and ticket-evidence changes.
- Migrations 001–004 and dependency files are unchanged. Migration 005 contains only
  the approved immutable verifier snapshot header and per-evidence relation schema,
  with existing evidence rank remaining authoritative.
- The cached diff contains no secret, sensitive/real fixture, generated/cache/model or
  local-environment artifact, debug/diagnostic residue, alternate runtime/provider,
  cloud/fallback path, CHAT-owned retrieval/sufficiency implementation, intake/UI/
  streaming work, later-ticket behavior, unexplained public abstraction, or privacy/
  logging/error leak.
- Version references are consistent: CHAT resource/response contracts remain v1 and
  the reused RAG-002 verifier/policy bindings remain `evidence-relations-v2` and
  `evidence-policy-v2`. The opt-in local smoke remains recorded as **NOT RUN**, not a
  live PASS, because the configured model was not cached/READY during Step 6.
- Step 1–6 technical evidence remains intact. Explicit human staged-diff review is
  still open and is the sole remaining gate.

## Final Validation Matrix

| Area | Required evidence |
|---|---|
| Owner/scope | Existing committed same-workspace QA, question, and immutable exact scope only; CHAT creates none of them. |
| Reuse | Existing RAG prepare/stage and implemented RAG-002 Application contract; no parallel embedding/retrieval/sufficiency path. |
| Outcomes | SUFFICIENT alone generates; both non-sufficient states use versioned Application non-answers whose contract version and exact protected rendering remain historically identifiable; operational failures stay failures. |
| Prompt/model | Versioned context-only/legal-safety prompt; exact READY process-owned local model; no substitution, download, network, or cloud fallback. |
| Structured output | Exact two-field object; non-whitespace answer; ordered unique exact-retrieval labels; no additional fields; at most one repair. |
| Citations | Application-derived evidence/provenance; citations-array order; one row per unique evidence; contiguous one-based ordinals; no occurrence offsets. |
| Transactions | No write transaction during retrieval/policy/inference; one final caller-owned atomic commit; complete rollback; separate safe failure recording. |
| Retry/cancellation | Compatible terminal reuse without work; corrupt/conflicting state fails; cooperative checkpoints; in-flight output discarded after cancellation. |
| Security | Codec-protected messages; no sensitive logs/errors/diagnostics; synthetic fixtures; production fail-closed; no native SDK objects. |
| Architecture/scope | Application owns orchestration/contracts, Infrastructure owns SQLite/codec mapping, Bootstrap only composes; no intake/later-ticket/framework work. |
| Schema/dependencies | Only approved migration 005 for the frozen verifier snapshot; applied migrations unchanged; no new dependency. |
| Quality/Git | Focused and full tests, architecture, Ruff, mypy, diff audit, explicit staging, then human approval. |

### Required detailed evidence

Implementation planning must assign focused tests that prove at least:

- existing same-workspace QA/question/scope acceptance and missing/cross-workspace/state
  rejection;
- exact reuse of RAG preparation/staging with no direct embedding/ranking path;
- all three injected RAG-002 outcomes and exact policy-version persistence;
- exact atomic RAG-002 snapshot persistence: header ownership, coverage/counts/repair,
  complete per-evidence relations in existing rank order, zero-evidence shape, and
  fail-closed partial/cross-scope/corrupt reconstruction;
- no model call for either insufficient state;
- exact non-answer persistence, the policy-approved related citations in their supplied
  order, zero insufficient citations, exact non-answer contract-version persistence,
  null non-sufficient model identity, and separation from the RAG-002 policy version;
- exact context-only prompt resource/version and exact READY local model identity;
- strict output parsing, non-object output, missing/additional fields, whitespace-only
  answer, malformed fields, zero citation, invalid label, duplicate label,
  out-of-retrieval evidence, one successful repair, and exhausted repair failure;
- exact citations-array ordering, contiguous ordinals, Application-derived provenance,
  workspace/scope isolation, prose-order independence, and no occurrence rows;
- inference and validation outside the final write transaction;
- one final atomic commit containing retrieval/evidence, assistant message, citations,
  QA/chat updates, and safe activity event;
- rollback for model/validation/citation/write/commit failure with no completed answer
  or citations;
- cancellation at every checkpoint, including cancellation during non-interruptible
  inference, with returned text discarded;
- sanitized failure-state recording and preservation of the original error when that
  recording also fails;
- complete compatible retry reuse and fail-closed partial/conflicting/corrupt graphs;
- message payload codec usage, no sensitive error/log leakage, production fail-closed,
  and no concrete Infrastructure dependency in Application;
- an anonymous opt-in cached local chat smoke with no download/network/fallback; and
- architecture, Ruff, mypy, full regression, diff, strict-scope, and staged human-review
  gates according to `CODEX_EXECUTION_RULES.md`.

## Definition of Done

CHAT-001 is complete only when repository evidence proves:

- [x] The operation accepts only an existing committed same-workspace QA request,
  question, and immutable exact scope.
- [x] CHAT creates none of those intake/scope records and duplicates no RAG behavior.
- [x] RAG-002 alone supplies the persisted versioned sufficiency decision.
- [x] Both insufficient states skip the model and persist the exact approved non-answer
  behavior, response-contract version, and protected historical rendering with null
  model identity; operational failures are never converted to insufficiency.
- [x] Sufficient generation uses the exact READY local model and the versioned
  context-only prompt with no alternate-model or cloud fallback.
- [x] Structured output and the single repair allowance are enforced exactly.
- [x] Every grounded answer has at least one citation resolving to its exact retrieval;
  model-supplied source metadata is never authoritative.
- [x] Citations use unique `EvidenceItemId` values in validated citations-array order
  with contiguous one-based ordinals and no occurrence/offset persistence.
- [x] Retrieval/model work occurs outside the final write transaction.
- [x] The completed retrieval/evidence, immutable RAG-002 snapshot, assistant outcome,
  citations, QA/chat updates, and safe activity event commit atomically through one
  caller-owned UoW.
- [x] Any failure or cancellation leaves no completed partial answer/citation graph;
  separate failure recording is sanitized and cannot mask the original error.
- [x] Cooperative cancellation and idempotent retry/reuse satisfy the frozen contract.
- [x] Questions, evidence, prompts, answers, and provider details do not leak through
  logs, errors, diagnostics, tests, or public representations.
- [x] The existing codec boundary and production fail-closed behavior remain intact.
- [x] Migration 005 contains only the frozen verifier snapshot header/relation
  schema, applied migrations remain unchanged, and no new dependency is introduced.
- [x] No CHAT-002+, RAG policy implementation, conversational context, UI, analysis,
  claim-validation, cloud, or unrelated framework/refactor enters the ticket.
- [x] Focused, rollback, architecture, security, offline smoke, Ruff, mypy, full-suite,
  and diff gates pass with actual recorded evidence.
- [ ] The exact staged diff is scope-clean and explicitly approved by a human.

## Current Position

- CHAT-001 behavior, ownership decisions, and ordered implementation plan are frozen.
- RAG-001 and RAG-002 prerequisites are available.
- Step 1 Domain/Application contracts are complete and validated.
- Step 2 SQLite completion persistence, migration 005, transaction behavior, and real
  UoW integration are complete and validated.
- Step 3 versioned prompts, strict output parsing, citation validation, constrained
  repair input, and deterministic non-answers are complete and validated.
- Step 4 atomic completion orchestration, idempotent reuse, cancellation/failure
  handling, and single-UoW final persistence are complete and validated.
- Step 5 Bootstrap composition and the anonymous synthetic CHAT vertical slice are
  complete and validated; the cached/offline local smoke path exists and remains
  explicitly opt-in for the documented later gate.
- Step 6 security, regression, quality, architecture, conditional offline-smoke, and
  strict-scope gates are complete with actual evidence; all technical DoD items are
  proven.
- Step 7 classified and staged the exact 22-path CHAT-001 set; the complete cached diff
  is scope/security clean and cached whitespace checks pass.
- **Next action: stop and wait for explicit human staged-diff review.**
