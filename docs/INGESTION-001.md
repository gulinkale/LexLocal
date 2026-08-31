# INGESTION-001 — Import One Structurally Valid Synthetic PDF Through Controlled Storage

## Ticket objective

Import one anonymous synthetic PDF into the currently selected active workspace,
validate only its PDF container/document safety, copy its exact bytes through the
existing controlled-source port, and atomically register the first logical document,
candidate version, controlled-blob metadata, and queued processing job.

Successful import returns SDK/Qt/SQLite-free identifiers and metadata and no longer
depends on the original external path. This ticket establishes registration only;
PROCESSING-001 owns native-text extraction and usability.

## Repository evidence / current state

- `LogicalDocument`, `DocumentVersion`, and `ProcessingJob` already enforce typed IDs,
  workspace ownership, relationship validation, immutable values, and state
  transitions.
- Initial states already exist: logical document `ACTIVE`, version
  `CANDIDATE_PROCESSING`, processing job `QUEUED`, version number `1`, and attempt
  number `1`.
- `ActiveWorkspaceScope.require_workspace_id()` is the sole Application-owned source
  of the selected workspace. Only an `ACTIVE` workspace can enter that scope.
- `ControlledSourceStorage.store/read/delete` already accepts bytes, returns an
  opaque workspace-bound `ControlledSourceRef`, and supports compensation without
  exposing physical paths.
- The development storage provider is explicitly process-memory-only and carries the
  four required non-release risk labels. It is valid only for anonymous synthetic M1
  fixtures.
- `SQLiteUnitOfWork` already owns one active connection and transaction. Repositories
  bound to it do not open connections or commit/rollback independently.
- The initial migration already contains `stored_blobs`, `documents`,
  `document_versions`, and `document_processing_jobs`, including composite
  workspace FKs and the live duplicate unique index.
- Canonical duplicate design is SHA-256 over the exact imported bytes followed in
  production by HMAC-SHA-256 with a workspace duplicate key. M1 has no such key and
  must use an unmistakably synthetic development token instead.
- The approved PDF adapter is an Infrastructure wrapper over Qt `QPdfDocument`.
  PySide6 is already installed; no new PDF dependency is justified.
- No ingestion/PDF validation implementation or document/blob/job repositories exist.
- Existing persistence code establishes application-generated IDs, UTC millisecond
  `Z` timestamps, strict row reconstruction, sanitized persistence errors, migrated
  `tmp_path` databases, and caller-owned transaction finalization.

## Reuse vs extension decisions

| Area | Decision | Reason |
|---|---|---|
| Domain document/version/job types | Reuse unchanged | Existing types already express the required initial identities, states, and workspace relationships. |
| Active workspace | Reuse unchanged | The use case resolves scope from injected `ActiveWorkspaceScope`; callers do not supply an alternate workspace ID. |
| Controlled source storage | Reuse unchanged | `store`, `read`, and `delete` cover import, later access, and rollback compensation. No finalize operation is needed. |
| Unit of Work | Minimal extension | Expose one ingestion repository bound to the existing transaction; do not add another UoW. |
| Stored blob identity | Add Application-owned `StoredBlobId` in the ingestion port | Blob identity is technical ingestion/persistence metadata, separate from the opaque storage locator, and has an immediate role in the version-to-blob FK. It does not enter Domain. |
| Ingestion persistence | Add one focused Application-owned repository port | One atomic operation must register the separately identified blob, document, version, and job together. Generic CRUD is unnecessary. |
| Duplicate fingerprint | Add one minimal Application-owned port and one development-only implementation | Application needs workspace-scoped equality without knowing HMAC keys or the synthetic algorithm. |
| PDF validation | Add one minimal Application-owned inspection port and Qt Infrastructure adapter | Application needs typed validation results without importing Qt. |
| Sensitive filename/display-name mapping | Reuse `SensitivePayloadCodec` through an Infrastructure persistence adapter | Logical names remain outside SQLite representation; no new public security framework is needed. |
| Bootstrap | Minimal extension | Bootstrap composes concrete Qt, development fingerprint/storage, repository, UoW, ID, and clock dependencies. |

## Frozen architecture decisions

1. Domain remains limited to business identity, state, and relationship validity.
2. Application owns ingestion orchestration, typed failures, the PDF inspection port,
   duplicate-fingerprint port, and atomic registration repository contract.
3. Infrastructure owns Qt document inspection, synthetic token calculation, encoded
   filename mapping, SQLite statements, and row/schema mapping.
4. Bootstrap alone constructs concrete implementations.
5. The use case consumes exact PDF bytes plus a logical filename. It does not accept
   or persist `Path`; a caller outside this ticket may read a selected file before
   invoking it.
6. The use case obtains `WorkspaceId` from injected `ActiveWorkspaceScope` so the
   selected active workspace is the only available ingestion scope.
7. Document, version, processing-job, and technical stored-blob IDs plus the
   timestamp are generated by injected Application callables before persistence.
   Repositories never generate them.
8. Storage occurs before the SQLite transaction. SQLite never claims to transact the
   storage operation.
9. The M1 storage and duplicate implementations are synthetic/process-lifetime and
   cannot be composed for release/production use.
10. No original filename path, physical controlled-storage path, Qt object, SQLite
    row, or development-provider type crosses into Application contracts.

## Scope IN

- One anonymous synthetic PDF represented by exact bytes and a logical filename.
- Active-workspace resolution.
- PDF container/type/readability/protection/support validation.
- Exact-byte SHA-256 and workspace-scoped synthetic duplicate token.
- Controlled-source storage and opaque reference.
- One logical document, first immutable candidate version, active blob metadata, and
  initial queued processing job.
- One atomic database registration transaction and storage-delete compensation.
- Workspace-scoped duplicate rejection and sanitized typed failures.
- Development/test Bootstrap composition and focused architecture/integration tests.

## Scope OUT

- OCR, native-text extraction, text-usability thresholds, page records, chunking,
  embeddings, indexing, retrieval, RAG, or source viewing.
- Images, multiple files, batch preflight UX, presentation/UI, background execution,
  progress workers, or queue submission.
- Replacement versions, retry attempts, archive, deletion, or reactivation.
- Production encryption, HMAC keys, key derivation/lifecycle, encrypted filesystem
  format, restart recovery, or release-safe storage.
- Schema/migration changes except the one approved forward migration making
  `stored_blobs.encryption_format_version` nullable; new dependencies, generic
  repositories, provider registries, DI containers, or storage frameworks.

## Layer/file ownership

| Layer | Expected ownership |
|---|---|
| Domain | Reuse `domain/documents.py`, `domain/processing.py`, and typed identifiers unchanged unless implementation proves a current contract defect. |
| Application ports | `application/ports/ingestion.py`: technical typed `StoredBlobId`, PDF inspector, duplicate fingerprint, immutable registration values/result, and one atomic repository operation. Minimal extension of `application/ports/unit_of_work.py`. |
| Application use case | `application/ingestion.py`: validation, scope resolution, hashing/fingerprinting, storage, entity creation, one DB transaction, and compensation. |
| Infrastructure PDF | `infrastructure/pdf/qt_pdf.py`: convert exact bytes to Qt-owned input and translate Qt status to Application failures/results. |
| Infrastructure security | `infrastructure/security/insecure_development_ingestion.py`: development-only workspace-scoped token and logical sensitive-name persistence mapping. |
| Infrastructure persistence | `infrastructure/persistence/sql_migrations/002_nullable_blob_encryption_format.sql`, `infrastructure/persistence/sqlite_ingestion_repository.py`, and minimal `sqlite_unit_of_work.py` wiring. |
| Bootstrap | `bootstrap/ingestion.py` and only the minimum existing composition integration needed to expose the use case in development/test. |
| Tests | Focused Application/Infrastructure unit tests, migrated SQLite integration tests, vertical-slice compensation tests, and existing architecture suite extensions only where coverage is missing. |

Do not add package-root re-exports unless an established local convention requires a
specific one.

## PDF validation semantics

Input is:

- `source: bytes`: exact bytes later hashed and stored;
- `logical_filename: str`: display/history metadata only, never an external path.

Application rejects non-`bytes`, empty bytes, and invalid logical filenames before
storage. The PDF inspection port receives bytes and returns immutable safe metadata
containing the supported MIME type (`application/pdf`) and non-negative page count.
It exposes no Qt types.

The Qt adapter must reject and translate distinctly:

- bytes that are not a PDF/detected as unsupported input;
- corrupt or unreadable document structure;
- password-protected/encrypted documents;
- Qt-reported unsupported PDF/document status.

Validation failures occur before fingerprint persistence, controlled storage, IDs
becoming visible, or database writes. Errors contain no source bytes, filename,
external path, Qt diagnostic, or native object representation.

A structurally valid image-only/scanned PDF is accepted. No page text is extracted
and no digital-text usability decision is made in INGESTION-001. PROCESSING-001 owns
that later failure boundary.

## Duplicate fingerprint semantics

Canonical production design remains:

```text
source_sha256 = SHA-256(exact imported source bytes)
production_fingerprint = HMAC-SHA-256(workspace_duplicate_key, source_sha256)
```

M1 does not implement or simulate that key/HMAC design. Application computes the
exact-byte SHA-256 digest with the standard library, then asks its fingerprint port
for a token scoped to the selected `WorkspaceId`.

The development adapter follows the existing development-only lookup-token pattern:

```text
SHA-256(
  b"lexlocal/insecure-development-only/document-duplicate/v1\x00"
  + canonical WorkspaceId UTF-8 bytes
  + b"\x00"
  + 32-byte source SHA-256 digest
)
```

This construction is deterministic and workspace-scoped only for synthetic M1
equality tests. Its module and class carry exactly:

- `DEVELOPMENT ONLY`
- `SYNTHETIC FIXTURES ONLY`
- `NOT RELEASE SAFE`
- `NOT FOR REAL USER DOCUMENTS`

Documentation must not call it HMAC, encryption, confidential, keyed, or
production-safe. The port permits M2 replacement without changing the use-case
signature.

Persist the 32-byte token in `document_versions.duplicate_fingerprint`; this column
and `ux_workspace_duplicate_live_source` are the authoritative duplicate gate.
`stored_blobs.duplicate_fingerprint` may carry the same token as matching blob
metadata, but duplicate classification must rely on the document-version unique
constraint in the same transaction. Do not persist the raw source digest in M1;
`plaintext_sha256_ciphertext` and `content_sha256_ciphertext` remain `NULL` because
no production-safe protection exists.

An existing live token in the same workspace becomes `DuplicateDocument`. The same
bytes in another workspace produce a different development token and are allowed.

## Controlled-storage / stored-blob mapping

`ControlledSourceStorage.store(workspace_id, source)` returns an opaque
`ControlledSourceRef`. `StoredBlobId` is generated separately by the Application use
case and is not a Domain identifier. The approved M1 mappings are:

| Value | SQLite mapping |
|---|---|
| generated `StoredBlobId` | `stored_blobs.id` and `document_versions.source_blob_id` |
| `ControlledSourceRef.workspace_id` | `workspace_id` |
| `ControlledSourceRef.value` | `relative_path` as an opaque storage-locator representation only; it is neither a physical path nor database identity |
| source kind | `SOURCE_DOCUMENT` |
| successful `store` | `state = ACTIVE` because the current port has no staging/finalize state |
| `len(source)` | `size_bytes` |
| raw digest | not persisted; `plaintext_sha256_ciphertext = NULL` |
| synthetic workspace token | `duplicate_fingerprint` |
| plaintext process-memory provider | `encryption_format_version = NULL` |
| injected UTC timestamp | `created_at` and `activated_at` in millisecond `Z` form |
| deletion fields | `deleted_at = NULL` |

The forward migration removes only the `NOT NULL` requirement from
`stored_blobs.encryption_format_version`; the existing positive-value check remains
for non-null values. `NULL` truthfully means that the synthetic plaintext provider
has no encryption/storage envelope version. It is not version `0`, a fake version
`1`, or a production encrypted-file claim.

Application continues to treat `ControlledSourceRef` as opaque. The M1 locator is
process-lifetime and has no restart reconstruction guarantee. A later release
provider may replace storage and locator persistence without changing the import
use-case inputs or controlled-storage port. Production composition continues to
reject insecure development storage.

## Document/version/job creation semantics

After successful validation, fingerprint calculation, and storage:

- create `LogicalDocument` with generated `DocumentId`, selected `WorkspaceId`, and
  `ACTIVE`;
- create `DocumentVersion` with generated `DocumentVersionId`, the same workspace and
  document ID, `VersionNumber(1)`, and `CANDIDATE_PROCESSING`;
- create stored-blob registration with a separately generated `StoredBlobId` and the
  opaque controlled reference as locator;
- create `ProcessingJob` with generated `ProcessingJobId`, the same workspace and
  version ID, `AttemptNumber(1)`, and `QUEUED`;
- validate existing Domain relationships before persistence;
- persist logical filename as both document display name and historical first-version
  filename through the development sensitive-payload mapping;
- persist MIME type `application/pdf`, extension `.pdf`, exact byte size, validated
  page count, source blob ID, and the duplicate token;
- persist job stage `VALIDATING`; no worker is submitted by this ticket.

The use case returns an immutable SDK-free result containing the document ID,
version ID, processing-job ID, controlled reference, and safe PDF metadata. It does
not return encoded columns, SQL rows, paths, source bytes, or fingerprints.

## Transaction + compensation semantics

The ordered use-case boundary is:

1. require the active workspace ID;
2. validate input and PDF structure;
3. compute exact source digest and development token;
4. generate document, version, processing-job, and stored-blob IDs plus one UTC
   timestamp;
5. store exact bytes and receive the opaque reference;
6. enter the existing UoW;
7. atomically insert stored blob, document, first version, and queued job;
8. commit;
9. return the registration result.

Failure rules:

- validation/fingerprint failure: no storage or DB operation;
- storage failure: no DB transaction/records;
- repository/constraint/commit failure: UoW rollback, then best-effort mandatory
  compensation with `ControlledSourceStorage.delete`;
- duplicate constraint failure: compensate storage and raise `DuplicateDocument`;
- compensation failure: raise a sanitized storage/consistency failure while retaining
  the primary failure as safe structured classification only; never expose source or
  provider details;
- there is no post-commit storage finalize call.

The Application use case owns this ordering and compensation. SQLite repositories
never call storage and storage never commits the database.

## Error/sanitization rules

Application owns a small ingestion error vocabulary under `IngestionError`:

- `InvalidPdfInput`: empty/invalid caller input;
- `UnsupportedPdf`: non-PDF or Qt-unsupported PDF;
- `UnreadablePdf`: corrupt/unreadable PDF;
- `ProtectedPdf`: encrypted/password-protected PDF;
- `DuplicateDocument`: live duplicate in the selected workspace;
- `IngestionStorageError`: controlled storage or compensation failure;
- `IngestionPersistenceError`: sanitized DB mapping/transaction failure.

Infrastructure exceptions are translated at their owning boundary. Messages and
exception chains must not contain PDF bytes, logical filenames, original paths,
fingerprints/digests, controlled references, SQL, database paths, Qt diagnostics, or
provider state. UI text, localization, and error codes are out of scope.

## Test strategy

- Application unit tests use fake PDF, fingerprint, storage, repository, UoW, ID, and
  clock dependencies. Prove ordering, selected-workspace use, exact bytes, initial
  states, separate stored-blob ID versus opaque locator, relationship validation,
  returned IDs, and every no-write/compensation path.
- Fingerprint unit tests use anonymous bytes and prove deterministic same-workspace
  equality, cross-workspace difference, exact-byte sensitivity, 32-byte output, four
  warning labels, and absence of HMAC/encryption/confidentiality claims.
- Qt adapter tests create minimal anonymous PDFs in memory and prove valid,
  image-only-valid, zero-byte, non-PDF, corrupt, protected, and unsupported status
  translation without native details. Tests must use Qt-owned buffers/objects only in
  Infrastructure.
- SQLite integration tests use migrated `tmp_path` databases. Prove exact four-row
  mapping, composite workspace relationships, initial states, timestamp format,
  separate blob identity, opaque locator mapping, nullable development format,
  positive encrypted-format validation, duplicate constraint translation,
  commit/rollback, and no incidental ordering contract.
- Migration tests prove an existing version-1 database upgrades without data loss,
  permits `NULL` only for the format field, still accepts positive format versions,
  and still rejects zero/negative versions while foreign-key/integrity checks remain
  clean.
- Vertical-slice tests compose development-only storage and a migrated database;
  prove controlled bytes remain readable without the original input, same-workspace
  duplicate rejection and cleanup, cross-workspace allowance, storage failure with no
  rows, and DB failure with storage deletion.
- Architecture tests reuse the existing AST framework to prove Application imports no
  Qt/PySide6, SQLite/SQL, or concrete Infrastructure and performs no direct filesystem
  writes. Bootstrap and Infrastructure remain allowed to compose/implement ports.
- All fixtures remain synthetic/anonymous; no real legal documents, secrets, raw
  keys, credentials, `.env` contents, prompts, or model data.

## Overengineering risks

- Do not combine PDF inspection, fingerprinting, storage, and persistence into a
  generic provider framework.
- Do not introduce generic blob CRUD, file abstractions, transaction managers, saga
  engines, event buses, registries, or a second UoW.
- Do not add repository methods for get/list/update/delete when the import transaction
  needs only one atomic registration operation.
- Do not expose raw hashes, encoded payloads, physical paths, Qt types, or SQLite
  details to Application callers.
- Do not turn the development token or format version into a production-security
  claim.
- Do not move PROCESSING-001 extraction, OCR, worker submission, or index staging into
  this ticket.

## Implementation steps

## 1. Define and test Application ingestion contracts and orchestration ✅

### Purpose

Create the minimal typed ingestion boundary and prove ordering, active scope,
validation, initial entities, atomic registration request, and compensation without
Qt or SQLite.

### Exact expected files

- `src/lexlocal/application/ports/ingestion.py`
- `src/lexlocal/application/ports/unit_of_work.py`
- `src/lexlocal/application/ingestion.py`
- `tests/unit/application/ports/test_ingestion.py`
- `tests/unit/application/test_ingestion.py`

### Do

- Add the PDF inspection, duplicate-fingerprint, and one-operation registration
  repository Protocols plus Application-owned `StoredBlobId`, immutable SDK-free
  values/results, and typed errors.
- Inject `ActiveWorkspaceScope`, storage, UoW factory, ID factories, and UTC clock.
- Implement exact ordering and compensation with Domain relationship validation.
- Add static Protocol compatibility proof where normal `mypy src` does not cover test
  doubles.

### Do not

- Do not import `Path`, Qt, SQLite, or concrete providers into Application.
- Do not add repository CRUD, worker submission, extraction, OCR, or persistence
  mapping.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_ingestion.py tests/unit/application/test_ingestion.py -v
uv run ruff check src/lexlocal/application/ports/ingestion.py src/lexlocal/application/ports/unit_of_work.py src/lexlocal/application/ingestion.py tests/unit/application/ports/test_ingestion.py tests/unit/application/test_ingestion.py
uv run mypy src
git diff --check
```

### Step completion condition

The use case is executable against fakes, consumes only the selected WorkspaceId,
creates the exact initial Domain relationships, and proves every pre-storage,
pre-transaction, rollback, and compensation path.

### Recorded validation

- Focused Step 1 suite: 16 passed.
- Ruff: passed for all Step 1 files and the minimal existing SQLite UoW compatibility
  shim.
- mypy: passed for 41 source files.
- Existing architecture boundary suite: 19 passed.
- `git diff --check`: passed.

## 2. Implement and test the development fingerprint and Qt PDF adapters ✅

### Purpose

Provide the two Infrastructure implementations needed to validate synthetic PDFs and
derive workspace-scoped synthetic equality tokens.

### Exact expected files

- `src/lexlocal/infrastructure/pdf/__init__.py`
- `src/lexlocal/infrastructure/pdf/qt_pdf.py`
- `src/lexlocal/infrastructure/security/insecure_development_ingestion.py`
- `tests/unit/infrastructure/pdf/test_qt_pdf.py`
- `tests/unit/infrastructure/security/test_insecure_development_ingestion.py`

### Do

- Wrap `QPdfDocument`/Qt-owned byte input and translate supported Qt statuses into the
  frozen Application error/result contract.
- Implement the exact versioned, domain-separated development token.
- Keep the token adapter and any logical-name persistence helper explicitly
  development-only with all four risk labels.
- Use only anonymous PDFs/bytes; verify image-only structural acceptance without OCR.

### Do not

- Do not add a PDF dependency, extract text, classify text usability, render pages,
  invoke OCR, expose Qt objects, or claim production security.

### Focused validation

```bash
uv run pytest tests/unit/infrastructure/pdf/test_qt_pdf.py tests/unit/infrastructure/security/test_insecure_development_ingestion.py -v
uv run ruff check src/lexlocal/infrastructure/pdf src/lexlocal/infrastructure/security/insecure_development_ingestion.py tests/unit/infrastructure/pdf/test_qt_pdf.py tests/unit/infrastructure/security/test_insecure_development_ingestion.py
uv run mypy src
git diff --check
```

### Step completion condition

All frozen PDF outcomes and synthetic token invariants are proven without native type
leakage, sensitive fixtures, OCR, or production-security claims.

### Recorded validation

- Focused Step 2 suite: 17 passed.
- Ruff: passed for all Step 2 files.
- mypy: passed for 44 source files.
- Existing architecture boundary suite: 19 passed.
- `git diff --check`: passed.

## 3. Implement and test atomic SQLite ingestion registration

### Purpose

Map the four required records to the existing schema through the existing UoW and
prove exact transaction, duplicate, corruption, and workspace behavior.

### Exact expected files

- `src/lexlocal/infrastructure/persistence/sqlite_ingestion_repository.py`
- `src/lexlocal/infrastructure/persistence/sql_migrations/002_nullable_blob_encryption_format.sql`
- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py`
- `tests/integration/persistence/test_migration_pipeline.py`
- `tests/integration/persistence/test_sqlite_ingestion_repository.py`
- `tests/integration/persistence/test_ingestion_transactions.py`
- `tests/integration/persistence/test_sqlite_unit_of_work.py`

### Do

- Add only the atomic registration operation required by the Application port.
- Encode logical names internally with deterministic SECURITY-001 metadata.
- Map all frozen columns, states, composite FKs, timestamp strings, locator, and
  nullable protected-digest columns exactly.
- Add the smallest forward migration that rebuilds/preserves `stored_blobs` as needed
  to allow `encryption_format_version IS NULL` while retaining the positive check for
  every non-null value, keys, indexes, and workspace constraints.
- Translate duplicate integrity failure separately from sanitized persistence/data
  failures.
- Use the active UoW connection; never open, commit, rollback, or generate IDs/times in
  the repository.

### Do not

- Do not modify `001_initial.sql`, relax any other schema invariant, add
  read/list/update/delete APIs, persist source bytes in SQLite, or perform storage
  operations from the repository.

### Focused validation

```bash
uv run pytest tests/integration/persistence/test_migration_pipeline.py tests/integration/persistence/test_sqlite_ingestion_repository.py tests/integration/persistence/test_ingestion_transactions.py tests/integration/persistence/test_sqlite_unit_of_work.py -v
uv run ruff check src/lexlocal/infrastructure/persistence/sqlite_ingestion_repository.py src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py tests/integration/persistence/test_migration_pipeline.py tests/integration/persistence/test_sqlite_ingestion_repository.py tests/integration/persistence/test_ingestion_transactions.py tests/integration/persistence/test_sqlite_unit_of_work.py
uv run mypy src
git diff --check
```

### Step completion condition

One caller-owned transaction creates exactly the blob/document/version/job graph,
duplicate and cross-workspace constraints are correctly classified, and rollback
leaves no partial database graph.

### Recorded validation

- Focused Step 3 suite: 29 passed.
- Ruff: passed for all Step 3 Python files.
- mypy: passed for 45 source files.
- `git diff --check`: passed.

## 4. Compose and verify the synthetic ingestion vertical slice ✅

### Purpose

Wire the existing active scope, Qt adapter, development token/storage, UoW, IDs, and
clock in Bootstrap and prove complete success/failure behavior without an original
path dependency.

### Exact expected files

- `src/lexlocal/bootstrap/ingestion.py`
- minimum existing Bootstrap composition file only if required to expose the use case
- `tests/unit/bootstrap/test_ingestion.py`
- `tests/integration/test_ingestion_vertical_slice.py`

### Do

- Compose only for the existing development/test synthetic path and preserve
  production fail-closed behavior.
- Prove exact-byte controlled read after import, original-input independence,
  same-workspace duplicate cleanup, cross-workspace allowance, storage failure with
  no rows, and DB failure with compensation delete.
- Keep generated IDs/time deterministic in tests.

### Do not

- Do not add UI, file-picker/path reading, workers, provider registry, production
  storage/fingerprint implementation, or application startup work not required by the
  frozen composition boundary.

### Focused validation

```bash
uv run pytest tests/unit/bootstrap/test_ingestion.py tests/integration/test_ingestion_vertical_slice.py -v
uv run ruff check src/lexlocal/bootstrap/ingestion.py tests/unit/bootstrap/test_ingestion.py tests/integration/test_ingestion_vertical_slice.py
uv run mypy src
git diff --check
```

### Step completion condition

One synthetic PDF is registered under the sole active workspace, is readable only
through its controlled reference, and every failure leaves storage/database state
consistent without enabling insecure production composition.

### Recorded validation

- Focused Step 4 suite: 7 passed.
- Ruff: passed for all Step 4 files.
- mypy: passed for 46 source files.
- Existing architecture boundary suite: 19 passed.
- `git diff --check`: passed.

## 5. Run architecture, quality, security, and strict-scope gates ✅

### Purpose

Validate the complete ticket and correct only genuine owning defects exposed by the
required gates.

### Exact expected files

- `tests/architecture/test_layer_boundaries.py` only if existing guards lack required
  representative coverage
- `docs/INGESTION-001.md`
- an owning Step 1–4 file only for a proven ticket defect

### Do

- Run focused ingestion, architecture, full pytest, Ruff, mypy, and diff gates.
- Audit every changed hunk for scope, security, synthetic fixtures, dependency
  direction, original-path independence, duplicate isolation, and compensation.
- Verify production security still fails closed and no insecure alias becomes release
  safe.
- Record actual counts and evidence; update only Step 5 status after all gates pass.

### Do not

- Do not weaken gates, manufacture refactors, add later processing work, or mark an
  unrun/failed check as passing.

### Focused validation

```bash
uv run pytest tests/unit/application/ports/test_ingestion.py tests/unit/application/test_ingestion.py tests/unit/infrastructure/pdf/test_qt_pdf.py tests/unit/infrastructure/security/test_insecure_development_ingestion.py tests/unit/bootstrap/test_ingestion.py tests/integration/persistence/test_sqlite_ingestion_repository.py tests/integration/persistence/test_ingestion_transactions.py tests/integration/test_ingestion_vertical_slice.py -v
uv run pytest tests/architecture -v
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```

### Step completion condition

All required gates pass with actual evidence; the full diff is architecture-, scope-,
security-, and compensation-clean; every Final DoD item except human staged-diff
review is proven.

### Recorded validation

- Focused ingestion suite: 50 passed.
- Architecture boundary suite: 19 passed.
- Full suite: 1142 passed, 1 opt-in Foundry Local smoke test skipped.
- Ruff: passed repository-wide.
- mypy: passed for 46 source files.
- `git diff --check`: passed.
- Strict architecture, security, ingestion, transaction, migration, and scope audits:
  clean.

## 6. Audit Git state for human review

### Purpose

Prepare the exact completed INGESTION-001 change set for explicit human staged-diff
review without committing, pushing, or creating a PR.

### Exact expected files

- only files proven to belong to INGESTION-001

### Do

- Verify Step 5 first.
- Inspect branch, status, tracked/untracked contents, complete diff, cached diff,
  dependencies, generated files, secrets, fixtures, and whitespace.
- Classify every file; stage only proven ticket-owned files using explicit paths.
- Report proposed commit/PR metadata and actual Step 5 validation evidence.

### Do not

- Do not stage unrelated/ambiguous work, commit, push, create a PR, merge, or mark
  human review approved.

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

The exact ticket file set is staged and fully audited, cached whitespace passes, and
the ticket stops at explicit human approval with the final DoD checkbox open.

## Final Definition of Done

- [x] One exact, non-empty, structurally supported synthetic PDF is accepted without
  native-text/OCR classification.
- [x] Unsupported, corrupt/unreadable, and protected/encrypted inputs fail through
  actionable sanitized Application errors before storage or registration.
- [x] The sole selected active `WorkspaceId` scopes every fingerprint, storage, and DB
  relationship.
- [x] Exact source bytes are hashed and stored; no original external path is retained
  or required after success.
- [x] Same bytes in one workspace are rejected and in different workspaces are
  allowed using the explicitly non-production development token.
- [x] Controlled storage remains unchanged and physical paths do not cross into
  Application.
- [x] Stored blob, logical document, first candidate version, and queued job are
  created in one UoW transaction with exact schema mappings.
- [x] `StoredBlobId` is Application-owned technical metadata, generated separately
  from `ControlledSourceRef.value`, and used for the blob PK/version FK only.
- [x] `ControlledSourceRef.value` is persisted only as the opaque development storage
  locator and is never treated as a physical path or database identity.
- [x] The forward migration permits `NULL` format only for providers without an
  encryption/storage envelope; positive versions remain constrained and the
  synthetic provider never claims encryption.
- [x] Duplicate registration commits no duplicate DB graph; its DB transaction rolls
  back and the newly stored controlled source is deleted as compensation, leaving no
  persistent partial registration.
- [x] Other storage failures create no DB rows, and other DB failures roll back and
  compensate the newly stored controlled source.
- [x] Domain relationships and initial states are reused without duplicate models.
- [x] Application imports no Qt, SQLite, SQL, concrete Infrastructure, physical path,
  or development-provider types.
- [x] Development adapters remain synthetic/process-lifetime, visibly non-release,
  and production continues to fail closed.
- [x] No OCR, extraction, processing worker, indexing, retrieval, UI, migration beyond
  the single nullable-format correction, dependency, production-security, or
  later-ticket work enters the diff.
- [x] Focused, architecture, full pytest, Ruff, mypy, diff, and strict-scope gates pass
  with actual evidence.
- [ ] Final staged diff is scope-clean and explicitly human-reviewed.

## Current position

**Steps 1–5 ✅. Step 6 ← NEXT.** All focused, architecture, full-suite, Ruff, mypy,
diff, security, transaction, migration, and strict-scope gates pass. Every Final DoD
item except explicit human staged-diff review is proven.

Next: **Step 6 — Audit Git state for human review.**
