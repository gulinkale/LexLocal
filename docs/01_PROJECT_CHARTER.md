# LexLocal Project Charter

> **Document Status — Preliminary Charter**
>
> This charter records the project's initial direction. Where this document
> conflicts with later approved documents, `02_SCOPE_AND_MVP.md` through
> `06_SECURITY_DESIGN.md` are authoritative.

## 1. Project Identity

- **Project Name:** LexLocal
- **Subtitle:** On-Device Legal Document Intelligence Workspace
- **Application Type:** Offline-first desktop application
- **Core Technologies:** Microsoft Foundry Local and Local RAG
- **Initial Platform:** Desktop
- **Initial User Model:** Single user
- **Document Scope:** Multiple digital PDF files within one legal case workspace

---

## 2. One-Sentence Project Definition

LexLocal is an offline-first desktop application that enables legal professionals to analyze long, multi-document legal case files on-device through source-grounded question answering and structured summaries without sending document content to external cloud LLM providers.

---

## 3. Problem Statement

Legal professionals frequently work with long and fragmented case files containing petitions, contracts, notices, expert reports, court decisions, evidence, and supporting documents.

Reviewing these files manually requires significant time and makes it difficult to:

- locate information across multiple documents,
- identify the source of a claim,
- create a consistent case summary,
- verify where a date, amount, statement, or legal provision appears,
- use generative AI without exposing confidential legal documents to external cloud providers.

Many existing AI tools require documents to be uploaded to third-party cloud services. For legal files that may contain personal data, sensitive personal data, professional secrets, client information, litigation strategy, or commercial secrets, this creates privacy, security, and compliance concerns.

LexLocal addresses this problem by performing document processing, indexing, retrieval, and language-model inference locally on the user’s device.

---

## 4. Target Users

### Primary Target Users

- Independent lawyers
- Small and medium-sized law firms
- In-house legal professionals who work with confidential document collections

### Initial MVP User

The MVP will be designed for a single legal professional using the application on one local computer.

### User Need

The target user needs to review and understand multi-document legal files more efficiently while keeping the document content on the local device.

---

## 5. Value Proposition

LexLocal provides legal professionals with a private, offline-capable workspace for analyzing legal case files.

The application’s main value is:

- keeping document content on the user’s device,
- enabling question answering across multiple legal documents,
- displaying document and page-level sources,
- generating a structured case summary,
- reducing the time required to search and review case files,
- supporting human verification rather than replacing legal judgment.

LexLocal does not claim to provide legal advice or guarantee legal accuracy. It is designed as a document analysis and decision-support tool.

---

## 6. Project Objectives

The MVP aims to:

1. Allow a user to create a local legal case workspace.
2. Allow multiple digital PDF documents to be added to the workspace.
3. Extract text while preserving document and page metadata.
4. Create a fully local searchable index.
5. Enable question answering across the case folder using Local RAG.
6. Generate answers through Microsoft Foundry Local.
7. Attach document and page citations to supported answers.
8. Avoid answering when sufficient supporting evidence cannot be retrieved.
9. Generate one structured case-file summary.
10. Allow the user to view the source passage behind an answer.
11. Allow a case workspace and its derived data to be deleted locally.
12. Operate without requiring an active internet connection after the required local components and models have been installed.

---

## 7. Why Microsoft Foundry Local?

Microsoft Foundry Local is used because the project requires language-model inference to run on the user’s own device.

Its role in LexLocal is to:

- generate answers from retrieved legal document passages,
- produce structured document and case summaries,
- support offline or disconnected usage,
- reduce the need to transfer confidential document content to an external LLM service.

Foundry Local is a core runtime component, not an optional classifier or a branding-only integration.

The project will not claim that using Foundry Local alone guarantees security, legal compliance, or accuracy. Security also depends on the application design, operating system, device configuration, storage, access controls, and data lifecycle.

---

## 8. Why Local RAG?

Local RAG is used because a legal case workspace may contain multiple long documents that cannot be handled reliably as a single prompt.

Its role is to:

- split documents into searchable passages,
- preserve document and page metadata,
- retrieve the most relevant passages for a user question,
- provide grounded context to the local language model,
- enable source-linked answers.

RAG will mainly be used for targeted question answering and evidence retrieval.

Whole-case summarization will use a structured, hierarchical approach rather than relying only on top-k retrieval.

---

## 9. Why a Desktop Application?

LexLocal will be delivered as a desktop application because:

- the product is intended to run locally and offline,
- legal professionals need direct access to files and folders on their computers,
- a desktop application provides a clearer local-product experience than a browser-based localhost interface,
- local storage, deletion, file selection, and model status can be managed within one application,
- the application can later be packaged for controlled distribution.

The desktop interface is planned to be implemented with Python-compatible desktop technologies. The final UI framework will be defined in the architecture document.

---

## 10. Core User Experience

The intended MVP workflow is:

1. The user opens LexLocal.
2. The user creates a new case workspace.
3. The user adds multiple digital PDF documents.
4. The application extracts and indexes the document content locally.
5. The user asks a question about the case file.
6. The system retrieves relevant passages.
7. Foundry Local generates a grounded answer.
8. The application displays the answer with document and page citations.
9. The user opens the cited source and verifies the result.
10. The user may generate a structured case summary.
11. The user may delete the entire local workspace and its derived data.

---

## 11. Initial Structured Case Summary

The first version will use one fixed summary template:

- Parties
- Case / Matter Overview
- Claimant or Plaintiff Arguments
- Respondent or Defendant Arguments
- Important Dates
- Evidence and Supporting Documents
- Requests / Relief Sought
- Unclear or Missing Information
- Sources

The exact field names may be adapted to the selected legal case type before implementation.

---

## 12. Project Boundaries

### The MVP Is

- an offline-first desktop application,
- a single-user system,
- a local legal document intelligence workspace,
- a multi-document PDF analysis tool,
- a source-grounded question-answering system,
- a structured case-summary tool,
- a Foundry Local and Local RAG project.

### The MVP Is Not

- a legal advice system,
- a lawyer replacement,
- a case outcome prediction system,
- a cloud LLM gateway,
- a redaction or tokenization proxy,
- a law-firm management system,
- a UYAP integration,
- a document drafting automation platform,
- a multi-user or multi-tenant SaaS product.

---

## 13. Explicitly Out of Scope for the MVP

The following features are excluded from the first version:

- external cloud LLM integration,
- automatic cloud fallback,
- sensitive-data masking or reversible tokenization,
- OCR for scanned documents,
- DOCX and email support,
- contradiction detection,
- automatic legal chronology generation,
- contract-specific analysis templates,
- automatic petition generation,
- UYAP or e-signature integration,
- multi-user authentication,
- team collaboration,
- role-based access control,
- mobile application,
- advanced analytics dashboard,
- automatic application updates,
- store distribution.

These may be considered in later versions only after the MVP is completed and evaluated.

---

## 14. Privacy, Security, and Legal Position

LexLocal is designed to reduce external data transfer by performing document processing and model inference locally.

The project will follow these principles:

- no external cloud LLM is used in the MVP,
- document text is not intentionally sent to third-party AI services,
- raw document content must not be written to application logs,
- local derived data must be removed when a workspace is deleted,
- the user must be able to inspect the sources behind generated answers,
- model output must be treated as assistance, not authoritative legal judgment,
- the product must not claim automatic KVKK compliance or full legal compliance,
- the product must not claim that local execution alone guarantees security.

The final legal and technical controls will be detailed in the privacy and security document.

---

## 15. Success Definition

The MVP will be considered successful when it demonstrates that:

- multiple digital PDFs can be processed locally,
- the application works without an active internet connection after setup,
- a user can ask questions across a case folder,
- answers include correct document and page references,
- unsupported questions produce a safe “not found / insufficient evidence” response,
- a structured case summary can be generated,
- cited source passages can be opened and verified,
- workspace deletion removes documents and derived local data,
- no external cloud LLM request is required,
- core automated tests pass.

Detailed measurable acceptance thresholds will be defined in
`07_TEST_AND_EVALUATION_PLAN.md`.

---

## 16. Key Risks and Constraints

### Main Risks

- Local model quality may be limited for Turkish legal language.
- Small local models may hallucinate or oversimplify legal content.
- Citation generation may point to incomplete or incorrect passages.
- Hardware limitations may affect latency and model availability.
- PDF text extraction may fail on malformed or image-based files.
- Offline operation does not automatically provide complete device security.
- Legal terminology may vary across document and case types.

### Main Constraints

- Single developer
- Limited MVP timeline
- Digital PDFs only
- Single-user desktop usage
- No cloud LLM fallback
- No OCR in the first version
- Performance depends on the user’s hardware

---

## 17. Assumptions

The initial project assumes that:

- required models and runtime components have already been installed,
- the user has permission and a valid legal basis to process the selected documents,
- the operating system account and device are adequately protected,
- the PDF files contain extractable digital text,
- the initial dataset is suitable for development and demonstration,
- generated outputs are reviewed by a human user.

---

## 18. Stakeholders

- **Project Owner / Developer:** Gülin Kale
- **Primary User Representative:** Legal professional working with confidential case documents
- **Technology Ecosystem:** Microsoft Foundry Local
- **Project Evaluators:** Microsoft program evaluators, academic reviewers, and portfolio reviewers

---

## 19. Pending Decisions

The following decisions are intentionally left for later project documents:

1. **Initial supported operating system**
   - Windows only
   - Windows and macOS

2. **Desktop UI framework**
   - PySide6
   - Alternative desktop framework

3. **Local vector store**
   - FAISS
   - Qdrant local
   - Another embedded option

4. **Local database**
   - SQLite
   - Another embedded database

5. **Embedding model**
   - To be selected through technical evaluation

6. **Foundry Local model**
   - To be selected based on Turkish quality, hardware requirements, and structured-output support

7. **Exact legal case type used for the MVP demo**
   - Civil case
   - Commercial dispute
   - Contract dispute
   - Another controlled example

8. **Maximum MVP limits**
   - maximum number of files,
   - maximum total pages,
   - maximum file size.

9. **Measurable quality thresholds**
   - retrieval accuracy,
   - citation accuracy,
   - unsupported-answer rate,
   - acceptable latency.

10. **Export format**
    - whether summaries can be exported in the MVP,
    - and if so, PDF, DOCX, or plain text.

These decisions do not change the project’s core scope. They will be resolved in the architecture, requirements, and acceptance-criteria documents.

---

## 20. Scope Change Rule

A feature may enter the MVP only when:

1. it directly supports the core user workflow,
2. it is required for the Foundry Local or Local RAG demonstration,
3. it does not threaten completion of the existing MVP,
4. its impact on architecture, testing, privacy, and timeline is documented,
5. the change is recorded in the approved scope baseline and document index.

New ideas that do not meet these conditions must be added to the post-MVP roadmap rather than implemented immediately.

---

## 21. Final Charter Statement

LexLocal will be developed as an offline-first desktop application that helps legal professionals analyze multi-document legal case files through local, source-grounded AI.

The project’s core commitment is not to provide legal advice, but to make legal document review faster, more traceable, and less dependent on external cloud AI services.

The first version will prioritize a small number of complete, measurable, and reliable workflows over a broad set of partially implemented features.
