# LexLocal — User Flows and Application States

**Document ID:** `03_USER_FLOWS_AND_STATES.md`  
**Project:** LexLocal — On-Device Legal Document Intelligence Workspace  
**Status:** Approved user-flow and state baseline for implementation  
**Primary platform:** macOS  
**Initial user model:** Single user, single device  
**Related documents:** `01_PROJECT_CHARTER.md`, `02_SCOPE_AND_MVP.md`  

---

## 1. Purpose and Authority

This document translates the approved scope in `02_SCOPE_AND_MVP.md` into implementable user flows, UI states, state transitions, recovery behavior, and interaction rules.

It is intended to guide:

- desktop UI implementation,
- application-service boundaries,
- asynchronous job handling,
- persistence and recovery logic,
- state-machine implementation,
- error handling,
- acceptance testing,
- and future screen-level design.

This document does not define final visual styling, exact database columns, cryptographic algorithms, model selection, or UI framework choice. Those belong to later architecture, data-model, security, and test documents.

If this document conflicts with `02_SCOPE_AND_MVP.md`, the scope document governs unless this document explicitly records an approved clarification that does not reduce the agreed scope.

---

## 2. Product Interaction Principles

The following principles apply across all screens and workflows.

### 2.1 Local-first and offline-first

LexLocal must not silently send documents, extracted text, user questions, chats, embeddings, analyses, or citations to a cloud model or external AI service.

If the local runtime or model is unavailable, the application enters a limited local mode. It does not fall back to a cloud model.

### 2.2 One active workspace at a time

All document, retrieval, chat, citation, and analysis operations are scoped to the active workspace.

The UI must always make the active workspace visible. No operation may silently retrieve from another workspace.

### 2.3 No silent historical mutation

Existing answers, citations, analysis versions, and document-version references must not be silently rewritten when:

- the document scope changes,
- a new document becomes ready,
- a document is replaced by a new version,
- the workspace profile changes,
- or an analysis is regenerated.

New operations use the current eligible data. Historical records continue to point to the exact data used when they were created.

### 2.4 No partial result presented as final

For question answering and structured analysis:

- incomplete model output is not stored as a completed result,
- unvalidated citations are not displayed as real citations,
- cancellation does not create a completed answer or analysis version,
- and failure does not overwrite the last valid result.

### 2.5 User control over irreversible or expensive actions

LexLocal must require explicit confirmation for:

- deleting a chat,
- deleting a document,
- overwriting user-edited analysis content through regeneration,
- archiving a workspace,
- and permanently deleting a workspace.

### 2.6 Actionable errors

User-facing errors must explain:

- what could not be completed,
- whether existing data is safe,
- what the user can do next,
- and whether a retry is possible.

Technical stack traces, raw prompts, document text, secrets, and sensitive implementation details must not be shown in the normal UI.

### 2.7 Friendly language with optional technical detail

The normal UI uses user-friendly language. Technical details may appear in a separate diagnostic view when safe.

Example:

- Primary text: **“Görüntüden metin çıkarılacak.”**
- Tooltip/details: **“Bu sayfalarda yerel OCR kullanılacak.”**

---

## 3. Primary Navigation Model

The first release should expose the following primary areas.

### 3.1 Application-level areas

- Unlock / security screen
- First-run setup
- Workspace dashboard
- Archived workspaces
- Application settings
- Security settings
- Local model status and repair
- Recovery mode, when required

### 3.2 Active-workspace areas

- Workspace overview
- Documents
- Chats / question answering
- Structured analysis
- Activity history
- Workspace settings

### 3.3 Contextual views

- Document details
- Document import preflight
- Processing progress
- Analysis preflight
- Analysis version history
- Analysis comparison
- Citation source viewer
- Confirmation dialogs

---

# PART I — APPLICATION SETUP, SECURITY, AND SESSION FLOWS

## 4. First-Run Setup Flow

### 4.1 Entry condition

This flow is shown when LexLocal has no completed local security profile.

### 4.2 Approved sequence

```text
Welcome
  -> System pre-check
  -> Create LexLocal master password
  -> Generate and confirm recovery key
  -> Optional Touch ID setup
  -> Foundry Local and model setup
  -> Local inference test
  -> Setup complete
  -> Workspace dashboard or first workspace creation
```

### 4.3 Welcome screen

The welcome screen must explain, briefly:

- LexLocal processes legal documents locally,
- the user will create a LexLocal-specific master password,
- a recovery key must be saved,
- the first model setup may require internet access,
- and core operation is offline after successful setup.

Primary action:

- **Kuruluma Başla**

### 4.4 System pre-check

The pre-check should verify at least:

- supported macOS environment,
- writable application-data directory,
- basic available disk space,
- Foundry Local runtime presence or install readiness,
- and whether required secure local facilities are available.

Possible outcomes:

- `PASS`: continue.
- `PASS_WITH_WARNING`: continue after showing the warning.
- `BLOCKED`: setup cannot continue until the blocking issue is resolved.

### 4.5 Master password creation

The user enters the new LexLocal master password twice.

The UI must:

- state that this password is separate from the macOS account password,
- show password-strength guidance without claiming absolute security,
- prevent continuation if the two entries differ,
- and never display or store the password in plaintext.

### 4.6 Recovery key setup

After key material is created:

1. LexLocal generates a cryptographically secure recovery key.
2. The key is displayed once in a dedicated protected setup view.
3. The user is required to save it.
4. LexLocal asks the user to confirm selected portions.
5. Setup cannot complete until the confirmation succeeds.

The screen must clearly state:

- LexLocal does not email or upload the recovery key,
- the recovery key is not stored in plaintext,
- losing both the password and recovery key may make the data unrecoverable.

### 4.7 Optional Touch ID

Touch ID is optional quick unlock.

The user may:

- enable it during setup,
- skip it,
- or enable it later in Security Settings.

Touch ID does not replace the LexLocal master password or recovery key.

### 4.8 Foundry Local and model setup

The setup flow checks:

- runtime availability,
- required model availability,
- model version compatibility,
- available disk space,
- model preparation/download status,
- file integrity where supported,
- and successful local inference.

The UI must show clear setup phases rather than one indefinite spinner.

Suggested phases:

```text
Yerel çalışma ortamı kontrol ediliyor…
Model hazırlanıyor…
Model doğrulanıyor…
Yerel çıkarım testi çalıştırılıyor…
```

### 4.9 Setup completion choices

After security setup succeeds, the user sees:

- **İlk Workspace’i Oluştur**
- **Şimdilik Ana Ekrana Geç**

The user is not forced to create a workspace immediately.

### 4.10 Model setup failure during first run

If the security setup succeeds but local model setup fails, LexLocal may still complete application setup and enter **Limited Mode**.

Persistent banner:

> **Yerel AI kurulumu tamamlanmadı. Belge işleme ve analiz özelliklerini kullanmak için kuruluma devam edin.**

In this mode, the user may:

- enter the application,
- create and rename workspaces,
- manage workspace metadata,
- access settings and security settings,
- inspect model status,
- and retry or repair model setup.

The user may not:

- add documents for processing,
- start OCR,
- create embeddings or indexes,
- ask document-grounded questions,
- or generate structured analysis.

Documents must not be silently queued for later processing while the model is unavailable.

---

## 5. Normal Startup and Unlock Flow

### 5.1 Startup sequence after setup

```text
Application launch
  -> Read non-sensitive startup metadata
  -> Validate security profile and encrypted storage access
  -> Show unlock screen
  -> Touch ID or master password
  -> Validate key access
  -> Check incomplete jobs and model health
  -> Open workspace dashboard
```

### 5.2 Unlock methods

Available methods:

- Touch ID, when enabled and available.
- LexLocal master password.

If Touch ID fails or is unavailable, the fallback is the LexLocal master password, not the macOS password.

### 5.3 Incorrect password handling

LexLocal uses progressive delay rather than data deletion or permanent lockout.

Expected behavior:

- early failed attempts show a normal error,
- later failed attempts introduce a temporary delay,
- delays increase progressively,
- a successful unlock resets the failed-attempt counter,
- no automatic data wipe occurs,
- no permanent lockout occurs.

The exact delay configuration belongs to the security design, but the UI must show the remaining temporary wait time.

Available recovery action:

- **Parolamı Unuttum — Recovery Key Kullan**

### 5.4 Password recovery flow

```text
Forgot password
  -> Enter recovery key
  -> Validate recovery path
  -> Create new LexLocal master password
  -> Re-wrap protected key material
  -> Invalidate old recovery key
  -> Generate and confirm new recovery key
  -> Unlock application
```

Rules:

- recovery does not decrypt and re-encrypt every document,
- the old recovery key becomes invalid after successful recovery,
- a new recovery key is mandatory,
- an invalid key does not reveal sensitive metadata.

---

## 6. Session Locking and Auto-Lock

### 6.1 Lock triggers

LexLocal locks when:

- the macOS user session locks,
- the device sleeps,
- the configured inactivity period expires,
- or the user selects **LexLocal’ı Kilitle**.

### 6.2 Inactivity configuration

Default inactivity timeout:

- 15 minutes.

Available choices:

- 5 minutes,
- 15 minutes,
- 30 minutes,
- 60 minutes.

### 6.3 Activity that resets the timer

Normal meaningful interaction resets the timer, including:

- keyboard input,
- pointer interaction,
- document scrolling,
- editing analysis text,
- and normal navigation.

Background processing alone does not count as user activity.

### 6.4 Lock warning

Approximately one minute before inactivity lock, the UI shows:

> **LexLocal kısa süre içinde kilitlenecek.**

Action:

- **Oturumu Açık Tut**

### 6.5 Behavior when locked during background work

Locking the UI does not cancel valid ongoing document-processing jobs.

While locked:

- sensitive views are hidden,
- normal interaction is blocked,
- processing may continue safely in the background,
- the result becomes visible only after unlock.

The security design must define safe session-key handling during this state.

---

## 7. Security Settings Flows

### 7.1 Change master password

Required steps:

1. Enter current LexLocal master password.
2. Enter new password twice.
3. Validate the new password.
4. Re-wrap protected application key material.
5. Confirm success.

Changing the password must not require re-encrypting every document and derived record.

The existing recovery key remains valid unless the user separately renews it.

### 7.2 Renew recovery key

Separate action:

- **Recovery Key’i Yenile**

Required steps:

1. Confirm current LexLocal master password.
2. Generate a new recovery key.
3. Display and require user confirmation.
4. Invalidate the previous recovery key.
5. Confirm completion.

The application must not leave both old and new recovery keys valid after successful rotation.

---

# PART II — MODEL AVAILABILITY AND RECOVERY MODES

## 8. Local Model Health and Limited Mode

### 8.1 Model health check

LexLocal checks local inference readiness:

- at startup,
- before model-dependent jobs,
- after model repair,
- and when a previous model operation failed unexpectedly.

### 8.2 Limited mode after a previously working model becomes unavailable

If Foundry Local or the required model becomes unavailable, LexLocal enters Limited Mode.

Persistent banner:

> **Yerel AI modeli kullanılamıyor. Soru-cevap, belge işleme ve analiz özellikleri geçici olarak devre dışı.**

Available read-only or non-AI actions:

- open existing workspaces,
- view ready documents,
- read old chats and answers,
- open existing citations,
- inspect existing analyses and version history,
- view activity history,
- manage settings and security.

Disabled actions:

- new document processing and OCR,
- embedding and indexing,
- new question answering,
- analysis generation or regeneration,
- profile/type suggestions requiring the local model.

Repair actions:

- **Model Durumunu Kontrol Et**
- **Kurulumu Onar**
- **Modeli Yeniden Hazırla**

LexLocal must not automatically download, reinstall, or use internet bandwidth without a clear user action.

### 8.3 Model failure during an active AI request

If the model fails during answer or analysis generation:

- the user input remains available,
- incomplete output is discarded,
- no completed answer or analysis version is created,
- the current valid analysis remains unchanged,
- the UI shows an actionable local error,
- retry is offered after health checks,
- no cloud fallback is attempted.

---

## 9. Secure Recovery Mode for Local Data Failure

### 9.1 Entry conditions

Recovery Mode is entered when LexLocal cannot safely open local data, for example:

- encryption-key material cannot be accessed,
- decryption authentication fails,
- SQLite integrity checks fail,
- required encrypted metadata is inconsistent,
- or a serious data-integrity error is detected.

### 9.2 Recovery Mode behavior

LexLocal must not open the normal workspace UI with partially trusted data.

Message:

> **Yerel veriler güvenli biçimde açılamadı. Verilerinizi korumak için LexLocal sınırlı kurtarma moduna geçti.**

Available actions:

- **Tekrar Dene**
- **Tanılama Kontrolü Yap**
- **Recovery Key ile Anahtar Erişimini Onar** — only when the problem is key access
- **Güvenli Tanılama Raporu Oluştur**
- **Uygulamayı Kapat**

Rules:

- do not write over the damaged database automatically,
- do not silently reset the application,
- do not delete user data,
- do not create a new workspace or process documents,
- do not imply that a recovery key can repair database corruption,
- do not switch to an empty database without explicit future recovery/reset design.

---

# PART III — WORKSPACE FLOWS

## 10. Workspace Dashboard and No-Workspace State

### 10.1 Dashboard content

The dashboard shows:

- active workspaces,
- access to archived workspaces,
- model/limited-mode status where applicable,
- and the primary workspace creation action.

### 10.2 No-workspace empty state

When no workspace exists, show a guided start screen rather than an empty list.

Suggested content:

> **Henüz bir çalışma alanınız yok.**  
> Belgelerinizi birbirinden izole biçimde yönetmek, kaynaklı sorular sormak ve yapılandırılmış analiz oluşturmak için ilk workspace’inizi oluşturun.

Primary action:

- **İlk Workspace’i Oluştur**

Supporting information:

- supported files: PDF, JPEG, PNG,
- documents are processed locally,
- short workflow: create workspace → add documents → ask grounded questions or create analysis.

No demo workspace or sample legal documents are created automatically.

---

## 11. Create Workspace Flow

### 11.1 Required and optional inputs

Required:

- Workspace name.

Optional during creation:

- Analysis profile.

Available profiles:

- **Dava Dosyası**
- **Sözleşme İncelemesi**
- **Genel Hukuki Dosya**
- **Daha Sonra Belirle**

### 11.2 Profile behavior

The user may:

- select a profile manually during creation,
- leave it unset,
- choose it later,
- or request a local AI suggestion after documents are processed.

An AI suggestion requires explicit user confirmation and must never silently become the active profile.

Profile rules:

- document import can proceed without a profile,
- question answering can proceed without a profile,
- structured analysis cannot start until a profile is selected,
- changing profile does not re-index documents,
- changing profile may make an existing analysis stale.

### 11.3 Successful creation

After creation, LexLocal opens the normal workspace screen.

It does not immediately force document import.

---

## 12. Empty Workspace State

If the active workspace has no documents, show a helpful dismissible panel:

> **Bu çalışma alanında henüz belge yok. Analize başlamak için PDF, JPEG veya PNG ekleyin.**

Primary action:

- **Belge Ekle**

Suggested steps:

1. Belgeleri ekleyin.
2. İşlenmelerini bekleyin.
3. Kaynaklı soru sorun veya yapılandırılmış analiz oluşturun.

If the profile is unset, show a smaller non-blocking notice:

> **Analiz profili henüz belirlenmedi.**

---

## 13. Rename Workspace

The user may rename an active workspace.

Renaming:

- changes only the display name,
- does not change the stable workspace identifier,
- does not break citations or document references,
- does not trigger document processing or re-indexing.

The new name is used for future display and permanent-deletion confirmation.

---

## 14. Archive Workspace Flow

### 14.1 Confirmation

When the user selects **Workspace’i Arşivle**, show:

> **Bu çalışma alanı arşivlenecek. Belgeler, sohbetler ve analizler korunacak; ancak yeniden etkinleştirilene kadar yeni işlem başlatılamayacak.**

Actions:

- **İptal Et**
- **Arşivle**

### 14.2 Archived workspace behavior

An archived workspace is read-only.

The user may:

- view documents,
- view active and archived document versions,
- read previous chats and answers,
- open citations,
- inspect analyses and analysis versions,
- view activity history.

The user may not:

- add documents,
- delete documents,
- replace a document with a new version,
- start or retry document processing,
- ask a new question,
- create, edit, regenerate, or save an analysis,
- change profile or content metadata.

Persistent banner:

> **Bu workspace arşivlenmiştir ve salt okunur durumdadır.**

Primary action:

- **Yeniden Etkinleştir**

### 14.3 Reactivation

Reactivation:

- returns the workspace to `ACTIVE`,
- does not reprocess documents,
- does not regenerate embeddings,
- does not modify chats or analyses,
- uses the existing valid active index.

---

## 15. Permanent Workspace Deletion

### 15.1 Entry and impact summary

Before deletion, LexLocal presents a clear impact summary, including counts where available:

```text
Bu workspace kalıcı olarak silinecek:

Müvekkil A — Dava Dosyası

• 18 belge ve 24 belge sürümü
• 7 sohbet
• 5 analiz sürümü
• 63 citation

Bu işlem geri alınamaz.
```

### 15.2 Required confirmation

The user must:

1. type the workspace name exactly,
2. enter the LexLocal master password,
3. press **Kalıcı Olarak Sil**.

The recovery key is not requested for normal deletion confirmation.

### 15.3 Deletion execution

During deletion:

- the workspace immediately becomes inaccessible for normal use,
- a deletion-in-progress screen is shown,
- documents, versions, extracted text, OCR, chunks, embeddings, chats, answers, analyses, citations, activity records, caches, and controlled temporary artifacts are removed,
- the workspace-specific data key is destroyed,
- success is shown only after the deletion workflow completes.

LexLocal must not claim physical overwrite of every SSD block.

### 15.4 Deletion failure

If deletion cannot complete:

- the workspace must not reopen in a partially deleted normal state,
- it remains blocked in a deletion-recovery state,
- the user is shown **Silme tamamlanamadı**,
- a safe retry is offered,
- sensitive low-level file details are kept out of the normal UI,
- safe diagnostics are recorded.

---

# PART IV — DOCUMENT IMPORT, PROCESSING, AND VERSION FLOWS

## 16. Add Documents Flow

### 16.1 Entry points

Document import may be started from:

- the empty-workspace panel,
- the Documents area,
- or a workspace-level **Belge Ekle** action.

Import is disabled when:

- the workspace is archived,
- LexLocal is in Limited Mode,
- LexLocal is in Recovery Mode,
- or a permanent workspace deletion is in progress.

### 16.2 File selection

The user may select one or multiple:

- PDF,
- JPEG/JPG,
- PNG files.

Selection does not immediately start processing.

---

## 17. Multi-File Preflight

### 17.1 Purpose

Preflight validates selected files and allows the user to review the batch before LexLocal creates processing jobs.

### 17.2 Per-file statuses

Examples:

```text
Dava_Dilekcesi.pdf     Hazır
Taranmis_Ek.png        Hazır — Görüntüden metin çıkarılacak
Kilitli_Belge.pdf      Reddedildi — Parola korumalı
Bozuk_Dosya.pdf        Reddedildi — Dosya okunamıyor
```

Possible preflight outcomes:

- Ready for native extraction.
- Ready with OCR expected.
- Ready with warning.
- Rejected: unsupported type.
- Rejected: zero-byte or unreadable.
- Rejected: password-protected/encrypted input.
- Rejected: exact duplicate in the workspace.
- Blocked: insufficient disk space for the batch.

### 17.3 User actions

The user may:

- add more files,
- remove a selected file,
- open warning details,
- continue with valid files,
- cancel the entire selection.

One rejected file does not block the other valid files, except when a batch-level safety condition such as insufficient disk space blocks processing.

### 17.4 OCR wording

Primary label:

- **Görüntüden metin çıkarılacak**

Detail/tooltip:

- **Bu dosyada yerel OCR kullanılacak.**

For visibly low-quality input:

> **Görüntü kalitesi düşük olabilir. Metin tanıma hataları oluşabilir.**

### 17.5 Duplicate behavior

An exact duplicate must not create a second active document record in the same workspace.

The preflight result should identify the existing matching document and offer a navigation action such as:

- **Mevcut Belgeyi Aç**

A version replacement must use the explicit **Yeni Sürümle Değiştir** flow rather than normal duplicate import.

---

## 18. Disk-Space Preflight

Before processing begins, LexLocal estimates required space for:

- controlled encrypted source copies,
- extraction/OCR artifacts,
- chunks,
- embeddings,
- index records,
- and safe temporary processing data.

If space is insufficient, processing does not start.

Message example:

> **Belge işleme başlatılamadı. Yeterli disk alanı bulunmuyor.**  
> Tahmini gereken alan: 1,8 GB  
> Kullanılabilir alan: 650 MB

Actions:

- **Depolama Ayarlarını Aç**
- **Dosya Seçimini Değiştir**
- **Tekrar Kontrol Et**
- **İptal Et**

Rules:

- no partial active index is created,
- existing ready documents are unaffected,
- LexLocal does not delete existing user data automatically,
- the user restarts the operation after resolving the issue.

---

## 19. Processing Progress Flow

### 19.1 Asynchronous processing

Each valid file becomes an independent background job. The desktop UI remains responsive.

A batch summary is shown:

> **3 belgeden 1’i hazır, 2’si işleniyor.**

Each document shows a friendly current stage. A percentage may be shown where the stage has measurable progress, but LexLocal must not invent precise percentages for indeterminate model or indexing work.

Suggested stage labels:

```text
Sırada bekliyor…
Dosya güvenli depolamaya alınıyor…
Metin çıkarılıyor…
Görüntüden metin çıkarılıyor…
Metin hazırlanıyor…
Arama parçaları oluşturuluyor…
Yerel gösterimler oluşturuluyor…
Aranabilir hâle getiriliyor…
Tamamlandı.
```

The internal implementation may use more technical stage names, but normal UI wording remains understandable.

### 19.2 Per-document actions

Depending on state, the user may:

- open processing details,
- cancel processing,
- retry a failed or cancelled job,
- remove a failed/cancelled document record.

### 19.3 Progressive usability

A document that reaches `READY` or `READY_WITH_WARNINGS` becomes eligible for Q&A and analysis even while other documents in the batch are still processing.

The result of one document must not depend on all other batch files succeeding.

---

## 20. Successful and Partially Successful Processing

### 20.1 READY

`READY` means:

- processing completed,
- the active version is eligible for retrieval,
- citations can resolve to validated source metadata.

### 20.2 READY_WITH_WARNINGS

Use `READY_WITH_WARNINGS` when the document is partially usable, such as when some pages could not be processed.

Example:

> **30 sayfanın 26’sı işlendi. 7, 12, 18 ve 29. sayfalarda kullanılabilir metin çıkarılamadı.**

Behavior:

- successfully processed pages enter retrieval,
- failed pages are excluded,
- citations may only point to successfully processed content,
- the user may inspect the failed-page list,
- the user may open the source,
- retry is available,
- structured analysis shows a partial-coverage warning when relevant.

### 20.3 OCR traceability

Document details must show:

- which pages used native text,
- which pages used OCR,
- which pages failed,
- and any quality warning.

The user must be able to open the original source for verification.

---

## 21. Failed Processing

When a document job fails:

- the document is not eligible for retrieval,
- no partial chunks or embeddings enter the active index,
- other documents remain unaffected,
- the UI identifies the failed stage in friendly language,
- the user may select **Yeniden Dene** or **Belge Kaydını Kaldır**.

Examples:

- **Belge metni çıkarılamadı.**
- **Yerel OCR işlemi tamamlanamadı.**
- **Belge aranabilir hâle getirilemedi.**

A retry must be idempotent and must not duplicate derived records.

---

## 22. User-Cancelled Processing

### 22.1 Cancellation behavior

When the user cancels a document job, the record remains visible as `CANCELLED`.

Message:

> **İşlem kullanıcı tarafından iptal edildi.**

Actions:

- **İşlemi Baştan Başlat**
- **Belge Kaydını Kaldır**

### 22.2 Data rules

After cancellation:

- partial extracted text, chunks, and embeddings do not enter the active index,
- controlled temporary processing artifacts are cleaned safely,
- the document cannot be used in Q&A or analysis,
- cancellation is distinguishable from failure,
- cancellation time and safe metadata may appear in details/activity history.

If the cancelled operation was a new version replacement, the previous active version remains active.

---

## 23. Interrupted Processing and Startup Recovery

### 23.1 Detection

On startup, LexLocal detects jobs that were left incomplete because of:

- application crash,
- forced termination,
- device shutdown,
- or unexpected process interruption.

### 23.2 Recovery-required UI

The document shows:

> **Önceki işleme tamamlanamadı.**

Actions:

- **İşlemi Baştan Başlat**
- **Belge Kaydını Kaldır**

### 23.3 Rules

- no incomplete derived data enters the active index,
- the document remains unavailable for Q&A and analysis,
- if a previous valid active version exists, it remains usable,
- the user is not forced into an automatic high-resource restart,
- first release restarts from the beginning rather than exact page/checkpoint resume.

---

## 24. Document Details Screen

A selected document opens one tabbed details view.

### 24.1 Tabs

#### General Information

- display name,
- user-confirmed document type,
- local AI type suggestion where available,
- file type,
- file size,
- page count,
- active version,
- added and last-updated timestamps.

#### Processing Status

- current/final job status,
- native extraction and OCR summary,
- OCR pages,
- failed pages,
- warnings,
- retry/reprocess actions where valid.

#### Versions

- active version,
- archived versions,
- version timestamps,
- safe metadata,
- open archived version read-only,
- **Yeni Sürümle Değiştir**.

#### Usage and Sources

- count of chat answers using the document,
- count of analysis versions using the document,
- citation count,
- navigation to related records where supported.

### 24.2 Dangerous actions area

Dangerous or high-impact actions are visually separated:

- **Yeni Sürümle Değiştir**
- **Belgeyi Kalıcı Olarak Sil**

### 24.3 Technical metadata

Hash values, chunk IDs, embedding model identifiers, raw job IDs, and similar implementation details are not shown in the normal legal-user view. They may be available in a safe diagnostic mode.

---

## 25. Document Type Suggestion and Confirmation

Potential type suggestions include:

- petition,
- response,
- contract,
- expert report,
- court decision,
- notice,
- evidence/attachment,
- other.

The local suggestion is not final until the user confirms or changes it.

Changing document-type metadata:

- does not require re-indexing,
- does not change the stored source,
- may affect filtering or analysis organization.

---

## 26. Replace Document with New Version

### 26.1 Explicit start

Version replacement begins only when the user selects a specific document and chooses:

- **Yeni Sürümle Değiştir**

LexLocal must not automatically guess that a newly imported file replaces another document.

### 26.2 Processing sequence

```text
Choose new file
  -> Preflight
  -> Controlled encrypted copy
  -> Text extraction / OCR
  -> Normalization
  -> Chunking
  -> Embedding
  -> Index preparation
  -> Validate result
  -> Activate new version
  -> Archive previous active version
```

### 26.3 During processing

Message:

> **Yeni sürüm hazırlanıyor. Mevcut sürüm kullanılmaya devam ediyor.**

The old active version remains available for new retrieval until the replacement succeeds.

### 26.4 Outcomes

#### Successful

- new version becomes active,
- previous version becomes archived,
- future retrieval uses only the new active version,
- existing historical answers still reference their original version,
- existing analysis is marked stale when affected.

#### Ready with warnings

- the user sees the warning and affected pages,
- explicit activation confirmation is required before replacing the old active version,
- if the user declines, the old version remains active.

#### Failed or cancelled

- old version remains active,
- failed/cancelled candidate does not enter retrieval,
- no existing chat or analysis record is rewritten.

### 26.5 Archived version visibility

Archived versions remain viewable in read-only mode, but they are excluded from new retrieval.

---

## 27. Delete Individual Document

### 27.1 Impact summary

Before deletion, show the document and affected historical records.

Example:

```text
Bu belge kalıcı olarak silinecek:

ana_sozlesme.pdf

Etkilenecek kayıtlar:
• 4 sohbet cevabı
• 2 analiz sürümü
• 11 citation

Belgenin bütün sürümleri ve türetilmiş verileri silinecek.
Bu işlem geri alınamaz.
```

### 27.2 Confirmation

Actions:

- **İptal Et**
- **Belgeyi Kalıcı Olarak Sil**

Deletion proceeds only after the user presses the explicit permanent-delete confirmation action; it must never occur silently.

### 27.3 Deletion effects

Delete:

- all versions of the selected document,
- encrypted source copies,
- extracted and OCR text,
- chunks,
- embeddings,
- active index membership,
- document-linked caches and derived records.

Historical chat messages and analysis text may remain as immutable history, but affected citation links show:

> **Kaynak belge silindiği için artık görüntülenemiyor.**

Rules:

- do not redirect the citation to another document or version,
- future retrieval cannot use the deleted document,
- affected current analysis becomes stale where applicable.

---

# PART V — CHAT, QUESTION ANSWERING, AND CITATION FLOWS

## 28. Q&A Availability

The question input becomes enabled when at least one active document version in the active workspace is:

- `READY`, or
- `READY_WITH_WARNINGS`.

If no document is ready, the input remains disabled with an explanation.

Example:

> **Soru sormak için en az bir belgenin işlenmesini bekleyin.**

Scope indicator example:

> **Şu anda 5 belgeden 3’ü aranabilir. 2 belge işleniyor.**

Documents in `QUEUED`, `PROCESSING`, `FAILED`, or `CANCELLED` are excluded.

---

## 29. Chat Creation and Naming

### 29.1 First question creates the chat

The user does not complete a separate chat-creation form.

If no active chat exists:

1. the user types the first question,
2. submitting it creates one new chat,
3. the question is processed in that chat.

Subsequent questions continue in the same chat until the user explicitly starts or selects another chat.

Each question does not create a new chat.

### 29.2 Automatic local title

After the first question, LexLocal creates a short local title.

Example:

```text
Question: Bu sözleşmedeki fesih şartları nelerdir?
Title: Sözleşme Fesih Şartları
```

Rules:

- the user may rename the chat at any time,
- after manual rename, LexLocal does not automatically overwrite the title,
- if title generation fails, use a shortened safe portion of the first question or **Yeni Sohbet**,
- no cloud service is used.

### 29.3 Empty chat

A newly opened but never-used empty chat may be removed automatically when the user leaves it.

A chat containing at least one message is never deleted without user confirmation. Chats belong permanently to their workspace in the first release and cannot be moved to another workspace.

---

## 30. Chat Document Scope

### 30.1 Initial default

A new chat defaults to all active document versions that are ready at the moment the chat is created.

### 30.2 User-defined scope

The user may restrict the chat to:

- all currently selected ready documents,
- one document,
- or multiple documents.

The scope is preserved per chat.

### 30.3 New document becomes ready

A newly ready document is not silently added to an existing chat scope.

Prompt:

> **Yeni bir belge hazır. Bu sohbetin kapsamına eklensin mi?**

The user may accept or decline.

### 30.4 Scope changes affect future questions only

When scope changes, show a small system event inside the chat, for example:

> **Belge kapsamı değiştirildi: ihtarname.pdf eklendi.**

Rules:

- old answers remain unchanged,
- old citations remain unchanged,
- future questions use the new scope,
- every answer stores the scope and exact document versions used.

Optional action on an old question:

- **Yeni Kapsamla Yeniden Sor**

This produces a new answer; it does not replace the old one.

---

## 31. Controlled Conversational Context

Follow-up questions use controlled chat context.

For a new user question, LexLocal may provide the model with:

- the current question,
- recent turns from the current chat,
- a short local summary for older relevant context,
- and newly retrieved evidence from the current eligible document scope.

Example references that should be understood:

- “bu süre”,
- “aynı madde”,
- “o taraf”,
- “peki bildirim şekli ne?”.

Rules:

- every new question performs fresh retrieval,
- previous AI answers are conversation context, not legal evidence,
- previous AI answers are not citation sources,
- the full unlimited chat history is not sent on every request,
- the new answer must be grounded in newly retrieved and validated evidence.

---

## 32. Question Submission and Generation Progress

### 32.1 Pre-submit checks

Before starting, verify:

- workspace is active,
- at least one scoped ready document exists,
- local model is ready,
- no conflicting request is already running in the same chat,
- the question is non-empty.

### 32.2 Progress UI

Do not stream unvalidated answer text word by word.

Show friendly stages:

```text
Belgelerde aranıyor…
İlgili kaynaklar değerlendiriliyor…
Yanıt hazırlanıyor…
Kaynaklar doğrulanıyor…
```

The user may select:

- **İptal Et**

While one request is running, a second question cannot be submitted in the same chat.

### 32.3 Cancellation

If cancelled:

- preserve the user’s question text for retry/editing,
- do not save a completed assistant answer,
- do not display unvalidated citations,
- return the chat to an interactive state.

---

## 33. Evidence Sufficiency Outcomes

Every completed retrieval request is categorized as one of three evidence states.

### 33.1 SUFFICIENT

Display:

> **Belgelerde yeterli kaynak bulundu.**

Behavior:

- provide a direct grounded answer,
- include validated claim-level or sentence-level citations,
- allow citation source inspection.

### 33.2 RELATED_BUT_INSUFFICIENT

Display:

> **Belgelerde bu soruyla ilişkili bilgiler bulundu; ancak kesin bir yanıt vermek için yeterli değil.**

Behavior:

- do not provide a definitive answer,
- show a short explanation,
- show relevant passages and citations,
- allow the user to inspect sources.

### 33.3 INSUFFICIENT

Display:

> **Bu soruyu yanıtlamak için çalışma alanındaki belgelerde yeterli bilgi bulunamadı.**

Suggested next actions:

- **Belge Kapsamını Değiştir**
- **Soruyu Yeniden Düzenle**
- **Belge Ekle**

Rules:

- do not fill gaps with general model knowledge,
- do not use speculative wording to simulate an answer,
- save the insufficiency result in chat history so the attempt remains understandable.

---

## 34. Completed Answer Presentation

### 34.1 Answer layout

A completed answer includes:

- evidence-status label,
- answer text,
- claim-level or sentence-level citation markers,
- source list,
- access to the source viewer.

Example:

> Sözleşme, yazılı bildirimle 30 gün önceden feshedilebilir. **[1]**  
> Haklı nedenle fesih için ayrıca süre bekleme şartı belirtilmemiştir. **[2]**

```text
[1] kira_sozlesmesi.pdf — Sayfa 8
[2] kira_sozlesmesi.pdf — Sayfa 9
```

### 34.2 Hidden technical details

Normal users do not see:

- raw similarity scores,
- chunk identifiers,
- top-K internals,
- raw model prompt,
- raw embedding data.

These may be available only in safe developer diagnostics.

---

## 35. Citation Source Viewer

### 35.1 Interaction model

Selecting a citation opens an optional, closable, resizable split view.

```text
Chat or Analysis                  Source Viewer
----------------                  -------------
Answer / report                   PDF page or image
Citation marker                   Supporting passage
```

The user can:

- resize the two areas,
- close the source viewer,
- move from one citation to another,
- keep the answer and source visible together.

### 35.2 PDF source

The viewer shows:

- document name,
- exact document version,
- page number,
- PDF page,
- supporting passage,
- evidence identifier internally.

The supporting passage should be highlighted where reliable positioning is available.

If exact on-page coordinates are unavailable:

- open the validated page,
- show the supporting passage in a separate highlighted panel,
- do not fabricate an exact visual location.

### 35.3 Image source

For JPEG/PNG:

- open the original image,
- show the OCR-derived supporting passage beside it,
- identify that the passage came from OCR.

### 35.4 Historical citation to archived version

An old answer’s citation always opens the exact document version used to generate that answer.

If that version is archived, show:

> **Bu kaynak, cevabın oluşturulduğu arşivlenmiş belge sürümüdür. Güncel aktif sürüm değildir.**

Rules:

- do not silently redirect to the current active version,
- show the archived version read-only,
- optionally allow navigation to the active version as a separate user action,
- archived versions remain excluded from new retrieval.

### 35.5 Citation after source deletion

If the document was permanently deleted, show:

> **Kaynak belge silindiği için artık görüntülenemiyor.**

Never resolve it to another source.

---

## 36. Q&A Failure and Retry

Failures are reported by stage.

Examples:

- **Belgelerde arama tamamlanamadı.**
- **Yerel AI modeli başlatılamadı.**
- **Yanıt oluşturulurken işlem kesildi.**
- **Kaynak doğrulaması tamamlanamadı.**

Behavior:

- preserve the user’s question,
- discard incomplete assistant output,
- do not save invalid citations,
- leave previous messages unchanged,
- offer **Yeniden Dene**,
- optionally offer **Model Durumunu Kontrol Et** or **Belge Kapsamını Değiştir** when relevant,
- never switch to a cloud model.

---

## 37. Rename and Delete Chat

### 37.1 Rename

The user may rename a chat at any time.

Manual rename disables later automatic title replacement.

### 37.2 Delete

Before deleting a non-empty chat, show:

> **Bu sohbetin tüm mesajları ve citation kayıtları kalıcı olarak silinecek. Bu işlem geri alınamaz.**

Actions:

- **İptal Et**
- **Sohbeti Sil**

Deletion removes only:

- the selected chat,
- its messages,
- its saved answer metadata,
- its citation records,
- and its document-scope history.

It does not remove:

- the workspace,
- documents,
- structured analyses,
- or other chats.

After deleting the active chat:

- open the most recently used remaining chat, or
- show an empty Q&A state if none remain.

---

# PART VI — STRUCTURED ANALYSIS FLOWS

## 38. Analysis Availability

Structured analysis requires:

- an active workspace,
- a confirmed analysis profile,
- at least one selected document in `READY` or `READY_WITH_WARNINGS`,
- a ready local model.

If the profile is unset, the analysis action remains blocked until the user selects one of:

- Dava Dosyası,
- Sözleşme İncelemesi,
- Genel Hukuki Dosya.

---

## 39. Analysis Preflight

Selecting **Analiz Oluştur** opens a preflight screen rather than starting immediately.

Example:

```text
Analiz profili: Sözleşme İncelemesi

Kullanılacak belgeler:
✓ ana_sozlesme.pdf — Hazır
✓ ek_protokol.pdf — Uyarılarla hazır
— ihtarname.pdf — Hâlâ işleniyor, analize dahil edilmeyecek

Belge kapsamı: 2 belge
```

The user may:

- review or change the profile,
- select ready documents for this analysis,
- inspect warnings and missing pages,
- wait for processing documents,
- continue without processing documents,
- cancel.

Rules:

- analysis selection applies only to this analysis generation,
- it does not change chat scopes,
- processing documents are not silently added later,
- `READY_WITH_WARNINGS` documents may be used with an explicit coverage warning,
- analysis cannot start with zero eligible selected documents.

---

## 40. Analysis Generation Progress

Analysis follows the global long-running AI operation rules:

- friendly progress stages,
- user cancellation,
- no partial final result,
- no cloud fallback,
- valid current analysis preserved until replacement succeeds.

Because analysis is section-based, the UI also shows section progress.

Example:

```text
✓ Taraflar
✓ Sözleşmenin Konusu
… Yükümlülükler işleniyor
○ Fesih Hükümleri
○ Riskler ve Eksik Maddeler
```

Suggested high-level stages:

```text
Belgeler taranıyor…
Bölümler için kaynaklar toplanıyor…
Yapılandırılmış bulgular hazırlanıyor…
Kaynaklar doğrulanıyor…
Analiz tamamlanıyor…
```

If generation fails or is cancelled:

- no new completed analysis version is created,
- the previous valid analysis remains available,
- a retry is offered.

---

## 41. Analysis Result Layout

Structured analysis is a persistent, sectioned, editable report rather than one long chat message.

### 41.1 Main layout

- Left: section navigation.
- Center: selected analysis section.
- Right: optional resizable citation source viewer.

Example litigation sections:

- Genel Bakış
- Taraflar
- Uyuşmazlık Konusu
- Kronoloji
- İddia ve Savunmalar
- Tartışmalı Konular
- Tarihler ve Süreler
- Deliller
- Talep ve Sonuçlar
- Usul Durumu
- Eksik veya Belirsiz Bilgiler

Contract and General Legal Matter profiles use their approved profile-specific sections from `02_SCOPE_AND_MVP.md`.

### 41.2 Section capabilities

The user may:

- read the section,
- inspect citations,
- edit the section,
- regenerate the section,
- navigate to version history,
- compare versions.

### 41.3 Citation granularity

- Concrete findings use finding-level citations.
- Broader synthesis may use paragraph- or section-level citations.
- Citations remain application-validated evidence references.

---

## 42. Analysis Editing and Draft Saving

### 42.1 Edit mode

When the user edits analysis content, changes are identified as user edits rather than silently relabeled as AI-generated content.

### 42.2 Automatic local draft

While editing, LexLocal automatically saves a local draft to protect against application close or lock.

The UI shows:

> **Kaydedilmemiş kullanıcı değişiklikleri**

This draft is not a formal analysis version.

### 42.3 Save formal version

When the user selects **Değişiklikleri Kaydet**:

- create a new analysis version,
- record changed sections,
- record that the source was user editing,
- preserve the previous version,
- clear the working draft after successful save.

Do not create a new analysis version for every keystroke.

### 42.4 Draft recovery

After restart or unlock, an unfinished valid draft may be restored so the user can:

- continue editing,
- discard the draft,
- or save it as a new version.

---

## 43. Regenerate a User-Edited Section

If the target section contains user edits, LexLocal must not overwrite it silently.

Warning:

> **Bu bölümde kullanıcı tarafından yapılmış değişiklikler var. Yeniden oluşturma mevcut içeriğin yerini alacaktır.**

Actions:

- **İptal Et**
- **Mevcut Bölümü Koru**
- **Yeniden Oluştur ve Yeni Sürüm Olarak Kaydet**

If regeneration proceeds:

- run fresh retrieval against current eligible active document versions,
- validate new citations,
- create a new analysis version,
- preserve the old manually edited version in history.

The same protection applies to full-analysis regeneration if any section contains user edits.

---

## 44. Analysis Staleness

### 44.1 Stale triggers

An existing analysis becomes `STALE` when relevant source conditions change, including:

- a document is added,
- a document is deleted,
- a document is replaced by a new version,
- the analysis profile changes.

### 44.2 Stale UI

Show:

> **Bu analiz, çalışma alanındaki güncel belge ve profil durumunu yansıtmıyor.**

Display reasons, for example:

```text
• ek_protokol.pdf eklendi
• ana_sozlesme.pdf v2 ile değiştirildi
• Analiz profili değiştirildi
```

Actions:

- **Mevcut Analizi Koru**
- **Etkilenen Bölümleri Yenile**
- **Tüm Analizi Yeniden Oluştur**

Rules:

- the old analysis remains readable,
- no automatic overwrite occurs,
- refresh happens only through explicit user action,
- profile change will commonly suggest full regeneration,
- document changes may allow affected-section regeneration.

---

## 45. Analysis Version History

Each formal analysis version stores at least:

- version number,
- timestamp,
- active profile used,
- exact document versions used,
- content and sections,
- validated citations,
- creation reason,
- changed sections,
- source type: AI generation, user edit, regeneration, or restore,
- optional user-defined version label.

Typical version-creating actions:

- first full generation,
- full regeneration,
- section regeneration,
- explicit save of user edits,
- restore of an older version.

Version history is immutable from the normal UI.

---

## 46. Restore Older Analysis Version

When the user selects an older version and chooses **Bu Sürümü Geri Yükle**:

1. The selected immutable historical version is the restore source.
2. Its sections, citation relationships, and exact source snapshot are copied
   deterministically into a new immutable analysis version.
3. Existing versions remain unchanged.
4. No model inference or retrieval generation runs.
5. The new version records `creation_reason = RESTORE` and
   `content_source = RESTORE`.
6. `restored_from_version_id` identifies the selected historical version.
7. `based_on_version_id` identifies the version that was current immediately
   before restore began.
8. `generation_run_id` is null.
9. A safe restore activity event is recorded.
10. The new version receives the next normal `version_number`.

The restored result may still be marked stale if its copied sources and profile
do not reflect current workspace state.

Example:

```text
Current: v4
Restore selected: v2
Result: v5 — v2 sürümünden geri yüklendi
```

The application does not delete or rewrite v3 or v4.

---

## 47. Compare Analysis Versions

Comparison is deterministic and section-based.

The comparison view shows:

- changed sections,
- added text,
- removed text,
- modified text,
- added citations,
- removed citations.

Example summary:

```text
Değişen bölümler:
• Kronoloji
• Fesih Hükümleri
• Riskler ve Eksik Maddeler
```

A local model may create a readable short summary, but that summary is secondary. The true change record is produced from structural text and citation comparison.

---

# PART VII — ACTIVITY HISTORY

## 48. Workspace Activity Timeline

Each workspace includes a user-visible **Etkinlik Geçmişi**.

### 48.1 Purpose

The timeline allows the user to understand significant lifecycle events without exposing sensitive document content or developer logs.

### 48.2 Example events

- workspace created or renamed,
- workspace archived or reactivated,
- document added,
- extraction/OCR completed or failed,
- indexing completed or failed,
- processing cancelled,
- document version activated,
- old version archived,
- document deleted,
- profile confirmed or changed,
- document type confirmed,
- analysis created, edited, regenerated, restored,
- chat created or deleted,
- permanent deletion initiated/result recorded where safely possible.

Example:

```text
25 Temmuz 2026, 14:32
ana_sozlesme.pdf v2 başarıyla etkinleştirildi.
Eski v1 sürümü arşivlendi.
```

### 48.3 Filters

- Tümü
- Belgeler
- Analizler
- Sohbetler
- Workspace İşlemleri
- Hatalar ve Uyarılar

### 48.4 Event interaction

A user may open a related existing entity from an event.

If the related entity was deleted, the event remains historical text and does not redirect to a different entity.

### 48.5 Sensitive-data exclusions

The timeline must not store or display:

- raw document text,
- full user questions,
- full prompts,
- passwords,
- recovery keys,
- encryption keys,
- decrypted payloads,
- raw stack traces.

Activity history is user-facing and separate from safe technical diagnostics.

---

# PART VIII — GLOBAL EMPTY, DISABLED, AND ERROR STATES

## 49. Common Empty States

### 49.1 No workspaces

Show guided first-workspace creation. Do not create demo data automatically.

### 49.2 Workspace has no documents

Show the dismissible **Belge Ekle** guidance panel.

### 49.3 No ready documents

Disable Q&A and analysis with an explanation. Do not let the user submit requests that cannot run.

### 49.4 No chats

Show the question input when eligible and explain that the first question will create a chat.

### 49.5 No analysis

Show the profile, eligible-document summary, and **Analiz Oluştur** action.

### 49.6 No activity events matching a filter

Show:

> **Bu filtreye uygun etkinlik bulunamadı.**

---

## 50. Common Disabled States

An action should remain visible but disabled with a reason when the user can understand how to make it available.

Examples:

- Q&A disabled because no ready document exists.
- Analysis disabled because no profile is selected.
- New processing disabled in Limited Mode.
- Editing disabled in archived workspace.
- Retry disabled while model health is unresolved.

Do not hide every unavailable action if its absence would confuse the user.

---

## 51. Common Error Presentation

A normal error component should include:

- concise title,
- user-safe explanation,
- whether existing data is preserved,
- primary recovery action,
- optional secondary action,
- safe reference/error code for support or diagnostics.

Example:

> **Yanıt oluşturulamadı.**  
> Sorunuz korundu ve mevcut sohbet geçmişiniz etkilenmedi. Yerel modeli kontrol edip yeniden deneyebilirsiniz.

Actions:

- **Yeniden Dene**
- **Model Durumunu Kontrol Et**

---

# PART IX — STATE MODELS

## 52. State-Machine Conventions

### 52.1 Persistent state vs derived UI state

Persistent domain states should remain compact and meaningful.

Some UI states are derived from persistent state plus conditions. For example:

- `RECOVERY_REQUIRED` may be a UI representation of an interrupted `PROCESSING` job detected at startup.
- `LIMITED_MODE` may be an application capability state derived from model readiness.
- `READ_ONLY` may be derived from workspace status `ARCHIVED`.

### 52.2 Transition ownership

State transitions must be performed by application services, not directly by UI widgets.

The UI requests an action. The relevant service validates guards, executes the operation, persists the transition, and returns the resulting state.

### 52.3 Atomic activation rule

New document versions, ready indexes, generated answers, and analysis versions must become visible as completed results only after their required data and references are valid.

---

## 53. Application Setup State

| State | Meaning | Allowed next states |
|---|---|---|
| `NOT_CONFIGURED` | No completed security profile | `SECURITY_SETUP` |
| `SECURITY_SETUP` | Password/key/recovery setup in progress | `MODEL_SETUP`, `NOT_CONFIGURED` on safe cancellation |
| `MODEL_SETUP` | Runtime/model preparation in progress | `READY`, `LIMITED_MODE` |
| `READY` | Security and model setup complete | Normal startup |
| `LIMITED_MODE` | Security setup complete, model unavailable | `READY`, remains `LIMITED_MODE` |
| `RECOVERY_MODE` | Local encrypted data cannot be safely opened | `READY` after valid repair, or remain blocked |

Invariant:

- normal workspace access requires valid security-key access.

---

## 54. Session State

| State | Meaning | Main transitions |
|---|---|---|
| `LOCKED` | Sensitive UI unavailable | `UNLOCKING` |
| `UNLOCKING` | Touch ID/password validation in progress | `UNLOCKED`, `LOCKED`, `TEMPORARY_DELAY` |
| `TEMPORARY_DELAY` | Progressive failed-attempt wait | `LOCKED` after timer |
| `UNLOCKED` | Normal authorized session | `LOCK_WARNING`, `LOCKED` |
| `LOCK_WARNING` | Inactivity lock is imminent | `UNLOCKED` via keep-open activity, `LOCKED` |

Triggers from `UNLOCKED` to `LOCKED`:

- manual lock,
- macOS session lock,
- sleep,
- inactivity timeout.

Invariant:

- background processing may continue while session is `LOCKED`, but sensitive UI remains unavailable.

---

## 55. Local Model State

| State | Meaning | Allowed transitions |
|---|---|---|
| `NOT_CONFIGURED` | Required model not prepared | `CHECKING`, `PREPARING` |
| `CHECKING` | Runtime/model validation in progress | `READY`, `ERROR`, `PREPARING` |
| `PREPARING` | Download/install/prepare in progress | `VERIFYING`, `ERROR`, `CANCELLED` where safe |
| `VERIFYING` | Integrity/compatibility/inference test | `READY`, `ERROR` |
| `READY` | Model-dependent operations enabled | `ERROR`, `CHECKING` |
| `ERROR` | Model unavailable/incompatible/broken | `CHECKING`, `PREPARING` |

Application capability rule:

- model state other than `READY` places model-dependent features in Limited Mode.

---

## 56. Workspace State

| State | Meaning | Allowed transitions |
|---|---|---|
| `ACTIVE` | Normal read/write workspace | `ARCHIVED`, `DELETING` |
| `ARCHIVED` | Read-only, preserved workspace | `ACTIVE`, `DELETING` |
| `DELETING` | Permanent deletion in progress; normal access blocked | removed/deleted, deletion-recovery state |
| `DELETION_RECOVERY` | Deletion failed or incomplete; normal access blocked | `DELETING` retry, resolved removal |
| `DELETED` / removed | No longer available | none |

Invariants:

- only `ACTIVE` permits new RAG, analysis, and document operations,
- `ARCHIVED` permits read-only historical viewing,
- `DELETING` and `DELETION_RECOVERY` permit no normal workspace activity.

---

## 57. Document Preflight State

Preflight is a temporary UI/service state before persistent processing jobs are created.

| State | Meaning | Result |
|---|---|---|
| `CHECKING` | File validation running | wait |
| `READY_NATIVE` | Valid, native text expected | eligible to continue |
| `READY_OCR` | Valid, OCR expected | eligible to continue with notice |
| `READY_WITH_WARNING` | Valid but quality/resource warning | eligible after review |
| `REJECTED` | Invalid, protected, unsupported, corrupt, or duplicate | no processing job |
| `BATCH_BLOCKED` | Batch-level safety issue such as insufficient disk | no jobs start |

---

## 58. Document Processing Job State

Required persistent states:

| State | Meaning | Allowed transitions |
|---|---|---|
| `QUEUED` | Accepted and waiting | `PROCESSING`, `CANCELLED` |
| `PROCESSING` | Extraction/OCR/index pipeline running | `READY`, `READY_WITH_WARNINGS`, `FAILED`, `CANCELLED` |
| `READY` | Fully eligible for retrieval | terminal for this processing-attempt record |
| `READY_WITH_WARNINGS` | Partially eligible with documented coverage gaps | terminal for this processing-attempt record |
| `FAILED` | Not eligible for retrieval | terminal for this processing-attempt record |
| `CANCELLED` | User cancelled; not eligible | terminal for this processing-attempt record |

One `ProcessingJob` represents exactly one processing attempt. Retry or
reprocessing never moves a terminal job back to `QUEUED` or `PROCESSING`.
Instead, it creates a new `ProcessingJob` for the same document version with a
new identifier and the next positive `attempt_number`. The application
use-case/repository transaction owns new-attempt creation and attempt-number
allocation. Existing terminal attempts remain immutable historical records.

Derived startup condition:

- An incomplete `PROCESSING` record detected after crash is displayed as **Recovery Required** and must be restarted from the beginning or removed.

Invariants:

- only `READY` and `READY_WITH_WARNINGS` enter retrieval,
- no failed, cancelled, or interrupted partial index becomes active,
- `READY`, `READY_WITH_WARNINGS`, `FAILED`, and `CANCELLED` processing-attempt
  records are terminal and immutable.

---

## 59. Document Version State

| State | Meaning | Allowed transitions |
|---|---|---|
| `CANDIDATE_PROCESSING` | New replacement version is being prepared | `CANDIDATE_READY`, `CANDIDATE_WARNING`, `CANDIDATE_FAILED`, `CANDIDATE_CANCELLED` |
| `CANDIDATE_READY` | Valid new version awaiting/performing activation | `ACTIVE` |
| `CANDIDATE_WARNING` | New version ready with warnings | `ACTIVE` after user confirmation, or remain unactivated/remove |
| `ACTIVE` | Used for new retrieval | `ARCHIVED`, `DELETED` |
| `ARCHIVED` | Historical, read-only, excluded from new retrieval | `DELETED` |
| `CANDIDATE_FAILED` | Replacement failed | remove/retry; old active remains |
| `CANDIDATE_CANCELLED` | Replacement cancelled | remove/retry; old active remains |
| `DELETED` | Source and derived records removed | none |

Invariant:

- at most one active version exists for a logical document.

---

## 60. Chat State

| State | Meaning | Allowed transitions |
|---|---|---|
| `EMPTY_DRAFT` | Chat opened but no message submitted | `ACTIVE`, automatically removed when abandoned |
| `ACTIVE` | Persistent chat with history | renamed, scope changed, `DELETING` |
| `DELETING` | Confirmed deletion in progress | removed |
| removed | Chat no longer exists | none |

Per-chat persistent properties include:

- title and title source,
- workspace identifier,
- current document scope,
- messages,
- answer-specific scope and document-version snapshots.

---

## 61. Q&A Request State

| State | Meaning | Allowed transitions |
|---|---|---|
| `DRAFT` | User composing question | `SEARCHING`, remain `DRAFT` |
| `SEARCHING` | Retrieval running | `EVALUATING_EVIDENCE`, `FAILED`, `CANCELLED` |
| `EVALUATING_EVIDENCE` | Sufficiency state being determined | `GENERATING`, `COMPLETED_INSUFFICIENT`, `FAILED`, `CANCELLED` |
| `GENERATING` | Local model preparing grounded answer | `VALIDATING_CITATIONS`, `FAILED`, `CANCELLED` |
| `VALIDATING_CITATIONS` | Evidence IDs and source links validated | `COMPLETED`, `FAILED` |
| `COMPLETED` | Grounded answer stored | terminal |
| `COMPLETED_INSUFFICIENT` | Related/insufficient result stored | terminal |
| `FAILED` | No completed assistant answer created | retry from preserved question |
| `CANCELLED` | User cancelled; no completed answer | return to editable question/retry |

Invariant:

- a completed displayed citation must resolve to a validated evidence record or an explicit deleted-source state.

---

## 62. Evidence State

| State | UI behavior |
|---|---|
| `SUFFICIENT` | Direct grounded answer and validated citations |
| `RELATED_BUT_INSUFFICIENT` | No definitive answer; show related passages and citations |
| `INSUFFICIENT` | State that documents lack enough information; no general-knowledge answer |

Evidence state is not presented as model confidence or a probability of legal correctness.

---

## 63. Analysis State Models

Analysis state is persisted through three separate state models. Formal report
state, generation-operation state, and draft state must not be combined into one
state field in the UI or application code.

### 63.1 Formal Analysis State

These states are stored in `analyses.state`.

| State | Meaning | Allowed transitions |
|---|---|---|
| `NOT_CREATED` | No formal analysis version exists | `CURRENT` after a successful initial generation |
| `CURRENT` | The latest formal analysis reflects its recorded source set and profile, and no later stale trigger exists | `STALE`; remain `CURRENT` when a new valid formal version is committed |
| `STALE` | A valid formal analysis exists, but current workspace data or profile has changed | `CURRENT` after a successful regeneration; remain `STALE` until a valid replacement is committed |

### 63.2 Analysis Generation Operation State

These states are stored in `analysis_generation_runs.state`. They describe one
full-analysis or section-generation operation, not the state of the formal
analysis itself.

| State | Meaning | Allowed transitions |
|---|---|---|
| `QUEUED` | Generation request is accepted and waiting to run | `GENERATING`, `CANCELLED` |
| `GENERATING` | Local model generation is in progress | `VALIDATING`, `FAILED`, `CANCELLED` |
| `VALIDATING` | Generated sections, evidence, and citations are being validated | `COMPLETED`, `FAILED`, `CANCELLED` where cancellation remains safe |
| `COMPLETED` | Valid output was committed successfully | terminal |
| `FAILED` | The operation failed without replacing the last valid formal analysis | retry as a new `QUEUED` run |
| `CANCELLED` | The operation was cancelled without replacing the last valid formal analysis | retry as a new `QUEUED` run |

If a generation run fails or is cancelled, the formal analysis state does not
change. The last valid formal analysis remains `CURRENT` or `STALE`. If no
formal analysis existed before the run, it remains `NOT_CREATED`.

### 63.3 Analysis Draft State

These states are stored in `analysis_drafts.state`. They describe the lifecycle
of editable user draft content and do not replace the formal analysis state.

| State | Meaning | Allowed transitions |
|---|---|---|
| `ACTIVE` | User edits are being auto-saved into the current mutable draft | `SAVED`, `DISCARDED` |
| `SAVED` | Draft content was committed as a new immutable formal analysis version | terminal |
| `DISCARDED` | Draft content was explicitly discarded without creating a formal version | terminal |

A draft may be `ACTIVE` while the formal analysis remains `CURRENT` or `STALE`.
Saving a draft creates a new formal analysis version; it does not edit an
existing formal version in place.

---

## 64. Analysis Version State

Formal versions are immutable records.

Creation reasons:

- `INITIAL_GENERATION`
- `FULL_REGENERATION`
- `SECTION_REGENERATION`
- `USER_EDIT_SAVE`
- `RESTORE`

A version is not edited in place. Restoring an old version creates a new version.
Restore is a deterministic version-copy operation and never enters the analysis
generation-operation state machine.

---

## 65. Activity Event State

Activity events are append-only from the normal UI.

Possible result statuses:

- `SUCCESS`
- `WARNING`
- `FAILED`
- `CANCELLED`
- `STARTED`, only where an initiation event is useful and safe.

An activity event must remain understandable even if the referenced entity is later deleted.

---

# PART X — CAPABILITY MATRIX AND GUARDS

## 66. Workspace Capability Matrix

| Action | Active | Archived | Limited Mode | Recovery Mode | Deleting |
|---|---:|---:|---:|---:|---:|
| View existing workspace metadata | Yes | Yes | Yes | No normal access | No |
| View existing ready document | Yes | Yes | Yes | No | No |
| View old chats/answers | Yes | Yes | Yes | No | No |
| Open existing citation | Yes | Yes | Yes | No | No |
| View existing analysis/history | Yes | Yes | Yes | No | No |
| Add/process document | Yes | No | No | No | No |
| Ask new question | Yes, when eligible | No | No | No | No |
| Generate/regenerate analysis | Yes, when eligible | No | No | No | No |
| Edit/save analysis | Yes | No | No | No | No |
| Change workspace profile | Yes | No | Yes, metadata-only | No | No |
| Archive | Yes | Already archived | Yes | No | No |
| Reactivate | N/A | Yes | Yes | No | No |
| Permanently delete | Yes | Yes | Yes with valid security access | No normal path | In progress |

Implementation note:

- Model Limited Mode is separate from workspace archive state. An active workspace can be readable but AI-disabled because the model is unavailable.

---

## 67. Core Invariants for Implementation

1. **Workspace isolation:** Retrieval and analysis must filter by active workspace identifier before ranking or generation.
2. **Active-version-only retrieval:** New queries never use archived document versions.
3. **Historical fidelity:** Stored answers and analysis versions retain exact source-version references.
4. **No partial activation:** A new index/version/result becomes active only after validation succeeds.
5. **Safe replacement:** Failed/cancelled new document versions never deactivate the old active version.
6. **Citation validation:** The UI never trusts free-text citations without application-side evidence resolution.
7. **No cloud fallback:** Local failure remains a local failure with an actionable error.
8. **No silent overwrite:** User edits, old answers, and historical versions are not silently replaced.
9. **Read-only archive:** Archived workspaces preserve access but block mutations and new AI jobs.
10. **Deletion isolation:** Deleting a chat does not delete documents or analyses; deleting a document does not silently rewrite historical text; deleting a workspace removes all workspace data and destroys its key.
11. **Retry idempotency:** Retrying a job must not duplicate documents, chunks, embeddings, citations, or versions.
12. **Safe startup recovery:** Interrupted jobs do not enter the active index and require explicit restart or removal.
13. **Evidence-gated answer:** Insufficient evidence never falls back to general model knowledge.
14. **User-visible reason:** Disabled or failed actions explain why and what the user can do next.

---

# PART XI — USER-FACING MESSAGE CATALOG

## 68. Recommended Core Messages

These strings are implementation guidance and may be refined for final UX wording without changing their meaning.

### Setup and model

- **Yerel AI kurulumu tamamlanmadı. Belge işleme ve analiz özelliklerini kullanmak için kuruluma devam edin.**
- **Yerel AI modeli kullanılamıyor. Soru-cevap, belge işleme ve analiz özellikleri geçici olarak devre dışı.**
- **Model Durumunu Kontrol Et**
- **Kurulumu Onar**

### Security and locking

- **LexLocal kısa süre içinde kilitlenecek.**
- **Oturumu Açık Tut**
- **Parolamı Unuttum — Recovery Key Kullan**

### Workspace

- **Henüz bir çalışma alanınız yok.**
- **Bu workspace arşivlenmiştir ve salt okunur durumdadır.**
- **Yeniden Etkinleştir**

### Documents

- **Bu çalışma alanında henüz belge yok. Analize başlamak için PDF, JPEG veya PNG ekleyin.**
- **Görüntüden metin çıkarılacak.**
- **Görüntü kalitesi düşük olabilir. Metin tanıma hataları oluşabilir.**
- **Yeni sürüm hazırlanıyor. Mevcut sürüm kullanılmaya devam ediyor.**
- **Önceki işleme tamamlanamadı.**
- **İşlem kullanıcı tarafından iptal edildi.**
- **Belge işleme başlatılamadı. Yeterli disk alanı bulunmuyor.**

### Q&A

- **Belgelerde aranıyor…**
- **İlgili kaynaklar değerlendiriliyor…**
- **Yanıt hazırlanıyor…**
- **Kaynaklar doğrulanıyor…**
- **Belgelerde yeterli kaynak bulundu.**
- **Belgelerde bu soruyla ilişkili bilgiler bulundu; ancak kesin bir yanıt vermek için yeterli değil.**
- **Bu soruyu yanıtlamak için çalışma alanındaki belgelerde yeterli bilgi bulunamadı.**
- **Yeni bir belge hazır. Bu sohbetin kapsamına eklensin mi?**

### Citations

- **Bu kaynak, cevabın oluşturulduğu arşivlenmiş belge sürümüdür. Güncel aktif sürüm değildir.**
- **Kaynak belge silindiği için artık görüntülenemiyor.**

### Analysis

- **Kaydedilmemiş kullanıcı değişiklikleri**
- **Bu bölümde kullanıcı tarafından yapılmış değişiklikler var. Yeniden oluşturma mevcut içeriğin yerini alacaktır.**
- **Bu analiz, çalışma alanındaki güncel belge ve profil durumunu yansıtmıyor.**

### Recovery

- **Yerel veriler güvenli biçimde açılamadı. Verilerinizi korumak için LexLocal sınırlı kurtarma moduna geçti.**

---

# PART XII — ACCEPTANCE SCENARIOS

## 69. First-Run Acceptance Scenario

Given a new installation:

1. User completes password setup.
2. User saves and confirms recovery key.
3. User optionally enables Touch ID.
4. Model setup succeeds or Limited Mode is shown clearly.
5. User may create a workspace or enter an empty dashboard.

Pass conditions:

- no workspace is forced,
- recovery-key confirmation cannot be skipped,
- cloud inference is not used,
- setup state persists across restart.

---

## 70. Document Batch Acceptance Scenario

Given four selected files:

- one digital PDF,
- one scanned image,
- one password-protected PDF,
- one corrupt PDF,

Preflight must:

- mark the first ready,
- mark the image as OCR-required,
- reject the protected PDF,
- reject the corrupt PDF,
- allow processing of the two valid files,
- keep each valid file as an independent job.

---

## 71. Partial OCR Acceptance Scenario

Given a 30-page scan where four pages fail:

- final status is `READY_WITH_WARNINGS`,
- failed pages are listed,
- 26 pages are eligible for retrieval,
- citations never point to failed pages,
- analysis shows partial-coverage warning where relevant.

---

## 72. Chat Scope and History Acceptance Scenario

1. Create a chat using documents A and B.
2. Ask and store Answer 1.
3. Add document C to the chat scope.
4. Ask Answer 2.

Pass conditions:

- Answer 1 remains tied to A and B,
- scope-change event is visible,
- Answer 2 may use A, B, and C,
- Answer 1 is not regenerated or rewritten.

---

## 73. Controlled Follow-Up Acceptance Scenario

1. Ask: “Sözleşmedeki fesih süresi nedir?”
2. Ask: “Peki bu süre hangi bildirimden itibaren başlıyor?”

Pass conditions:

- second question understands “bu süre” from recent chat context,
- retrieval runs again,
- the second answer cites current active source evidence,
- the first AI answer is not treated as evidence.

---

## 74. Historical Citation Acceptance Scenario

1. Ask a question using document v1.
2. Replace the document successfully with v2.
3. Ask a new question.
4. Open the old answer’s citation.

Pass conditions:

- new question retrieves from v2,
- old answer remains unchanged,
- old citation opens v1 read-only,
- archived-version warning is shown,
- old citation does not redirect to v2.

---

## 75. Analysis Editing and Regeneration Acceptance Scenario

1. Generate analysis v1.
2. User edits one section; draft auto-saves.
3. User explicitly saves; v2 is created.
4. User requests section regeneration.

Pass conditions:

- warning appears before overwriting user-edited content,
- cancellation preserves v2,
- confirmation runs fresh retrieval and creates v3,
- v1 and v2 remain viewable.

---

## 76. Analysis Staleness Acceptance Scenario

1. Generate current analysis.
2. Replace one source document with a successful new version.

Pass conditions:

- existing analysis remains readable,
- analysis becomes stale,
- stale reason identifies the changed document/version,
- no automatic overwrite occurs,
- user may preserve, partially regenerate, or fully regenerate.

---

## 77. Interrupted Processing Acceptance Scenario

1. Start OCR/indexing.
2. Force-close the application.
3. Restart LexLocal.

Pass conditions:

- incomplete data is not in retrieval,
- the document shows recovery-required messaging,
- user may restart from the beginning or remove the record,
- no automatic resource-heavy processing begins without user action.

---

## 78. Archive Acceptance Scenario

1. Archive an active workspace.
2. Open it from Archived Workspaces.

Pass conditions:

- documents, old chats, citations, analyses, and activity history remain viewable,
- all mutation and new AI actions are disabled,
- reactivation restores normal access without re-indexing.

---

## 79. Permanent Deletion Acceptance Scenario

1. Start workspace deletion.
2. Verify impact summary.
3. Enter incorrect workspace name: deletion remains blocked.
4. Enter correct name but incorrect master password: deletion remains blocked.
5. Complete both correctly and confirm.

Pass conditions:

- workspace becomes inaccessible during deletion,
- workspace data and key material are removed,
- success is not shown early,
- failure leaves the workspace blocked rather than partially usable,
- no physical SSD-overwrite claim is made.

---

# PART XIII — IMPLEMENTATION GUIDANCE

## 80. Recommended Separation of Responsibilities

The UI should not directly implement domain transitions. Suggested responsibilities include:

- `SetupService`: setup orchestration and completion state.
- `SecuritySessionService`: unlock, lock, inactivity state, failed-attempt delay.
- `RecoveryService`: password recovery and recovery-key rotation.
- `ModelManagerService`: runtime/model checks, preparation, repair, health state.
- `WorkspaceService`: create, rename, active selection, profile metadata.
- `WorkspaceArchiveService`: archive/reactivate guards and transitions.
- `WorkspaceDeletionService`: deletion plan, confirmation validation, controlled deletion.
- `DocumentImportService`: preflight-to-job orchestration.
- `ValidationService`: type, integrity, protection, duplicate, resource checks.
- `DocumentProcessingService`: extraction/OCR/chunk/embed/index pipeline.
- `DocumentVersionService`: candidate preparation and atomic activation.
- `ProcessingRecoveryService`: incomplete-job detection and cleanup.
- `ChatService`: chat lifecycle, rename, delete, current scope.
- `ConversationContextService`: recent-turn selection and local summary.
- `RetrievalService`: active-workspace/active-version filtering and top-K retrieval.
- `EvidenceSufficiencyService`: evidence-state policy.
- `AnswerGenerationService`: model request and structured result handling.
- `CitationValidationService`: evidence-ID validation and source resolution.
- `AnalysisService`: preflight, generation, section operations, stale rules.
- `AnalysisVersionService`: immutable versions, restoration, deterministic diff.
- `ActivityHistoryService`: safe append-only user-facing events.
- `DiagnosticService`: safe technical records, separate from activity history.

### 80.1 UI command pattern

A recommended interaction pattern:

```text
UI action
  -> command/request DTO
  -> application service guard checks
  -> domain operation
  -> atomic persistence
  -> event/result DTO
  -> UI state update
```

### 80.2 Long-running job pattern

```text
Create job record
  -> QUEUED
  -> worker claims job
  -> PROCESSING with stage metadata
  -> write derived data to non-active staging area
  -> validate completeness and references
  -> atomic activation
  -> READY / READY_WITH_WARNINGS
```

Failure or cancellation:

```text
Stop work
  -> clean controlled temporary artifacts
  -> keep active index unchanged
  -> FAILED or CANCELLED
  -> expose retry/remove actions
```

### 80.3 Historical snapshot requirements

At answer/analysis creation time, persist enough metadata to reconstruct history:

- workspace ID,
- chat or analysis version ID,
- document-scope snapshot,
- exact document version IDs,
- evidence IDs,
- page/image locators,
- supporting-passage references,
- profile and generation metadata where applicable.

Do not depend on mutable display names or current active-version pointers to reconstruct old citations.

---

## 81. Coding Order Suggested by This Document

A practical implementation order is:

1. Domain enums, guards, and transition tests.
2. Workspace lifecycle and active-workspace isolation.
3. Security setup/session state interfaces.
4. Model health and Limited Mode capability gate.
5. Document preflight and processing job state machine.
6. Staged index activation and startup recovery.
7. Document details and version replacement.
8. Chat lifecycle and document-scope snapshots.
9. Q&A request states, evidence sufficiency, and citation validation.
10. Split source viewer.
11. Structured-analysis preflight, generation, editing, stale status, and version history.
12. Archive, deletion, and activity-history flows.
13. Recovery Mode and failure-path hardening.
14. Full acceptance tests based on Parts XII and
    `07_TEST_AND_EVALUATION_PLAN.md`.

Security-sensitive storage must be designed before services begin writing sensitive content directly to arbitrary files or unprotected database fields.

---

## 82. Deferred Details for Later Documents

The following are intentionally deferred and must be specified later without changing these flows:

### `04_SYSTEM_ARCHITECTURE.md`

- process boundaries,
- desktop/UI framework,
- worker model,
- Foundry Local adapter,
- OCR adapter,
- repository and service interfaces,
- event/job orchestration.

### `05_DATA_MODEL.md`

- exact tables and columns,
- foreign keys and deletion policies,
- immutable snapshot records,
- evidence and citation schema,
- draft and version storage,
- safe activity-event schema.

### `06_SECURITY_DESIGN.md`

- key derivation and wrapping,
- encryption algorithms/libraries,
- workspace key lifecycle,
- Keychain/Touch ID adapter,
- progressive-delay configuration,
- secure temporary-file behavior,
- recovery and diagnostic safeguards.

### `07_TEST_AND_EVALUATION_PLAN.md`

- state-transition unit tests,
- end-to-end flow tests,
- RAG evidence test set,
- OCR evaluation,
- citation validation tests,
- workspace isolation tests,
- encryption/deletion verification,
- crash and recovery tests.

---

## 83. Final User-Flow Baseline

The approved LexLocal experience is defined by the following summary:

- The application is protected by a LexLocal-specific password, recovery key, optional Touch ID, and automatic locking.
- Local model failure produces Limited Mode rather than cloud fallback or total loss of access.
- Workspaces isolate legal matters and can be archived read-only or permanently deleted with strong confirmation.
- Document import uses reviewable multi-file preflight, background processing, page-level OCR fallback, safe cancellation, retry, and crash recovery.
- Only ready active document versions participate in new retrieval.
- Chats are persistent, scoped, locally titled, and use controlled conversational context with fresh retrieval for every question.
- Answers are gated by evidence sufficiency and displayed only after citation validation.
- Citations open a resizable source viewer and preserve exact historical document-version references.
- Structured analysis is a persistent sectioned report with preflight, citations, safe drafts, immutable version history, deterministic comparison, and explicit stale status.
- No user-edited or historical content is silently overwritten.
- Deletion never silently redirects historical citations to unrelated sources.
- Long-running operations expose understandable stages, preserve prior valid results, and never present incomplete output as final.

This document is the implementation baseline for LexLocal user interaction and application-state behavior.
