# INDEX-001 — Deterministic Page-Aware Chunking and Index Generation

## Status

**READY FOR HUMAN STAGED-DIFF REVIEW**

All eight human decisions are approved and frozen. The required minimal forward
migration is `003_chunk_source_offsets.sql`; it adds only the two exact source-offset
columns. No new dependency is required. Steps 1–7 are complete; the exact 21-file
INDEX-001 change set is staged and explicit human review remains open.

## Purpose

Convert PROCESSING-001's exact ordered page handoff into deterministic, page-scoped
chunks under one inactive index generation, expose those chunks through an
Application-owned embedding handoff, and provide the final atomic activation boundary
that is invoked only after the complete chunks-and-embeddings pipeline is valid.

## Completion Condition

INDEX-001 is complete only when its approved chunking and candidate-generation
contracts, persistence, retry behavior, embedding handoff, and activation boundary are
implemented and proven. The product-level completion state is an active document
version with exactly one compatible `ACTIVE` index generation; reaching that state
requires the downstream embedding work and must not be simulated by INDEX-001.

## Scope

- Configurable deterministic page-aware chunking.
- Candidate `IndexGeneration` creation and complete ordered chunk persistence.
- Exact page and `SourceLocator` provenance on every chunk.
- Idempotent repeat/restart behavior for candidate and already-active generations.
- Application-owned ordered chunk handoff for EMBEDDING-001.
- Application-owned final validation/activation transaction, invoked only when the
  downstream embedding stage proves completeness.
- Failure and cooperative cancellation behavior that never exposes partial data as
  active.
- Bootstrap composition from existing processing, model-identity, security, UoW, ID,
  and clock components.

## Non-Goals

- Embedding inference, vector serialization, or embedding persistence.
- Retrieval, cosine similarity, RAG, citations, chat, or UI.
- PDF extraction, OCR, original paths, or controlled-source access.
- Worker/task infrastructure or a generic retry framework.
- A tokenizer, index library, NumPy, vector database, or new dependency without a
  separately approved requirement.
- Production cryptography, key management, or claims that the development codec is
  release-safe.
- Geometry or UI-specific citation metadata.

## Current Repository State

- The current audited branch is `main`; the worktree is clean before this plan file is
  created.
- `ChunkId` and `IndexGenerationId` already exist as distinct typed UUID identifiers.
- Domain already defines `IndexGeneration`, `IndexGenerationState`, guarded
  `STAGING -> ACTIVE/FAILED` transitions, and activation validation against a terminal
  ready processing job.
- `DocumentVersion` already supports
  `CANDIDATE_PROCESSING -> CANDIDATE_READY/CANDIDATE_WARNING -> ACTIVE`.
- PROCESSING-001 leaves the job `PROCESSING` at stage `CHUNKING`, leaves the version
  `CANDIDATE_PROCESSING`, and persists the complete page/locator set atomically.
- No Application chunk/index contract, chunker, repository, use case, Bootstrap
  composition, or INDEX-001 test currently exists.
- The initial schema already contains `index_generations`, `chunks`, embeddings, the
  relevant composite foreign keys, ordered-chunk uniqueness, and partial unique indexes
  for one active version/index generation.
- `SQLiteUnitOfWork` exposes workspace, local-model, ingestion, and processing
  repositories; it has no index repository yet.
- Foundry composition already exposes an SDK-free resolved embedding model identity and
  positive dimensions, but INDEX-001 must not call embedding inference.

## Upstream Contract — PROCESSING-001

INDEX-001 consumes only
`ProcessingRepository.list_pages_for_chunking(workspace_id, document_version_id)` from
inside an active UoW. It receives an immutable ordered sequence of `ProcessedPage`
values containing:

- `DocumentPageId`, `WorkspaceId`, and `DocumentVersionId`;
- one-based `PageNumber`;
- exact decoded page text with no trimming, case-folding, normalization, or newline
  rewriting;
- `READY` or `WARNING` state;
- extraction method `NATIVE`;
- the matching page-level `SourceLocator`.

The repository verifies the candidate version and the `PROCESSING`/`CHUNKING` job and
rejects cross-workspace, cross-version, corrupt, incomplete, or unordered mappings.
INDEX-001 must not observe Qt values, SQL rows, encoded payload metadata, storage
references, paths, source bytes, or UI types.

## Downstream Contract — EMBEDDING-001

EMBEDDING-001 needs an Application-owned read contract returning one exact candidate
generation plus its complete ordered chunks. Each chunk handoff value must expose only
logical identity and compatibility metadata, exact decoded chunk text, ordering,
extraction method, and page/source-locator provenance. It must expose no SQL, codec
payload, Qt type, path, storage reference, or chunker implementation detail.

The generation already carries the exact resolved embedding `LocalModelId`, dimensions,
`float32` schema commitment, chunking profile version, and normalization profile
version. EMBEDDING-001 writes one compatible vector per chunk, validates completeness,
then invokes the Application-owned finalization boundary. INDEX-001 does not generate
vectors.

## Architecture Mapping

| Layer | Ownership |
|---|---|
| Domain | Reuse typed IDs, document/job/generation states, relationships, and guarded transitions. Add no second index model unless an approved contract cannot be represented. |
| Application ports | Own chunk configuration/value/result/error contracts, chunk equality-token boundary, candidate persistence/handoff/finalization repository, and the Step 2 UoW extension introduced with its concrete repository. |
| Application use case | Resolve sole active workspace, load the exact processing handoff, calculate deterministic chunks in memory, enforce provenance/config/cancellation invariants, create injected IDs/time, and coordinate short transactions. |
| Infrastructure persistence | Own SQL, codec mapping, equality-token storage, strict relationship reconstruction, candidate/chunk writes, retry queries, embedding-completeness query, and atomic activation. |
| Infrastructure security | Provide only an explicitly named synthetic development implementation of any approved chunk equality-token contract. |
| Bootstrap | Supply settings, active scope, resolved embedding identity, codec/provider, UoW, IDs, clock, and cancellation; contain no chunking or activation rules. |

## Existing Components Reused

- `WorkspaceId`, `DocumentVersionId`, `ProcessingJobId`, `DocumentPageId`,
  `SourceLocatorId`, `ChunkId`, `IndexGenerationId`, and `LocalModelId`.
- `ProcessedPage`, `ProcessedPageState`, `PageExtractionMethod`, `SourceLocator`, and
  `PageNumber`.
- `ProcessingRepository.list_pages_for_chunking` and the processing handoff's strict
  workspace/version/state validation.
- `DocumentVersion`, `ProcessingJob`, `IndexGeneration`, and their existing state and
  relationship validation.
- `ActiveWorkspaceScope`, `UnitOfWork`, `SQLiteUnitOfWork`, connection/migration/test
  helpers, injected UUID factories, and UTC millisecond clocks.
- `SensitivePayloadCodec`, `SensitivePayloadContext`, and `WorkspaceKeyReference` for
  chunk text; the insecure codec remains synthetic-development-only.
- `LocalModelComposition.embedding_status.model` for exact model ID and dimensions,
  without invoking `EmbeddingProvider.embed`.
- Existing AST architecture tests and migrated temporary-database test patterns.

## Gaps Found

1. No Application chunk configuration/value/algorithm contract exists yet.
2. The schema requires non-null `chunks.normalized_text_fingerprint`, but no
   purpose-specific Application contract produces a workspace-scoped chunk equality
   token. The ingestion duplicate-fingerprint port is source-document-specific and must
   not be silently repurposed.
3. No Application value represents a chunk or candidate-generation handoff.
4. No index repository/UoW surface maps the existing tables.
5. Chunk offsets are not represented in the current schema. Page and locator provenance
   is supported; exact persisted start/end offsets are not.
6. The INDEX-owned guarded finalizer and its EMBEDDING-001 invocation contract are not
   implemented yet.

## Migration / Dependency Impact

- **Schema impact: REQUIRED.** Add only
  `src/lexlocal/infrastructure/persistence/sql_migrations/003_chunk_source_offsets.sql`
  in Step 2. It adds the approved inclusive-start/exclusive-end columns to `chunks`,
  preserves the existing table's relationships/keys/constraints/indexes, edits neither
  applied migration, and fabricates no legacy offsets.
- **New dependencies: NONE.** Unicode code-point slicing, deterministic SHA-256 fixture
  tokens, profile construction, persistence, and validation use Python/SQLite facilities
  already present in the repository.

## Frozen / Proven Decisions

1. A chunk belongs to exactly one workspace, document version, index generation, page,
   and source locator. Existing schema relationships enforce those dimensions.
2. A chunk never crosses a PDF page or combines source locators.
3. `document_order` is zero-based and unique within a generation; `page_order` is
   zero-based within a page. Retrieval order is explicit and never incidental SQL order.
4. Chunks are persisted only below an `IndexGeneration` in `STAGING` state.
5. `UNIQUE(index_generation_id, document_order)` prevents duplicate order positions;
   `ux_version_one_active_index` prevents two active generations for one version.
6. The current schema can persist exact chunk text, counts, extraction method, and
   page/locator ownership. It cannot persist character offsets without a migration.
7. Chunk text must use the existing sensitive-payload codec boundary. The approved
   insecure provider may store plaintext bytes only for anonymous synthetic fixtures
   and is DEVELOPMENT ONLY, SYNTHETIC FIXTURES ONLY, NOT RELEASE SAFE, and NOT FOR REAL
   USER DOCUMENTS. Production remains fail-closed.
8. `token_count_estimate` may remain `NULL`; INDEX-001 has no tokenizer or approved token
   estimation algorithm.
9. Candidate creation needs the already resolved embedding model ID and dimensions
   because both are non-null generation compatibility fields. This metadata does not
   authorize embedding inference in INDEX-001.
10. A generation is retrieval-eligible only when its generation, document version, and
    workspace are active and its embedding model is query-compatible.
11. In-memory chunk calculation occurs before a short persistence transaction. SQLite
    atomicity applies to candidate/chunk writes and final activation, not CPU text
    calculation.
12. Failure or cancellation may never expose a partial generation as `ACTIVE`; any
    previous active version/generation remains untouched.
13. Final activation must verify a complete chunk set and one compatible embedding per
    chunk, then atomically transition the job, candidate version, and candidate index.
14. No new dependency is required. `chunking_profile_version` can store the canonical
    complete chunk-profile identity; `normalization_profile_version`, model ID,
    dimensions, and fixed `float32` fields can represent full downstream compatibility.
    The approved `003_chunk_source_offsets.sql` forward migration supplies the only
    missing explicit metadata.
15. Chunk size and overlap use Unicode code points/Python string positions. Defaults are
    `chunk_size=1000` and `overlap=200`, remain injectable/configurable, and require
    `chunk_size > 0` and `0 <= overlap < chunk_size`. These are M1 defaults, not claimed
    universal optima. No tokenizer is used.
16. Each `READY` page is chunked independently with exact sliding windows: start at 0,
    `end=min(start+chunk_size, page_length)`, emit `text[start:end]`, stop when end equals
    page length, otherwise continue at `end-overlap`. Text is never trimmed, normalized,
    case-converted, newline-rewritten, or joined with separators. The final chunk may be
    short and a page no longer than the size yields one exact chunk.
17. `WARNING` pages produced by the frozen whitespace-only rule emit zero chunks. Their
    page and locator provenance remains upstream. A zero-usable-page document never
    reaches INDEX-001 because PROCESSING-001 rejects it.
18. Logical chunk equality excludes random `ChunkId` and derives from canonical
    workspace/version ownership, page/source identity, complete chunk profile, exact
    source offsets/orders, and exact UTF-8 content. Application owns a narrow equality-
    token port. Its M1 SHA-256 adapter is explicitly development-only, deterministic,
    synthetic-fixture-only, non-confidential, and non-release-safe; it introduces no
    HMAC or key management.
19. Chunk-profile compatibility covers algorithm/version, Unicode-code-point unit,
    size, overlap, page/source isolation, warning skip, exact-text behavior, and equality
    contract version. A canonical versioned string containing these values is stored in
    `chunking_profile_version`; it is not a hash and is compared exactly. Full active
    compatibility additionally requires `exact-text-v1`, resolved embedding model ID,
    dimensions, and `float32`. INDEX-001 does not claim full compatibility before
    EMBEDDING-001 completes vectors.
20. Retry reuses exactly one compatible active generation without writes; reuses exactly
    one matching staging generation and atomically verifies/rebuilds its deterministic
    chunks; or creates one staging generation when none matches. Ambiguous/conflicting
    state fails closed. Incompatible existing state is neither silently selected nor
    deleted. No retry framework or attempt infrastructure is introduced.
21. INDEX-001 owns the generation lifecycle and guarded finalizer. Chunk success creates
    only `STAGING`; it never activates. EMBEDDING-001 consumes the Application handoff,
    persists every compatible embedding, and invokes the INDEX-owned finalizer. That
    finalizer atomically verifies completeness/compatibility and reuses existing Domain
    transitions. Failure or cancellation cannot replace old active state or expose a
    partial active generation.
22. Every persisted chunk stores its exact source range within its owning processed page
    using Unicode code-point/Python string positions. `source_start_offset` is zero-based
    inclusive and non-negative; `source_end_offset` is exclusive and strictly greater.
    The required invariant is
    `chunk.text == page.text[source_start_offset:source_end_offset]`. Offsets never cross
    page/locator boundaries, WARNING pages still emit no chunks, and offsets are
    provenance/determinism metadata rather than UI geometry.
23. The current migration convention uses increasing numeric versions and lowercase
    snake_case filenames; versions 001 and 002 exist. The approved next migration is
    `003_chunk_source_offsets.sql`. It adds only
    `source_start_offset INTEGER NOT NULL CHECK (source_start_offset >= 0)` and
    `source_end_offset INTEGER NOT NULL CHECK (source_end_offset > source_start_offset)`
    to `chunks`, edits no applied migration, and preserves every existing relationship,
    key, constraint, and index. Because no current repository can create chunk rows, a
    legitimate pre-003 database has none; unexpected legacy rows must fail migration
    atomically rather than receive fabricated offsets.

## Human Decisions Required

None. All eight decisions are approved and frozen above.

## Decision Record — Approved INDEX-001 Decisions

### APPROVED DECISION — Chunk source-offset persistence

Evidence:
- The approved algorithm freezes start/end as Unicode code-point offsets and requires
  deterministic source offsets/provenance to be preserved.
- `chunks` persists page/source identity, orders, exact text, counts, and an opaque
  equality token, but has no start/end offset columns.
- `page_order` is an ordinal, exact text may repeat within a page, and an equality token
  is not reversible metadata. None can reconstruct offsets losslessly.

Approved outcome:
- Preserve exact inclusive-start/exclusive-end Unicode code-point offsets and add only
  those two constrained columns through `003_chunk_source_offsets.sql`.

Alternatives rejected:
- Remove persisted offset preservation from the frozen decision and retain only page/
  locator provenance and order.

Implementation consequence:
- Add the two explicit offset columns in one forward migration.
  They are the smallest truthful representation, preserve exact provenance, and avoid
  hiding structured metadata in profile strings, ciphertext, or fingerprints.

Impact:
- Defines persistence mapping/tests, downstream handoff, equality material, schema
  impact, and final DoD.

### APPROVED DECISION — Chunk measurement and defaults

Evidence:
- Product scope requires configurable chunk size and overlap.
- No settings, unit, default, or tokenizer is currently defined.

Approval question (resolved):
- What unit measures size/overlap, and what exact M1 defaults and validation limits apply?

Options:
- Unicode code points with fixed positive size and `0 <= overlap < size`.
- Words with a frozen separator/boundary algorithm.
- Model tokens, requiring a tokenizer and model/version coupling.

Approved outcome:
- Unicode code points/Python string positions, default size 1000, default overlap 200,
  injectable configuration, `size > 0`, and `0 <= overlap < size`; no tokenizer.

Implementation impact:
- Defines configuration/value contracts, the chunker, profile identity, settings,
  Bootstrap, and all boundary tests.

### APPROVED DECISION — Exact chunk boundary and text semantics

Evidence:
- PROCESSING-001 preserves exact text.
- No current rule authorizes trimming, normalization, word-boundary expansion, newline
  rewriting, or inserted separators.

Approval question (resolved):
- Must chunks be exact fixed-window substrings, or may boundaries/text be rewritten?

Options:
- Exact consecutive substrings using the approved unit and overlap.
- Boundary-aware splitting with separately frozen Unicode/newline/word rules.

Approved outcome:
- Exact fixed-window substrings of each page, no mutation, with the next
  start equal to `previous_start + size - overlap`; emit the final non-empty short
  substring and never emit an empty chunk.

Implementation impact:
- Defines deterministic algorithm, metadata/count semantics, fingerprint input, and
  determinism/overlap tests.

### APPROVED DECISION — Mixed WARNING-page consumption

Evidence:
- A `WARNING` page in M1 contains only empty/whitespace native text and is retained for
  provenance.
- PROCESSING-001 explicitly leaves its chunk-consumption decision to INDEX-001.

Approval question (resolved):
- Does such a page produce any chunk?

Options:
- Persist zero chunks while retaining the page and locator.
- Persist whitespace-only chunks.

Approved outcome:
- Skip `WARNING` pages and persist zero chunks for them. A mixed
  document proceeds through its `READY` pages; meaningless whitespace is not indexed.

Implementation impact:
- Defines page filtering, chunk-count validation, candidate completeness, and mixed-page
  tests.

### APPROVED DECISION — Chunk equality-token contract

Evidence:
- `chunks.normalized_text_fingerprint` is `BLOB NOT NULL` and documented as a
  workspace-scoped keyed fingerprint.
- Existing `DuplicateFingerprint` is specifically an ingestion/source-digest contract;
  the generic security codec does not produce deterministic equality material.

Approval question (resolved):
- Approve a minimal purpose-specific Application port and synthetic development adapter,
  or authorize a schema change/other security prerequisite.

Options:
- Add a small `ChunkTextFingerprint` port over exact chunk UTF-8 digest plus a visibly
  insecure development-only domain-separated adapter.
- Add a prerequisite security ticket for a broader release-safe keyed fingerprint.
- Make the column nullable through a forward migration (changes the documented model).

Approved outcome:
- Use a narrow Application port and synthetic adapter for M1, using the canonical
  ownership/source/profile/offset/order identity plus exact chunk UTF-8 bytes and a
  distinct versioned/domain-separated development
  token. Make no HMAC, encryption, confidentiality, or production-safety claim;
  production remains fail-closed.

Implementation impact:
- Defines chunk persistence and Bootstrap composition without a schema change.

### APPROVED DECISION — Compatibility/profile identity

Evidence:
- `index_generations` stores model ID, dimensions, chunking profile version,
  normalization profile version, and fixed `float32` dtype.
- It does not store separate chunk size/overlap columns.

Approval question (resolved):
- What exact stable profile strings encode algorithm, unit, size, overlap, and exact-text
  behavior, and which fields define a compatible generation?

Options:
- A canonical versioned profile string containing all chunk configuration plus a fixed
  exact-text normalization profile.
- A migration adding individual configuration columns.

Approved outcome:
- No migration; use a canonical unambiguous profile identity with a
  frozen versioned encoding of algorithm/unit/size/overlap and an `exact-text-v1`
  normalization profile. Compatibility is exact equality of both profiles plus resolved
  embedding model ID, dimensions, and `float32`.

Implementation impact:
- Defines generation construction, lookup/idempotency, active-generation reuse, and
  downstream compatibility tests.

### APPROVED DECISION — Retry treatment of existing generations

Evidence:
- The schema allows multiple `STAGING` generations but only one `ACTIVE` generation per
  version.
- Backlog requires idempotency but does not specify reuse, rebuild, or replacement.
- Chunk IDs are injected UUIDs; deterministic output does not imply deterministic IDs.

Approval question (resolved):
- What happens for matching staging, matching active, and incompatible generations?

Options:
- Reuse a matching staging generation and atomically replace/verify its complete chunk
  set; return an already compatible active result; create a new staging generation for
  incompatible configuration while leaving old non-active history explicit.
- Always fail when staging exists.
- Always create a new generation and later clean old staging rows.

Approved outcome:
- Reuse the one matching generation for the same
  workspace/version/job/profile/model identity; atomically rebuild its chunk set when
  incomplete, return the existing compatible active result without writes, and reject
  ambiguous multiple matches. Generated IDs need not be stable across a rolled-back
  calculation; persisted logical content/order and database effects must be idempotent.

Implementation impact:
- Defines repository queries, orchestration, cleanup/failure behavior, and repeat/restart
  tests.

### APPROVED DECISION — Activation ownership across EMBEDDING-001

Evidence:
- Canonical INDEX-001 says activation follows complete pipeline success.
- Architecture/data model place embedding before atomic version/index activation.
- Schema requires one embedding per chunk, and EMBEDDING-001 owns their generation and
  persistence.
- Activating from INDEX-001 immediately after chunk persistence would expose an
  incomplete index.

Approval question (resolved):
- Should INDEX-001 define and implement the finalization boundary but defer its invocation
  to EMBEDDING-001, or should the tickets be combined/reordered so activation is tested
  only after real embedding persistence exists?

Options:
- INDEX-001 creates `STAGING` plus chunks and implements an Application-owned guarded
  finalizer; EMBEDDING-001 invokes it after vector completeness.
- Move activation implementation and product completion entirely to EMBEDDING-001.
- Combine the tickets (larger scope).

Approved outcome:
- INDEX-001 owns the guarded finalization contract/repository operation;
  EMBEDDING-001 invokes it. INDEX-001 tests activation with persisted synthetic embedding
  rows solely as repository fixtures, never by implementing embedding behavior. Ticket
  status must distinguish INDEX contract completion from product-level active completion.

Implementation impact:
- Defines lifecycle/finalization implementation, the vertical-slice endpoint, completion
  wording, and Steps 3–4 below.

## Deterministic Chunking Model

The approved deterministic identity is:

- identical exact ordered page inputs plus identical approved configuration produce the
  same ordered chunk text, page/locator ownership, document/page ordinals, counts, and
  profile identity;
- no chunk crosses a page or locator;
- warning-page filtering is deterministic;
- no locale, platform newline conversion, random choice, tokenizer, or database row
  order affects boundaries;
- chunk IDs and generation IDs are injected technical identities and are not part of
  deterministic equality or logical output.

Deterministic output and idempotent persistence are separate contracts: the former is
proved by a pure Application chunker; the latter by repository/use-case repeat tests.

## Page / Source Boundary Model

Every chunk copies the source page's workspace/version/page ID, page number, extraction
method, and page-level source locator ID. `page_order` restarts at zero per page;
`document_order` increases monotonically across emitted chunks only. A skipped warning
page creates an ordinal gap in page numbers but no gap in `document_order`.

The current schema has no start/end offset columns. INDEX-001 can prove exact substring
content and ordering in memory/tests, but persisted citations resolve at page locator
granularity. Geometry and offsets must not be invented or hidden in unrelated fields.

## Index Generation Lifecycle

1. Validate active workspace, processing target/job stage, pages, configuration, and
   resolved embedding identity.
2. Calculate the complete deterministic chunk set in memory with cancellation checks.
3. In a short transaction, find/reuse or create the compatible `STAGING` generation and
   persist one complete ordered chunk set; commit no partially successful set.
4. Expose the generation/chunks to EMBEDDING-001 while remaining `STAGING`.
5. After compatible embeddings exist for every chunk, the guarded finalization
   transaction validates completeness, moves job to `READY` or
   `READY_WITH_WARNINGS`, moves version to `CANDIDATE_READY` or `CANDIDATE_WARNING` and
   then `ACTIVE`, and activates the generation. Any supported previous active version/
   generation is archived in the same transaction.

The finalizer is implemented by INDEX-001 but must not be invoked by chunking alone;
EMBEDDING-001 invokes it only after compatible embedding persistence.

## Retry / Idempotency Model

Idempotency is keyed by workspace, version, processing job, exact
chunking/normalization profiles, embedding model ID, dimensions, and dtype.

- Failure before persistence leaves no candidate/chunks.
- Failure during the candidate/chunk transaction rolls back the complete write.
- A committed compatible `STAGING` generation is reused and its exact complete chunk set
  is verified or rebuilt atomically.
- A compatible `ACTIVE` generation is returned without creating IDs or rows.
- Incompatible configuration creates no silent fallback or overwrite.
- Multiple ambiguous matching candidates fail closed with a sanitized persistence error.
- Restart repeats use persisted identity/state; no process-memory retry registry exists.

## Failure / Cancellation / Cleanup Model

- Reuse the existing cooperative synchronous cancellation style; add checks before page
  loading, between pages/chunks, before persistence, and before commit/finalization.
- Cancellation/failure before committed candidate persistence leaves no rows.
- A failed chunk transaction rolls back; it does not terminally activate or expose the
  generation.
- A previously committed matching staging generation remains inactive and is reused;
  its deterministic chunk set is verified or rebuilt atomically. Ambiguous or
  conflicting state fails closed, and incompatible state is not deleted implicitly.
- The old active version/generation, if any, remains untouched unless final activation
  commits successfully.
- Errors are typed and sanitized; they contain no page/chunk text, codec payload,
  fingerprints, vectors, model/provider diagnostics, SQL, paths, locators, or IDs.

## Persistence / Transaction Model

Chunk calculation and equality-token calculation occur outside SQLite transactions.
Page handoff is read in a short transaction and copied into immutable Application
values. Candidate lookup plus generation/chunk persistence is a separate immediate
transaction. Chunk text is UTF-8 encoded/decoded by Infrastructure through the existing
codec with deterministic chunk-owned context and a workspace key reference. The
repository writes exact schema-supported fields only; `token_count_estimate` remains
`NULL` and no offsets are fabricated.

Final activation is a separate short transaction after embedding persistence. It must
verify exact chunk count, one compatible embedding per chunk, generation/job/version/
workspace relationships, candidate states, and model/dimension/dtype identity before
any state becomes active. The partial unique indexes are the final database guard.

## Compatibility / Activation Model

Chunk-profile compatibility is exact equality of:

- workspace and document version;
- canonical chunking profile identity;
- exact-text normalization profile identity;
- the approved algorithm/unit/size/overlap, page/source, warning, exact-text, and
  equality-contract semantics encoded by the canonical chunk profile.

Full active compatibility additionally requires the resolved embedding `LocalModelId`,
embedding dimensions, `float32` vector dtype, and complete compatible embeddings.

Activation is never a Bootstrap operation and never follows chunk persistence alone.
The Application repository operation owns final validation and atomic state changes;
Infrastructure owns the SQL transaction; EMBEDDING-001 is the first legitimate caller
after it has persisted and validated every vector.

## Implementation Steps

## Step 1 — Define chunk contracts and deterministic page-aware algorithm

### Status

**COMPLETE**

Evidence: 36 focused tests passed; Ruff passed; mypy passed across 53 source files;
19 architecture tests passed; `git diff --check` passed.

### Purpose

Define the minimal Application-owned values/errors/ports and pure deterministic chunker.

### Architecture ownership

Application owns configuration, chunk values, chunking algorithm, candidate/handoff
Protocol, and sanitized errors. Domain types are reused unchanged.

### Existing pieces reused

`ProcessedPage`, typed IDs, `SourceLocator`, page/extraction states, resolved model
record, cancellation Protocol pattern, and codec/fingerprint conventions.

### Expected files

Modify:
- None.

Add:
- `src/lexlocal/application/ports/indexing.py`
- `src/lexlocal/application/indexing.py`

Tests:
- `tests/unit/application/ports/test_indexing.py`
- `tests/unit/application/test_indexing.py`

### Do

- Implement approved size/overlap validation, canonical profile identity, exact ordered
  chunk values, candidate/result/handoff values, errors, and repository Protocol.
- Require candidate reads to identify the exact workspace, document version, and index
  generation so persistence cannot infer or normalize version ownership.
- Calculate chunks page-by-page with exact provenance, explicit orders, injected IDs,
  time, inclusive start/exclusive end offsets, and approved warning handling.
- Keep output determinism independent of generated identities.

### Do not

- Add SQL, codec/provider implementation, embedding calls, activation, tokenizer, or
  settings/Bootstrap work.

### Failure / edge cases

Invalid configuration, no eligible chunks, malformed page/provenance, cancellation, and
ambiguous identity inputs fail with sanitized Application errors.

### Focused tests

Short page, exact boundary, boundary plus one, multiple windows, overlap, final short
window, Unicode/newlines, multiple pages/locators, warning pages, deterministic repeat,
invalid size/overlap, exact offset sequences and slice invariant, ID/time injection, and
Protocol type compatibility.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_indexing.py tests/unit/application/test_indexing.py -v
uv run ruff check src/lexlocal/application/ports/indexing.py src/lexlocal/application/indexing.py tests/unit/application/ports/test_indexing.py tests/unit/application/test_indexing.py
uv run mypy src
git diff --check
```

### Step completion condition

Approved configuration and identical page inputs produce the exact deterministic
ordered logical chunk set through SDK/SQLite-free Application contracts.

## Step 2 — Implement synthetic chunk fingerprint and SQLite candidate persistence

### Status

**COMPLETE**

Evidence: 46 focused migration/token/repository/UoW tests passed; Ruff passed; mypy
passed across 55 source files; 14 closest PROCESSING persistence/transaction regression
tests passed; `git diff --check` passed.

### Purpose

Apply the approved minimal forward migration and map the candidate generation and
complete chunk set to the resulting schema.

### Architecture ownership

Infrastructure security owns the explicit development token adapter. Infrastructure
persistence owns codec/fingerprint mapping and SQL without transaction finalization.
Application extends the shared UoW Protocol with `indexing` only when the real
`SQLiteIndexRepository` is introduced in this step.

### Existing pieces reused

Existing schema, `SensitivePayloadCodec`, workspace key/context values,
`SQLiteProcessingRepository` mapping patterns, migrations/SQLite fixtures, and Domain
generation validation.

### Expected files

Modify:
- `src/lexlocal/application/ports/unit_of_work.py`
- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py`
- `tests/integration/persistence/test_migration_pipeline.py`
- `tests/integration/persistence/test_sqlite_unit_of_work.py`

Add:
- `src/lexlocal/infrastructure/persistence/sql_migrations/003_chunk_source_offsets.sql`
- `src/lexlocal/infrastructure/security/insecure_development_indexing.py`
- `src/lexlocal/infrastructure/persistence/sqlite_index_repository.py`
- `tests/unit/infrastructure/security/test_insecure_development_indexing.py`
- `tests/integration/persistence/test_sqlite_index_repository.py`

Tests:
- Existing UoW tests above.

### Do

- Add only the two approved constrained offset columns in migration 003; preserve every
  existing relationship, key, constraint, index, and legitimate empty pre-003 state.
- Persist/reconstruct every schema-supported generation/chunk field faithfully,
  including approved start/end code-point offsets.
- Encode exact chunk UTF-8 bytes with deterministic chunk-owned codec metadata.
- Store approved workspace-scoped token, explicit order/count, `NATIVE`, and null token
  estimate.
- Enforce strict workspace/version/job/generation/page/locator/model relationships,
  staging-only writes, complete-set atomicity, and sanitized errors.

### Do not

- Commit/rollback, generate identities/time, edit an applied migration, add schema work
  beyond an approved offset migration, calculate vectors, or claim development token/
  codec security.

### Failure / edge cases

Corrupt payload/mapping, cross-workspace graph, duplicate order, missing page/locator,
wrong candidate state, and partial insertion fail without a successful partial set.

### Focused tests

Migration discovery/order/idempotency, unchanged existing constraints/indexes/FKs,
fail-closed unexpected legacy chunks, exact codec and source-offset round trip,
`chunk.text == page.text[start:end]`, complete candidate/chunk mapping, profiles/model
metadata, orders/provenance, warning skip, Unicode, cross-workspace precedence,
corruption, rollback, sanitized messages, risk labels, and no repository commit/rollback.

### Focused validation

```bash
uv run pytest tests/unit/infrastructure/security/test_insecure_development_indexing.py tests/integration/persistence/test_migration_pipeline.py tests/integration/persistence/test_sqlite_index_repository.py tests/integration/persistence/test_sqlite_unit_of_work.py -v
uv run ruff check src/lexlocal/infrastructure/security/insecure_development_indexing.py src/lexlocal/infrastructure/persistence/sqlite_index_repository.py src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py tests/unit/infrastructure/security/test_insecure_development_indexing.py tests/integration/persistence/test_migration_pipeline.py tests/integration/persistence/test_sqlite_index_repository.py tests/integration/persistence/test_sqlite_unit_of_work.py
uv run mypy src
git diff --check
```

### Step completion condition

One complete deterministic chunk set round-trips under a compatible staging generation
through the existing schema and approved development security boundaries.

## Step 3 — Implement idempotent orchestration and embedding handoff

### Status

**COMPLETE**

Evidence: 53 focused Application orchestration/transaction/SQLite repository tests
passed; Ruff passed; mypy passed across 55 source files; 19 architecture tests passed;
`git diff --check` passed.

Prerequisite contract correction: state-neutral generation discovery now exposes exact
workspace/version/job-scoped persisted metadata for Application compatibility decisions;
one existing STAGING generation can have its complete chunk set atomically replaced;
and explicit immutable results distinguish a STAGING embedding handoff from reuse of an
ACTIVE index. The Step 3 orchestration now uses these contracts.

### Purpose

Compose page loading, in-memory calculation, candidate persistence, repeat behavior, and
the ordered downstream handoff without embedding or activation.

### Architecture ownership

Application owns orchestration/transactions; repositories perform state-aware reads and
writes; no business rule enters Bootstrap.

### Existing pieces reused

`ActiveWorkspaceScope`, processing handoff, UoW, resolved model record, injected
factories/clock, and cooperative cancellation.

### Expected files

Modify:
- `src/lexlocal/application/indexing.py`
- `src/lexlocal/application/ports/indexing.py`

Add:
- `tests/integration/persistence/test_indexing_transactions.py`

Tests:
- `tests/unit/application/test_indexing.py`
- `tests/integration/persistence/test_sqlite_index_repository.py`

### Do

- Resolve workspace only from active scope and model identity from the injected SDK-free
  record.
- Use separate short read and write UoWs around in-memory chunking.
- Implement approved matching-staging, already-active, incompatible, interrupted, and
  ambiguous-candidate behavior.
- Expose exact ordered staging chunks for EMBEDDING-001.

### Do not

- Invoke embedding inference, write embeddings, activate candidates, or add a retry
  service/worker.

### Failure / edge cases

Scope substitution, stale job/version stage, empty eligible output, read/write/commit
failure, cancellation at each meaningful checkpoint, and repeat after restart.

### Focused tests

Ordering, UoW boundaries, rollback, repeat identical run, interrupted run, existing
staging, compatible active return, incompatible/ambiguous generations, no duplicate
chunks/generations, and exact embedding handoff.

### Focused validation

```bash
uv run pytest tests/unit/application/test_indexing.py tests/integration/persistence/test_indexing_transactions.py tests/integration/persistence/test_sqlite_index_repository.py -v
uv run ruff check src/lexlocal/application/ports/indexing.py src/lexlocal/application/indexing.py tests/unit/application/test_indexing.py tests/integration/persistence/test_indexing_transactions.py tests/integration/persistence/test_sqlite_index_repository.py
uv run mypy src
git diff --check
```

### Step completion condition

Repeated execution yields one persisted compatible candidate and one complete ordered
chunk set, and EMBEDDING-001 can consume it through Application contracts.

## Step 4 — Implement and verify guarded final activation boundary

### Status

**COMPLETE**

Evidence: 42 focused Application/finalization integration tests passed; 51 nearby
indexing port/orchestration/SQLite repository regression tests passed; Ruff passed;
mypy passed across 55 source files; 19 architecture tests passed; `git diff --check`
passed.

### Purpose

Implement the atomic finalizer that can activate only a fully embedded compatible
candidate.

### Architecture ownership

Application owns the finalization command/invariants; Infrastructure owns completeness
queries and atomic SQL state changes. EMBEDDING-001 is the intended caller.

### Existing pieces reused

Domain activation transitions, schema embeddings/chunks relationships, partial unique
active indexes, processing lifecycle, and UoW transaction conventions.

### Expected files

Modify:
- `src/lexlocal/application/ports/indexing.py`
- `src/lexlocal/application/indexing.py`
- `src/lexlocal/infrastructure/persistence/sqlite_index_repository.py`

Tests:
- `tests/unit/application/test_indexing.py`
- `tests/integration/persistence/test_index_activation.py`

### Do

- Require exact chunk/embedding completeness and compatibility before transitions.
- Atomically update processing job, candidate version, candidate generation, and any
  supported prior active version/generation.
- Preserve warning outcome from skipped warning pages.

### Do not

- Generate fake embeddings, call the model, activate after chunks alone, or implement
  replacement lifecycle beyond existing supported states.

### Failure / edge cases

Missing/extra/mismatched vectors, wrong model/dimensions/dtype, stale lifecycle,
concurrent activation, commit failure, cancellation before transaction, and previous
active preservation.

### Focused tests

Activation with complete synthetic embedding rows, every incomplete/incompatible case,
exactly one active generation/version, atomic rollback, previous-active behavior, and
READY versus READY_WITH_WARNINGS terminal state.

### Focused validation

```bash
uv run pytest tests/unit/application/test_indexing.py tests/integration/persistence/test_index_activation.py -v
uv run ruff check src/lexlocal/application/ports/indexing.py src/lexlocal/application/indexing.py src/lexlocal/infrastructure/persistence/sqlite_index_repository.py tests/unit/application/test_indexing.py tests/integration/persistence/test_index_activation.py
uv run mypy src
git diff --check
```

### Step completion condition

The finalizer cannot activate incomplete data and atomically produces exactly one
compatible active index only when downstream embedding completeness is proven.

## Step 5 — Compose and verify the synthetic processing-to-index slice

### Status

**COMPLETE**

Evidence: 13 focused Bootstrap and real processing-to-index vertical-slice tests
passed; 51 affected settings/security/processing regression tests passed; Ruff passed;
mypy passed across 56 source files; 19 architecture tests passed; `git diff --check`
passed.

### Purpose

Wire existing development/test components through candidate chunk persistence and expose
the embedding handoff, while preserving production rejection.

### Architecture ownership

Bootstrap composes only; Application retains chunking/lifecycle rules and Infrastructure
retains codec/token/SQLite behavior.

### Existing pieces reused

Processing composition, local-model composition/status, security providers, SQLite UoW,
active scope, injected ID/time patterns, and production fail-closed checks.

### Expected files

Modify:
- `src/lexlocal/bootstrap/settings.py`
- `tests/unit/bootstrap/test_settings.py`

Add:
- `src/lexlocal/bootstrap/indexing.py`
- `tests/unit/bootstrap/test_indexing.py`
- `tests/integration/test_indexing_vertical_slice.py`

Tests:
- Existing processing/security architecture suites as affected.

### Do

- Compose approved config, exact embedding status metadata, codec/token adapter, UoW,
  active scope, cancellation, IDs, and clock.
- Prove synthetic processing pages become one staging generation/ordered chunks and an
  SDK-free embedding handoff.
- Prove production cannot compose the insecure providers.

### Do not

- Call embeddings, add provider selection/DI, activate incomplete data, or add UI/workers.

### Failure / edge cases

Invalid config, missing/incompatible model metadata, storage/security production mode,
commit failure, cancellation, repeat run, and different workspace/version scope.

### Focused tests

End-to-end synthetic processed pages to candidate chunks, exact provenance/text,
deterministic factories/time, repeat idempotency, failure rollback, and architecture-
clean downstream handoff.

### Focused validation

```bash
uv run pytest tests/unit/bootstrap/test_indexing.py tests/integration/test_indexing_vertical_slice.py -v
uv run ruff check src/lexlocal/bootstrap/indexing.py tests/unit/bootstrap/test_indexing.py tests/integration/test_indexing_vertical_slice.py
uv run mypy src
git diff --check
```

### Step completion condition

The real synthetic PROCESSING-001 output reaches one compatible staging generation and
ordered embedding handoff without production fallback or downstream implementation.

## Step 6 — Run quality, architecture, security, and strict-scope gates

### Status

**COMPLETE**

### Purpose

Run the complete INDEX-001 evidence matrix and audit the ticket diff.

### Architecture ownership

Validation only; correct only genuine owning defects from earlier steps.

### Existing pieces reused

Focused tests, architecture suite, PROCESSING-001 regressions, project Ruff/mypy, and
Git diff checks.

### Expected files

Modify:
- `docs/INDEX-001.md` only after every gate passes

Add:
- None

Tests:
- None unless a genuine earlier defect lacks proof.

### Do

- Run focused INDEX, architecture, full pytest, Ruff, mypy, diff/whitespace, strict
  scope, security, determinism, lifecycle, retry, and downstream-boundary audits.
- Record actual counts/results and audit every Final DoD item against evidence.

### Do not

- Add features, weaken checks, implement EMBEDDING-001, or perform Git staging.

### Failure / edge cases

Classify failures as ticket-owned or pre-existing and make only the smallest authorized
owning correction.

### Focused tests

The complete Final Validation Matrix below.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_indexing.py tests/unit/application/test_indexing.py tests/unit/infrastructure/security/test_insecure_development_indexing.py tests/integration/persistence/test_sqlite_index_repository.py tests/integration/persistence/test_indexing_transactions.py tests/integration/persistence/test_index_activation.py tests/unit/bootstrap/test_indexing.py tests/integration/test_indexing_vertical_slice.py -v
uv run pytest tests/architecture -v
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```

### Actual validation evidence

- Focused INDEX suite: 109 passed.
- Architecture suite: 19 passed.
- Full suite: 1321 passed, 1 unrelated opt-in Foundry Local smoke test skipped.
- Ruff: all checks passed.
- mypy: no issues found in 56 source files.
- `git diff --check`: passed.
- PROCESSING-001 and shared settings, security, persistence, and Unit of Work
  regressions passed as part of the full suite.
- Determinism, boundary, persistence, idempotency, activation, lifecycle, downstream,
  security, architecture, and strict-scope audits are clean. Every changed or untracked
  path is INDEX-001-owned; no new dependency or schema change beyond migration 003 is
  present.

### Step completion condition

All approved INDEX-001 behavior, gates, scope/security checks, regressions, and technical
DoD items pass with actual evidence.

## Step 7 — Audit Git state for human staged-diff review

### Status

**COMPLETE**

Evidence: 21 INDEX-001-owned paths are staged; no unrelated, ambiguous, unstaged, or
untracked path remains; the complete cached diff is scope/security clean; and
`git diff --cached --check` passed. Explicit human approval remains open.

### Purpose

Stage only the completed INDEX-001 change set and stop for explicit human review.

### Architecture ownership

Git/diff audit only.

### Existing pieces reused

Step 6 evidence and repository Git conventions.

### Expected files

Modify:
- `docs/INDEX-001.md` only to record a clean staged audit

Add:
- None

Tests:
- None

### Do

- Classify every tracked/untracked file, stage only proven ticket-owned paths, inspect
  every staged hunk, and run cached diff checks.
- Leave final human-review approval open.

### Do not

- Commit, push, create a PR, merge, switch branches, or claim human approval.

### Failure / edge cases

Leave unrelated/ambiguous files unstaged; reopen Step 6 if a technical defect appears.

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

### Step completion condition

The exact clean ticket diff is staged and audited, with explicit human review the only
remaining delivery gate.

## Final Validation Matrix

| Area | Required evidence |
|---|---|
| Determinism | Same exact ordered pages and config produce identical ordered boundaries, text, provenance, counts, and profile metadata; generated technical IDs are tested separately from logical output. |
| Boundaries | One page/locator per chunk; short page, exact boundary, boundary + 1, multiple chunks, overlap, final short chunk, Unicode/newlines, mixed warning/empty behavior, no empty chunks. |
| Configuration | Approved defaults/unit, positive size, overlap range, canonical profile identity, invalid types/bools/bounds, and exact compatibility comparison. |
| Persistence | One staging generation, complete ordered chunks, strict workspace/version/job/generation/page/locator/model relationships, exact codec round trip, required equality token, exact approved source-offset round trip, and null token estimate. |
| Retry/idempotency | Identical repeat, pre-write failure, mid-transaction failure, committed staging, compatible active, incompatible config, ambiguous candidates, process restart, no duplicate chunk set or active generation. |
| Activation | Never after chunks alone; complete compatible embedding rows required; one active version/generation; atomic rollback; concurrency/unique-index failure; prior active preserved on failure. |
| Lifecycle | Job remains PROCESSING/CHUNKING while staging; final READY/READY_WITH_WARNINGS and version/generation transitions only at approved completion; cancellation/failure never yields false success. |
| Downstream | EMBEDDING-001 receives exact ordered candidate chunks and compatibility metadata through Application-owned contracts without SQL, Qt, storage, UI, or chunker internals. |
| Architecture | No SQLite/concrete Infrastructure in Application, no chunking rules in Bootstrap, Infrastructure implements Application ports, Domain stays independent. |
| Security | Synthetic anonymous fixtures only; chunk text through codec; development token/codec warnings; production fail-closed; sanitized errors/logs with no text/payload/token/vector/path/SQL/ID leakage. |
| Regression | PROCESSING-001 handoff and all existing processing/architecture behavior remain green. |
| Strict scope | No embeddings, retrieval/RAG/UI/OCR/worker/generic retry/DI/tokenizer/new dependency/production crypto, migration beyond an approved offset correction, or unrelated refactor. |
| Quality | Focused suites, architecture, full pytest, Ruff, mypy, diff checks, and full scope audit pass with actual results. |

## Final Definition of Done

- [x] All human decisions are explicitly approved and frozen.
- [x] Chunk size/overlap are configurable in the approved unit with deterministic
  validation and canonical compatibility identity.
- [x] Same page input/config produces the exact same ordered logical chunk output.
- [x] No chunk crosses a page or source locator; provenance and explicit orders persist.
- [x] Every persisted chunk round-trips inclusive start/exclusive end Unicode code-point
  offsets and equals the exact owning page slice at that range.
- [x] Approved warning-page and exact-text rules are implemented without meaningless
  empty chunks or silent normalization.
- [x] Chunk text and required equality material use approved Application/security
  boundaries with explicit development-only risk labeling and production fail-closed.
- [x] Chunks persist only under a compatible `STAGING` generation as one complete set.
- [x] Retry/restart behavior is idempotent and cannot duplicate chunk sets or active
  generations.
- [x] EMBEDDING-001 receives ordered candidate chunks and compatibility metadata through
  an Application-owned contract.
- [x] Activation cannot occur before every compatible embedding exists.
- [x] Finalization atomically produces exactly one compatible active index generation and
  active document version, with correct job terminal state.
- [x] Failure/cancellation/activation rollback never exposes a partial active index and
  preserves any prior active generation.
- [x] Application remains independent of SQLite, Qt, concrete Infrastructure, storage,
  paths, UI, and embedding implementation.
- [x] No migration or dependency is added without newly approved evidence.
- [x] PROCESSING-001 regressions and all focused/architecture/full quality gates pass.
- [x] Strict scope/security/overengineering audit is clean and fixtures are anonymous
  synthetic data.
- [x] Exact ticket files are staged and cached diff checks pass.
- [ ] Final staged diff is scope-clean and explicitly human-reviewed. *(Human only)*

## Current Position

- PROCESSING-001 already provides exact ordered pages, READY/WARNING classification,
  NATIVE extraction method, page-level locators, strict workspace/version isolation,
  and a job at `PROCESSING`/`CHUNKING` with a candidate processing version.
- All eight decisions are approved. Step 1 is complete: Application-owned contracts,
  deterministic page-aware chunking, exact offsets/provenance, warning-page exclusion,
  injected identities/time, cancellation, sanitized failures, and exact workspace/
  version/generation candidate-read ownership are implemented and validated.
- Migration 003, the synthetic chunk equality adapter, staging candidate/chunk SQLite
  persistence, exact codec/source-slice reconstruction, and the real UoW indexing
  repository are implemented and validated. Step 3 provides idempotent Application
  orchestration, separate read/write UoWs, compatible ACTIVE/STAGING reuse, and the exact
  ordered embedding handoff. Step 4 provides the guarded finalizer, complete compatible
  embedding gate, atomic READY/READY_WITH_WARNINGS version/job/generation transitions,
  and supported previous-ACTIVE preservation. Step 5 now composes the approved chunk
  configuration, ready SDK-free embedding model metadata, development codec/equality
  token, SQLite UoW, scope, cancellation, identities, and clock. The real synthetic
  PROCESSING output reaches one idempotent STAGING generation and exact ordered embedding
  handoff without embedding or activation. Step 6 quality, architecture, security,
  regression, and strict-scope gates are complete: 109 focused tests and 19 architecture
  tests passed; the full suite passed 1321 tests with one unrelated opt-in Foundry Local
  smoke test skipped; Ruff, mypy across 56 source files, and diff checks passed.
- No human or repository blocker remains. Schema impact is the single approved forward
  migration; new dependency impact is none.
- The technical Final Definition of Done and repository staging audit are complete
  (18 of 18 Codex-verifiable items). The exact 21-file INDEX-001 change set is staged;
  cached diff and scope/security checks passed. Explicit human review remains open.
- Next action: perform the explicit human staged-diff review. Do not commit, push, create
  a PR, or merge before that approval.
