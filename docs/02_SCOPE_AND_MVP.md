# LexLocal — Scope and First Complete Release Specification

**Document ID:** `02_SCOPE_AND_MVP.md`  
**Project:** LexLocal — On-Device Legal Document Intelligence Workspace  
**Status:** Approved scope baseline for implementation  
**Primary platform:** macOS  
**Initial user model:** Single user, single device  
**Core technologies:** Microsoft Foundry Local, Local RAG, Python, SQLite, local OCR, encrypted local storage  

---

## 1. Document Purpose and Authority

This document defines the complete functional and non-functional scope of LexLocal's first deliverable.

In this project, **MVP does not mean a reduced proof of concept**. It means the first complete release that:

1. satisfies the mandatory Microsoft Foundry Local and Local RAG project requirements,
2. implements the agreed LexLocal-specific product workflows,
3. can be tested, documented, demonstrated, and evaluated as a coherent desktop application.

This document is the authoritative scope baseline for implementation. If it conflicts with preliminary statements in `01_PROJECT_CHARTER.md`, this document governs the first release.

In particular, this specification intentionally updates earlier preliminary assumptions concerning:

- OCR support,
- supported input formats,
- analysis profiles,
- document and analysis versioning,
- security and encryption,
- application authentication,
- workspace archiving,
- persistent chat sessions,
- recovery behavior,
- and delivery expectations.

Detailed UI design, database column definitions, exact library selection, and final model selection belong to later technical documents. They must not change the scope defined here without an explicit scope change.

---

## 2. Requirement Language

The keywords below are used consistently:

- **MUST:** Required for the first complete release.
- **MUST NOT:** Prohibited in the first complete release.
- **SHOULD:** Strongly recommended; omission requires a documented technical reason.
- **MAY:** Optional or implementation-dependent.
- **Future-ready:** Not implemented in the first release, but the architecture must not make it unnecessarily difficult to add later.

---

## 3. Product Definition

LexLocal is an offline-first desktop application that enables legal professionals to work with multiple confidential legal documents in isolated local workspaces.

The application provides:

- local document ingestion,
- direct PDF text extraction,
- local OCR for scanned documents and images,
- page-aware chunking,
- local embeddings,
- SQLite-backed storage,
- cosine-similarity top-K retrieval,
- source-grounded question answering through Microsoft Foundry Local,
- verifiable document/page/passage citations,
- profile-specific structured legal analysis,
- analysis version history,
- persistent workspace-specific chat sessions,
- encrypted local storage,
- and controlled data deletion.

LexLocal is a document intelligence and decision-support tool. It is not a lawyer replacement, a legal advice service, or a case outcome prediction system.

---

## 4. Target User and Initial Operating Model

### 4.1 Primary Users

The product is designed for legal professionals, including:

- independent lawyers,
- small legal teams,
- small and medium-sized law firms,
- and in-house legal professionals working with confidential document collections.

### 4.2 Initial User Model

The first release is a **single-user desktop application**.

The release does not include:

- multi-user accounts,
- tenant separation,
- role-based access control,
- team collaboration,
- or centralized administration.

### 4.3 Human Responsibility

The user remains responsible for:

- confirming that they have authority to process the documents,
- reviewing OCR results,
- verifying cited source passages,
- reviewing generated analysis,
- and making all legal judgments.

Generated output must be presented as assistance, not authoritative legal advice.

---

## 5. Supported Platform and Deployment

### 5.1 Initial Platform

The first release MUST be:

- developed primarily on macOS,
- packaged for macOS,
- and validated on the documented macOS test machine.

Windows packaging and Windows validation are not part of the first release.

### 5.2 Cross-Platform-Friendly Design

Although macOS is the delivery platform, the codebase MUST avoid unnecessary platform lock-in.

Examples:

- no hard-coded `/Users/<name>/...` paths,
- use application data directory abstractions,
- use relative storage references,
- isolate macOS-specific functionality behind interfaces,
- isolate Touch ID and Keychain integration behind platform adapters,
- keep document processing, RAG, analysis, and persistence logic independent from the UI framework.

### 5.3 Foundry Local and Model Setup

The standard distribution model is:

1. install LexLocal,
2. start LexLocal,
3. verify Foundry Local runtime availability,
4. download and prepare the required local model(s) during first-run setup,
5. complete setup,
6. use core functionality offline afterward.

The application package MUST NOT be required to contain the full language model.

The setup flow SHOULD verify:

- runtime availability,
- required model availability,
- model version compatibility,
- sufficient disk space,
- download completion,
- file integrity where supported,
- and successful local inference.

The first model/runtime setup may require internet access. After successful setup, the following core operations MUST work without an active internet connection:

- document extraction,
- OCR,
- chunking,
- embedding,
- retrieval,
- question answering,
- structured analysis,
- document classification suggestions,
- workspace and chat management.

No cloud LLM fallback is allowed.

A future air-gapped installer may bundle models for environments that cannot access the internet even during setup.

---

## 6. Core User Workflows

### 6.1 First-Run Security Setup

1. User launches LexLocal.
2. User creates a LexLocal master password.
3. LexLocal generates the required encryption key material.
4. LexLocal generates a recovery key.
5. User is required to save and confirm the recovery key.
6. User may enable Touch ID as an optional quick-unlock method.
7. User completes local model setup.
8. The application opens the workspace dashboard.

### 6.2 Workspace Workflow

1. User creates a workspace.
2. User names the workspace.
3. User selects an analysis profile manually or requests a local AI suggestion.
4. User adds one or more documents.
5. Documents are validated, copied into controlled encrypted storage, processed, and indexed.
6. User asks questions, creates chats, and generates structured analysis.
7. User reviews citations and source documents.
8. User may edit analysis, create new analysis versions, archive the workspace, reactivate it, or permanently delete it.

### 6.3 Document Update Workflow

1. User selects an existing document.
2. User explicitly chooses **Replace with New Version**.
3. User selects the new file.
4. The new version is processed independently.
5. If processing succeeds:
   - the previous active version becomes archived,
   - the new version becomes active,
   - new retrieval uses only the new version.
6. If processing fails:
   - the previous version remains active,
   - no partial new version enters retrieval.

### 6.4 Question-Answer Workflow

1. User selects the active workspace.
2. User optionally restricts the query to selected documents.
3. LexLocal embeds the query with the same embedding model used for chunks.
4. LexLocal retrieves top-K relevant chunks from SQLite using cosine similarity.
5. LexLocal evaluates evidence sufficiency.
6. If sufficient, Foundry Local generates a grounded answer using retrieved context only.
7. LexLocal displays validated citations.
8. User may open the document, page, and supporting passage.
9. If evidence is insufficient, LexLocal does not answer from general model knowledge.

### 6.5 Structured Analysis Workflow

1. User explicitly starts analysis generation.
2. LexLocal applies the active analysis profile.
3. LexLocal performs targeted retrieval and structured extraction.
4. For long multi-document workspaces, LexLocal uses hierarchical summarization rather than relying only on one top-K retrieval call.
5. The generated analysis is saved locally with citations.
6. User may edit the analysis.
7. User may regenerate one section or the entire analysis.
8. Each saved or regenerated state creates a version according to the versioning rules.

---

## 7. Workspace Requirements

### 7.1 Multiple Workspaces

- The application MUST support multiple workspaces.
- Only one workspace is active at a time.
- Every RAG, analysis, chat, and document operation MUST be scoped to the active workspace.
- Data from another workspace MUST NOT be retrieved, shown, or used as context.

### 7.2 Workspace Properties

A workspace MUST have at least:

- stable unique identifier,
- display name,
- status,
- active analysis profile,
- creation timestamp,
- modification timestamp,
- and encryption-key reference metadata.

### 7.3 Workspace Statuses

At minimum:

- `ACTIVE`
- `ARCHIVED`
- `DELETING`
- `DELETED` or physically removed

### 7.4 Rename

The user MUST be able to rename a workspace.

Renaming MUST NOT:

- change the workspace identifier,
- break document references,
- break citations,
- or require re-indexing.

### 7.5 Archive and Reactivate

The user MUST be able to archive a workspace.

Archiving:

- removes it from the normal active list,
- preserves all documents, chats, analyses, versions, citations, and activity events,
- prevents normal new RAG or analysis operations until reactivated,
- and is reversible.

Archiving is not deletion.

### 7.6 Workspace Transfer

Workspace export/import and device-to-device transfer are not implemented in the first release.

However, implementation MUST remain future-ready by using:

- stable identifiers,
- relative storage references,
- structured metadata,
- independently reproducible embeddings and indexes,
- and a storage service instead of direct file-path logic throughout the application.

---

## 8. Supported Input Files

### 8.1 Supported Formats

The first release MUST support:

- PDF,
- JPEG/JPG,
- PNG.

### 8.2 Unsupported Formats

The first release does not support ingestion of:

- DOCX,
- XLSX,
- email files,
- ZIP archives,
- audio,
- video,
- or other document formats.

### 8.3 Controlled Local Copy

Imported files MUST be copied into LexLocal-controlled local storage.

The system MUST NOT depend only on the original external path because the original may be:

- moved,
- renamed,
- deleted,
- disconnected,
- or modified outside LexLocal.

### 8.4 Validation

Before processing, the system MUST validate at least:

- file existence,
- supported extension and detected content type,
- readable file structure,
- non-zero size,
- available disk space,
- duplicate content within the target workspace,
- and whether the file is password-protected or otherwise inaccessible.

### 8.5 Hashing and Duplicate Detection

A cryptographic content hash, such as SHA-256, MUST be calculated before or during import.

The hash is used for:

- duplicate detection,
- integrity checks,
- version metadata,
- and change tracking.

At minimum, exact duplicate content within the same workspace MUST be detected.

Cross-workspace duplicate policy may be defined later, but workspace isolation must be preserved.

### 8.6 Password-Protected or Encrypted Input Files

Password-protected or input-encrypted documents are not decrypted inside the first release.

The application MUST show a clear message requesting an unlocked copy.

### 8.7 Corrupt or Unreadable Files

Corrupt or unreadable files:

- MUST NOT enter the active retrieval index,
- MUST receive a failed processing status,
- MUST show an understandable error,
- and MUST support removal or retry after the user supplies a valid file.

---

## 9. Text Extraction and OCR

### 9.1 Hybrid Page-Level Strategy

LexLocal MUST not apply OCR blindly to every PDF.

For each PDF page:

1. attempt native text extraction,
2. evaluate whether the extracted text is usable,
3. use native text when usable,
4. invoke local OCR when text is missing or insufficient.

This allows mixed PDFs to be processed page by page.

Example:

```text
Page 1 -> native PDF text
Page 2 -> OCR
Page 3 -> native PDF text
Page 4 -> OCR
```

### 9.2 Image Inputs

JPEG and PNG inputs require OCR to become searchable.

An image source must retain enough source metadata to open and verify the original image.

### 9.3 OCR Scope

The first release targets:

- clear scanned documents,
- printed Turkish text,
- printed English text,
- normal page orientation or modest correctable rotation,
- and readable image quality.

### 9.4 OCR Limitations

The first release does not guarantee:

- handwriting recognition,
- seal or signature recognition,
- perfect processing of blurred or severely skewed scans,
- perfect preservation of complex table structure,
- perfect reading of dates, amounts, names, or identifiers,
- or legally error-free OCR output.

### 9.5 OCR Transparency

The application MUST identify pages that were processed by OCR.

The user MUST be able to open the original source and verify the page.

OCR text must never be presented as unquestionably accurate.

### 9.6 Partial Success

If some pages cannot be extracted or OCR-processed:

- usable pages MAY be indexed,
- the document MUST be marked `READY_WITH_WARNINGS`,
- failed or empty pages MUST be recorded,
- the user MUST see a clear coverage warning,
- citations MUST only point to successfully processed source content.

---

## 10. Document Processing Pipeline

### 10.1 Required Pipeline

The conceptual processing flow is:

```text
Desktop UI
    -> DocumentImportService
    -> ValidationService
    -> ControlledStorageService
    -> DocumentProcessingService
        -> NativeTextExtractor
        -> OcrTextExtractor
    -> TextNormalizationService
    -> ChunkingService
    -> EmbeddingService
    -> IndexingService
    -> Repository Layer
```

### 10.2 UI Separation

UI event handlers MUST NOT contain:

- parsing logic,
- OCR logic,
- chunking logic,
- embedding logic,
- direct SQL,
- encryption logic,
- or Foundry Local orchestration.

The UI may call application use cases or services and render their state.

### 10.3 Future Folder Watcher Compatibility

Manual file selection is the only ingestion trigger in the first release.

The import pipeline MUST be designed so that a future `FolderWatcher` can submit discovered files to the same `DocumentImportService`.

A future watcher must not require rewriting:

- validation,
- storage,
- OCR,
- chunking,
- embedding,
- indexing,
- or rollback logic.

### 10.4 Background Processing

Long-running document work MUST execute outside the main UI thread.

The UI MUST remain responsive while:

- OCR is running,
- chunks are being created,
- embeddings are being generated,
- and indexes are being updated.

### 10.5 Processing Statuses

At minimum:

```text
QUEUED
PROCESSING
READY
READY_WITH_WARNINGS
FAILED
CANCELLED
```

An implementation MAY use more detailed internal stages, such as:

```text
VALIDATING
COPYING
EXTRACTING
OCR_PROCESSING
CHUNKING
EMBEDDING
INDEXING
FINALIZING
```

### 10.6 Active Index Rule

Only documents and document versions in a successful active state may be used for new retrieval.

Partial records MUST NOT become visible to the retrieval layer.

### 10.7 Cancellation

The user MUST be able to cancel a running document-processing job.

Cancellation behavior:

- stop at a safe cancellation point,
- prevent progression to later stages,
- remove partial derived data,
- mark the job/document version `CANCELLED`,
- leave unrelated ready documents usable,
- allow a later retry.

### 10.8 Failure and Retry

A failed job MUST:

- preserve a user-readable failure reason,
- not expose partial index data,
- not deactivate a previously valid active version,
- and offer a retry action where appropriate.

### 10.9 Restart Recovery

If the application closes or crashes during processing:

- incomplete `PROCESSING` jobs MUST be detected on restart,
- incomplete data MUST remain excluded from retrieval,
- the user MUST be offered restart-from-beginning or removal,
- the first release is not required to resume from the exact page/checkpoint.

Checkpoint-based resume is a future enhancement.

### 10.10 Idempotency

Retrying the same processing request MUST not create duplicate chunks, embeddings, or active versions.

---

## 11. Chunking, Embeddings, SQLite, and Retrieval

### 11.1 Page-Aware Chunking

Chunks MUST preserve:

- workspace identifier,
- document identifier,
- document version identifier,
- page number or image-source locator,
- chunk identifier,
- chunk text,
- ordering information,
- and extraction method metadata where relevant.

Chunking SHOULD consider:

- headings,
- paragraphs,
- legal section boundaries,
- page boundaries,
- and limited overlap.

Exact chunk size and overlap are configuration values and must be tuned through evaluation.

### 11.2 Local Embeddings

Document chunks and user queries MUST be embedded locally.

The same compatible embedding model/version MUST be used for:

- indexed document chunks,
- and query vectors.

Model identity and version MUST be stored as index metadata.

### 11.3 SQLite Persistence

To satisfy the required project architecture, SQLite MUST persist at least:

- chunk text or encrypted chunk payload,
- chunk metadata,
- embedding vector representation,
- document and version relationships,
- and index/model metadata.

Embedding storage may use a BLOB or another documented SQLite-compatible representation.

### 11.4 Cosine Similarity and Top-K

The first release MUST include a working retrieval path that:

1. embeds the query,
2. loads eligible embeddings from the active workspace and document scope,
3. computes cosine similarity in Python,
4. ranks results,
5. returns top-K chunks.

This path is required even if a future optimized vector extension is later introduced.

### 11.5 Retrieval Scope

Default retrieval scope:

- active workspace,
- active document versions,
- all eligible ready documents.

The user MAY restrict retrieval to one or more selected documents.

Archived document versions MUST NOT be used for new retrieval.

### 11.6 Configurable Retrieval Parameters

At minimum, the following must be configurable:

- top-K,
- chunk size,
- chunk overlap,
- minimum evidence threshold values,
- and optional maximum context size.

Values must not be scattered as unexplained magic numbers throughout the code.

---

## 12. Evidence Sufficiency and Grounding

### 12.1 Terminology

The product MUST use the term **evidence sufficiency**, not **model confidence**, for retrieval-based answer gating.

A similarity score is not a probability that the answer is correct.

### 12.2 Evidence States

At minimum:

- `SUFFICIENT`
- `RELATED_BUT_INSUFFICIENT`
- `INSUFFICIENT`

### 12.3 Required Behavior

#### Sufficient Evidence

The application may produce:

- a direct grounded answer,
- supporting citations,
- and source passages.

#### Related but Insufficient Evidence

The application MUST NOT present a definitive answer.

It should state that related information was found but is insufficient, then show the relevant passages and citations.

#### Insufficient Evidence

The application MUST clearly state that the documents do not contain enough information.

It MUST NOT answer from general model knowledge.

### 12.4 Calibration

Thresholds must be:

- configurable,
- evaluated against a controlled test set,
- and documented with the chosen embedding model.

They must not be presented as universal accuracy guarantees.

---

## 13. Foundry Local Answer Generation

### 13.1 Foundry Local Role

Foundry Local is responsible for local inference used in:

- grounded answer generation,
- structured extraction,
- structured summarization,
- workspace profile suggestions,
- document type suggestions,
- and readable analysis change summaries where used.

### 13.2 Context-Only Instruction

The system prompt MUST instruct the model to:

- use only the supplied evidence,
- avoid unsupported claims,
- state when information is missing,
- keep claims traceable to provided evidence,
- and not provide authoritative legal advice.

### 13.3 No Cloud Fallback

If the local model is unavailable, incompatible, or fails:

- the application MUST show an actionable local error,
- MUST preserve user data,
- and MUST NOT send the request to a cloud model.

### 13.4 Citation Safety

Citations MUST be generated from application-controlled evidence metadata, not trusted solely as free-text citations invented by the model.

Preferred pattern:

1. assign stable evidence/chunk identifiers,
2. provide identifiers with context,
3. request structured answer output referencing evidence identifiers,
4. validate returned identifiers,
5. resolve identifiers to document/page/passage in the application.

Invalid evidence identifiers must not be displayed as real citations.

---

## 14. Citation Requirements

### 14.1 Citation Content

A normal citation MUST include:

- document name,
- exact document version reference internally,
- PDF page number or image-source locator,
- supporting passage,
- and stable evidence reference.

### 14.2 Citation Interaction

When the user activates a citation, the application MUST:

- open the correct source document or image,
- navigate to the relevant PDF page where applicable,
- display the supporting passage in a source panel,
- and preserve the connection between answer and source.

### 14.3 Multiple Sources

When more than one source supports an answer, each source must be shown separately.

### 14.4 No Fabricated Pages

If a page cannot be reliably determined, the system MUST NOT invent one.

### 14.5 Structured Analysis Citation Strategy

Structured analysis uses a hybrid citation model:

- concrete important findings receive finding-level citations,
- broader synthesis paragraphs or sections receive section-level citations,
- citation activation opens the relevant source.

Citations are stored independently from editable analysis text so that user edits do not silently corrupt source references.

---

## 15. Persistent Chat Sessions

### 15.1 Multiple Chats per Workspace

Each workspace MUST support multiple persistent chat sessions.

Examples:

- Termination Clauses
- Expert Report Review
- Plaintiff Claims
- Important Dates

### 15.2 Chat Rules

A chat session:

- belongs to exactly one workspace,
- cannot be moved to another workspace,
- persists across application restarts,
- may be renamed,
- may be deleted individually,
- may restrict retrieval to selected documents.

### 15.3 Stored Answer Context

Stored answers MUST retain:

- answer text,
- citations,
- cited chunk identifiers,
- cited document version identifiers,
- timestamp,
- and relevant retrieval scope metadata.

### 15.4 Archived Source Versions

An old answer must continue to reference the exact document version used when it was generated.

The system MUST NOT silently redirect an old citation to a newer version.

The exact UI for opening archived-source citations may be refined later, but the data model must preserve the original version reference.

---

## 16. Workspace Analysis Profiles

### 16.1 Required Profiles

The first release MUST include:

1. **Litigation Case**
2. **Contract Review**
3. **General Legal Matter**

### 16.2 Profile Selection

The user may:

- select a profile manually,
- or request a local Foundry Local profile suggestion after documents are available.

AI suggestions are not final.

The user MUST confirm or change the profile.

### 16.3 Profile Effect

The active profile affects:

- structured analysis schema,
- analysis prompts,
- targeted retrieval strategy,
- extraction targets,
- and UI labels or suggestions.

It MUST NOT change:

- ingestion,
- source storage,
- base chunking,
- embedding,
- or index format.

Changing the profile does not require re-indexing.

It may mark an existing structured analysis stale and require regeneration.

---

## 17. Document Type Suggestions

### 17.1 Supported Type Suggestions

The system may suggest types such as:

- petition,
- response petition,
- contract,
- expert report,
- court decision,
- notice,
- evidence or attachment,
- other.

### 17.2 Evidence Priority

Suggestion logic should prioritize:

1. document content and structure,
2. title and first pages,
3. filename as a low-weight auxiliary signal.

### 17.3 User Confirmation

The suggestion MUST NOT be automatically finalized.

The user may confirm or change it.

### 17.4 Effect of Document Type

Document type is metadata used for:

- filtering,
- analysis targeting,
- and display.

Changing the type MUST NOT require re-indexing.

---

## 18. Structured Legal Analysis

### 18.1 Nature of Analysis

Structured analysis is a persistent workspace report.

It is not:

- a temporary chat message,
- a legal opinion,
- an autonomous legal decision,
- or a replacement for reviewing source documents.

### 18.2 Litigation Case Schema

The litigation profile should cover, where supported by evidence:

- case or matter information,
- parties and roles,
- dispute overview,
- event chronology,
- claimant/plaintiff claims,
- respondent/defendant defenses,
- contested issues,
- important dates and deadlines,
- evidence and supporting documents,
- requests or relief sought,
- procedural status,
- unclear or missing information,
- sources.

### 18.3 Contract Review Schema

The contract profile should cover, where supported by evidence:

- parties,
- subject and purpose,
- obligations,
- payment terms and amounts,
- effective date,
- term and renewal,
- termination,
- liability,
- penalties or liquidated damages,
- risk areas,
- missing or unclear clauses,
- important dates,
- sources.

### 18.4 General Legal Matter Schema

The general profile should cover, where supported by evidence:

- key entities,
- matter overview,
- events,
- important dates,
- obligations,
- amounts,
- legal issues visible in the documents,
- open questions,
- missing information,
- sources.

### 18.5 Generation Strategy

Whole-workspace analysis MUST NOT rely only on a single top-K query.

It should use:

- profile-specific targeted retrieval,
- structured extraction,
- per-document or per-section intermediate summaries,
- hierarchical synthesis,
- and evidence-linked output.

### 18.6 User-Initiated Generation

Analysis is generated only when the user explicitly requests it.

Document changes MUST NOT silently overwrite the current analysis.

---

## 19. Analysis Editing, Staleness, and Version History

### 19.1 Editing

The user MUST be able to edit every analysis section.

The system MUST distinguish:

- AI-generated original content,
- user-modified content,
- and source citations.

Source documents remain read-only.

### 19.2 Regeneration

The user may regenerate:

- the entire analysis,
- or a selected section.

If regeneration would overwrite manual edits, the application MUST request confirmation.

### 19.3 Stale Analysis

An analysis becomes stale when relevant underlying state changes, including:

- document added,
- document removed,
- active document version changed,
- document content changed,
- or analysis profile changed.

The system MUST:

- mark the analysis as stale,
- preserve the existing analysis,
- not auto-overwrite it,
- offer full or section-level regeneration.

### 19.4 Version Creation Events

A new analysis version MUST be created when:

- full analysis is generated or regenerated,
- a section is regenerated,
- the user explicitly saves edits,
- an older version is restored.

No version is created for every keystroke.

### 19.5 Version Metadata

Each analysis version MUST store:

- version number,
- optional user label,
- timestamp,
- underlying document version set,
- profile,
- structured content,
- citations,
- trigger or reason,
- changed sections,
- and whether the change came from AI generation, user edits, or restoration.

### 19.6 Change Summaries

Structural differences MUST be detected deterministically in code.

Foundry Local MAY generate a readable summary of those detected changes, but the model must not be the only source of truth for determining what changed.

### 19.7 Restore Behavior

Restoring an older analysis version creates a new version.

History is not overwritten.

### 19.8 Excluded Git Complexity

The first release does not include:

- branches,
- merges,
- conflict resolution,
- or line-level Git behavior.

---

## 20. Workspace Activity History

### 20.1 User-Visible Timeline

Each workspace MUST include a user-visible activity history.

### 20.2 Events

At minimum, record significant events such as:

- workspace creation,
- rename,
- archive/reactivation,
- document import,
- OCR/extraction result,
- indexing result,
- document deletion,
- version replacement,
- profile selection or confirmation,
- document type confirmation,
- analysis generation,
- analysis version save,
- chat creation or deletion,
- processing failure,
- processing cancellation,
- permanent deletion initiation/result where safely possible.

### 20.3 Event Fields

Each event should include:

- event type,
- timestamp,
- related entity identifier,
- safe human-readable description,
- result/status.

### 20.4 Sensitive Data Exclusion

Activity logs MUST NOT contain:

- raw document text,
- full user questions,
- model prompts,
- LexLocal password,
- recovery key,
- encryption keys,
- decrypted payloads.

### 20.5 Audit Level

The activity history is append-only from the normal application UI.

A cryptographically signed, externally verifiable enterprise audit system is not required in the first release.

---

## 21. Security and Privacy Scope

### 21.1 Local-First Rule

LexLocal MUST NOT intentionally send the following to an external AI or cloud service:

- source documents,
- extracted text,
- OCR output,
- chunks,
- embeddings,
- user questions,
- chat content,
- structured analysis.

### 21.2 Sensitive At-Rest Data

The following MUST be encrypted at rest:

- source PDF/JPEG/PNG files,
- extracted native text,
- OCR text,
- chunks,
- embeddings,
- chat content,
- analyses and versions,
- citation passages,
- sensitive SQLite content,
- temporary persisted processing artifacts.

### 21.3 Standard Cryptography Only

The project MUST use standard, reviewed cryptographic primitives and libraries.

It MUST NOT implement a custom encryption algorithm.

Exact algorithm and library selection are defined in the security design, but the solution must provide authenticated encryption and an appropriate password-based key derivation method.

### 21.4 LexLocal Master Password

LexLocal MUST use its own master password.

The LexLocal master password:

- is independent from the macOS account password,
- is not stored in plaintext,
- is not replaced by the macOS password,
- is used through a secure key-derivation and key-wrapping design,
- is required as the fallback when Touch ID is unavailable or fails.

### 21.5 Touch ID

Touch ID is optional.

It is a quick-unlock convenience, not the identity foundation of the application.

Touch ID integration may use Keychain/Secure Enclave mechanisms behind a macOS adapter.

If Touch ID fails, the application requests the LexLocal master password, not the macOS password.

### 21.6 Recovery Key

The first release MUST include a recovery key.

Requirements:

- generated using a cryptographically secure random source,
- shown during setup,
- user required to save it,
- user required to confirm selected portions,
- not stored in plaintext by LexLocal,
- not emailed,
- not uploaded to a server,
- usable to establish a new LexLocal password,
- invalidated and replaced after successful recovery.

If both the LexLocal password and recovery key are lost, data may be unrecoverable. This must be communicated clearly.

### 21.7 Key Hierarchy Requirement

The implementation must use a separable key hierarchy rather than encrypting all data directly with the user's password.

Conceptually:

```text
LexLocal password
    -> password-based key derivation
    -> key-encryption key

Recovery key
    -> separate recovery key derivation
    -> recovery key-encryption key

Optional Touch ID
    -> secure local quick-unlock path

Key-encryption key(s)
    -> protect application/master key material

Application/master key material
    -> protects workspace-specific data keys

Workspace data key
    -> encrypts workspace documents and sensitive workspace payloads
```

Exact physical database layout is deferred, but workspace-specific cryptographic deletion must remain possible.

### 21.8 Secure Logging

Logs MUST NOT contain sensitive document or user content.

Technical logs may contain:

- event identifiers,
- safe status codes,
- exception class,
- non-sensitive component information.

### 21.9 Temporary Data

The implementation SHOULD avoid writing decrypted temporary files.

Where unavoidable:

- use controlled temporary storage,
- restrict lifetime,
- remove after success, cancellation, or failure,
- clean abandoned temporary data during startup recovery.

### 21.10 Security Claims

The product MUST NOT claim:

- automatic KVKK compliance,
- complete legal compliance,
- absolute protection against a compromised operating system,
- guaranteed physical secure erase from SSD blocks,
- or perfect AI/OCR accuracy.

---

## 22. Permanent Deletion and Cryptographic Erasure

### 22.1 Permanent Workspace Deletion

Permanent deletion MUST remove:

- encrypted source files,
- extracted text,
- OCR output,
- chunks,
- embeddings,
- index records,
- chats,
- messages,
- analyses,
- analysis versions,
- citations,
- document versions,
- activity records associated with the workspace,
- caches,
- temporary artifacts,
- workspace database records.

### 22.2 Workspace Key Destruction

The workspace-specific encryption key MUST be destroyed as part of permanent deletion.

This provides cryptographic erasure: any inaccessible encrypted residue should no longer be decryptable through LexLocal.

### 22.3 Confirmation

Before permanent deletion, the application MUST require:

- a clear irreversible-action warning,
- the LexLocal master password,
- and typing the workspace name or equivalent explicit confirmation.

### 22.4 No Physical Overwrite Guarantee

The application MUST NOT claim that every physical SSD block was overwritten.

Modern SSD wear leveling and filesystem behavior make that guarantee unreliable.

### 22.5 Document-Level Deletion

Deleting an individual document MUST remove its:

- active and derived data according to the selected deletion semantics,
- extracted/OCR text,
- chunks,
- embeddings,
- index membership,
- document-linked cached summaries,
- and citation relationships where appropriate.

The implementation must preserve historical consistency. If old immutable chat or analysis records reference a deleted source, the UI must not falsely resolve them to a different source. The detailed retention behavior for historical references will be defined in the data model and security design.

---

## 23. File and Capacity Limits

### 23.1 Soft, Configurable Limits

The first release MUST not rely on arbitrary hard-coded product limits such as:

- fixed maximum 50 documents,
- fixed maximum 200 pages,
- or fixed maximum 50 MB.

Instead:

- limits and warnings are configuration-driven,
- preflight checks estimate disk/resource requirements where possible,
- large jobs show warnings,
- processing stops safely if required resources are unavailable.

### 23.2 Safe Failure

Resource failure MUST NOT leave:

- partial active indexes,
- orphaned active versions,
- or corrupted workspace state.

### 23.3 Benchmark Scale

A controlled benchmark dataset will be defined during test planning.

The first release does not promise a universal maximum document count or fixed latency across all Macs.

---

## 24. Non-Functional Requirements

### 24.1 Offline Operation

After initial setup, core workflows MUST operate without internet access.

### 24.2 Responsiveness

The UI MUST remain responsive during long-running processing and model operations.

### 24.3 Persistence

After a normal restart:

- workspaces,
- documents,
- statuses,
- chats,
- analyses,
- versions,
- citations,
- and activity history

must remain available after successful unlock.

### 24.4 Isolation

Queries in one workspace MUST NOT retrieve content from another workspace.

This must be tested as a security and correctness requirement.

### 24.5 Reliability

Failed or cancelled processing MUST not expose incomplete content to retrieval.

### 24.6 Maintainability

The codebase MUST use:

- clear module boundaries,
- dependency inversion for infrastructure services,
- typed interfaces where practical,
- explicit state transitions,
- centralized configuration,
- consistent error handling,
- automated tests.

### 24.7 Observability Without Data Leakage

The application should provide useful diagnostics without logging sensitive content.

### 24.8 Performance Reporting

Performance must be measured and reported on documented hardware.

No arbitrary commercial SLA is declared before benchmarking.

---

## 25. Reference Software Architecture for Coding

This section defines implementation boundaries, not final class names.

### 25.1 Layering

```text
Presentation Layer
    Desktop windows, dialogs, view models, source viewer

Application Layer
    Use cases, orchestration, transactions, authorization of actions

Domain Layer
    Entities, value objects, state rules, policies, domain errors

Infrastructure Layer
    SQLite, encrypted storage, Foundry Local, OCR, PDF parsing,
    Keychain/Touch ID adapter, filesystem, background jobs
```

Dependencies should point inward:

```text
Presentation -> Application -> Domain
Infrastructure -> Application/Domain interfaces
```

The domain and application layers should not import UI framework modules.

### 25.2 Suggested Application Services

At minimum, the architecture should expose responsibilities equivalent to:

- `SecuritySetupService`
- `UnlockService`
- `RecoveryService`
- `WorkspaceService`
- `WorkspaceArchiveService`
- `WorkspaceDeletionService`
- `DocumentImportService`
- `DocumentValidationService`
- `DocumentVersionService`
- `DocumentProcessingService`
- `NativeTextExtractionService`
- `OcrService`
- `ChunkingService`
- `EmbeddingService`
- `IndexingService`
- `RetrievalService`
- `EvidenceSufficiencyPolicy`
- `AnswerGenerationService`
- `CitationService`
- `ChatService`
- `AnalysisService`
- `AnalysisVersionService`
- `ClassificationSuggestionService`
- `ActivityEventService`
- `ModelManagerService`
- `EncryptionService`
- `BackgroundJobService`

Exact names may change, but responsibilities must remain separated.

### 25.3 Example Use-Case Contracts

Illustrative Python-style contracts:

```python
class DocumentImportService:
    def import_files(
        self,
        workspace_id: str,
        source_paths: list[str],
    ) -> list[str]:
        # Create import jobs and return job identifiers.
        ...


class RetrievalService:
    def retrieve(
        self,
        workspace_id: str,
        query: str,
        document_ids: list[str] | None,
        top_k: int,
    ) -> list["RetrievedEvidence"]:
        # Return ranked evidence from active eligible document versions only.
        ...


class AnswerGenerationService:
    def answer(
        self,
        workspace_id: str,
        chat_id: str,
        question: str,
        document_ids: list[str] | None = None,
    ) -> "GroundedAnswer":
        # Return answer, evidence state, validated citations, and diagnostics.
        ...


class AnalysisService:
    def generate(
        self,
        workspace_id: str,
        section_ids: list[str] | None = None,
    ) -> "AnalysisVersion":
        # Generate a full or partial profile-specific analysis version.
        ...
```

These are architectural examples, not final signatures.

### 25.4 Repository Boundaries

UI and model orchestration code MUST NOT execute raw SQL directly.

Repositories should cover concepts such as:

- workspaces,
- documents and versions,
- pages and chunks,
- embeddings,
- chats and messages,
- citations,
- analyses and versions,
- jobs,
- activity events,
- security metadata.

### 25.5 Transaction Boundaries

Operations that change active state must be transactional.

Examples:

- replacing a document version,
- finalizing an index,
- activating a new analysis version,
- archiving a workspace,
- permanent deletion.

A new document version must not become active before all mandatory processing succeeds.

### 25.6 Configuration

Centralized configuration should include:

- model identifiers,
- embedding model identifier,
- chunk size,
- overlap,
- top-K,
- evidence thresholds,
- OCR languages,
- temporary directory policy,
- processing concurrency,
- soft resource limits.

Configuration must be validated at startup.

---

## 26. Conceptual Data Model

Exact tables are defined later, but the implementation must support these concepts.

### 26.1 Security

- `AppSecurityProfile`
- `WrappedMasterKey`
- `RecoveryKeyMetadata`
- `TouchIdUnlockMetadata`
- `WorkspaceKeyMetadata`

### 26.2 Workspace

- `Workspace`
- `WorkspaceProfile`
- `WorkspaceStatus`

### 26.3 Documents

- `Document`
- `DocumentVersion`
- `DocumentTypeSuggestion`
- `PageContent`
- `SourceLocator`
- `ProcessingJob`

### 26.4 Retrieval

- `Chunk`
- `Embedding`
- `EmbeddingModelMetadata`
- `IndexGeneration`
- `RetrievedEvidence`

### 26.5 Chat and Citation

- `ChatSession`
- `ChatMessage`
- `Citation`
- `EvidenceReference`

### 26.6 Analysis

- `StructuredAnalysis`
- `AnalysisSection`
- `AnalysisVersion`
- `AnalysisChangeRecord`
- `AnalysisCitation`

### 26.7 Audit

- `ActivityEvent`

### 26.8 Identifier Rule

Entities referenced by history or citations MUST use stable identifiers.

Display names and file paths are not stable identifiers.

---

## 27. Definition of Done

The first release is complete only when all applicable items below are demonstrated.

### 27.1 Application and Setup

- macOS application starts successfully,
- user can create a LexLocal master password,
- recovery key setup works,
- optional Touch ID path works where supported,
- Foundry Local model setup is validated,
- core operations work offline after setup.

### 27.2 Workspace

- multiple workspaces can be created,
- one active workspace is enforced,
- workspace rename works,
- archive and reactivate work,
- workspace isolation tests pass.

### 27.3 Documents

- PDF/JPEG/PNG can be imported,
- controlled encrypted copy is created,
- digital PDF extraction works,
- scanned PDF and images use local OCR,
- mixed PDF page-level fallback works,
- source metadata is preserved,
- duplicate/corrupt/protected file handling is clear,
- processing statuses are visible.

### 27.4 Processing Reliability

- UI remains responsive,
- cancellation works,
- failed jobs do not enter retrieval,
- retries do not duplicate derived data,
- restart recovery detects incomplete jobs.

### 27.5 RAG

- chunks and embeddings are stored in SQLite,
- query embedding uses the compatible model,
- cosine similarity top-K retrieval works,
- retrieval respects workspace and selected-document scope,
- archived versions are excluded,
- unsupported questions do not receive general-knowledge answers.

### 27.6 Citations

- answer citations resolve to correct source,
- PDF page or image source is shown,
- supporting passage is visible,
- invalid/fabricated source identifiers are rejected.

### 27.7 Chat

- multiple persistent chats per workspace work,
- rename and delete work,
- stored answers retain citations and document version identifiers.

### 27.8 Structured Analysis

- three profiles are available,
- profile suggestion requires user confirmation,
- profile-specific analysis can be generated,
- analysis is editable,
- full and section regeneration work,
- stale status works,
- version history works,
- restoration creates a new version,
- citations remain source-linked.

### 27.9 Security

- sensitive at-rest data is encrypted,
- incorrect password does not unlock data,
- incorrect recovery key does not recover data,
- successful recovery rotates the recovery key,
- sensitive text is absent from normal logs,
- permanent deletion removes application data and workspace key material.

### 27.10 Documentation and Testing

- automated tests pass,
- evaluation results are documented,
- README is complete,
- architecture and limitations are documented,
- demo dataset and demo flow are ready,
- final presentation is ready.

---

## 28. Testing and Evaluation Scope

### 28.1 Unit Tests

Must cover important deterministic logic such as:

- hashing,
- chunking boundaries,
- state transitions,
- active-version selection,
- evidence sufficiency policy,
- cosine similarity,
- citation mapping,
- analysis version creation,
- deterministic change detection,
- encryption/decryption wrappers,
- password verification,
- recovery-key verification.

### 28.2 Integration Tests

Must cover:

- digital PDF -> extraction -> chunk -> embedding -> SQLite -> retrieval,
- scanned PDF -> OCR -> chunk -> embedding -> retrieval,
- image -> OCR -> retrieval,
- mixed PDF extraction,
- workspace isolation,
- document replacement,
- deletion and index cleanup,
- cancellation and rollback,
- restart recovery,
- persisted chat and analysis reload.

### 28.3 RAG Evaluation Set

The evaluation set must include:

- answerable questions,
- unanswerable questions,
- ambiguous questions,
- empty input,
- overly broad questions,
- questions requiring one document,
- questions requiring multiple documents,
- questions scoped to selected documents,
- attempts to retrieve from another workspace.

Measure separately:

- correct document retrieval,
- correct page/source retrieval,
- whether the passage supports the answer,
- unsupported-answer behavior,
- citation validity,
- answer usefulness.

### 28.4 OCR Evaluation

Digital extraction and OCR must be measured separately.

The OCR set should include:

- clear Turkish scans,
- clear English scans,
- mixed digital/scanned PDFs,
- image files,
- a small number of intentionally difficult examples to document limitations.

### 28.5 Performance Evaluation

The report must document:

- Mac model,
- CPU/GPU/NPU information where relevant,
- RAM,
- operating system version,
- Foundry Local runtime version,
- language model name/version,
- embedding model name/version,
- OCR engine/language pack version,
- number of documents,
- total pages,
- processing times,
- answer latency,
- memory and disk observations where practical.

Exact pass thresholds will be finalized after baseline benchmarking.

### 28.6 Security Verification

Tests should verify:

- no obvious plaintext sensitive payload is present in at-rest files,
- wrong credentials fail,
- logs do not contain document text,
- temporary artifacts are cleaned,
- workspace cryptographic deletion makes normal application recovery impossible.

---

## 29. Delivery Artifacts

The first complete release package MUST include:

1. working macOS desktop application,
2. complete source code,
3. dependency and environment configuration,
4. comprehensive README,
5. setup instructions,
6. model setup instructions,
7. architecture documentation and diagram,
8. security design summary,
9. automated unit tests,
10. automated integration tests,
11. RAG evaluation dataset and results,
12. performance/benchmark report,
13. documented known limitations,
14. anonymized, public, or synthetic demo documents,
15. final demo script,
16. final presentation.

Real confidential client documents must not be distributed as demo data.

---

## 30. Explicitly Out of Scope for the First Release

### 30.1 Platform and User Management

- Windows packaging and validation,
- mobile application,
- multi-user authentication,
- RBAC,
- team collaboration,
- centralized administration,
- email registration/login,
- email password reset.

### 30.2 Cloud and External Integrations

- cloud LLM,
- cloud fallback,
- cloud synchronization,
- SharePoint,
- OneDrive,
- Google Drive,
- UYAP,
- mailbox ingestion,
- internet legal research,
- mandatory remote telemetry.

### 30.3 Automatic File Monitoring

- folder watcher,
- automatic external change detection,
- automatic document-version matching,
- automatic activation without user confirmation.

### 30.4 Advanced Document Intelligence

- guaranteed handwriting OCR,
- seal/signature recognition,
- guaranteed table reconstruction,
- advanced contradiction detection,
- autonomous legal reasoning,
- outcome prediction.

### 30.5 Drafting and Editing

- petition drafting automation,
- contract generation,
- Word-like source-document editor,
- autonomous legal agent actions.

### 30.6 Export, Backup, and Transfer

- PDF/DOCX analysis export,
- chat-report export,
- workspace export/import,
- device-to-device workspace transfer,
- automatic backup,
- device synchronization.

### 30.7 Enterprise Security

- enterprise KMS,
- administrator recovery,
- enterprise identity provider,
- centralized policy management,
- signed external audit reports,
- multi-device key synchronization.

### 30.8 Advanced Processing Recovery

- exact page-level checkpoint resume after crash.

---

## 31. Architecturally Prepared Future Enhancements

The first release must avoid blocking later addition of:

- Windows adapter and packaging,
- automatic folder watching,
- document change detection,
- suggested automatic version matching with user confirmation,
- document version comparison,
- workspace export/import,
- encrypted backup,
- PDF/DOCX report export,
- additional input formats,
- improved OCR engines,
- offline model-bundled installer,
- multi-user and RBAC,
- enterprise key management,
- stronger tamper-evident audit,
- checkpoint-based job resume.

Future features must use existing service boundaries instead of bypassing them.

---

## 32. Known Limitations and Risks

### 32.1 Model Quality

Local models may:

- misunderstand Turkish legal terminology,
- omit nuance,
- oversimplify,
- or generate unsupported language.

Grounding, citations, and human review reduce but do not eliminate this risk.

### 32.2 OCR Quality

OCR errors may affect:

- names,
- dates,
- amounts,
- article numbers,
- identifiers,
- and citations.

Users must be able to verify original sources.

### 32.3 Hardware Variation

Latency and available model size depend on the device.

No universal speed guarantee is made before benchmark results.

### 32.4 Encryption and Recovery

Strong encryption means that losing both the LexLocal password and recovery key may permanently prevent access.

### 32.5 Local Does Not Mean Invulnerable

A compromised operating system, malware, screen capture, or memory inspection may still create risk.

### 32.6 Legal Position

LexLocal does not provide legal advice and does not guarantee legal correctness or compliance.

---

## 33. Microsoft Project Requirement Traceability

The uploaded Microsoft project brief requires a working local RAG assistant with Foundry Local, Python, embeddings, SQLite, retrieval, local generation, testing, documentation, and a final demo.

| Microsoft brief requirement | LexLocal implementation |
|---|---|
| Install and run Foundry Local locally | First-run model/runtime validation and local inference |
| Python project and SDK usage | Python desktop/application services and Foundry Local adapters |
| Generate embeddings locally | `EmbeddingService` for chunks and queries |
| Store text and vectors in SQLite | SQLite-backed encrypted chunk/embedding persistence |
| Document ingestion | Manual multi-file import pipeline |
| Split documents into chunks | Page-aware legal-document chunking |
| Query embedding | Same compatible embedding model as document chunks |
| Cosine similarity | Python similarity engine |
| Top-K retrieval | Configurable workspace-scoped retrieval |
| Local LLM integration | Foundry Local answer and analysis generation |
| Prompt uses retrieved context | Context-only grounded generation policy |
| Do not guess when missing | Evidence sufficiency and insufficient-evidence response |
| Source citations | Validated document/page/passage citations |
| User interface | Packaged macOS desktop application |
| Functional tests | Unit, integration, RAG, OCR, and security tests |
| Performance evaluation | Hardware/model/dataset benchmark report |
| README/report | Comprehensive project documentation |
| Final demo/presentation | Controlled offline demo and final presentation |

LexLocal extends the minimum brief with professional workspace, OCR, structured analysis, history, encryption, and lifecycle management. These extensions must not remove or hide the required baseline SQLite/cosine-similarity RAG implementation.

---

## 34. Recommended Implementation Sequence

This is an implementation order, not permission to remove later scope.

### Delivery Milestone M1 — Local RAG Vertical Slice

M1 must be completed before work spreads across the complete product
surface. It proves one working, end-to-end local RAG path:

```text
Workspace
-> PDF ingestion
-> text extraction
-> page-aware chunking
-> Foundry Local embedding
-> SQLite chunk/vector storage
-> Python/NumPy cosine similarity
-> configurable top-K retrieval
-> grounded local Q&A
-> validated citation
```

M1 is complete only when this path is automated-testable and demonstrable
without a cloud model.

M1 has a strict test-data boundary:

- only synthetic, anonymous, and non-sensitive test documents may be used,
- a development-only plaintext or insecure encryption provider may exist only
  during early skeleton development,
- no real legal document, external demo dataset, or user data may be processed
  before Security Gate SG-1 passes,
- external demonstrations, release candidates, and packaged applications must
  use the authenticated production encryption provider,
- release composition must refuse to start with an insecure development
  provider.

M1 validates the local RAG path early. It does not remove, postpone, or weaken
any M2 security or product requirement.

### Delivery Milestone M2 — Complete LexLocal Release

M2 completes the approved first-release scope after M1:

- OCR and image inputs,
- encrypted storage and security setup,
- recovery and locking,
- persistent chats,
- structured analysis,
- document and analysis versioning,
- deletion and cryptographic erasure,
- activity history,
- and `.app` / `.dmg` packaging.

These milestones do not reduce or defer the approved first-release scope. They
prevent M2 complexity from obscuring or delaying the mandatory M1
vertical slice.

### Stage 1 — Foundation

- project structure,
- configuration,
- error model,
- SQLite access,
- controlled storage,
- Foundry Local smoke test,
- model manager.

### Stage 2 — Microsoft RAG Baseline

- document text ingestion,
- page-aware chunks,
- local embeddings,
- SQLite vector persistence,
- cosine similarity,
- top-K retrieval,
- grounded local Q&A,
- basic citation metadata,
- baseline tests.

### Stage 3 — Desktop Product Core

- macOS desktop UI,
- workspaces,
- background jobs,
- processing statuses,
- persistent chats,
- source viewer.

### Stage 4 — OCR and Versioning

- native/OCR strategy,
- JPEG/PNG,
- mixed PDFs,
- document versions,
- archive rules,
- cancellation/rollback.

### Stage 5 — Structured Legal Analysis

- profiles,
- classification suggestions,
- targeted retrieval,
- hierarchical analysis,
- editable sections,
- stale state,
- analysis versions and change summaries.

### Stage 6 — Security and Lifecycle

- LexLocal password,
- encrypted storage,
- recovery key,
- optional Touch ID,
- activity history,
- permanent cryptographic deletion.

### Stage 7 — Evaluation and Delivery

- full automated tests,
- RAG/OCR evaluation,
- performance benchmark,
- README,
- architecture diagram,
- demo dataset,
- demo rehearsal,
- final presentation.

Security-sensitive storage design should be considered from the beginning even if its final integration is completed in a later stage. Retrofitting encryption after business logic directly writes files and SQL everywhere is not acceptable.

---

## 35. Scope Change Rule

A new feature may enter the first release only if:

1. it directly supports the agreed core workflow or mandatory Microsoft requirement,
2. its data, security, testing, and timeline impact are documented,
3. it does not replace or weaken an existing required feature,
4. it is approved as a scope change,
5. the change is recorded in the project change log.

Unapproved ideas must be placed in the future roadmap.

---

## 36. Final Scope Statement

LexLocal's first complete release is a macOS, single-user, encrypted, offline-first legal document intelligence workspace.

It will process PDF and image documents locally, use OCR where required, persist page-aware chunks and embeddings in SQLite, retrieve evidence through cosine similarity, generate source-grounded answers and structured legal analyses through Microsoft Foundry Local, preserve verifiable citations and history, and provide controlled lifecycle and deletion behavior.

The release is complete only when the full workflow is implemented, tested, documented, evaluated, and demonstrated. It must not be reduced to a basic chatbot, while its additional professional features must remain grounded in the required Local RAG architecture.
