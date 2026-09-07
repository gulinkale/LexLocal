# EMBEDDING-001 — Generate and Persist Compatible Local Embeddings

## Status

**TECHNICALLY COMPLETE — HUMAN STAGED-DIFF REVIEW OPEN**

Steps 1–7 are complete. All technical gates and the exact staged ticket-diff audit
pass; explicit human staged-diff review is the only remaining gate. No migration or
new dependency was required.

## Purpose

Consume INDEX-001's exact ordered staging chunks, generate compatible local embeddings
in bounded batches, validate and normalize them, persist deterministic protected
`float32` payloads, and invoke INDEX-001's existing `FinalizeIndexing` command only
after the complete compatible set exists. Generate compatible query embeddings for an
explicit ACTIVE `PersistedIndexGeneration` target through the same local provider while
keeping query vectors ephemeral.

## Completion Condition

EMBEDDING-001 is complete when anonymous synthetic staging chunks produce one complete,
idempotent, compatible persisted embedding set; INDEX-001's `FinalizeIndexing` remains
the sole final-activation authority and activates only that complete set; and a synthetic
query produces a normalized in-memory vector compatible with its explicit ACTIVE index
target through the same exact local model identity. No cloud fallback, query persistence,
partial successful set, or independent activation path may exist.

## Scope

- Consume the exact ordered `StagingEmbeddingHandoff`.
- Reuse the existing SDK-free `EmbeddingProvider` and `LocalModelStatus` identity.
- Generate chunk vectors locally in configurable bounded batches.
- Validate exact output count and map output position `i` to input position `i`; also
  validate dimensions, numeric values, norm, model identity, and metadata.
- Normalize accepted vectors and represent persisted values as deterministic `float32`.
- Persist chunk embeddings under the exact staging ownership graph through the existing
  sensitive-payload boundary.
- Resume compatible partial staging work without duplicate rows.
- Verify the complete persisted set before invoking INDEX-001's `FinalizeIndexing`, the
  sole authority for final index activation.
- Generate normalized query vectors in memory for an explicit compatible ACTIVE index
  target supplied by RAG-001.
- Preserve cooperative cancellation, sanitized failures, and short transactions.

## Explicit Non-Goals

- Query-vector persistence, retrieval, ranking, RAG, prompts, chat, citations, or UI.
- Embedding inference in INDEX-001 or a second index-activation implementation.
- Cloud/Azure/OpenAI endpoints, network fallback, or silent model substitution.
- OCR, extraction, chunking, tokenizer, vector database, or worker/queue/retry framework.
- Generic provider registry, plugin architecture, DI container, repository hierarchy, or
  vector framework.
- Production cryptography, key lifecycle, or claims that development plaintext behavior
  provides confidentiality.
- New model download/preparation behavior or automatic normal-runtime setup.
- Unrelated schema, lifecycle, Domain, or repository refactoring.

## Architecture Ownership

| Layer | EMBEDDING-001 responsibility |
|---|---|
| Domain | Reuse typed IDs and existing document/job/generation transitions; add no vector or provider concern. |
| Application ports | Reuse `EmbeddingProvider`; own normalized vector, compatibility, chunk/query result, embedding repository, cancellation, and sanitized error contracts. |
| Application use case | Validate exact model/shape and positional mapping, normalize vectors, batch work, coordinate short UoWs, resume compatible rows, prove completeness, and call the injected existing `FinalizeIndexing` command. |
| Infrastructure Foundry | Continue implementing `EmbeddingProvider` without exposing SDK objects; preserve exact local model binding and sanitized failures. |
| Infrastructure persistence | Own fixed-endian float32 bytes, codec/context mapping, SQLite rows, strict graph reconstruction, corruption checks, and no transaction finalization. |
| Bootstrap | Supply settings, active scope, exact local provider/status, codec, UoW, clock, cancellation, and the existing `FinalizeIndexing` command; contain no vector or lifecycle rules. |

## Existing Repository Evidence

- `src/lexlocal/application/ports/local_models.py::EmbeddingProvider` already exposes
  `status: LocalModelStatus` and batched `embed(texts)` without SDK types.
- `ResolvedModelRecord` supplies stable `LocalModelId`, requested alias, resolved model
  ID, optional version, provider, `EMBEDDING` capability, and positive dimensions;
  `LocalModelStatus` supplies readiness and execution-provider metadata.
- `src/lexlocal/infrastructure/foundry/local_adapter.py` already binds
  `FoundryLocalEmbeddingProvider` to one exact ready `LocalModelId`, calls the local SDK
  with a sequence of texts, returns a result sequence for positional mapping, and rejects
  count/shape, dimension, nonnumeric, boolean, NaN, and infinity failures without
  leaking SDK data.
- `src/lexlocal/application/ports/indexing.py::StagingEmbeddingHandoff` contains one
  exact `CandidateChunkSet`; its generation carries workspace, version, processing job,
  model ID, dimensions, dtype/profile compatibility, and ordered chunks.
- `src/lexlocal/application/indexing.py::FinalizeIndexing` already owns the only guarded
  activation path. It requires exact candidate identity and complete compatible
  embedding metadata before committing lifecycle transitions.
- `UnitOfWork.indexing` and `SQLiteUnitOfWork` already provide caller-owned transaction
  orchestration; repositories neither commit nor roll back.
- `embeddings` already stores one row per `chunk_id`, workspace, index generation,
  embedding model, dimensions, `float32` dtype, unit-normalized flag, protected payload,
  and creation timestamp. Composite workspace FKs and the chunk primary key provide
  ownership and duplicate protection.
- The schema does not directly assert that an embedding's generation equals its chunk's
  generation. The embedding repository must reconstruct and validate that exact graph;
  this is not evidence for a migration.
- `SensitivePayloadCodec`, `SensitivePayloadContext`, and `WorkspaceKeyReference` already
  support a deterministic workspace/chunk/model/dimension/dtype-bound vector context.
- `foundry-local-sdk` and PySide6 are the only direct runtime dependencies. NumPy appears
  transitively in the lockfile but is not a declared LexLocal dependency.

## Approved Decisions

1. Input is exactly INDEX-001's ordered `StagingEmbeddingHandoff`; no alternate chunk
   read or reconstruction path is added.
2. Reuse the existing Application-owned `EmbeddingProvider`. Do not create another
   provider interface merely for this ticket.
3. Provider status must be `READY`, capability `EMBEDDING`, and its exact `LocalModelId`
   and dimensions must match the staging generation before inference and persistence.
4. Chunk and query inference use that same provider contract and exact compatible model
   identity. There is no substitution, discovery, or cloud fallback.
5. Application owns numeric validation and L2 normalization. It accepts only the exact
   expected vector count and maps provider output position `i` to input position `i`;
   this positional contract is not described as independent semantic reorder detection.
   It also requires positive expected dimensions, real non-boolean finite values, and a
   non-zero norm. It uses deterministic standard-library `math.hypot` and produces
   immutable normalized tuples whose values are hidden from representations.
6. Infrastructure owns the persisted representation. Vector format
   `lexlocal-f32-le-v1` is a contiguous sequence of IEEE-754 binary32 values encoded with
   explicit little-endian `struct` format and no platform-native byte order. Payload
   length is exactly `4 * dimensions`; decoding must reproduce the exact canonical
   float32 values and reject malformed length, non-finite values, zero norm, or a norm
   outside `math.isclose(..., rel_tol=1e-6, abs_tol=1e-6)`.
7. Float32 round-trip equality means equality with the values obtained by the specified
   binary32 canonicalization, not bit-for-bit equality with a provider's original Python
   binary64 values.
8. Persisted payload context uses the owning workspace, a canonical owner identity
   containing the chunk/model/dimensions/dtype tuple, purpose
   `chunk-embedding-vector`, and schema version 1. This uses the existing security
   contract without raw keys or a new public security abstraction.
9. `chunk_id` is the embedding database identity. No `EmbeddingId` is introduced because
   the current table intentionally has one embedding row per chunk.
10. Batches are generated outside SQLite transactions. Each completely validated batch
    is persisted in one short caller-owned transaction while the generation remains
    `STAGING`. `LEXLOCAL_EMBEDDING_BATCH_SIZE=32` is the approved frozen M1 operational
    default; an explicit value must remain a positive bounded integer. Batch size is
    operational tuning, not compatibility metadata.
11. Compatible already-persisted rows are reused. Missing rows are generated in chunk
    order. Partial/incompatible/corrupt or cross-scope rows fail closed; rows are never
    silently normalized, reassigned, or deleted to manufacture compatibility.
12. Cancellation/provider failure may leave previously committed compatible rows only
    under `STAGING`; this is not successful partial output. Retry/restart reloads them,
    embeds only missing chunks, and converges under the existing `chunk_id` primary key.
13. After all batches, Application re-reads and validates the exact complete ordered
    set, including decoded payloads, before calling the injected existing
    `lexlocal.application.indexing.FinalizeIndexing` command. That INDEX command is the
    sole final-activation authority: EMBEDDING-001 adds no activation port, alias, SQL,
    or transition rules and does not call `IndexRepository.activate_candidate`
    directly.
14. Query input is passed exactly to the same provider after rejecting an empty or
    whitespace-only query. The query use case explicitly accepts an existing immutable
    `PersistedIndexGeneration` whose generation state is `ACTIVE`; this is the target
    compatibility metadata, not an inferred provider default or an Application lookup.
    Active scope, generation identity, exact `LocalModelId`, dimensions,
    normalization-profile compatibility, and `float32` dtype must match before query
    success. `QueryEmbedding` echoes the target workspace/generation/model compatibility,
    unit-normalized status, and an immutable vector hidden from repr. It is returned only
    in memory and never written. RAG-001 will own selecting/providing the eligible ACTIVE
    target.
15. Use an injected UTC clock for persisted row timestamps and an injected positive
    batch size. IDs are not generated because embedding identity is the existing
    `ChunkId`.
16. No new dependency is required. Standard-library `math` and `struct` are sufficient;
    EMBEDDING-001 must not rely on undeclared transitive NumPy.

## Human Decisions

None outstanding. The explicit ACTIVE query target, positional provider-result mapping,
INDEX `FinalizeIndexing` as the sole final-activation authority, and batch size 32 as the
approved M1 operational default are frozen above. The remaining provider, schema,
security, and transaction choices follow existing repository contracts.

## Schema Impact

**NONE.**

The existing `embeddings` table truthfully represents every required persisted field:
`chunk_id` primary key, workspace/generation/model ownership, positive dimensions,
`float32`, unit-normalized status, payload bytes, and timestamp. Existing FKs and the
repository's strict candidate/chunk reconstruction enforce the remaining cross-table
relationship. No applied migration is edited and no forward migration is needed.

## Dependency Impact

**NONE.**

The existing local SDK implements inference. Application normalization uses `math`;
Infrastructure serialization uses explicit-endian `struct`. NumPy is not a direct
project dependency and is not required by this ticket.

## Security / Local-Only Constraints

- Every persisted vector crosses `SensitivePayloadCodec`; Application never sees codec
  envelopes, raw keys, SQLite BLOBs, or physical paths.
- Development tests may use `InsecureDevelopmentOnlyPayloadCodec` only with anonymous
  synthetic vectors. Its exact warnings remain visible: DEVELOPMENT ONLY, SYNTHETIC
  FIXTURES ONLY, NOT RELEASE SAFE, and NOT FOR REAL USER DOCUMENTS.
- Development plaintext output is not encryption or confidentiality. Production/release
  composition continues to reject the insecure provider before embedding work begins.
- Failures never include chunk text, query text, vector values, encoded payloads, model
  paths/URIs, SDK exceptions/objects, SQL, keys, or local environment values.
- The provider is local-only; no endpoint, credential, network fallback, or remote
  provider setting is introduced.

## Lifecycle / INDEX-001 Integration

Chunk path:

```text
StagingEmbeddingHandoff
→ exact local provider/model compatibility check
→ ordered bounded batch inference outside transactions
→ count/dimension/finite/non-zero validation
→ Application L2 normalization
→ deterministic float32 payload through SensitivePayloadCodec
→ short per-batch SQLite commits under the same STAGING generation
→ exact decoded complete-set verification
→ INDEX-001 FinalizeIndexing (sole final-activation authority)
→ guarded atomic activation
```

Query path:

```text
exact query text + explicit ACTIVE PersistedIndexGeneration target
→ same local EmbeddingProvider and exact LocalModelId
→ exact-count positional mapping + dimension/finite/non-zero validation
→ L2 normalization and exact target-compatibility verification
→ compatible immutable QueryEmbedding in memory
→ RAG-001
```

No query vector is persisted. Chunks or partial embedding rows cannot activate an index.

## Step 1 — Define Application embedding contracts and vector invariants

### Status

**COMPLETE**

### Purpose

Define the minimal SDK/SQLite-free values, errors, repository boundary, normalization,
and chunk/query compatibility rules required by both workflows.

### Architecture ownership

Application owns contracts and numeric validity; Domain remains unchanged.

### Existing pieces reused

`EmbeddingProvider`, `LocalModelStatus`, typed workspace/chunk/generation/model IDs,
`StagingEmbeddingHandoff`, and existing frozen-dataclass/error conventions.

### Expected files

Add:
- `src/lexlocal/application/ports/embeddings.py`
- `src/lexlocal/application/embeddings.py`
- `tests/unit/application/ports/test_embeddings.py`
- `tests/unit/application/test_embeddings.py`

Modify:
- None; defer the shared UoW extension until the concrete repository exists in Step 3.

### Do

- Define immutable normalized-vector, chunk-embedding, persisted-set, query-embedding,
  compatibility, repository, cancellation, and sanitized error contracts.
- Implement deterministic validation/L2 normalization for exact count and positional
  mapping (`output[i]` belongs to `input[i]`), dimensions, finite real values, non-zero
  norm, and exact model metadata.
- Hide text/vector values from repr and require timezone-aware UTC persisted timestamps.
- Require explicit ACTIVE `PersistedIndexGeneration` compatibility metadata for query
  generation, and make query results ephemeral and workspace/generation/model scoped.

### Do not

- Import Foundry, NumPy, SQLite, security providers, or INDEX activation implementation.
- Serialize payloads, add UoW/Infrastructure behavior, persist queries, or orchestrate
  batches.

### Failure / edge cases

Empty/short/extra result sets, invalid positional entries, booleans/nonnumeric values,
wrong dimensions, NaN, infinity, zero/underflow norm, non-UTC timestamps, model/status
mismatch, non-ACTIVE or incompatible query target, empty query, and sanitized dependency
errors.

### Focused tests

Immutability and compatibility behavior; exact count and input/output positional mapping;
robust normalization; finite/non-zero/dimension rejection; hidden repr; chunk ownership;
explicit ACTIVE query-target compatibility; query ephemerality; and Protocol shape/type
compatibility.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_embeddings.py tests/unit/application/test_embeddings.py -v
uv run ruff check src/lexlocal/application/ports/embeddings.py src/lexlocal/application/embeddings.py tests/unit/application/ports/test_embeddings.py tests/unit/application/test_embeddings.py
uv run mypy src
git diff --check
```

Actual Step 1 evidence:

- Focused Application embedding contracts/normalization: **32 passed**.
- Prerequisite correction: `NormalizedEmbeddingVector` now applies the frozen
  `rel_tol=1e-6, abs_tol=1e-6` unit-norm validity tolerance, accepting exact canonical
  float32 round-trip values without renormalization while rejecting clearly non-unit
  vectors; focused rerun: **34 passed**.
- Ruff: **PASS**.
- mypy: **PASS — 58 source files**; focused Protocol/type proof: **PASS — 2 test
  files**.
- Architecture: **19 passed**.
- Diff/whitespace check: **PASS**.

### Step completion condition

Application can represent and validate exact normalized chunk/query vectors and the
minimal persistence boundary without technical provider or storage types.

## Step 2 — Verify the existing local Foundry embedding adapter

### Status

**COMPLETE**

### Purpose

Prove the existing adapter satisfies EMBEDDING-001's local batch provider contract;
harden it only if focused evidence exposes a real gap.

### Architecture ownership

Infrastructure adapts native Foundry responses to the existing Application port.

### Existing pieces reused

`FoundryLocalEmbeddingProvider`, its exact bound `LocalModelStatus`, cached-only runtime,
SDK response extraction, and existing Foundry fakes/tests.

### Expected files

Tests:
- `tests/unit/infrastructure/foundry/test_local_adapter.py`

Modify only if a proven adapter defect exists:
- `src/lexlocal/infrastructure/foundry/local_adapter.py`

### Do

- Prove exact multi-input output count and stable positional sequence, exact status/model
  binding, dimensions, numeric canonicalization, finite rejection, and sanitized
  provider failure.
- Preserve local cached-only execution and existing handle lifetime behavior.

### Do not

- Add a second provider, cloud fallback, normalization/persistence rules, batching
  orchestration, model download, or SDK types to Application.

### Failure / edge cases

Missing/extra outputs, malformed positional items, wrong dimensions, non-finite values,
runtime failure, unavailable exact identity, and native error leakage.

### Focused tests

Existing health/inference tests plus one multi-vector positional-mapping batch case and
any smallest missing sanitized failure proof.

### Focused validation

```bash
uv run pytest tests/unit/infrastructure/foundry/test_local_adapter.py -v
uv run ruff check src/lexlocal/infrastructure/foundry/local_adapter.py tests/unit/infrastructure/foundry/test_local_adapter.py
uv run mypy src
git diff --check
```

Actual Step 2 evidence:

- Existing Foundry adapter focused suite: **37 passed**.
- Exact multi-input cardinality and positional mapping, bound READY
  `LocalModelStatus`, dimensions, SDK-free float values, malformed/bool/nonnumeric/
  non-finite rejection, sanitized provider failure, and failure cleanup are directly
  covered.
- Existing cached-only resolution and handle-lifetime tests remain green.
- Production adapter change: **NONE**; repository evidence showed no contract defect.
- Ruff: **PASS**.
- mypy: **PASS — 58 source files**.
- Architecture: **19 passed**.
- Diff/whitespace check: **PASS**.

### Step completion condition

The existing concrete local adapter demonstrably implements the existing SDK-free
provider contract for exact-cardinality, positionally mapped batches without new
provider behavior outside a proven correction.

## Step 3 — Implement deterministic vector persistence

### Status

**COMPLETE**

### Purpose

Implement strict float32/codec/SQLite mapping and wire the Application embedding
repository into the existing UoW.

### Architecture ownership

Infrastructure owns serialization and SQL; Application owns the repository Protocol;
UoW callers own commit/rollback.

### Existing pieces reused

The `embeddings` schema, `CandidateChunkSet`, SQLite index repository graph conventions,
`SensitivePayloadCodec`, migration fixtures, and SQLiteUnitOfWork lifecycle.

### Expected files

Add:
- `src/lexlocal/infrastructure/persistence/sqlite_embedding_repository.py`
- `tests/integration/persistence/test_sqlite_embedding_repository.py`

Modify:
- `src/lexlocal/application/ports/unit_of_work.py`
- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py`
- `tests/integration/persistence/test_sqlite_unit_of_work.py`

No migration file.

### Do

- Add the UoW embedding property only alongside the real SQLite implementation.
- Serialize normalized values as exact `lexlocal-f32-le-v1` bytes and decode strictly.
- Encode/decode through deterministic workspace/chunk/model/dimension/dtype context.
- Read candidate rows in candidate chunk order; validate exact staging ownership,
  model/dimensions/dtype/unit flag, payload length/content/norm, and timestamp.
- Insert only a complete validated batch; preserve `chunk_id` identity and reject
  duplicate, conflicting, partial-corrupt, or cross-scope mappings with sanitized errors.
- Never generate IDs/timestamps or commit/rollback.

### Do not

- Modify migrations, activate generations, persist queries, expose BLOB/context values,
  or create a generic vector/repository framework.

### Failure / edge cases

Malformed bytes, wrong length/endianness metadata, NaN/infinity/zero/non-unit payload,
wrong model/dimension/dtype, chunk-generation mismatch, non-STAGING candidate, duplicate
chunk ID, SQL failure, inactive transaction, and corrupt timestamp.

### Focused tests

Deterministic byte fixtures and exact float32 round-trip; codec use; all schema fields;
ordered subset/complete reads; ownership substitution; duplicate prevention; rollback;
corrupt payload/metadata; repository transaction neutrality; and UoW lifetime.

### Focused validation

```bash
uv run pytest tests/integration/persistence/test_sqlite_embedding_repository.py tests/integration/persistence/test_sqlite_unit_of_work.py -v
uv run ruff check src/lexlocal/application/ports/unit_of_work.py src/lexlocal/infrastructure/persistence/sqlite_embedding_repository.py src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py tests/integration/persistence/test_sqlite_embedding_repository.py tests/integration/persistence/test_sqlite_unit_of_work.py
uv run mypy src
git diff --check
```

Actual Step 3 evidence:

- SQLite embedding repository and UoW lifetime integration: **42 passed**.
- Deterministic little-endian float32 bytes, exact codec context, schema metadata,
  ordered partial/complete reconstruction, scope substitution, duplicate/conflict,
  corruption, rollback, statement atomicity, and transaction neutrality: **PASS**.
- Ruff: **PASS**.
- mypy: **PASS — 59 source files**.
- Architecture: **19 passed**.
- Diff/whitespace check: **PASS**.

### Step completion condition

One validated batch round-trips through the codec and current schema with exact
ownership and deterministic float32 bytes, while transaction finalization remains in
Application/UoW orchestration.

## Step 4 — Implement idempotent batched orchestration and query embedding

### Status

**COMPLETE**

### Purpose

Generate/resume chunk embeddings batch by batch, verify the complete persisted set,
call INDEX-001's existing `FinalizeIndexing` as the sole final-activation authority, and
expose a compatible ephemeral query path.

### Architecture ownership

Application owns ordering, batching, compatibility, cancellation, retry convergence,
transactions, and finalizer sequencing.

### Existing pieces reused

`StagingEmbeddingHandoff`, existing provider/status, active workspace scope, embedding
repository/UoW, injected clock, ACTIVE `PersistedIndexGeneration` metadata, and the
existing `FinalizeIndexing` command/result.

### Expected files

Modify:
- `src/lexlocal/application/embeddings.py`
- `tests/unit/application/test_embeddings.py`

Add:
- `tests/integration/persistence/test_embedding_transactions.py`

### Do

- Resolve workspace only from `ActiveWorkspaceScope` and reject candidate/provider
  substitution before inference or persistence.
- Load compatible existing rows, embed only missing chunks in exact document order, map
  each provider result position to its corresponding batch input position, and preserve
  global chunk order across batches.
- Keep provider calls outside transactions; validate a full provider batch before one
  short persistence transaction and checkpoint cancellation between batches.
- Re-read/decode the exact complete set before invoking the injected existing
  `FinalizeIndexing` command; do not introduce another activation authority or call the
  repository activation primitive directly.
- On retry/restart, reuse compatible rows and converge without duplicates; never report
  success until finalization succeeds.
- Accept explicit ACTIVE `PersistedIndexGeneration` target metadata, validate it against
  active scope and the same provider/model/shape/profile contract, generate one exact-query
  batch, normalize it, and return `QueryEmbedding` without opening a persistence UoW.

### Do not

- Duplicate activation rules/SQL, hold a transaction during inference, delete
  incompatible rows, persist query vectors, or add progress/worker/retry frameworks.

### Failure / edge cases

No active workspace, stale/wrong candidate, provider status change, partial batch
response, provider failure, cancellation before/between/after batches, batch commit
failure, compatible partial resume, complete-set commit with finalizer interruption,
restart, incompatible existing row, concurrent duplicate, and finalizer failure.

### Focused tests

Multiple batches, positional result mapping, and global chunk order; exact input text;
fixed clock; count/dimension/finite/zero validation; cancellation boundaries; no
transaction during inference; per-batch rollback; partial resume/restart; identical
repeat; no duplicates; complete proof before `FinalizeIndexing`; that sole authority
called exactly once; explicit ACTIVE query-target compatibility; and no query repository
calls.

### Focused validation

```bash
uv run pytest tests/unit/application/test_embeddings.py tests/integration/persistence/test_embedding_transactions.py -v
uv run ruff check src/lexlocal/application/embeddings.py tests/unit/application/test_embeddings.py tests/integration/persistence/test_embedding_transactions.py
uv run mypy src
git diff --check
```

Actual Step 4 evidence:

- Batched orchestration, resume/retry, cancellation, finalizer sequencing, query
  ephemerality, and real transaction rollback behavior: **41 passed**.
- Provider inference outside UoWs, full batch validation before writes, exact global
  order and positional mapping, compatible-row reuse, complete-set re-read, and sole
  `FinalizeIndexing` activation authority: **PASS**.
- Commit/write failures roll back only the current batch; previously committed compatible
  STAGING rows remain reusable and no failed path reports success: **PASS**.
- Ruff: **PASS**.
- mypy: **PASS — 59 source files**.
- Architecture: **19 passed**.
- Diff/whitespace check: **PASS**.

### Step completion condition

Chunk work converges to one complete compatible persisted set before INDEX
`FinalizeIndexing` runs, and queries produce compatible normalized in-memory vectors
for an explicit ACTIVE index target through the same local model contract.

## Step 5 — Compose and verify the synthetic embedding vertical slice

### Status

**COMPLETE**

### Purpose

Compose existing local-model, security, indexing, persistence, scope, clock, and
cancellation components and prove the complete synthetic chunk/query paths.

### Architecture ownership

Bootstrap selects and injects concrete components only; Application retains all vector,
batch, retry, and lifecycle rules.

### Existing pieces reused

`LocalModelComposition.embedding` and `embedding_status`, INDEX composition/handoff and
sole activation authority `FinalizeIndexing`, security-provider selection, SQLite
factory/UoW, active scope, and synthetic vertical-slice fixtures.

### Expected files

Add:
- `src/lexlocal/bootstrap/embeddings.py`
- `tests/unit/bootstrap/test_embeddings.py`
- `tests/integration/test_embedding_vertical_slice.py`

Modify:
- `src/lexlocal/bootstrap/settings.py`
- `tests/unit/bootstrap/test_settings.py`

### Do

- Add positive bounded `LEXLOCAL_EMBEDDING_BATCH_SIZE` settings loading using existing
  settings patterns and the approved frozen M1 operational default of 32.
- Compose one exact ready local embedding provider/status, development/test codec,
  repository/UoW, active scope, cancellation, clock, and the existing INDEX
  `FinalizeIndexing` command as the sole final-activation authority.
- Prove synthetic processed chunks reach complete persisted embeddings and guarded
  activation, and a synthetic query with explicit ACTIVE index compatibility metadata
  yields a compatible ephemeral vector.
- Prove production rejects insecure composition before vector work.

### Do not

- Put validation/normalization/batching/SQL in Bootstrap, initialize another model
  runtime, use real user text, call cloud services, or add RAG/retrieval behavior.

### Failure / edge cases

Invalid batch setting, missing/not-ready/wrong model status, production insecure
provider, storage/commit/finalizer failure, cancellation, repeat, and workspace/model
substitution.

### Focused tests

Exact wiring and provider lifetime; approved default batch size 32 and positive bounded
override; real SQLite/codec path with synthetic vectors; complete activation only via
`FinalizeIndexing`; retry; explicit ACTIVE-target ephemeral query; production
fail-closed; sanitized errors; and no SDK/SQLite values crossing Application results.

### Focused validation

```bash
uv run pytest tests/unit/bootstrap/test_embeddings.py tests/integration/test_embedding_vertical_slice.py -v
uv run ruff check src/lexlocal/bootstrap/embeddings.py src/lexlocal/bootstrap/settings.py tests/unit/bootstrap/test_embeddings.py tests/unit/bootstrap/test_settings.py tests/integration/test_embedding_vertical_slice.py
uv run mypy src
git diff --check
```

Actual Step 5 evidence:

- Bootstrap composition and synthetic chunk/query vertical slices: **10 passed**.
- Settings, security-provider, and INDEX Bootstrap regressions: **53 passed**.
- Exact existing local embedding-provider reuse, codec-bound SQLite UoW wiring, shared
  cancellation/clock, configured batching, and existing `FinalizeIndexing` authority:
  **PASS**.
- Synthetic STAGING chunks persist and activate; compatible retries reuse rows; query
  vectors remain ephemeral; workspace/model/readiness substitution, cancellation,
  write/commit/finalizer failures, and production insecure composition fail safely:
  **PASS**.
- Ruff: **PASS**.
- mypy: **PASS — 60 source files**.
- Architecture: **19 passed**.
- Diff/whitespace check: **PASS**.

### Step completion condition

The real local Application provider boundary, codec, SQLite repository, and INDEX
`FinalizeIndexing` compose into one synthetic chunk-embedding/activation path plus one
explicit ACTIVE-target compatible ephemeral query path with no cloud fallback.

## Step 6 — Run quality, security, architecture, and strict-scope gates

### Status

**COMPLETE**

### Purpose

Run the complete EMBEDDING-001 evidence matrix and audit every changed path.

### Architecture ownership

Validation only; correct only genuine owning defects from Steps 1–5.

### Existing pieces reused

Focused embedding suites, Foundry/INDEX/PROCESSING regressions, architecture suite,
project Ruff/mypy, and Git diff checks.

### Expected files

Modify:
- `docs/EMBEDDING-001.md` only after every required gate passes

Tests:
- None unless a genuine earlier defect lacks proof.

### Do

- Run focused embedding, architecture, full pytest, Ruff, mypy, diff/whitespace,
  local/security, lifecycle, retry, query-ephemerality, and strict-scope audits.
- Record actual counts/results and audit every technical Final DoD item.

### Do not

- Add features, weaken gates, implement RAG-001, or stage files.

### Failure / edge cases

Classify failures as ticket-owned or pre-existing; make only the smallest authorized
owning correction and rerun every invalidated gate.

### Focused tests

The complete Final Validation Matrix below.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_embeddings.py tests/unit/application/test_embeddings.py tests/unit/infrastructure/foundry/test_local_adapter.py tests/integration/persistence/test_sqlite_embedding_repository.py tests/integration/persistence/test_embedding_transactions.py tests/unit/bootstrap/test_embeddings.py tests/integration/test_embedding_vertical_slice.py -v
uv run pytest tests/architecture -v
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```

Actual Step 6 evidence:

- Complete focused EMBEDDING-001 matrix: **116 passed**.
- Architecture suite: **19 passed**.
- Full repository suite: **1420 passed, 1 opt-in Foundry smoke skipped**.
- Ruff: **PASS**.
- mypy: **PASS — 60 source files**.
- Diff/whitespace checks: **PASS**.
- Provider/model identity, vector validation, deterministic serialization, exact
  persistence ownership, batching/cancellation, retry/idempotency, ephemeral queries,
  sole `FinalizeIndexing` activation, and production fail-closed behavior: **PASS**.
- Strict architecture/security/scope audit: **PASS**; no migration, dependency,
  query persistence, cloud fallback, production crypto, RAG/UI/OCR/worker framework,
  alternate activation path, sensitive fixture, or unrelated implementation entered
  EMBEDDING-001.

### Step completion condition

All focused/full gates, regressions, security/architecture checks, strict scope, and
technical DoD items pass with actual evidence.

## Step 7 — Audit Git state for human staged-diff review

### Status

**COMPLETE**

### Purpose

Stage only the completed EMBEDDING-001 change set, audit every cached hunk, and stop for
explicit human review.

### Architecture ownership

Git/diff audit only.

### Existing pieces reused

Step 6 evidence and repository Git conventions.

### Expected files

Modify:
- `docs/EMBEDDING-001.md` only to record a clean staged audit

### Do

- Classify all tracked/untracked paths, explicitly stage only proven ticket-owned files,
  inspect the full cached diff, and run cached whitespace/security/scope checks.
- Leave human approval open.

### Do not

- Change behavior, commit, push, create a PR, merge, switch branches, or claim human
  approval.

### Failure / edge cases

Leave unrelated/ambiguous paths unstaged; reopen Step 6 if a technical defect appears.

### Focused tests

No new tests; preserve Step 6 evidence.

### Focused validation

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

Actual Step 7 evidence:

- Exact staged set: **18 EMBEDDING-001-owned paths**; unrelated/ambiguous paths:
  **NONE**.
- Entire cached diff inspected for every staged file and hunk: **PASS**.
- Cached scope/security/generated-file audit: **PASS**; no migration, dependency,
  secret, credential, real/sensitive fixture, local-environment file, generated
  artifact, cloud fallback, production crypto, RAG implementation, or alternate
  activation path is staged.
- Unstaged ticket-owned changes: **NONE**.
- `git diff --cached --check`: **PASS**.
- Explicit human staged-diff review: **OPEN**.

### Step completion condition

The exact scope-clean ticket diff is staged and cached checks pass, with explicit human
review as the only remaining gate.

## Final Validation Matrix

| Area | Required evidence |
|---|---|
| Provider/model identity | Existing `EmbeddingProvider`; exact ready EMBEDDING status, stable model ID, dimensions, local execution, no substitution, exact chunk/query compatibility. |
| Vector validation | Exact output count and positional `output[i]` to `input[i]` mapping; dimensions; real non-boolean finite values; robust non-zero norm; deterministic L2 normalization; decoded norm tolerance. |
| Serialization | Explicit little-endian IEEE-754 binary32 v1 bytes; exact length and canonical round-trip; malformed/corrupt payload rejection. |
| Persistence | Exact staging workspace/version/generation/chunk/model graph; codec context; all metadata/timestamps; ordered reads; duplicate prevention; repository transaction neutrality. |
| Batching/cancellation | Approved M1 operational default 32 plus positive bounded override; multiple bounded batches, global chunk order with positional provider-result mapping, no inference transaction, validation before write, checkpoints between batches, failure never activates partial data. |
| Retry/idempotency | Identical repeat, compatible partial resume, restart after committed batches/finalizer interruption, conflicting rows fail closed, no duplicate rows or inference for reusable chunks. |
| Query embedding | Explicit ACTIVE `PersistedIndexGeneration` target; matching active scope/generation/model/dimensions/profile/dtype; exact query input; normalized immutable result; no UoW or SQLite query-vector row. |
| INDEX finalization integration | Chunks/partial vectors never activate; exact decoded complete set precedes one call to INDEX `FinalizeIndexing`, the sole final-activation authority; no alternate port, direct repository activation, transition, or activation SQL. |
| Local-only/security | No cloud/fallback/credentials; payload codec and risk labels; synthetic fixtures; production fail-closed; sanitized errors with no text/vector/payload/path/SQL/SDK leakage. |
| Architecture | Domain unchanged; Application has no Foundry/SQLite/codec implementation; Infrastructure implements ports; Bootstrap only composes. |
| Regression | Existing Foundry, INDEX-001, PROCESSING-001, settings, security, persistence, UoW, and architecture behavior remains green. |
| Strict scope | No query persistence, retrieval/RAG/UI/OCR/worker/retry/DI/plugin/tokenizer/production crypto/new dependency/unrelated refactor. |
| Quality | Focused suites, architecture, full pytest, Ruff, mypy, diff checks, full scope/security audit, and actual results recorded. |

## Final Definition of Done

- [x] Existing local `EmbeddingProvider` is used with the exact ready compatible model
  identity for chunk and query embeddings; no silent substitution or cloud fallback.
- [x] Provider output count and positional `output[i]` to `input[i]` mapping, dimensions,
  numeric type, finite values, and non-zero norm are validated before persistence or
  query success.
- [x] Accepted vectors are deterministically L2-normalized and immutable.
- [x] Persisted values use exact versioned little-endian float32 serialization and strict
  deterministic round-trip/corruption validation.
- [x] Every chunk vector crosses the sensitive-payload boundary with exact workspace,
  chunk, generation/model compatibility and explicit development-only risk handling.
- [x] Embeddings persist only under the exact workspace/version/STAGING generation/chunk
  graph represented by the INDEX handoff.
- [x] Batches are bounded, ordered, generated outside transactions, and cooperatively
  cancellable without exposing a successful partial set.
- [x] Retry/restart reuses compatible rows, resumes missing chunks, and cannot create
  duplicate or silently replace incompatible embeddings.
- [x] The exact decoded complete persisted set is proven before INDEX
  `FinalizeIndexing`, the sole final-activation authority, is invoked.
- [x] EMBEDDING-001 contains no independent activation port/alias, direct repository
  activation call, transition, SQL, or fallback path.
- [x] Query embeddings explicitly accept an ACTIVE `PersistedIndexGeneration` target,
  match its active workspace/generation/model/dimensions/profile plus the frozen
  `float32` compatibility, and remain ephemeral with no SQLite persistence.
- [x] `LEXLOCAL_EMBEDDING_BATCH_SIZE=32` is the approved frozen M1 operational default;
  explicit overrides are positive bounded integers and do not become compatibility
  metadata.
- [x] Errors/logs expose no chunk/query text, vectors, payloads, paths, SQL, SDK objects,
  secrets, credentials, or environment values.
- [x] Domain remains independent; Application remains Foundry/SQLite/Infrastructure-free;
  Bootstrap contains composition only.
- [x] No migration or new dependency is added; existing schema constraints and
  standard-library math/struct are used.
- [x] Foundry, INDEX-001, PROCESSING-001, settings, security, persistence, UoW, and
  architecture regressions remain green.
- [x] Focused tests, architecture tests, full pytest, Ruff, mypy, and diff checks pass
  with actual results recorded.
- [x] Strict scope/security/overengineering audit is clean and fixtures are anonymous
  synthetic data.
- [x] Exact ticket files are staged and cached diff checks pass.
- [x] Final staged diff is scope-clean and explicitly human-reviewed. *(Human only)*

## Current Position

- Step 1 is complete: immutable SDK/SQLite-free embedding values, repository and
  cancellation contracts, exact-count positional mapping, deterministic L2
  normalization, strict model compatibility, and explicit ACTIVE query-target behavior
  are implemented and focused-tested.
- Step 1 added no UoW, Infrastructure, provider invocation, serialization, persistence,
  batching, finalization, migration, or dependency work.
- Step 2 is complete: the existing cached-only Foundry adapter satisfies exact-count
  positional mapping, exact READY model/status binding, dimension and finite numeric
  validation, SDK-free output, sanitized failure, and handle-cleanup requirements.
- Step 2 required focused test coverage only; production adapter behavior was unchanged.
- Step 3 is complete: exact STAGING graph validation, deterministic
  `lexlocal-f32-le-v1` serialization, codec-bound vector persistence, strict ordered
  reconstruction, sanitized corruption/conflict rejection, and real UoW repository
  lifetime are implemented and focused-tested.
- Step 3 added no migration, dependency, query persistence, inference, batching,
  activation, or transaction finalization behavior.
- Step 4 is complete: missing vectors are generated outside transactions in exact
  ordered batches, validated before short caller-owned writes, resumed idempotently,
  re-read as one complete set, and activated only through the injected existing
  `FinalizeIndexing` command.
- Step 4 query embedding requires the sole active workspace and an explicit compatible
  ACTIVE target, sends the exact query text once, and returns only an ephemeral
  normalized `QueryEmbedding` without a UoW or persistence path.
- Step 5 is complete: Bootstrap reuses the existing process-owned local embedding
  provider, development codec, SQLite UoW, active scope, cancellation, UTC clock, and
  INDEX `FinalizeIndexing` without introducing another runtime or activation path.
- Step 5 proves the synthetic STAGING-to-ACTIVE chunk path, idempotent recovery after
  finalizer interruption, atomic write/commit failure behavior, fail-closed
  substitution/cancellation/production behavior, and an explicit ACTIVE-target query
  path with no persistence.
- Step 6 is complete: the focused matrix passed 116 tests, architecture passed 19 tests,
  and the full repository suite passed 1420 tests with one unrelated opt-in Foundry
  smoke test skipped; Ruff, mypy over 60 source files, and diff checks passed.
- The technical Final Definition of Done and staged Git audit are complete; explicit
  human staged-diff review remains open.
- Step 7 is complete: all 18 ticket-owned paths are staged, the entire cached diff is
  scope/security clean, no ticket hunk remains unstaged, and the cached whitespace
  check passes.
- No human blocker remains. Schema impact is NONE and dependency impact is NONE.
- Next action: obtain **explicit human staged-diff review**; do not commit, push, or
  create a PR before that approval.
