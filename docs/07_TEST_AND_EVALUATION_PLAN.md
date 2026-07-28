# LexLocal — Test and Evaluation Plan

**Document ID:** `07_TEST_AND_EVALUATION_PLAN.md`  
**Status:** Approved test and evaluation baseline for implementation  
**Applies to:** First complete LexLocal release  
**Depends on:** `02_SCOPE_AND_MVP.md`, `03_USER_FLOWS_AND_STATES.md`, `04_SYSTEM_ARCHITECTURE.md`, `05_DATA_MODEL.md`, `06_SECURITY_DESIGN.md`

---

## 1. Purpose and Authority

This document defines how approved requirements become automated tests,
evaluation runs, release evidence, and milestone/security-gate decisions.
It cannot add, remove, or weaken product scope. `02` defines scope, `03`
behavior, `04` architecture, `05` persistence, and `06` security.

---

## 2. Test Principles

- deterministic invariants are automated,
- failures must be reproducible and evidence-backed,
- no partial output is counted as success,
- security tests fail closed,
- model quality is measured on versioned fixtures,
- unmeasured quality/performance thresholds remain `TBD-BENCHMARK`,
- a threshold-dependent gate cannot pass until its threshold is locked.

Each detailed test record uses: Test ID, source requirement, level,
preconditions, fixture, procedure, expected result, metric, threshold, evidence
artifact, milestone/gate, and automation status.

---

## 3. Test Environments

1. **Fast automated:** in-memory/temp SQLite, fake ports, deterministic fixtures.
2. **Local integration:** real SQLite/filesystem/Qt adapters and controlled
   Foundry/Tesseract dependencies.
3. **Reference benchmark:** hardware/runtime manifest fully recorded.
4. **Clean machine:** packaged `.app`/`.dmg`, fresh user profile, offline restart.

Minimum release environment values remain `TO_BE_VERIFIED` in
`release/release_manifest.yaml`.

---

## 4. Test Data and Privacy Rules

- Development and automation use synthetic, anonymous, or explicitly permitted
  controlled fixtures only.
- Real client/legal files never enter the repository.
- Unique secret markers are allowed for leakage scanning.
- OCR fixtures include Turkish and English printed text.
- Dataset versions and expected answers are version-controlled.
- RAG sets contain answerable, related-but-insufficient, and unanswerable cases.
- Isolation fixtures include similar content in separate workspaces.
- Real/external data cannot be processed before SG-1 passes.

---

## 5. Unit Test Scope

| Test ID | Target | Expected result | Threshold | Gate |
|---|---|---|---|---|
| `UNIT-001` | State transitions | Invalid transition rejected | 100% | M1/M2 |
| `UNIT-002` | Canonical source-set bytes | Same logical payload gives same bytes | 100% | M2 |
| `UNIT-003` | Source-set HMAC | Required change inputs alter fingerprint | 100% | SG-1 |
| `UNIT-004` | File nonce builder | 12-byte unique nonces, big-endian counter | 100% | SG-1 |
| `UNIT-005` | Citation validator | Unknown evidence ID rejected | 100% | M1 |

Evidence: automated test report and failing-case diagnostics without content.

---

## 6. Integration Test Scope

`INT-001` exercises import → extraction/OCR → chunks → embeddings → retrieval →
answer → citation. `INT-002` exercises analysis generation/commit. `INT-003`
exercises encrypted storage/unlock. `INT-004` exercises deletion coordination.
All must preserve transaction and historical-snapshot rules. Acceptance: 100%
for deterministic fixtures; evidence is test logs plus sanitized DB assertions.

---

## 7. Architecture Boundary Tests

- `ARCH-001`: domain/application packages import no PySide6 infrastructure.
- `ARCH-002`: UI performs no SQL, cryptography, OCR, or model calls directly.
- `ARCH-003`: repositories do not expose raw connections/rows.
- `ARCH-004`: no FastAPI, cloud model, vector DB, or hidden HTTP dependency.
- `ARCH-005`: model execution goes through the approved adapter/coordinator.

Threshold: zero prohibited dependency violations. Gate: M1/M2 as applicable.

---

## 8. SQLite and Migration Tests

- `DB-001`: empty DB applies all migrations.
- `DB-002`: `PRAGMA foreign_key_check` is empty.
- `DB-003`: `PRAGMA integrity_check` returns `ok`.
- `DB-004`: two active versions for one document are rejected.
- `DB-005`: two active indexes for one version are rejected.
- `DB-006`: live duplicate fingerprint is unique per workspace.
- `DB-007`: changed applied migration checksum blocks normal startup.
- `DB-008`: analysis source fingerprint requires a 32-byte BLOB.

Threshold: 100%; checksum mismatch accepted as normal startup: 0.

---

## 9. Workspace Isolation Tests

`ISO-001` inserts cross-workspace parent/child references; DB must reject them.
`ISO-002` executes every repository query under wrong scope; no row may return.
`ISO-003` asks similar questions across two workspaces; no evidence, citation,
cache, draft, or activity entry may cross. Cross-workspace leakage threshold: 0.
Evidence: DB assertions, query audit, marker scan. Gates: M1, M2, SG-1.

---

## 10. Document Processing Tests

Cover format validation, duplicate detection, controlled copy, cancellation,
retry, idempotency, partial pages, warning activation, replacement rollback,
and crash recovery. Failed/cancelled candidate becoming active: 0. Evidence:
state-transition trace, rows/files before and after, activity event.

---

## 11. Native PDF Extraction Tests

`DOC-101` validates page count/text/bounds for digital PDFs; `DOC-102` validates
mixed pages and OCR routing; `DOC-103` rejects protected/corrupt PDFs safely.
Text/page accuracy thresholds: `TBD-BENCHMARK`, locked after the versioned PDF
fixture baseline. Wrong page numbering in deterministic fixtures: 0.

---

## 12. OCR Evaluation

Metrics: character error rate, word error rate, page-processing coverage,
native/OCR routing accuracy, locator availability. Fixtures include Turkish and
English printed text, rotations, low contrast, and mixed PDFs. Thresholds:
`TBD-BENCHMARK`; lock after reference Tesseract/model/hardware run. No OCR gate
passes before dataset version, language packs, and measurements are recorded.

---

## 13. Chunking Evaluation

Validate page confinement, overlap, stable order, no empty chunks, locator
ownership, token estimate bounds, and deterministic output for identical
inputs/config. Deterministic invariants: 100%. Quality thresholds for size and
retrieval impact: `TBD-BENCHMARK`.

---

## 14. Embedding and Vector Validation

Validate resolved model identity, dimension, finite values, non-zero norm,
unit normalization, fixed-endian `float32`, encryption, batch consistency, and
same model for document/query vectors. Invalid vector accepted: 0. Model
dimension and performance remain `TO_BE_VERIFIED`.

---

## 15. Retrieval Evaluation

Metrics:

- Recall@K,
- MRR/reciprocal rank,
- correct-document retrieval rate,
- correct-page retrieval rate.

Use versioned answerable/unanswerable datasets and record K, model identity,
chunk policy, hardware, and dataset version. Thresholds: `TBD-BENCHMARK`,
locked after baseline and error review; M1/M2 cannot pass their quality
acceptance until locked.

---

## 16. Evidence Sufficiency Evaluation

Measure answerable-question sufficient rate, unsupported-question abstention,
false definitive answers, and related-but-insufficient classification quality.
False definitive-answer threshold: `TBD-BENCHMARK`; deterministic policy cases
must match expected state 100%. Evidence: labeled confusion matrix and cases.

---

## 17. Grounded Answer Evaluation

Review factual claims against retrieved evidence, instruction following,
structured-output validity, Turkish legal fixture behavior, and abstention.
No general-knowledge completion is allowed for insufficient evidence.
Quality threshold: `TBD-BENCHMARK`; schema validity for completed answers: 100%.

---

## 18. Citation Accuracy Evaluation

Metrics: valid evidence-ID rate, exact document-version accuracy,
page/locator accuracy, supporting-passage support rate, fabricated citation
count. Fabricated citation displayed: 0. Exact version and resolvability for
deterministic fixtures: 100%. Evidence: citation audit export without secrets.

---

## 19. Structured Analysis Evaluation

Evaluate required-section completeness, schema validity, section evidence,
cross-section consistency, missing-information behavior, and profile fit.
Completed formal version with invalid/missing required section: 0. Semantic
quality threshold: `TBD-BENCHMARK`.

---

## 20. Analysis Version, Draft, Restore and Staleness Tests

- `ANALYSIS-201`: generation failure preserves prior formal state/version.
- `ANALYSIS-202`: draft auto-save creates no formal version.
- `ANALYSIS-203`: save creates one next immutable version.
- `ANALYSIS-204`: restore copies sections/citations/source snapshot, records
  prior current and restored source IDs, uses next version number.
- `ANALYSIS-205`: restore creates no generation run and invokes no
  retrieval/model adapter.
- `ANALYSIS-206`: stale triggers and resolution are exact.

Restore operation invoking model generation: 0.

---

## 21. Chat and Historical Scope Tests

Validate chat scope changes apply only to future requests, request snapshots use
exact versions, prior AI messages are context but never evidence, chat deletion
is isolated, and archived citations open exact historical sources.
Source-deleted citation redirected to another version: 0.

---

## 22. Security and Cryptographic Tests

Cover AES-GCM tamper failure, Argon2id metadata/calibration, HKDF label
separation, recovery rotation, progressive delay, Touch ID fallback,
workspace-key isolation, source-set/text/duplicate HMACs, and file nonces.
Nonce tests cover unique prefixes, unique chunk nonces, big-endian encoding,
boundaries, overflow, header separation, tamper failure, and retry non-reuse.
Threshold: 100% deterministic; gates SG-1 through SG-4.

---

## 23. Plaintext Leakage Tests

Scan SQLite, WAL, SHM, controlled files, staging, logs, diagnostics, crash
artifacts, clipboard-controlled paths, and package test output with unique
markers. Plaintext marker outside explicitly allowed decrypted output: 0.
Cloud/legal-content telemetry marker transmission: 0. Gate: SG-1/SG-3.

---

## 24. Deletion and Cryptographic-Erasure Tests

Validate document derived-data purge/tombstones, deleted citation state,
workspace row/file purge, workspace-key destruction, cache clearing, unrelated
workspace survival, interruption recovery, and inaccessible residual
ciphertext. Required undeleted sensitive artifacts: 0. Gate: SG-3.

---

## 25. Offline and Network-Policy Tests

After setup/cache preparation, deny network and exercise startup, import, OCR,
retrieval, answer, analysis, history, and deletion. Capture attempted
connections. Cloud fallback requests: 0. Unexpected network requests: 0.

---

## 26. Failure, Cancellation, Rollback and Restart-Recovery Tests

Inject failure/cancellation at each pipeline, answer, analysis, encryption, and
deletion stage. Verify no partial final result, old active data survives,
staging is recoverable/cleaned, and startup offers approved actions.
False completed state: 0.

---

## 27. Performance and Resource Benchmarks

Record hardware, OS, SDK/runtime/model versions, dataset scale, import latency,
OCR latency/page, embedding throughput, retrieval latency, answer latency, peak
memory, and disk usage. Thresholds are `TBD-BENCHMARK` until reference and
minimum-candidate runs are reviewed and locked.

---

## 28. Packaging and Clean-Machine Tests

Install `.app` from controlled `.dmg` on clean Apple Silicon user profile.
Verify launch, Qt PDF, Tesseract/languages, Foundry catalog/cache, encrypted
storage, offline restart, resources, permissions, and uninstall instructions.
Exact environment baseline: `TO_BE_VERIFIED`. Gate: M2/SG-4.

---

## 29. Accessibility and Basic Desktop UX Checks

Keyboard navigation, focus order, readable scaling, light/dark contrast,
screen-reader labels for core controls, progress/cancellation feedback, Turkish
messages, and destructive confirmation are checked. Threshold:
`TBD-BENCHMARK` where measurement is needed; blocking keyboard traps: 0.

---

## 30. Delivery Milestone M1 Acceptance

M1 passes when the synthetic/non-sensitive local PDF → chunk → Foundry
embedding → SQLite → cosine top-K → grounded answer → validated citation path
is automated and demonstrable offline after setup. Real/external/user data is
forbidden before SG-1. An insecure development provider is forbidden in
release composition. M1 does not waive M2.

---

## 31. Delivery Milestone M2 Acceptance

M2 passes only when complete approved scope, locked benchmark thresholds,
required automated tests, SG-1 through SG-3, applicable SG-4 packaging checks,
clean-machine/offline evidence, and release manifest verification are complete.

---

## 32. Security Gates SG-1 Through SG-4

- **SG-1 Encryption Baseline:** production encryption, separate workspace keys,
  ciphertext storage, nonce/HMAC/tamper tests, insecure provider rejection.
- **SG-2 Recovery and Lock:** recovery rotation, password change, delay,
  auto/manual lock, job leases.
- **SG-3 Deletion and Plaintext Leakage:** deletion recovery, key destruction,
  zero forbidden markers.
- **SG-4 Optional Touch ID and Packaged Application:** if enabled, biometric-set
  handling, password fallback, package behavior; Touch ID remains optional.

---

## 33. Requirements Traceability Matrix

| Requirement group | Source | Test categories | Milestone/gate |
|---|---|---|---|
| Product workflows and DoD | `02` | INT, DOC, RAG, CIT, ANALYSIS, PKG | M1/M2 |
| User flows and states | `03` | UNIT, INT, CHAT, ANALYSIS, DEL | M1/M2 |
| Architecture boundaries | `04` | ARCH, INT, PERF, PKG | M1/M2 |
| SQLite, history, isolation | `05` | DB, ISO, CHAT, ANALYSIS | M1/M2 |
| Cryptography, lock, deletion | `06` | SEC, DEL, PKG | SG-1–SG-4 |
| OCR | `02`/`04` | OCR, DOC, PERF | M2 |
| Foundry model compatibility | `04` | RAG, EVID, PERF, PKG | M1/M2 |

---

## 34. Release Evidence and Artifact Retention

Retain sanitized test reports, dataset/version manifests, benchmark results,
traceability export, migration checks, leakage scan, package hashes, release
manifest, model resolution evidence, and gate sign-offs. Never retain legal
content, secrets, keys, recovery text, raw prompts, or decrypted fixtures beyond
approved test scope.

---

## 35. Known Limitations and Deferred Measurements

Pending external measurement/verification:

- minimum macOS and Apple Silicon generation,
- RAM and disk baselines,
- pinned dependency/runtime versions,
- Foundry resolved model IDs/versions/dimensions,
- OCR, retrieval, sufficiency, answer, analysis, performance, and accessibility
  thresholds marked `TBD-BENCHMARK`.

Each item must identify its benchmark run and approver before its dependent
release gate passes. `TBD-BENCHMARK` is not acceptance.
