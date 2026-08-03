# LexLocal Implementation Backlog

## M0 — Project Foundation

- SETUP-001: Establish Python package structure — Completed in PR #2

- FOUNDATION-002: Establish runnable desktop project foundation — Completed in PR #4
  - Covers the former SETUP-002 and SETUP-003 tasks
  - Python 3.11, `pyproject.toml`, `uv.lock`
  - pytest, Ruff, mypy, and coverage
  - Minimal PySide6 application, bootstrap, startup test, and README

- FOUNDATION-003: Add configuration, logging, and architecture guardrails
  - Central application configuration
  - Safe logging foundation
  - Architecture import-boundary tests
  - Covers the former CONFIG-001, LOG-001, and ARCH-001 tasks

- FOUNDRY-001: Validate Foundry Local runtime and local model inference
  - Verify Foundry Local installation and device compatibility
  - Run a supported local model successfully
  - Call the local model from Python
  - Confirm that inference works without an internet connection
  - Add a small smoke test or validation script
  - Record the selected model and known limitations

- PERSISTENCE-001: Establish SQLite persistence foundation
  - Define and validate the initial database migration
  - Add schema-version tracking for applied migrations
  - Implement an atomic and repeatable migration runner
  - Add the SQLite connection factory
  - Configure foreign-key enforcement and connection timeouts
  - Resolve the database path through application settings
  - Add the Unit of Work foundation with commit and rollback behavior
  - Add persistence integration tests using temporary databases
  - Verify migration ordering, repeat execution, commit, and rollback behavior
  - Covers the former DB-001, DB-002, DB-003, and DB-004 tasks

## Roadmap Mapping and Open Decisions

- M1 below is the approved **Delivery Milestone M1 — Local RAG Vertical Slice**
  defined in `02_SCOPE_AND_MVP.md`, `04_SYSTEM_ARCHITECTURE.md`, and
  `07_TEST_AND_EVALUATION_PLAN.md`.
- M2 through M8 collectively deliver the approved **Delivery Milestone M2 —
  Complete LexLocal Release**. These implementation milestones divide that
  delivery scope into reviewable, dependency-aware capabilities; they do not
  defer any first-release requirement.
- Only synthetic, anonymous, non-sensitive documents may be used in M1. A
  development-only plaintext or insecure payload provider is permitted solely
  behind the approved storage/cryptography ports. Real, external, demo, or user
  documents remain prohibited until Security Gate SG-1 passes in M2.
- The production chat model, embedding model identity and vector dimensions
  remain release-manifest decisions. The requested embedding alias is
  `qwen3-embedding-0.6b`, pending Foundry catalog resolution and compatibility
  validation. No implementation may silently substitute a different model.
- Minimum supported macOS version, Apple Silicon generation, RAM, free-disk
  requirement, performance thresholds, and evaluation thresholds marked
  `TBD-BENCHMARK` remain release-blocking decisions to resolve with recorded
  benchmark evidence in M8.
- Touch ID remains optional. M6 must provide the platform abstraction and safe
  disabled behavior; enabling it for release requires Security Gate SG-4 and a
  packaged-application test.

## M1 — Local RAG Vertical Slice

### Goal

Deliver one automated-testable and demonstrable local path from a synthetic
digital PDF to a grounded answer with a validated page-level citation, using
Foundry Local, SQLite, and Python/NumPy retrieval without any cloud model.

### User-visible outcome

A developer or evaluator can open the desktop application, create a basic
workspace, import one synthetic digital PDF, process it locally, ask one
question, receive a grounded answer, and open the cited page and passage.

### Dependencies

- M0 project, logging, Foundry validation, SQLite, migration, and Unit of Work
  foundations.
- Existing initial schema and documented architecture boundaries.
- Synthetic, anonymous test fixtures only.

### Tickets

- DOMAIN-001: Establish core workspace, document, processing, and RAG domain contracts
  - Define documented identifiers, statuses, evidence states, and transition guards in the domain layer.
  - Keep persisted state distinct from derived UI state and prohibit cross-workspace operations.
  - Represent typed failures without exposing infrastructure or UI types to the domain.
  - Test valid transitions, invalid transitions, equality, and workspace-scope guards.
  - Complete when later application use cases can depend on stable domain contracts without importing SQLite, Qt, or Foundry SDK types.

- SECURITY-001: Define the sensitive-payload and controlled-storage ports for M1
  - Define application-facing boundaries for field payload encoding, controlled source storage, and workspace key references.
  - Provide a clearly marked development-only provider for synthetic fixtures; prevent it from being selected by release composition.
  - Keep direct plaintext file and sensitive SQLite writes out of application services.
  - Test provider selection, contextual payload metadata, and release-mode rejection of the insecure provider.
  - Complete when M1 can be built without creating an encryption retrofit dependency in later milestones.

- WORKSPACE-001: Implement the minimal workspace vertical slice
  - Implement workspace creation, listing, selection, and active-workspace application behavior through repository ports and a Unit of Work.
  - Persist stable identifiers, display name, profile selection, timestamps, and documented workspace state.
  - Enforce workspace-scoped repository inputs and database-level cross-workspace invariants already present in the schema.
  - Add domain, repository, temporary-database, and transaction rollback tests.
  - Complete when a newly created workspace can be selected as the only scope for ingestion and retrieval.

- FOUNDRY-002: Implement the Foundry Local runtime and model adapter boundary
  - Isolate SDK initialization, catalog lookup, resolved identity, health, load, inference, and unload behind infrastructure ports.
  - Resolve the requested chat and embedding aliases and persist exact model identity and compatibility metadata.
  - Fail closed when models are absent or incompatible; never use a cloud fallback.
  - Add fake-adapter tests for lifecycle and failure paths plus an opt-in local-runtime smoke test.
  - Complete when application services do not import Foundry SDK types and resolved model information is observable without sensitive output.

- INGESTION-001: Import one synthetic digital PDF through controlled storage
  - Validate PDF type/readability, compute the documented workspace-scoped duplicate fingerprint, and copy through the storage port.
  - Create the logical document, immutable first version, blob metadata, and processing job atomically where required.
  - Reject corrupt, unreadable, password-protected, unsupported, or duplicate input with actionable typed failures.
  - Exclude multi-file UX, OCR, images, replacement, and production encryption from this M1 ticket.
  - Complete when a temporary synthetic PDF is registered without depending on its original external path.

- PROCESSING-001: Extract page-aware text from a digital PDF
  - Use the architecture-approved PDF extraction adapter and preserve page number, extraction method, and source locator metadata.
  - Treat empty or unusable digital text as an explicit processing failure in M1; OCR fallback belongs to M3.
  - Stage results so failure creates no active index generation.
  - Add fixtures for normal pages, empty pages, malformed PDF, cancellation checkpoints, and cleanup.
  - Complete when exact page text and source locators are available to chunking without UI dependencies.

- INDEX-001: Implement deterministic page-aware chunking and active index generation
  - Implement configurable chunk size and overlap while preserving page and source boundaries.
  - Persist chunks only under a candidate index generation and activate it atomically after the complete pipeline succeeds.
  - Ensure retry is idempotent and failed processing leaves no active partial index.
  - Add deterministic boundary, overlap, metadata, activation, rollback, and repeat-run tests.
  - Complete when the active document version has exactly one compatible active index generation.

- EMBEDDING-001: Generate and persist local document and query embeddings
  - Use the same resolved Foundry-compatible embedding model for chunks and queries.
  - Store normalized `float32` vector payloads, dimensions, model identity, and compatibility metadata through the payload boundary.
  - Validate dimensions and reject mismatched, non-finite, corrupt, or incompatible vectors.
  - Add serialization round-trip, batching, identity-mismatch, and fake-provider failure tests.
  - Complete when synthetic chunks and questions produce compatible persisted vectors without a cloud dependency.

- RAG-001: Implement workspace-scoped cosine top-K retrieval and evidence persistence
  - Load only eligible active-version vectors for the active workspace and optional document scope.
  - Compute cosine similarity in Python/NumPy; do not introduce an ORM or vector database.
  - Make top-K and documented thresholds configurable and persist the exact retrieval scope and evidence items.
  - Add ranking, tie, empty-index, dimension mismatch, workspace isolation, version filtering, and repeatability tests.
  - Complete when relevant synthetic passages are returned with stable evidence IDs and source locators.

- CHAT-001: Generate one grounded answer and validated citation
  - Orchestrate query embedding, retrieval, initial evidence sufficiency, context-only prompting, local generation, and citation validation.
  - Reject fabricated document/page/evidence references and return an explicit insufficient-evidence result rather than general model knowledge.
  - Commit a completed assistant answer, exact scope snapshot, evidence, and citations atomically; cancellation or failure must leave no completed answer.
  - Add fake-model tests, temporary-database rollback tests, citation validation tests, and one offline local-model smoke path.
  - Complete when one question produces either a grounded cited answer or an explicit non-answer.

- UI-001: Deliver the M1 desktop RAG workflow
  - Add minimal screens for workspace creation/selection, single-PDF import, processing status, one chat question, answer, and citation opening.
  - Run long extraction, embedding, retrieval, and inference work outside the GUI thread with safe progress and cancellation signals.
  - Display active workspace, model unavailability, processing failures, and insufficient evidence clearly.
  - Add Qt startup/workflow tests with fake adapters and a manual synthetic-PDF desktop smoke test.
  - Complete when the documented M1 workflow is demonstrable end to end without command-line database manipulation.

### Milestone acceptance criteria

- A synthetic digital PDF completes the PDF → page text → chunk → Foundry
  embedding → SQLite → NumPy cosine top-K → grounded answer → validated
  citation path.
- The cited page and supporting passage can be opened from the desktop flow.
- Workspace and active-version isolation are enforced, and failure/cancellation
  cannot activate partial processing or commit a completed answer.
- The complete path works offline after model setup and makes no cloud LLM call.
- Release composition refuses the development-only payload provider.

### Required verification

- Domain and application unit tests.
- Temporary-database repository and transaction tests.
- Architecture boundary tests.
- Synthetic PDF processing, retrieval, grounding, and citation integration tests.
- Qt workflow test and manual desktop smoke validation.
- Offline local-model validation with sanitized evidence.
- Ruff, mypy, and full pytest suite.

### Out of scope

- Real, external, demo, or user legal documents before SG-1.
- Production encryption, recovery, Touch ID, OCR, JPEG/PNG, multi-file import,
  document replacement, persistent multi-chat UX, and structured analysis.
- Vector databases, cloud fallback, and production model claims not backed by
  the release manifest.

## M2 — Production Encryption and First-Run Security

### Goal

Pass Security Gate SG-1 and establish the password, recovery, and key hierarchy
needed before LexLocal may process real or externally sourced documents.

### User-visible outcome

On first launch, a user creates a LexLocal-specific master password, saves and
confirms a recovery key, unlocks the application, and creates workspaces whose
sensitive database fields and controlled source files are encrypted.

### Dependencies

- M1 sensitive-payload and controlled-storage ports.
- M1 workspace and document vertical slice.
- Approved algorithms and mandatory sequence in `06_SECURITY_DESIGN.md`.

### Tickets

- SECURITY-002: Implement cryptographic primitives and versioned envelopes
  - Implement approved secure randomness, AES-256-GCM envelopes, HKDF-SHA-256 purpose derivation, contextual associated data, and algorithm versioning.
  - Use the approved maintained cryptographic dependency; do not implement custom cryptography.
  - Reject wrong keys, altered headers/nonces/ciphertext/tags, copied ciphertext contexts, and unknown versions.
  - Add trusted vectors where available, nonce-uniqueness checks, boundary-size tests, and sensitive-error tests.
  - Complete when field and binary payload round trips authenticate and every tamper case fails closed.

- AUTH-001: Calibrate Argon2id and initialize the application master key
  - Implement password policy, common-password rejection, no trimming, Unicode handling, and runtime Argon2id calibration within documented bounds.
  - Derive only a key-encryption key from the password and use it to wrap a random application master key.
  - Store only approved salts, parameters, wrappers, and verification metadata; never plaintext passwords or master keys.
  - Add calibration-bound, valid/invalid unlock, metadata corruption, and plaintext-leakage tests.
  - Complete when a fresh profile can initialize and later unlock the same random master key.

- SECURITY-003: Create and wrap independent workspace data keys
  - Generate one random data key per workspace and wrap it under the application master key.
  - Derive separate field, file, embedding, and fingerprint subkeys by purpose and workspace context.
  - Prevent raw keys from reaching presentation code or being persisted in plaintext.
  - Add cross-workspace decryption/copy, wrong-context, key-reference, and transaction rollback tests.
  - Complete when workspaces have cryptographically isolated data keys and contextual subkeys.

- STORAGE-001: Implement authenticated controlled-file storage
  - Implement documented chunked encrypted-file format, authenticated header, relative path layout, atomic staging/rename, and cleanup.
  - Keep plaintext source data out of persistent temporary files, previews, logs, crash reports, and filenames where prohibited.
  - Support authenticated streaming reads needed by extraction and source viewing without exporting a permanent plaintext copy.
  - Add empty/boundary/multi-chunk, interruption, altered-header/chunk, atomic-write, and orphan-cleanup tests.
  - Complete when imported sources survive restart encrypted and tampering prevents use.

- STORAGE-002: Integrate encrypted SQLite payload codecs
  - Route every field listed by the security and data-model documents through contextual authenticated encryption before SQLite writes.
  - Encrypt embedding payloads while preserving only approved searchable metadata and workspace-scoped HMAC fingerprints.
  - Reject malformed or unauthenticated payloads with typed recovery errors and no plaintext fallback.
  - Add repository round-trip, raw-database leakage, cross-row copy, cross-workspace copy, and WAL/plaintext scan tests.
  - Complete when raw SQLite/WAL inspection contains no prohibited sensitive fixture markers.

- AUTH-002: Implement mandatory recovery-key setup and confirmation
  - Generate a high-entropy random recovery key and use it only through the approved master-key wrapping path.
  - Display it once, require partial confirmation, prohibit logging/analytics, and follow clipboard timeout rules.
  - Persist only protected recovery metadata and make incomplete setup non-final.
  - Add generation, confirmation, invalid key, clipboard cleanup, abandoned setup, and leakage tests.
  - Complete when first-run setup cannot finish without a confirmed recovery path.

- AUTH-003: Implement unlock and progressive password delay
  - Validate password wrappers, release key material only after success, and reset failure state on successful unlock.
  - Apply persistent progressive delays without permanent lockout or automatic deletion; show only safe remaining-delay metadata.
  - Provide the recovery-key entry path without revealing whether sensitive metadata exists.
  - Add timing-policy, restart persistence, successful reset, invalid recovery, and concurrency tests.
  - Complete when normal and recovery unlock paths fail safely and rate limiting matches the approved policy.

- UI-002: Build first-run security and unlock screens
  - Implement welcome, system pre-check, master-password creation, recovery display/confirmation, unlock, and safe setup-resume states.
  - Clearly distinguish the LexLocal password from the macOS account password and explain data-loss consequences honestly.
  - Keep model setup capability separate so a model failure may lead to Limited Mode without weakening completed security setup.
  - Add Qt state/workflow tests, keyboard/focus checks, and manual first-run/restart validation.
  - Complete when a clean profile can securely set up, restart, and unlock before reaching workspace content.

- SECURITY-004: Enforce SG-1 composition and leakage gate
  - Make production/release bootstrap require authenticated field and file providers and reject development providers.
  - Scan database, WAL, controlled storage, temporary roots, and logs for forbidden synthetic markers.
  - Record sanitized SG-1 evidence without keys, recovery material, plaintext fixtures, or raw prompts.
  - Add composition, packaged-configuration, tamper, and leakage-gate tests.
  - Complete when SG-1 passes and the prohibition on real/external/user documents can be lifted.

### Milestone acceptance criteria

- Master-password unlock opens a random application master key; each workspace
  has a separate wrapped data key.
- Required SQLite payloads, embeddings, and controlled source files are
  authenticated ciphertext at rest.
- Recovery-key setup is mandatory and confirmed.
- Tampering and wrong-context use fail closed.
- Release composition cannot select the development-only provider, and the
  SG-1 plaintext-leakage scan passes.

### Required verification

- Cryptographic unit and trusted-vector tests.
- Temporary-database and controlled-file integration tests.
- Password, recovery, tamper, cross-workspace, and plaintext-leakage tests.
- First-run and unlock UI workflow tests.
- Architecture tests, Ruff, mypy, and full pytest suite.
- Security Gate SG-1 evidence review.

### Out of scope

- Touch ID, password change, recovery-key rotation, automatic session lock,
  deletion/cryptographic erasure, OCR, full chat, and analysis workflows.
- Claims of protection against a fully compromised unlocked operating system.

## M3 — Reliable Multi-Document Ingestion, OCR, and Versioning

### Goal

Turn the M1 single-digital-PDF path into a reliable encrypted ingestion system
for PDF, JPEG/JPG, and PNG files with page-level OCR, background processing,
staged activation, recovery, and document versions.

### User-visible outcome

A user can preflight and import multiple supported files, follow per-document
progress, cancel or retry safely, review OCR warnings, replace a document with a
new version, and open exact PDF or image sources.

### Dependencies

- M2 SG-1 production encryption and controlled storage.
- M1 processing, chunking, embedding, and active-index pipeline.

### Tickets

- INGESTION-002: Implement multi-file validation and preflight
  - Validate PDF/JPEG/PNG signatures, readability, encryption/password state, size/page limits, duplicates, and estimated storage before copying.
  - Present per-file accepted, warning, duplicate, unsupported, corrupt, and blocked outcomes without starting hidden work.
  - Require explicit user decisions for duplicates and limit warnings.
  - Add mixed-batch, spoofed-extension, corrupt-file, duplicate, cancellation, and no-write-on-preflight tests.
  - Complete when each selected file has a deterministic preflight result and only confirmed files enter ingestion.

- PROCESSING-002: Implement persistent background processing jobs
  - Run independent document jobs outside the GUI thread with persisted stage, progress, warning, cancellation, and retry state.
  - Add cooperative cancellation checkpoints and ensure cancellation never activates a candidate version/index.
  - Detect interrupted jobs on startup and expose retry, discard, or safe recovery actions.
  - Add crash simulation, restart discovery, idempotent retry, cancellation race, and connection-lifecycle tests.
  - Complete when app restart cannot hide or misclassify incomplete processing work.

- OCR-001: Implement page-level native-text versus OCR decision
  - Evaluate each PDF page independently using documented text-quality signals and preserve the chosen extraction method.
  - Use native extraction when adequate and local OCR only when required; never send pages to a remote service.
  - Preserve partial-page success and actionable warnings rather than treating every mixed document as all-or-nothing.
  - Add digital, scanned, mixed, blank, rotated, and low-quality synthetic page tests.
  - Complete when every processed page has traceable extraction provenance and confidence/warning metadata.

- OCR-002: Integrate local Turkish and English printed-text OCR
  - Isolate Tesseract or the approved local OCR runtime behind the documented adapter and package `tur+eng` language resources appropriately.
  - Support printed Turkish and English for PDF page images, JPEG/JPG, and PNG; expose preprocessing and OCR failures safely.
  - Explicitly exclude handwriting and guaranteed extraction of every complex layout.
  - Add representative synthetic fixtures, language/resource-missing tests, offline checks, and quality evaluation hooks.
  - Complete when supported image inputs can produce local page text with honest warnings and no network dependency.

- PROCESSING-003: Harden staging, activation, retry, and cleanup
  - Coordinate filesystem staging and SQLite transactions so only fully valid document versions and index generations become active.
  - Preserve the prior active version on replacement failure or cancellation.
  - Clean candidate rows/files safely while retaining approved diagnostic state and recovery visibility.
  - Add injected-failure tests at every pipeline boundary, repeat execution tests, and orphan detection.
  - Complete when partial work cannot enter retrieval and retries do not duplicate active data.

- DOCUMENT-001: Implement document details and processing diagnostics
  - Expose general metadata, processing state, warnings, extraction provenance, versions, source use, and safe technical metadata.
  - Keep stack traces, raw text, prompts, paths, and keys out of normal UI errors.
  - Provide retry/cancel actions only when allowed by the persisted state machine.
  - Add presenter/state tests and Qt tests for READY, READY_WITH_WARNINGS, FAILED, CANCELLED, and recovery-required states.
  - Complete when users can understand whether existing data is safe and what action is available.

- DOCUMENT-002: Implement explicit document replacement with immutable versions
  - Create a candidate numbered version without changing the current active version during processing.
  - Atomically archive the previous version and activate the candidate only after source, extraction, chunks, embeddings, and warnings are valid.
  - Preserve historical source locators and citations to archived versions.
  - Add successful, warning, failed, cancelled, restart, and concurrent replacement tests.
  - Complete when replacement failure never affects current retrieval and successful replacement affects future retrieval only.

- STORAGE-003: Implement secure PDF/image source viewing
  - Decrypt only through a short-lived controlled read path and render PDFs/images without persistent plaintext exports.
  - Navigate to exact page/image and highlight or show the supporting passage where available.
  - Clean temporary artifacts on close, lock, crash recovery, and startup.
  - Add source locator, archived version, tamper, missing source, temp cleanup, and viewer lifecycle tests.
  - Complete when exact active or archived evidence can be inspected locally without leaking persistent plaintext.

- UI-003: Deliver multi-document import and processing workflows
  - Implement file selection, preflight, disk warning, progress list, per-document status/actions, details, replacement, and recovery-required UI.
  - Keep the application responsive and progressively usable while independent jobs run.
  - Make OCR use, warnings, cancellation consequences, and retry behavior visible in user-friendly Turkish text.
  - Add Qt workflow tests and manual mixed-batch/offline smoke validation.
  - Complete when the approved Parts IV document flows are demonstrable end to end.

- EVALUATION-001: Establish ingestion and OCR evaluation fixtures
  - Create versioned synthetic/approved non-sensitive PDF and image fixtures covering digital, scanned, mixed, rotated, blank, and malformed inputs.
  - Record expected pages, extraction route, warning state, and reference text without confidential content.
  - Add reproducible OCR metric and error-report generation while leaving release thresholds marked until M8 benchmark approval.
  - Complete when ingestion/OCR regressions are measurable and fixture provenance is documented.

### Milestone acceptance criteria

- Confirmed multi-file PDF/JPEG/PNG batches process independently and remain
  responsive.
- Native extraction and local `tur+eng` OCR decisions are page-traceable.
- Failure, cancellation, or restart cannot activate partial data or replace the
  previous valid document version.
- Exact active and archived PDF/image sources can be opened securely.
- All processing remains local and uses encrypted storage.

### Required verification

- File validation, state-machine, chunking, and OCR unit tests.
- Temporary-database and encrypted controlled-storage integration tests.
- Failure injection, cancellation, retry, restart, and orphan-cleanup tests.
- OCR fixture evaluation and offline checks.
- Qt import/processing/source-viewer workflow tests.
- Ruff, mypy, full pytest, and architecture tests.

### Out of scope

- DOCX, email, spreadsheets, ZIP, audio/video, handwriting guarantees, folder
  watching, automatic external-file synchronization, and full chat/analysis UX.

## M4 — Persistent Grounded Chat and Citation History

### Goal

Deliver reliable workspace-specific multi-chat question answering with exact
scope snapshots, controlled conversational context, calibrated evidence
sufficiency, persistent history, and historical citations.

### User-visible outcome

A user can maintain multiple chats, choose document scope, ask follow-up
questions, receive grounded answers or explicit low-evidence outcomes, and open
citations that continue to resolve to the exact historical document version.

### Dependencies

- M3 reliable active/archived document versions and secure source viewer.
- M1 embedding, retrieval, generation, evidence, and citation baseline.

### Tickets

- CHAT-002: Implement persistent chat lifecycle and naming
  - Create the chat on first question, generate a safe local title, and support user rename and confirmed deletion.
  - Persist multiple chats per workspace without making previous answers evidence.
  - Retain only approved tombstone/activity information after deletion.
  - Add create/rename/delete, empty-chat, workspace isolation, rollback, and title-failure tests.
  - Complete when chats survive restart and deletion does not damage documents or other chats.

- CHAT-003: Implement logical-document scope and per-request version snapshots
  - Store a chat's current logical-document scope while snapshotting exact active versions for every request.
  - Apply scope changes and newly ready documents only to future questions.
  - Prevent archived, failed, deleted, or cross-workspace versions from silently entering new retrieval.
  - Add scope-change, replacement, new-document, deletion, archive, and historical replay tests.
  - Complete when every request can reconstruct its exact eligible source set.

- CHAT-004: Implement controlled conversational context
  - Distinguish prior dialogue context from retrievable documentary evidence.
  - Summarize or limit conversation history locally according to configuration without silently changing stored historical messages.
  - Prevent assistant output from becoming a citation source or factual evidence.
  - Add follow-up resolution, context truncation, poisoned prior answer, restart, and scope-change tests.
  - Complete when follow-up questions remain coherent but answers are grounded only in documents.

- RAG-002: Calibrate evidence sufficiency outcomes
  - Implement `SUFFICIENT`, `RELATED_BUT_INSUFFICIENT`, and `INSUFFICIENT` behavior using documented configurable signals.
  - Present caveated related evidence without a definitive answer when support is incomplete.
  - Store decision inputs and safe diagnostic metadata for evaluation, not raw sensitive prompts in logs.
  - Add threshold boundary, empty retrieval, conflicting weak evidence, and false-confidence regression tests.
  - Complete when insufficient support cannot be presented as certain.

- CHAT-005: Harden streaming, cancellation, retry, and atomic answer commit
  - Keep partial streamed text ephemeral and never store it as a completed answer.
  - Validate all citations before atomically committing the assistant message, request outcome, evidence, and citations.
  - Preserve the failed/cancelled request for safe retry without duplicating messages or evidence.
  - Add stream interruption, cancellation race, invalid citation, database failure, retry, and model-unavailable tests.
  - Complete when only fully validated answers appear as completed history.

- HISTORY-001: Resolve historical and deleted-source citations honestly
  - Resolve citations by immutable version/source locator rather than current display name or active pointer.
  - Open archived source versions and show an explicit unavailable/tombstone state after approved source deletion.
  - Never redirect a historical citation to a replacement document.
  - Add archived-version, renamed-document, deleted-source, missing-file, and cross-workspace tests.
  - Complete when every retained citation is either exact and viewable or explicitly unavailable.

- UI-004: Deliver persistent chat and citation workflows
  - Implement chat list, automatic/user title, document-scope controls, progress/cancel/retry, evidence states, answer citations, and delete confirmation.
  - Hide unsafe technical details while exposing useful source and low-confidence explanations.
  - Preserve future-only scope semantics visibly when documents or versions change.
  - Add Qt workflow, keyboard/focus, historical citation, and manual offline chat tests.
  - Complete when the approved Parts V chat flows are demonstrable after restart.

- EVALUATION-002: Establish retrieval, grounding, and citation evaluation set
  - Create versioned synthetic/approved non-sensitive questions with expected relevant pages, answerability, and citation targets.
  - Measure retrieval ranking, sufficiency classification, grounded answer support, citation validity, and unsupported-answer rate.
  - Record model/embedding identity and configuration with every run.
  - Complete when regressions are reproducible and M8 can lock release thresholds from recorded evidence.

### Milestone acceptance criteria

- Multiple workspace-scoped chats persist across restart.
- Every request stores exact document-version scope and validated evidence.
- Unsupported questions produce the approved non-answer/caveated outcome.
- Partial, cancelled, failed, or invalidly cited output never becomes a
  completed answer.
- Historical citations never redirect and remain honest after deletion.

### Required verification

- Chat, scope, context, sufficiency, and citation unit tests.
- Temporary-database atomic-commit and workspace-isolation tests.
- Streaming/cancellation/failure/retry integration tests.
- Retrieval and citation evaluation run.
- Qt chat/source workflow tests and offline model smoke validation.
- Ruff, mypy, full pytest, and architecture tests.

### Out of scope

- Cloud chat, web search, prior assistant messages as evidence, shared/team
  chats, document drafting, and structured analysis generation.

## M5 — Structured Legal Analysis and Version History

### Goal

Deliver profile-specific, source-grounded structured analysis with staged
generation, editable drafts, immutable formal versions, section regeneration,
staleness, restore, comparison, and exact source history.

### User-visible outcome

A user can select an approved legal profile, generate a cited structured
analysis, edit and save it, regenerate selected sections safely, compare or
restore versions, and see when later document/profile changes make it stale.

### Dependencies

- M4 calibrated retrieval, citations, exact source snapshots, and local model orchestration.
- M3 document type metadata and immutable document versions.

### Tickets

- ANALYSIS-001: Implement analysis profiles and document-type suggestions
  - Define the approved litigation, contract review, and general legal matter schemas and required sections.
  - Implement local suggestion evidence and require user confirmation; suggestions must not silently change profile or document type.
  - Persist profile/version metadata used for each generation.
  - Add schema validation, suggestion confidence, confirmation, profile-change, and workspace isolation tests.
  - Complete when the chosen profile deterministically controls analysis structure and retrieval strategy.

- ANALYSIS-002: Implement analysis preflight and source-set snapshot
  - Validate workspace state, ready documents, selected profile, model compatibility, disk/resource needs, and overwrite implications.
  - Freeze the exact eligible document versions and source-set fingerprint before generation.
  - Require explicit confirmation before replacing user-edited content through regeneration.
  - Add blocked/warning preflight, concurrent document change, fingerprint, and cancellation tests.
  - Complete when every run has an immutable, auditable input snapshot.

- ANALYSIS-003: Implement staged hierarchical analysis generation
  - Perform targeted section retrieval and hierarchical aggregation for long multi-document workspaces rather than one top-K prompt.
  - Persist generation-run and section progress separately from formal analysis state.
  - Validate structure and citations before atomically creating a formal version; failure must preserve the last valid analysis.
  - Add long-source, section failure, malformed output, invalid citation, cancellation, and atomic rollback tests.
  - Complete when full generation produces one complete cited version or no formal change.

- ANALYSIS-004: Implement editable auto-saved drafts and formal save
  - Maintain `ACTIVE`, `SAVED`, and `DISCARDED` draft lifecycle independently from formal analysis and generation-run state.
  - Auto-save local edits safely without creating formal versions until explicit save.
  - Recover active drafts after restart and protect them from unconfirmed regeneration overwrite.
  - Add autosave, crash recovery, discard, save, conflict, and no-premature-version tests.
  - Complete when editing is resilient and formal history changes only on approved save events.

- ANALYSIS-005: Implement section and full regeneration
  - Regenerate against a fresh documented source snapshot while preserving unaffected sections when section-only regeneration is selected.
  - Create a new immutable formal version only after complete validation.
  - Preserve user edits unless the user explicitly confirms replacement.
  - Add source-change, section merge, failure preservation, cancellation, and citation validation tests.
  - Complete when regeneration cannot partially overwrite the current formal analysis.

- ANALYSIS-006: Implement staleness reasons and current-state rules
  - Keep formal `NOT_CREATED`, `CURRENT`, and `STALE` state separate from generation operation and draft states.
  - Mark stale for approved document/profile/source changes without mutating historical versions.
  - Ensure failed or cancelled generation leaves the last valid formal analysis `CURRENT` or `STALE` as it was.
  - Add every stale trigger, failed-run, cancelled-run, and clearing-on-valid-version test.
  - Complete when users can distinguish valid-but-old analysis from active generation or draft work.

- HISTORY-002: Implement immutable analysis history, restore, and deterministic diff
  - Persist exact source/version/citation/profile/model metadata and safe change summaries for each formal version.
  - Restore by creating a new version; never rewrite or reactivate an old row in place.
  - Compare versions deterministically without requiring an LLM.
  - Add immutability, restore, diff, archived-source, deleted-source, and ordering tests.
  - Complete when historical analysis can be verified and restored without silent mutation.

- UI-005: Deliver structured-analysis workflows
  - Implement preflight, progress, section layout, citations, edit/draft state, regeneration confirmation, stale banner, version history, restore, and compare views.
  - Present missing/unclear information and low-confidence content without false certainty.
  - Keep failure and cancellation from replacing the displayed last valid result.
  - Add Qt state/workflow, draft recovery, historical citation, and manual offline analysis tests.
  - Complete when approved Parts VI analysis flows are demonstrable across restart.

- EVALUATION-003: Establish structured-analysis evaluation
  - Create approved non-sensitive workspaces with expected section coverage, unsupported-field behavior, and citation requirements.
  - Measure completeness, source support, citation validity, missing-information honesty, and version stability.
  - Record model identity, profile version, retrieval configuration, and dataset version.
  - Complete when analysis quality regressions are measurable and M8 can lock release thresholds.

### Milestone acceptance criteria

- All approved profiles generate complete staged analyses with validated sources.
- Draft, generation operation, and formal analysis states remain independent.
- Failure/cancellation preserves the last valid formal version.
- Save, regeneration, and restore create immutable versions with exact source
  snapshots; drafts alone do not.
- Staleness, deterministic comparison, and historical citations behave as documented.

### Required verification

- Profile, state-machine, draft, staleness, restore, and diff unit tests.
- Temporary-database generation/version transaction tests.
- Failure injection, cancellation, restart, and historical-source tests.
- Structured-analysis evaluation run.
- Qt workflow and manual offline analysis validation.
- Ruff, mypy, full pytest, and architecture tests.

### Out of scope

- Legal advice, outcome prediction, contradiction detection, automatic legal
  chronology, document drafting, arbitrary user-defined templates, and LLM-based diffs.

## M6 — Lifecycle, Locking, Deletion, and Recovery

### Goal

Complete Security Gates SG-2 and SG-3 and the documented workspace/document
lifecycle: session locking, credential recovery and rotation, archive,
cryptographic deletion, activity history, and safe recovery modes.

### User-visible outcome

A user can lock and unlock LexLocal, recover or change credentials, archive and
reactivate workspaces, delete documents or workspaces with clear consequences,
review a safe activity timeline, and recover from interrupted sensitive work.

### Dependencies

- M2 key hierarchy, recovery foundation, encrypted payloads, and SG-1.
- M3 document/version lifecycle and M5 analysis history.

### Tickets

- AUTH-004: Implement password change and recovery-key rotation
  - Re-wrap the application master key without re-encrypting every workspace document or database field.
  - Invalidate the previous recovery wrapper and require generation/confirmation of a new recovery key after recovery.
  - Fail atomically so at least one valid approved unlock path remains or recovery mode is explicit.
  - Add old/new credential, interrupted rotation, wrapper corruption, concurrent session, and leakage tests.
  - Complete when successful rotation invalidates old credentials without changing content keys.

- SECURITY-005: Implement manual, inactivity, sleep, and macOS-session locking
  - Model documented session states and configurable 5/15/30/60-minute inactivity policy with a 15-minute default.
  - Clear UI plaintext, caches, key material, viewers, and temporary artifacts on lock.
  - Coordinate job-scoped key leases according to approved background-work rules without handing keys to presentation code.
  - Add activity reset, timer, sleep/session event, manual lock, active job, and key-memory lifecycle tests.
  - Complete when every lock trigger closes sensitive UI access and unlock restores only authorized state.

- SECURITY-006: Add optional Touch ID adapter and safe disabled mode
  - Isolate LocalAuthentication/Keychain behavior behind platform contracts with master-password fallback.
  - Ensure biometric-set changes invalidate quick unlock and Touch ID never replaces recovery or the LexLocal password.
  - Provide a safe disabled adapter when packaged-platform requirements cannot be met.
  - Add mocked adapter tests; declare enabled support complete only after packaged `.app` SG-4 validation.
  - Complete when absence/failure cannot lock users out or weaken key handling.

- WORKSPACE-002: Implement rename, archive, and reactivate lifecycle
  - Rename without changing stable ID, storage references, citations, or indexes.
  - Archive with confirmation, preserve all history, remove from normal active list, and block new RAG/analysis until reactivated.
  - Keep archive distinct from deletion and log only approved activity metadata.
  - Add capability matrix, active-operation guard, restart, citation, and workspace isolation tests.
  - Complete when archived workspaces are read-only for new AI work and reactivate safely.

- DOCUMENT-003: Implement individual document deletion
  - Show impact, require approved confirmation, and run a recoverable deletion task.
  - Remove source-derived sensitive rows/files/index data while preserving only approved tombstones and historical unavailability semantics.
  - Mark affected current analysis stale without redirecting citations.
  - Add success, interruption, retry, missing-file, historical citation, key/fingerprint cleanup, and leakage tests.
  - Complete when deleted content is cryptographically inaccessible and no derived sensitive payload remains.

- WORKSPACE-003: Implement permanent workspace deletion and cryptographic erasure
  - Transition through `DELETING`, block normal capability, delete owned rows/files, and destroy workspace key material.
  - Require strong confirmation and report partial failure through a persistent recoverable deletion task.
  - Do not claim physical overwrite guarantees on SSDs; prove cryptographic inaccessibility and approved cleanup.
  - Add interruption at every phase, restart recovery, cross-workspace safety, key destruction, orphan, and leakage tests.
  - Complete when no workspace-sensitive content is decryptable or reachable and unrelated workspaces remain intact.

- HISTORY-003: Implement workspace activity timeline
  - Record approved lifecycle, processing, chat, analysis, security, and deletion events with workspace scope and safe metadata.
  - Exclude document text, prompts, answers, keys, recovery material, and sensitive filenames/paths where prohibited.
  - Provide documented filters and links only to still-authorized entities.
  - Add event mapping, redaction, ordering, filter, deleted-target, and workspace isolation tests.
  - Complete when users can understand significant actions without turning the timeline into a sensitive audit log.

- RECOVERY-001: Implement Limited Mode and secure Recovery Mode
  - Derive capability gates from model health, security profile, storage integrity, deletion tasks, and migration/startup checks.
  - Limited Mode must allow safe metadata/security/model repair actions but block ingestion, OCR, embedding, Q&A, and analysis.
  - Recovery Mode must fail closed on authenticated-data failure and expose only approved repair/reset actions.
  - Add model-loss, tamper, partial restore, interrupted deletion, retry, restart, and no-cloud-fallback tests.
  - Complete when startup failures cannot silently open normal workspace capability.

- UI-006: Deliver lifecycle, security settings, history, and recovery workflows
  - Implement security settings, manual lock, delay/recovery UI, archive/reactivate, deletion impact/confirmation/progress, activity timeline, Limited Mode, and Recovery Mode.
  - Use actionable safe messages and protect against accidental irreversible actions.
  - Clear sensitive presentation state immediately on lock or deletion transition.
  - Add Qt workflow, destructive-confirmation, recovery, focus, and manual restart tests.
  - Complete when approved Parts I–III, VII, and recovery flows are demonstrable.

- SECURITY-007: Execute SG-2 and SG-3 verification
  - Run recovery rotation, password change, auto/manual lock, progressive delay, job lease, deletion recovery, key destruction, and plaintext leakage suites.
  - Inspect SQLite/WAL, controlled storage, temp roots, caches, logs, and packaged diagnostics using forbidden synthetic markers.
  - Retain sanitized gate evidence and explicit limitations.
  - Complete when SG-2 and SG-3 pass with no unresolved required finding.

### Milestone acceptance criteria

- Password/recovery rotation, progressive delay, and manual/automatic lock match
  the approved flows.
- Archive is reversible and distinct from deletion.
- Document/workspace deletion is recoverable when interrupted and produces
  cryptographic erasure without cross-workspace damage.
- Limited/Recovery modes fail closed and activity history contains no prohibited content.
- Security Gates SG-2 and SG-3 pass.

### Required verification

- Credential, session, capability, activity, and lifecycle unit tests.
- Security, plaintext leakage, deletion, restart, and recovery integration tests.
- Temporary-database and controlled-storage failure injection.
- Qt security/lifecycle workflow tests.
- Architecture tests, Ruff, mypy, and full pytest suite.
- SG-2 and SG-3 evidence review; SG-4 only if Touch ID is enabled.

### Out of scope

- Multi-user authentication, role-based access, remote administration, cloud
  backup, workspace export/import, physical SSD overwrite guarantees, and
  automatic application updates.

## M7 — Complete Desktop Product Workflows

### Goal

Connect all implemented capabilities into a coherent, accessible desktop
product with first-run model setup, dashboard/navigation, capability-aware
states, settings, and consistent error handling.

### User-visible outcome

A user can install/open LexLocal, complete setup, understand model and security
status, manage the full workspace/document/chat/analysis lifecycle, and recover
from expected errors without using developer tools.

### Dependencies

- M1 through M6 application services and persisted state machines.
- Approved user flows and message catalog in `03_USER_FLOWS_AND_STATES.md`.

### Tickets

- FOUNDRY-003: Implement first-run local model setup and health repair
  - Check runtime, release-manifest aliases/versions, cache, compatibility, disk space, preparation/download, integrity where supported, and local inference.
  - Show explicit phases and allow completed security setup to enter Limited Mode when model setup fails.
  - Never report offline status based only on cached mode and never add cloud fallback.
  - Add fake-runtime state tests, interrupted setup/repair tests, and recorded online/offline hardware validation.
  - Complete when setup and repair resolve exact model identities and capability state honestly.

- UI-007: Implement application shell and navigation
  - Build unlock/setup, dashboard, archived workspaces, settings, security, model status, and active-workspace navigation.
  - Keep the active workspace visible and prevent stale view state from crossing workspace boundaries.
  - Restore only safe navigation state after restart or unlock.
  - Add navigation, workspace switch, lock, Limited Mode, empty-state, and restart tests.
  - Complete when every first-release area is reachable through normal UI navigation.

- UI-008: Complete workspace dashboard and empty/disabled states
  - Implement no-workspace, empty workspace, no-ready-document, no-chat, no-analysis, archived, deleting, and recovery states.
  - Derive enabled actions from application capability/state rather than duplicating business rules in widgets.
  - Provide documented calls to action and active-operation guards.
  - Add capability matrix and Qt state tests.
  - Complete when users cannot invoke an operation in a prohibited state.

- UI-009: Standardize progress, cancellation, and actionable errors
  - Apply consistent progress and cancellation behavior to model setup, ingestion, OCR, Q&A, analysis, and deletion.
  - Map typed failures to friendly messages explaining safety, retry, and next action while keeping safe technical details separate.
  - Prevent raw exceptions, prompts, document text, secrets, and local paths from appearing in normal UI.
  - Add error mapping, cancellation race, duplicate notification, and sensitive-output tests.
  - Complete when failure behavior is consistent across all long-running workflows.

- SETTINGS-001: Complete validated application and workspace settings
  - Expose only documented configurable values such as inactivity timeout, retrieval top-K/threshold controls where user-facing, processing limits, and model status.
  - Validate configuration at its boundary and preserve safe defaults/migrations.
  - Separate global preferences from workspace/profile state.
  - Add invalid-value, restart persistence, migration, and capability-impact tests.
  - Complete when settings cannot create unsupported or unsafe runtime states.

- UI-010: Perform accessibility and desktop UX hardening
  - Verify keyboard navigation, focus order, readable scaling, light/dark contrast, labels, Turkish messages, progress feedback, and destructive confirmations.
  - Remove blocking keyboard traps and ensure source/citation navigation remains usable without a pointer.
  - Record remaining limitations against approved benchmarks.
  - Complete when core workflows pass the documented accessibility/basic UX checklist.

- DIAGNOSTICS-001: Implement safe diagnostics and performance instrumentation
  - Separate technical diagnostics from user activity history and use structured non-sensitive identifiers/stage/timing fields.
  - Provide approved diagnostic export without document content, prompts, answers, keys, recovery material, or decrypted paths.
  - Instrument extraction, OCR, embedding, retrieval, inference, analysis, and startup for M8 benchmarks.
  - Add redaction/leakage, export, rotation, performance-field, and repeated-handler tests.
  - Complete when failures and benchmarks are diagnosable without leaking protected content.

### Milestone acceptance criteria

- Every approved first-release workflow is accessible without developer tools.
- UI capability and error states reflect the persisted/application state machines.
- Model failure leads to Limited Mode, not cloud fallback or silent queueing.
- Long-running work remains responsive, cancellable where approved, and safe on failure.
- Core keyboard, focus, scaling, language, and destructive-confirmation checks pass.

### Required verification

- Presenter/view-model and capability unit tests.
- Qt startup, navigation, workflow, cancellation, and error-state tests.
- Sensitive UI/diagnostic leakage tests.
- Manual desktop UX and accessibility smoke checks.
- Online first-run and strict offline restart validation.
- Ruff, mypy, full pytest, and architecture tests.

### Out of scope

- Final visual branding perfection, mobile/web clients, collaboration, cloud
  services, automatic updates, store distribution, and advanced analytics.

## M8 — Evaluation, Packaging, and Release Readiness

### Goal

Lock measurable release criteria, validate the complete encrypted offline product
on supported macOS environments, package it as a clean-installable `.app` and
`.dmg`, and retain reproducible sanitized release evidence.

### User-visible outcome

A user can install LexLocal on a supported Mac, complete setup, use every core
workflow offline after model preparation, upgrade without losing data, diagnose
safe failures, and uninstall according to documented instructions.

### Dependencies

- All functional milestones M1 through M7.
- SG-1 through SG-3; SG-4 if Touch ID is enabled.
- Resolved release model/runtime/dependency and hardware decisions.

### Tickets

- EVALUATION-004: Lock datasets, thresholds, and traceability
  - Resolve every release-blocking `TBD-BENCHMARK` for OCR, retrieval, sufficiency, answers, citations, analysis, performance, and accessibility.
  - Version datasets/configuration and map approved requirements to automated/manual evidence.
  - Record approver, environment, model identities, and limitations without retaining sensitive content.
  - Complete when no release acceptance criterion depends on an unresolved threshold.

- PERFORMANCE-001: Benchmark documented workload and resource behavior
  - Measure startup, ingestion, OCR, embedding, retrieval, first token/answer, analysis, memory, disk growth, and cancellation on the reference Mac.
  - Determine and document minimum macOS, Apple Silicon, RAM, free-disk, and workload guidance from evidence.
  - Verify configurable soft limits fail safely without partial activation or UI lockup.
  - Complete when benchmark reports are reproducible and release claims match measured hardware.

- PACKAGING-001: Build and validate the macOS `.app`
  - Package Python, PySide6/Qt PDF, SQL migrations, OCR runtime/languages, application resources, and release configuration.
  - Ensure release composition rejects development encryption, unpinned model metadata, and missing required resources.
  - Verify app data paths/permissions, controlled storage, logs, migrations, and subprocess/native resource lookup from the packaged app.
  - Complete when the `.app` launches and core workflows work outside the source checkout.

- PACKAGING-002: Produce controlled `.dmg` installation and uninstall guidance
  - Build the documented DMG, retain package hash, and document install, first run, model preparation, data location, and uninstall behavior.
  - State signing/notarization limitations honestly; do not imply App Store distribution.
  - Test clean-user installation and removal without deleting user data unless explicitly requested.
  - Complete when a reviewer can install and remove the application using release documentation.

- RELEASE-001: Verify upgrade and migration behavior
  - Install the previous supported package/data fixture, upgrade to the candidate, and run forward-only migrations through real startup.
  - Verify checksum/history validation, rollback/fail-closed behavior, encrypted payload compatibility, and no silent data loss.
  - Document that downgrade is unsupported unless a future explicit design adds it.
  - Complete when supported upgrade paths preserve usable workspaces and failed migration prevents normal startup safely.

- RELEASE-002: Execute clean-machine and offline release smoke tests
  - Validate first-run online model preparation, then deny network access and exercise restart, unlock, import/OCR, retrieval/Q&A, analysis, history, and deletion.
  - Test Qt PDF, OCR `tur+eng`, Foundry catalog/cache, permissions, paths, encryption, and migration resources on a clean user profile and second Mac where available.
  - Record external network-denial mechanism; cached-only mode alone is not strict offline evidence.
  - Complete when core release workflows pass without network after setup.

- SECURITY-008: Perform final security and dependency review
  - Run SG-1 through SG-3 again on packaged composition and SG-4 if Touch ID is enabled.
  - Review pinned dependencies, vulnerability/license evidence, key lifecycle, temporary data, logs/diagnostics, deletion, reset, and plaintext scans.
  - Verify unknown/tampered formats and lost credentials fail according to approved recovery/reset rules.
  - Complete when no unresolved required security finding remains and limitations are documented honestly.

- RELEASE-003: Assemble release documentation and evidence
  - Update README/setup, architecture diagram, release manifest, supported environment, model identities, benchmark results, known limitations, security language, demo dataset, and demo script.
  - Retain sanitized test reports, traceability, migration checks, leakage scans, package hashes, offline evidence, and gate sign-offs.
  - Rehearse the complete demonstration without real confidential documents.
  - Complete when another person can install, verify, operate, and evaluate the release from the retained artifacts.

### Milestone acceptance criteria

- All first-release scope and locked evaluation thresholds pass.
- The packaged `.app`/`.dmg` works on the documented supported Mac baseline and
  a clean user profile.
- Core functionality works under externally enforced network denial after setup.
- Upgrade migrations preserve data or fail closed without normal startup.
- Required security gates and plaintext scans pass on release composition.
- Release claims, known limitations, model identities, package hashes, and
  sanitized evidence are complete and reproducible.

### Required verification

- Full unit, integration, architecture, UI, security, deletion, recovery, and evaluation suites.
- Ruff, mypy, branch coverage, migration integrity, and package-resource checks.
- Clean-install, upgrade, uninstall, second-Mac, and strict offline smoke tests.
- OCR/RAG/citation/analysis and performance benchmark reports.
- Security gate, dependency, plaintext-leakage, and release-manifest reviews.
- Manual end-to-end demo rehearsal.

### Out of scope

- Windows packaging, App Store distribution, automatic updates, air-gapped model
  installer, SaaS/cloud deployment, team administration, mobile clients,
  workspace transfer/export, and features listed as future-only in the approved scope.
