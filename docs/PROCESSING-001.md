# PROCESSING-001 — Extract Page-Aware Digital PDF Text

## Status

**READY FOR HUMAN STAGED-DIFF REVIEW**

Steps 1–6 and every technical Definition of Done item are complete. The exact ticket
diff is staged and audited; explicit human staged-diff review remains open.

## Purpose

Extract exact native text from each page of one already-ingested anonymous synthetic
digital PDF, preserve page-level provenance, and persist the result so INDEX-001 can
consume it without Qt, SQLite, storage-locator, or UI knowledge.

This ticket is the native-text stage of the existing processing attempt. It does not
make a document retrieval-ready and does not create or activate an index generation.

## Completion Condition

PROCESSING-001 is complete when an INGESTION-001 result can be processed through the
real development/test composition and:

- exact per-page native text is stored and can be read through an Application-owned
  chunking handoff contract in one-based page order;
- each page retains `NATIVE` extraction provenance and a workspace/version/page-bound
  page-level `SourceLocator`;
- the processing job reaches the explicit `CHUNKING` handoff stage while remaining
  `PROCESSING`, and the version remains `CANDIDATE_PROCESSING` for INDEX-001;
- malformed, unreadable, protected, unusable, cancelled, and persistence-failure paths
  never appear successful and leave no partial committed page set or active index;
- Application remains independent of Qt, SQLite, concrete Infrastructure, physical
  paths, and UI types.

## Scope

- One already-registered synthetic PDF represented by INGESTION-001's safe result and
  opaque `ControlledSourceRef`.
- Selected-workspace verification through `ActiveWorkspaceScope`.
- Exact controlled-source byte retrieval through `ControlledSourceStorage.read`.
- Native page-text extraction through an Application-owned port and a Qt Infrastructure
  adapter.
- One-based page identity, exact text, `NATIVE` method, page state, and page-level
  source locator metadata.
- Processing-job start, progress/handoff, failure, and cancellation persistence.
- Atomic insertion of the complete page/locator set after extraction succeeds.
- Provider-independent page-text encoding through `SensitivePayloadCodec` before
  SQLite persistence, using deterministic workspace/page context.
- A persistence-independent read contract supplying exact page text and provenance to
  INDEX-001.
- Cooperative cancellation checkpoints and sanitized typed failures.
- Anonymous synthetic unit, integration, architecture, and vertical-slice coverage.

## Non-Goals

- OCR, page rendering for OCR, image preprocessing, or an OCR fallback.
- Text normalization, chunking, chunk persistence, embeddings, vector search,
  retrieval, RAG, answers, citations, or UI source viewing.
- Creating, failing, activating, or otherwise managing `IndexGeneration` rows.
- Moving the version to `CANDIDATE_READY`/`CANDIDATE_WARNING` or the processing job to
  `READY`/`READY_WITH_WARNINGS`; those are whole-pipeline outcomes owned downstream.
- Background workers, task queues, retry-attempt creation, startup recovery, progress
  UI, file pickers, or original-path access.
- Production encryption, key generation/lifecycle, release-safe storage, or weakening
  the existing production fail-closed composition.
- Generic PDF, processing, repository, cancellation, DI, provider, or event frameworks.
- Schema redesign, modification of applied migrations, new dependencies, or unrelated
  refactoring.
- Real documents, legal/customer data, secrets, credentials, raw keys, or real `.env`
  content.

## Pre-Implementation Repository Baseline

This section records the repository state observed before Step 1 began. It is retained
as historical planning evidence and does not describe the current implementation.

- `ImportSyntheticPdf` commits one `ACTIVE` logical document, one
  `CANDIDATE_PROCESSING` document version, one `ACTIVE` stored-blob row, and one
  `QUEUED` processing job at stage `VALIDATING`.
- Its immutable `IngestionResult` exposes `DocumentId`, `DocumentVersionId`,
  `ProcessingJobId`, the workspace-bound opaque `ControlledSourceRef`, and safe PDF
  metadata including page count. It exposes neither source bytes nor a path.
- `ActiveWorkspaceScope.require_workspace_id()` is the sole current Application source
  of selected workspace scope.
- `ControlledSourceStorage.read(workspace_id, reference)` retrieves exact controlled
  bytes and enforces workspace/reference ownership. The M1 development implementation
  is process-memory-only, so this vertical slice has a process-lifetime boundary and
  no restart reconstruction guarantee.
- `PdfInspector` and `QtPdfInspector` deliberately validate container support only.
  Their contracts and documentation explicitly exclude text extraction.
- Installed PySide6 `QPdfDocument` exposes native page-text extraction (`getAllText`),
  so no PDF dependency is missing.
- Domain already provides typed `DocumentPageId`, `SourceLocatorId`, `PageNumber`,
  `SourceLocator`, `SourceLocatorKind`, `ProcessingJob`, `ProcessingJobState`,
  `DocumentVersion`, and `DocumentVersionState`.
- `PageNumber` is one-based. A `SourceLocatorKind.PAGE` locator is explicitly valid
  without geometry; the viewer must not invent geometry.
- Processing jobs support `QUEUED -> PROCESSING`, then terminal
  `READY`/`READY_WITH_WARNINGS`/`FAILED`/`CANCELLED`. Document candidate versions
  support failure and cancellation states.
- Migration 001 already creates `document_pages`, `source_locators`,
  `document_processing_jobs`, and `index_generations`, with composite workspace
  foreign keys and page-number uniqueness. No PROCESSING-001 schema addition is
  required.
- `document_pages` already stores page state, `NATIVE`/`OCR` method, encoded text,
  counts, warnings, and timestamps. `source_locators` already stores page ownership,
  locator kind/version, and optional geometry.
- `index_generations` has explicit `STAGING` and `ACTIVE` states and a unique active
  generation rule. INGESTION-001 creates no index row, and PROCESSING-001 need not
  create one.
- `SQLiteUnitOfWork` owns one connection and transaction and currently exposes
  workspace, local-model, and ingestion repositories. A processing repository is not
  implemented.
- Architecture tests already forbid Domain outward dependencies and Application
  dependencies on concrete Infrastructure, Qt-adjacent layers, SQLite imports, raw SQL
  writes, and direct filesystem writes.
- The planning audit ran on `main` with a clean worktree before this plan file was
  created. Implementation subsequently moved to the approved
  `feature/processing-001-page-text` branch.

## Upstream Contract — INGESTION-001

The committed relationship is:

```text
LogicalDocument (ACTIVE)
  -> DocumentVersion (CANDIDATE_PROCESSING, source_blob_id)
     -> stored_blobs (ACTIVE, opaque ControlledSourceRef.value representation)
     -> ProcessingJob (QUEUED, stage VALIDATING, attempt 1)
```

PROCESSING-001 receives the committed `IngestionResult`. It obtains the selected
`WorkspaceId` again from `ActiveWorkspaceScope`, requires that it matches the opaque
reference, and uses `ControlledSourceStorage.read` with that workspace/reference pair.
It never accepts or reconstructs an original external path.

The same controlled-storage instance used by ingestion must be injected into processing
composition. This is required because the approved development provider stores bytes in
process memory. The result's document/version/job IDs identify the exact committed graph;
the processing repository must verify those IDs, workspace ownership, initial states, and
expected page count before changing state.

## Downstream Contract — INDEX-001

INDEX-001 receives an Application-owned sequence of immutable processed-page values,
ordered by one-based `PageNumber`. Each value contains:

- `DocumentPageId`;
- owning `WorkspaceId` and `DocumentVersionId`;
- one-based `PageNumber`;
- exact decoded page text, without trimming, case-folding, normalization, or newline
  rewriting;
- page state determined by the approved empty-page policy;
- extraction method `NATIVE`;
- the matching page-level `SourceLocator`.

The read contract must reject workspace/version substitution and corrupt or incomplete
page/locator mappings. It returns no encoded database payload, codec metadata, SQL row,
Qt object, physical path, or storage reference.

On successful PROCESSING-001 handoff, the job remains `PROCESSING` with stage `CHUNKING`
and the version remains `CANDIDATE_PROCESSING`. INDEX-001 owns deterministic chunking,
index-generation creation/staging, whole-pipeline terminal job/version transitions, and
atomic index activation.

## Architecture Mapping

| Layer | Ownership |
|---|---|
| Domain | Reuse typed IDs, page number/source locator validity, document/version relationships, and processing state transitions. No duplicate page/locator identity model. |
| Application ports | Own SDK-free native extraction values/Protocol, processing request/result/errors, cancellation check, page persistence/handoff repository contract, and the minimal UoW extension. |
| Application use case | Resolve active scope, retrieve exact bytes through storage, enforce ordering and page-count/result invariants, check cancellation, assess the approved usability rule, create typed page/locator values with injected IDs/time, and coordinate short UoW transactions. |
| Infrastructure PDF | Own `QBuffer`, `QPdfDocument`, `QPdfSelection`, zero-based Qt page access, status/error translation, and conversion to exact SDK-free page values. |
| Infrastructure persistence | Own SQL, UTC millisecond `Z` serialization, page-text encoding/decoding, row mapping, conditional job/version updates, page/locator insertion, and integrity-error translation. |
| Bootstrap | Select only approved development/test providers, preserve production rejection, share active scope/storage, inject codec/UoW/ID/clock/cancellation dependencies, and contain no processing rules. |

The existing container-only `PdfInspector` remains unchanged. A separate extraction port
is required because inspection and page extraction have different outputs and failure
timing. A sibling `QtNativePdfTextExtractor` is the smallest repository-consistent
adapter: it can reuse Qt internally without widening `PdfInspector` or allowing Qt/native
objects into Application.

## Existing Components Reused

- `IngestionResult`, `PdfInspectionResult`, and the exact initial ingestion graph.
- `ActiveWorkspaceScope` as the sole selected-workspace source.
- `ControlledSourceRef` and `ControlledSourceStorage.read`.
- `SensitivePayloadCodec`, `SensitivePayloadContext`, `WorkspaceKeyReference`, and
  `EncodedSensitivePayload` for page-text protection boundaries.
- `DocumentPageId`, `SourceLocatorId`, `WorkspaceId`, `DocumentVersionId`, and
  `ProcessingJobId`.
- `PageNumber`, `SourceLocator`, and `SourceLocatorKind.PAGE`.
- `ProcessingJob`/`ProcessingJobState` and
  `DocumentVersion`/`DocumentVersionState` transition rules.
- Existing `UnitOfWork`/`SQLiteUnitOfWork`, connection factory, migration runner,
  timestamp conventions, repository sanitization patterns, and migrated `tmp_path`
  integration fixtures.
- Existing `QtPdfInspector` status/error translation patterns and Qt-owned in-memory
  synthetic PDF fixtures.
- Existing security-provider production rejection and development-only provider risk
  boundaries.
- Existing architecture AST/import guards.

## Initial Gaps Found — Resolved

The planning audit originally found the gaps below. Steps 1–4 resolved every
ticket-owned implementation gap; the final index observation remains an intentionally
excluded, unmeasured optimization rather than missing PROCESSING-001 work.

- No Application-owned native page-text extraction contract or processing use case
  exists.
- No Application processing error vocabulary or cancellation-check contract exists.
- No immutable Application persistence/handoff value combines exact page text with
  typed page and locator provenance.
- No processing repository exists, and `UnitOfWork` does not expose one.
- No SQLite mapping currently inserts/reads `document_pages` and `source_locators` or
  updates processing/version states for this stage.
- No Bootstrap composition shares the ingestion controlled-storage lifetime with a
  processing use case.
- No focused native extraction, processing transaction, cancellation, or end-to-end
  processing tests exist.
- The schema has no dedicated `source_locators(document_version_id, page_number)`
  index although the data-model prose shows one. The existing page index, uniqueness,
  primary/composite keys, and M1 access pattern are sufficient; adding a performance
  index without measured need is outside this ticket.

## Frozen / Proven Decisions

1. Input is an already committed `IngestionResult`; callers do not supply a separate
   workspace or path.
2. The active `WorkspaceId` is resolved from `ActiveWorkspaceScope` and must match the
   result/reference and every persisted relationship.
3. Exact source bytes are read only through `ControlledSourceStorage.read`; the original
   external path is neither required nor available.
4. `PdfInspector` remains container-only. Native extraction uses a separate
   Application-owned port and sibling Qt Infrastructure adapter.
5. Qt page indices are converted at the adapter boundary to existing one-based
   `PageNumber` values. Application never observes a zero-based Qt index.
6. Exact extracted text is preserved byte-for-byte after UTF-8 encoding at the
   persistence boundary; usability assessment must not mutate the stored/returned text.
7. M1 extraction method is `NATIVE`. OCR and OCR locators are not fallback options.
8. Each persisted page gets an Application-generated `DocumentPageId` and one
   Application-generated `SourceLocatorId`; the locator is `PAGE`, uses the same
   workspace/version/page/page number, has no invented geometry, and maps to locator
   version 1.
9. Page text is sensitive. Infrastructure encodes exact UTF-8 bytes with the configured
   `SensitivePayloadCodec`, deterministic context owned by the page ID and purpose
   `document-page-text`, schema version 1, and a workspace-bound key reference. SQLite
   stores the provider-produced payload bytes, and decoding reconstructs and verifies
   the same context. The existing `InsecureDevelopmentOnlyPayloadCodec` may produce
   plaintext payload bytes for anonymous synthetic M1 fixtures. That provider and its
   persisted payloads are explicitly **DEVELOPMENT ONLY**, **SYNTHETIC FIXTURES ONLY**,
   **NOT RELEASE SAFE**, and **NOT FOR REAL USER DOCUMENTS**. PROCESSING-001 makes no
   encryption, confidentiality, or plaintext-at-rest protection claim for it.
   Production/release composition continues to reject it fail-closed. Real at-rest
   protection belongs to a future approved secure provider; this ticket adds no fake
   obfuscation/encryption, replacement development codec, production crypto, keys,
   dependency, or schema change.
10. `normalized_text_fingerprint` remains `NULL`; PROCESSING-001 has no approved keyed
    normalized-text equality need. Geometry and warning metadata remain `NULL`; the
    `WARNING` page state is sufficient for the frozen M1 empty-page classification.
11. No index-generation row is created. Therefore processing failure/cancellation
    cannot activate an index generation.
12. Successful extraction is a stage handoff, not whole-pipeline completion: job
    `PROCESSING`/stage `CHUNKING`, version `CANDIDATE_PROCESSING`.
13. Native extraction cannot be placed inside a SQLite transaction. Complete page
    values are accumulated in memory and validated before their single atomic insert.
14. Repositories never open a second connection, generate IDs/timestamps, commit,
    rollback, call Qt, or access controlled storage.
15. Cancellation is cooperative and synchronous for M1. It adds no worker/executor or
    retry framework.
16. All errors are sanitized and suppress native/provider/database exception chains.
17. No forward migration and no new dependency are justified by current repository
    evidence.
18. The approved M1 native-text usability and mixed empty-page policy is:
    - a page is usable if and only if its exact extracted native text contains at least
      one non-whitespace Unicode character;
    - classification never trims, normalizes, rewrites, or otherwise modifies the exact
      extracted text;
    - an empty or whitespace-only page in a mixed document is persisted with `WARNING`
      state, its exact text, `NATIVE` method, and its page-level `SourceLocator`;
    - a mixed document continues when at least one page is usable;
    - a document with zero usable native-text pages fails with
      `UnusableNativeText`;
    - no OCR fallback is permitted;
    - PROCESSING-001 preserves every page result and its provenance but performs no
      chunking. INDEX-001 owns the later decision about consuming `WARNING`/unusable
      pages under this handoff policy.

## Human Decisions Required

None. Option 1 was explicitly approved and is now frozen in
[Frozen / Proven Decisions](#frozen--proven-decisions).

## Failure / Cancellation / Cleanup Model

Application owns a small sanitized processing error vocabulary:

- `ProcessingError`: base processing failure;
- `ProcessingSourceError`: controlled source unavailable, invalid, or ownership-mismatched;
- `NativePdfExtractionError`: malformed/unreadable/protected/unsupported PDF or native
  extraction failure;
- `UnusableNativeText`: approved M1 usability rule failed and OCR is unavailable;
- `ProcessingCancelled`: cooperative cancellation was observed;
- `ProcessingPersistenceError`: graph/state/encoding/transaction mapping failed.

No error message or exception chain may contain PDF bytes, exact/partial text,
`ControlledSourceRef.value`, filenames, filesystem/database paths, SQL, encoded payloads,
workspace/document/version/job/page/locator values, Qt diagnostics, or native object
representations.

Cancellation checkpoints are required:

1. before starting the queued job;
2. after the start transition and before controlled-source read;
3. after source read and before opening/extracting the PDF;
4. between yielded pages;
5. after extraction/usability validation and before opening the page-write transaction;
6. immediately before commit.

Cancellation before start persists `QUEUED -> CANCELLED` and
`CANDIDATE_PROCESSING -> CANDIDATE_CANCELLED`. Cancellation after start persists
`PROCESSING -> CANCELLED` and the same version cancellation state. Since page rows are
not inserted until the complete set is ready, pre-write cancellation has no derived rows
to clean. Cancellation or a write/commit failure inside the final transaction rolls back
the complete page/locator set. A failure while recording the terminal cancellation or
failure state is reported as `ProcessingPersistenceError`; it must not be reported as a
successful or cleanly persisted cancellation.

Malformed/unreadable/protected input at this stage can occur only through direct adapter
testing or controlled-source corruption/substitution because INGESTION-001 rejects those
inputs first. The processing boundary still translates them safely and marks the attempt
failed rather than trusting upstream history.

## Persistence / Transaction Model

Qt/PDF work and controlled-source reads occur outside SQLite transactions. The
Application use case coordinates short transactions through the existing UoW:

1. Resolve the selected workspace and validate the INGESTION-001 result/reference.
2. In a short transaction, verify the exact committed document/version/job graph,
   expected `QUEUED`/`CANDIDATE_PROCESSING` states and page count, then conditionally
   transition the job to `PROCESSING`, stage `EXTRACTING_NATIVE_TEXT`, set safe
   progress/timestamps, and commit.
3. Outside SQLite, read exact controlled bytes, extract pages, check cancellation between
   pages, validate contiguous one-based ordering/page count/ownership, apply the approved
   usability policy, and create all page/locator IDs and one UTC timestamp.
4. In one final transaction, revalidate job/version state, encode and insert the complete
   page/locator set, update safe progress, set stage `CHUNKING`, and commit.
5. On extraction/usability failure, use a separate short transaction to transition
   `PROCESSING -> FAILED` and version to `CANDIDATE_FAILED`, storing only a fixed safe
   error classification. On cancellation, transition to the corresponding cancellation
   states.

The repository operation inserting pages/locators and setting `CHUNKING` is atomic. It
must delete/reject any pre-existing partial rows for the same still-processing attempt
only if the frozen retry policy later authorizes reuse; PROCESSING-001 itself creates no
retry attempt and must fail closed on unexpected pre-existing rows. A rollback leaves no
new pages/locators and the use case then records a sanitized terminal failure in a fresh
transaction.

Persistence mapping:

- `document_pages.id/workspace_id/document_version_id/page_number` come from typed
  Application values;
- state follows the approved empty-page decision; method is `NATIVE`;
- exact UTF-8 text is codec-encoded into `text_ciphertext` and decoded through the same
  deterministic context on handoff reads;
- `normalized_text_fingerprint = NULL`; character count is `len(exact_text)`; word count
  remains `0` because no tokenization contract is owned here;
- `source_locators` uses `PAGE`, the matching page ID/number, `geometry_json_ciphertext =
  NULL`, and `locator_version = 1`;
- timestamps use the existing injected UTC millisecond `Z` representation;
- all writes use the already-active UoW connection and repositories never finalize it.

## Implementation Steps

## Step 1 — Define and test Application processing contracts and orchestration ✅

**Status: COMPLETE**

### Purpose

Create the minimal SDK-free native-processing boundary and prove workspace scope,
controlled-source retrieval, page/provenance construction, state coordination,
cancellation, and sanitized failure behavior against fakes.

### Architecture ownership

- Application ports own extraction input/output, processing values/errors,
  cancellation, persistence/handoff Protocols, and the UoW repository property.
- Application use case owns orchestration, ordering, approved usability classification,
  ID/time creation, cancellation checkpoints, and transaction sequencing.
- Domain types continue to own identifier, page/locator relationship, and state-transition
  validity; no parallel Domain model is added.

### Existing pieces reused

- `IngestionResult`, `ActiveWorkspaceScope`, `ControlledSourceStorage`.
- Existing typed IDs, `PageNumber`, `SourceLocator`, processing/version states, and UoW
  context/commit/rollback semantics.

### Expected files

Modify:

- `src/lexlocal/application/ports/unit_of_work.py`
- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py` only for the smallest
  explicit fail-closed Protocol compatibility property until Step 3 supplies the real
  repository

Add:

- `src/lexlocal/application/ports/processing.py`
- `src/lexlocal/application/processing.py`

Tests:

- `tests/unit/application/ports/test_processing.py`
- `tests/unit/application/test_processing.py`
- `tests/integration/persistence/test_sqlite_unit_of_work.py` only if needed to prove
  the temporary inactive processing property is explicit and does not affect existing
  repositories

### Do

- Define immutable exact-page extraction and persisted/handoff values with typed
  ownership, one-based page number, exact text, method, state, and `SourceLocator`.
- Define one focused native extractor Protocol whose iterable/page sequence exposes no
  Qt type and permits Application cancellation checks between pages.
- Define one minimal cancellation-check Protocol; do not add submission/executor APIs.
- Define repository operations for exact graph/start validation, atomic page-set/handoff
  persistence, terminal failure/cancellation, and ordered chunking handoff reads.
- Extend the existing UoW with one processing repository property.
- Implement the ordered use case with injected page/locator ID factories and UTC clock.
- Validate active workspace/reference/graph before source access; validate extractor
  page count, contiguous one-based order, types, and duplicate/missing pages before any
  page insert.
- Apply the frozen native usability and mixed empty-page policy exactly.
- Suppress unexpected dependency exception chains behind the approved typed errors.

### Do not

- Do not import Qt, SQLite, concrete Infrastructure, `Path`, or UI types.
- Do not implement SQL, a real repository, OCR, normalization, chunking, index creation,
  retry attempts, worker submission, or terminal whole-pipeline readiness.
- Do not turn the cancellation contract into a generic job framework.

### Failure / edge cases

- Missing active scope; cross-workspace reference/result; absent/corrupt graph; wrong
  initial state; source read failure; malformed extractor result; page-count/order
  mismatch; approved unusable-text failure; cancellation at every checkpoint; start,
  final-write, commit, and terminal-state persistence failures.
- A failed final write must roll back and then record failure separately; if that record
  fails, return only a sanitized persistence failure.

### Focused tests

- Sole selected workspace is used and substitutions fail before source lookup.
- Exact source bytes reach the extractor unchanged; no path is used.
- Injected page/locator IDs and UTC time produce exact relationships.
- Normal multi-page order, exact text, method, locator, and handoff values.
- Frozen empty/mixed/all-unusable behavior.
- Start/extract/write/commit call ordering and state targets.
- Cancellation at all six checkpoints produces no completed result or page write.
- Every dependency failure maps to a sanitized typed error without sensitive values.
- Static fake assignments prove Protocol compatibility where `mypy src` cannot.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_processing.py tests/unit/application/test_processing.py -v
uv run ruff check src/lexlocal/application/ports/processing.py src/lexlocal/application/ports/unit_of_work.py src/lexlocal/application/processing.py src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py tests/unit/application/ports/test_processing.py tests/unit/application/test_processing.py
uv run mypy src
uv run pytest tests/architecture -v
git diff --check
```

### Step completion condition

The use case executes entirely against typed fakes, enforces the approved usability
rule and all checkpoints/transactions, and exposes exact page/provenance output without
Qt, SQLite, path, or concrete-provider knowledge.

### Recorded validation

- Focused Application processing suite: 22 passed.
- Existing SQLite UoW suite, including the explicit processing fail-closed shim: 20
  passed.
- Ruff: passed for all Step 1 production/tests and the touched UoW integration test.
- mypy: passed for 48 source files.
- Explicit mypy proof for both processing test-double files: passed.
- Existing architecture suite: 19 passed.
- `git diff --check`: passed.

## Step 2 — Implement and test the Qt native page-text adapter ✅

**Status: COMPLETE**

### Purpose

Convert exact in-memory PDF bytes into the Application native-page sequence while
containing all Qt ownership, indexing, lifecycle, and diagnostics in Infrastructure.

### Architecture ownership

- Infrastructure owns `QBuffer`, `QPdfDocument`, `QPdfSelection`, document readiness,
  zero-based page calls, and safe native-error translation.
- Application receives immutable exact text plus one-based page numbers only.

### Existing pieces reused

- `QtPdfInspector` loading/status/error patterns and PySide6 dependency.
- Existing synthetic Qt PDF fixture conventions and Application processing errors.

### Expected files

Modify:

- None expected; `qt_pdf.py` remains the container inspector.

Add:

- `src/lexlocal/infrastructure/pdf/qt_text_extractor.py`

Tests:

- `tests/unit/infrastructure/pdf/test_qt_text_extractor.py`

### Do

- Add `QtNativePdfTextExtractor` as a sibling adapter implementing the Step 1 port.
- Keep the Qt buffer alive for the document/extraction lifetime and close owned
  resources deterministically.
- Require ready/supported input, iterate Qt indices `0..pageCount-1`, obtain exact
  selection text, and emit matching one-based page numbers without altering text.
- Translate malformed, unreadable, protected, unsupported, invalid page, and native
  exceptions to sanitized processing errors with no native cause chain.
- Keep page iteration lazy/cooperative enough for the Application to check cancellation
  between pages, while never leaking a Qt-owned selection/document.

### Do not

- Do not add another PDF library, extend the container inspection contract, render
  pages, calculate quality scores, run OCR, normalize text, or create locators/IDs.
- Do not add thread pools or UI objects. Thread ownership remains with the future caller;
  adapter-created Qt objects stay within the calling thread.

### Failure / edge cases

- Empty bytes, non-PDF/corrupt PDF, protected PDF, unsupported Qt status, zero pages,
  normal text, exact empty text, multiple pages, and a native exception during later
  iteration.

### Focused tests

- Anonymous synthetic multi-page PDF yields exact text and one-based ordering.
- Exact newlines/Unicode/whitespace and an empty page are not normalized.
- Adapter status/error translations are sanitized and contain no bytes, text, Qt enum,
  selection representation, path, or cause.
- Returned values satisfy the Application port and contain no PySide6 type.

### Focused validation

```bash
uv run pytest tests/unit/infrastructure/pdf/test_qt_text_extractor.py -v
uv run ruff check src/lexlocal/infrastructure/pdf/qt_text_extractor.py tests/unit/infrastructure/pdf/test_qt_text_extractor.py
uv run mypy src
git diff --check
```

### Step completion condition

The real Qt adapter emits exact SDK-free page text in one-based order for anonymous
digital PDFs and safely rejects every supported native failure without OCR behavior.

### Recorded validation

- Focused Qt native-text extractor suite: 12 passed.
- Ruff: passed for both Step 2 files.
- mypy: passed for 49 source files.
- Explicit mypy proof for the Qt adapter test/Protocol assignment: passed.
- Existing architecture suite: 19 passed.
- `git diff --check`: passed.

## Step 3 — Implement and test SQLite processing persistence and staging ✅

**Status: COMPLETE**

### Purpose

Persist the complete page/locator set and processing state transitions through the
existing schema/UoW while providing the exact decoded INDEX-001 handoff contract.

### Architecture ownership

- Infrastructure owns SQL, schema mapping, codec calls, conditional updates, ordering,
  and integrity translation.
- Application owns the repository interface and commits/rollbacks through UoW.
- Bootstrap supplies the configured codec; the repository does not select providers.

### Existing pieces reused

- Existing migration tables/constraints/indexes, SQLite connection/UoW, security codec
  contracts, UTC serializer pattern, and repository integration fixtures.

### Expected files

Modify:

- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py`
- `tests/integration/persistence/test_sqlite_unit_of_work.py`

Add:

- `src/lexlocal/infrastructure/persistence/sqlite_processing_repository.py`

Tests:

- `tests/integration/persistence/test_sqlite_processing_repository.py`
- `tests/integration/persistence/test_processing_transactions.py`

No migration file is expected.

### Do

- Bind `SQLiteProcessingRepository` to the active UoW connection and injected
  `SensitivePayloadCodec`; replace the Step 1 fail-closed compatibility property.
- Strictly resolve the INGESTION graph by workspace/document/version/job IDs and page
  count, treating missing, cross-workspace, or wrong-state rows identically through a
  sanitized persistence error.
- Use conditional state updates so stale/concurrent transitions fail closed.
- Atomically insert all `document_pages` and `source_locators` and set stage `CHUNKING`.
- Encode/decode page UTF-8 bytes with deterministic page context and validate decoded
  UTF-8, ownership, page order, method/state, locator identity, and completeness.
- Return chunking handoff rows only for the exact workspace/version and in explicit
  `page_number` order.
- Record fixed safe failure/cancellation classifications without text, IDs, references,
  SQL, paths, or native details.
- Preserve repository rules: already-active connection only, no IDs/time generation,
  no commit/rollback, no storage/Qt access.

### Do not

- Do not modify migrations, add indexes speculatively, create index generations/chunks,
  calculate fingerprints, bypass the configured codec boundary, instantiate a concrete
  security provider, or add CRUD/list-all APIs.

### Failure / edge cases

- Duplicate/missing/out-of-order page numbers; page-count mismatch; workspace/version/
  job/page/locator mismatch; invalid state; pre-existing page rows; codec/UTF-8 failure;
  corrupt state/method/timestamp/locator mapping; constraint/database/commit failure.
- Workspace mismatch is rejected before existence/format detail where substitution could
  disclose another workspace's graph.

### Focused tests

- Exact multi-page write/read round trip, explicit ordering, IDs, ownership, method,
  state, page-level locator, counts, null fingerprints/geometry, and millisecond `Z`
  timestamps.
- Exact text always passes through the codec boundary; a context-binding codec proves
  non-plaintext provider output and substitution rejection, while the explicitly
  insecure development codec may truthfully persist plaintext synthetic payloads.
- Start, success handoff, failure, and cancellation state mappings are exact.
- Mixed/empty mapping follows the approved human decision.
- Any mid-batch insert/update failure rolls back every page/locator and never creates or
  activates an index generation.
- Repository never commits/rolls back; UoW finalizes; existing workspace/local-model/
  ingestion properties remain unchanged.
- Corruption and integrity errors are sanitized without values or cause chains.

### Focused validation

```bash
uv run pytest tests/integration/persistence/test_sqlite_processing_repository.py tests/integration/persistence/test_processing_transactions.py tests/integration/persistence/test_sqlite_unit_of_work.py -v
uv run ruff check src/lexlocal/infrastructure/persistence/sqlite_processing_repository.py src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py tests/integration/persistence/test_sqlite_processing_repository.py tests/integration/persistence/test_processing_transactions.py tests/integration/persistence/test_sqlite_unit_of_work.py
uv run mypy src
git diff --check
```

### Step completion condition

The existing schema stores and reconstructs one complete exact page/locator set through
the Application port, every state transition is conditional/atomic, and no failure or
cancellation leaves a partial successful result or index row.

### Recorded validation

- Focused processing repository/transaction/UoW suite: 35 passed.
- Ruff: passed for all Step 3 production and test files.
- mypy: passed for 50 source files.
- Closest ingestion persistence/UoW regression suite: 31 passed.
- `git diff --check`: passed.

## Step 4 — Compose and verify the synthetic processing vertical slice ✅

**Status: COMPLETE**

### Purpose

Wire Steps 1–3 with the already-completed ingestion slice and prove exact controlled PDF
bytes become persisted chunking input without an original path or UI dependency.

### Architecture ownership

- Bootstrap owns concrete Qt/SQLite/development-security selection, shared lifetimes,
  factories, and clock wiring only.
- Application retains all processing rules; Infrastructure retains all technical work.

### Existing pieces reused

- `compose_ingestion_application`, its composition result/storage instance,
  `create_security_providers`, `SQLiteConnectionFactory`, `ActiveWorkspaceScope`, and
  existing deterministic factory/test patterns.

### Expected files

Modify:

- `src/lexlocal/bootstrap/ingestion.py` only if required to expose/reuse the already
  composed security dependencies without creating a second process-memory storage
  instance
- `tests/unit/bootstrap/test_ingestion.py` only for any modified shared-lifetime contract

Add:

- `src/lexlocal/bootstrap/processing.py`

Tests:

- `tests/unit/bootstrap/test_processing.py`
- `tests/integration/test_processing_vertical_slice.py`

### Do

- Compose the real Qt extractor, existing active scope, the exact same controlled-source
  storage lifetime as ingestion, configured payload codec, SQLite UoW/repository,
  injected page/locator ID factories, UTC millisecond clock, and minimal cancellation
  check.
- Allow only existing development/test security composition; call the established
  production fail-closed selection before any insecure provider can be used.
- Prove import then processing with real migrated SQLite and anonymous in-memory PDF.
- Expose the processing use case and Application-owned chunking handoff only; expose no
  concrete provider or native/database object.

### Do not

- Do not add processing rules to Bootstrap, create a registry/DI container, wire UI or
  workers, add a production provider, or add INDEX-001 behavior.

### Failure / edge cases

- Wrong/new storage instance, missing active scope, cross-workspace selection, source
  read failure, malformed/corrupted controlled bytes, approved unusable input,
  cancellation, page-write failure, and production settings.

### Focused tests

- One anonymous synthetic multi-page PDF is ingested then processed; exact bytes are
  retrieved through the shared opaque reference and exact page text/locators are read
  through the chunking handoff.
- Original path is absent and unnecessary.
- Normal, empty, mixed, all-unusable, malformed, and protected cases follow the approved
  rules and sanitized failures.
- Cancellation at representative pre-read, between-page, and pre-commit checkpoints
  leaves no successful partial page set.
- Injected IDs/time are deterministic; job/version/handoff states are exact.
- Every failure leaves zero active index generations; successful extraction also creates
  no index generation.
- Production composition rejects the insecure development path unchanged.

### Focused validation

```bash
uv run pytest tests/unit/bootstrap/test_processing.py tests/integration/test_processing_vertical_slice.py -v
uv run ruff check src/lexlocal/bootstrap/processing.py tests/unit/bootstrap/test_processing.py tests/integration/test_processing_vertical_slice.py
uv run mypy src
uv run pytest tests/architecture -v
git diff --check
```

Include modified ingestion Bootstrap/test paths in Ruff when they are actually touched.

### Step completion condition

The real development/test composition converts one ingested synthetic PDF into exact
persisted page/provenance handoff values, exercises all principal cleanup paths, remains
production-fail-closed, and contains no UI or downstream indexing work.

### Recorded validation

- Focused Bootstrap/processing vertical-slice suite: 12 passed.
- Ingestion Bootstrap regression suite: 2 passed.
- Ingestion vertical-slice regression suite: 5 passed.
- Ruff: passed for all Step 4 production/tests and the touched ingestion Bootstrap
  files.
- mypy: passed for 51 source files.
- Existing architecture suite: 19 passed.
- `git diff --check`: passed.

## Step 5 — Run processing quality, architecture, security, and strict-scope gates ✅

**Status: COMPLETE**

### Purpose

Validate the complete ticket against its functional, atomicity, architecture, security,
regression, and scope requirements without adding features.

### Architecture ownership

- Tests audit the existing ownership rules. This step creates no new architecture.
- Corrections, if any, remain in the owning Step 1–4 file and must be minimal.

### Existing pieces reused

- Focused processing suites, existing architecture suite, full repository quality gates,
  and INGESTION-001 regression suites.

### Expected files

Modify:

- `tests/architecture/test_layer_boundaries.py` only if the existing guards do not
  meaningfully prove a required processing boundary
- `docs/PROCESSING-001.md` for actual gate evidence/status only after all gates pass

Add:

- None expected.

Tests:

- Only the smallest missing architecture regression fixture if current evidence is
  insufficient.

### Do

- Run all focused processing/Application/Qt/persistence/Bootstrap/vertical-slice tests,
  existing architecture tests, full pytest, Ruff, mypy, and whitespace checks.
- Audit every requirement and Final Definition of Done item against actual evidence.
- Inspect the full ticket diff for schema/dependency/config changes, later-ticket work,
  generated artifacts, real/sensitive data, leaks, and unnecessary abstractions.
- Reconfirm the ingestion regression, shared storage lifetime, production rejection,
  exact text/provenance handoff, cancellation cleanup, and absence of active indexes.

### Do not

- Do not weaken a test, implement INDEX-001/OCR/UI/workers, refactor unrelated code, or
  mark an unrun/failed gate as passed.

### Failure / edge cases

- Classify failures as current-ticket or pre-existing. Fix only a genuine owning
  Step 1–4 defect, rerun its focused checks, then rerun all required final gates.

### Focused tests

- The final matrix below is authoritative; do not duplicate coverage solely to increase
  test count.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_processing.py tests/unit/application/test_processing.py tests/unit/infrastructure/pdf/test_qt_text_extractor.py tests/integration/persistence/test_sqlite_processing_repository.py tests/integration/persistence/test_processing_transactions.py tests/unit/bootstrap/test_processing.py tests/integration/test_processing_vertical_slice.py -v
uv run pytest tests/architecture -v
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```

### Step completion condition

All required gates pass with actual recorded results, the strict scope/security/
architecture audit is clean, and every non-human DoD item has concrete evidence.

### Recorded validation

- Focused PROCESSING-001 suite: 60 passed, 0 skipped.
- Existing architecture suite: 19 passed, 0 skipped.
- Full repository suite: 1204 passed, 1 skipped. The skipped test is the opt-in,
  hardware-dependent Foundry Local inference smoke test; it is outside PROCESSING-001
  and does not weaken this ticket's evidence.
- Closest INGESTION-001 Bootstrap/vertical-slice/UoW regression: 28 passed, 0 skipped.
- Ruff: passed for the complete repository.
- mypy: passed for 51 source files.
- `git diff --check`: passed.
- Functional, lifecycle/atomicity, cancellation, updated codec-boundary/development-risk,
  architecture, strict-scope, and non-human technical DoD audits: clean.
- `tests/unit/bootstrap/__init__.py` is PROCESSING-001-owned test-module isolation: without
  the package marker, Bootstrap and Domain `test_processing.py` files collide as the
  same top-level pytest module; with it, the full suite collects and passes.

## Step 6 ✅ — Audit Git state for human staged-diff review

**Status: COMPLETE**

### Purpose

Prepare the exact completed PROCESSING-001 change set for explicit human review without
committing, pushing, or creating a PR.

### Architecture ownership

- This is a Git/diff audit only. It changes no implementation or architecture.

### Existing pieces reused

- Step 5 evidence, repository Git conventions, and this ticket's Final Definition of
  Done.

### Expected files

Modify:

- `docs/PROCESSING-001.md` only to record Step 6 status after a clean staged audit

Add:

- None.

Tests:

- None.

### Do

- Verify the approved feature branch, classify every tracked/untracked change, and stage
  only proven PROCESSING-001 paths explicitly.
- Inspect the complete staged diff/stat/status and run cached diff whitespace checks.
- Audit every staged hunk for requirement ownership, sensitive data, generated/cache/IDE
  files, dependency/migration changes, later-ticket work, and unexpected formatting.
- Stop with the final human-review checkbox open and provide proposed delivery metadata.

### Do not

- Do not use broad staging, guess ambiguous ownership, fix technical defects silently,
  commit, push, create/merge a PR, switch/delete branches, or claim human approval.

### Failure / edge cases

- Leave unrelated or ambiguous files unstaged and report them. A discovered technical
  defect reopens Step 5 rather than being repaired inside this audit.

### Focused tests

- No new tests. Confirm Step 5 evidence remains applicable to the staged content.

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

Exactly the ticket-owned, previously validated change set is staged and fully audited,
cached diff checks pass, no unrelated file is staged, and explicit human staged-diff
review remains the sole open delivery gate.

## Final Validation Matrix

| Area | Required evidence |
|---|---|
| Happy path | Anonymous synthetic multi-page PDF; exact text retained; explicit one-based order; `NATIVE` method; matching page locator and ownership; handoff readable without UI/path. |
| Page edge cases | Normal page, exact empty page, mixed normal/empty pages, all-unusable document, and the human-approved classification/result. |
| Input failures | Malformed/non-PDF, unreadable/corrupt, protected/encrypted, unsupported native status, and controlled-source read/substitution failure. |
| Lifecycle | Exact `QUEUED -> PROCESSING` start; success remains `PROCESSING` at `CHUNKING`; failure becomes `FAILED`/`CANDIDATE_FAILED`; cancellation becomes `CANCELLED`/`CANDIDATE_CANCELLED`; no false terminal success. |
| Cancellation | Pre-start, pre-read, pre-extraction, between-page, pre-transaction, and pre-commit checkpoints; no completed result or partial committed page set. |
| Atomicity/cleanup | Complete page/locator set commits together; any insertion/update/commit failure rolls it back; terminal failure recording is separate and sanitized; no active index generation on any path. |
| Persistence | Exact UTF-8 codec round trip through provider payload bytes; the insecure development codec may store plaintext synthetic payloads; null unapproved fingerprint/geometry; strict workspace/version/page relationships; corrupt mapping rejection; explicit order. |
| Downstream | Application handoff returns exact page text/state/method/locator only for the requested workspace/version and is sufficient for deterministic page-aware chunking. |
| Architecture | No Qt/native types, SQLite/SQL, concrete Infrastructure, path, or direct write in Application; Infrastructure implements ports; Bootstrap composes only; Domain stays independent. |
| Security | Codec boundary is mandatory; the insecure provider is DEVELOPMENT ONLY, SYNTHETIC FIXTURES ONLY, NOT RELEASE SAFE, and NOT FOR REAL USER DOCUMENTS, with no encryption/confidentiality/at-rest claim; no bytes/text/reference/path/SQL/Qt/native diagnostics/encoded payloads/IDs leak through errors or logs; production remains fail-closed. |
| Regression | Existing INGESTION-001 unit, Qt, persistence, transaction, Bootstrap, and vertical-slice behavior remains green. |
| Strict scope | No OCR, chunk/index/embedding/retrieval/RAG/UI/worker/retry framework, migration, dependency, generic abstraction, production security, or unrelated change. |
| Quality | Focused tests, architecture suite, full pytest, Ruff, mypy, worktree/cached whitespace checks, and full diff audit pass with actual recorded results. |

## Final Definition of Done

- [x] Human approved the native-text usability and mixed empty-page policy.
- [x] Application owns a Qt/SQLite-free native extraction, processing, cancellation,
  persistence, and INDEX-001 handoff contract.
- [x] Processing obtains the sole workspace from `ActiveWorkspaceScope` and rejects all
  workspace/reference/graph substitutions.
- [x] Exact controlled PDF bytes are read through the existing opaque storage reference;
  no original path is required.
- [x] The Qt Infrastructure adapter preserves exact multi-page text and converts native
  zero-based indexing to existing one-based `PageNumber` values.
- [x] Exact page text, approved page state, `NATIVE` method, typed ownership, and matching
  page-level source locator are persisted and reconstructed.
- [x] Sensitive page text always uses the existing codec boundary; development plaintext
  payloads remain explicitly synthetic-only/non-release-safe, no at-rest protection is
  claimed, production rejects the insecure provider, and errors never expose page text.
- [x] Empty, mixed, and no-usable-text outcomes exactly follow the approved M1 rule; no
  OCR fallback exists.
- [x] Malformed, unreadable, protected, unsupported, corrupt mapping, and persistence
  failures are typed and sanitized.
- [x] All defined cancellation checkpoints are tested and cancellation never appears
  completed or exposes partial successful output.
- [x] Page/locator staging and job-stage handoff are atomic; rollback/cleanup behavior is
  proven.
- [x] Successful extraction hands off at `PROCESSING`/`CHUNKING` with version still
  `CANDIDATE_PROCESSING`; INDEX-001 terminal/activation ownership is untouched.
- [x] No PROCESSING-001 path creates or activates an index generation; failures and
  cancellation leave none active.
- [x] INDEX-001 can obtain exact ordered page text and provenance through an
  Application-owned contract without Qt, SQLite, path, storage, or UI knowledge.
- [x] Existing INGESTION-001 and architecture behavior remains green.
- [x] No migration or new dependency was added without new approved evidence.
- [x] Final focused, architecture, full pytest, Ruff, mypy, and diff gates pass with
  actual results recorded.
- [x] Strict scope/security/overengineering audit is clean and all fixtures are
  anonymous synthetic data.
- [x] Exact ticket files are staged and the cached diff check passes.
- [x] Final staged diff is scope-clean and explicitly human-reviewed. *(Human only)*

## Current Position

- Before PROCESSING-001, INGESTION-001 is implemented and provides the committed initial
  graph, opaque controlled reference, exact process-memory source access, selected
  workspace scope, and queued job needed by this ticket.
- The schema, Domain page/locator identities, processing/version states, security ports,
  UoW, Qt dependency, Bootstrap conventions, and architecture guards are available and
  now composed for the synthetic processing slice.
- The native-text usability and mixed empty-page policy is approved and frozen.
- Step 1 is complete: Application contracts/orchestration are implemented and validated.
- Step 2 is complete: the sibling Qt native-text adapter preserves exact text and
  one-based ordering behind the Application port with sanitized native failures.
- Step 3 is complete: SQLite processing persistence replaces the initial fail-closed UoW
  compatibility state when configured, atomically maps exact codec-backed page/locator
  sets, conditionally transitions lifecycle state, and exposes the ordered INDEX-001
  handoff behind the existing UoW.
- Step 4 is complete: Bootstrap reuses ingestion's exact controlled-storage and codec
  lifetime, wires the real Qt/SQLite path, and proves the ordered chunking handoff plus
  fail-closed failure/cancellation behavior.
- Step 5 is complete: every required gate was rerun against the frozen codec-boundary
  and development-risk policy, and the functional, atomicity, security, architecture,
  strict-scope, regression, and technical DoD audits are clean.
- Step 6 is complete: all 19 ticket-owned files are staged, every staged hunk is audited,
  no unrelated or ambiguous file is staged, and the cached diff check passes.
- Next action: explicit human review of the staged PROCESSING-001 diff. No commit, push,
  or PR action is authorized yet.
