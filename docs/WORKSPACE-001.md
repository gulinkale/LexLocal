# WORKSPACE-001 — Implement the minimal workspace vertical slice

## Ticket objective

Implement the smallest Application-to-SQLite vertical slice that can create,
list, select, and expose one active workspace scope. Persist a stable
`WorkspaceId`, synthetic/non-sensitive M1 display name, optional profile,
documented state, and timestamps through an Application-owned repository and
the existing Unit of Work. Completion means a newly created workspace can be
selected and its typed ID becomes the sole Application scope available to later
ingestion and retrieval; those workflows are not part of this ticket.

WORKSPACE-001 is an explicitly synthetic-only M1 slice. It makes no production
encryption, keyed-fingerprint, workspace-key, or real-user-data claim.

## Repository evidence / current state

- `WorkspaceId` is already an immutable nominal UUID type. It validates and
  canonicalizes supplied identifiers but intentionally does not generate them.
- `Workspace` is already an immutable Domain aggregate with a sensitive
  `display_name`, the four persisted `WorkspaceState` values, the approved
  transition matrix, and state-derived capabilities.
- The Domain aggregate does not yet represent profile or timestamps.
- Migration `001_initial.sql` already defines `workspaces`. It requires
  `name_ciphertext`, `name_lookup_fingerprint`, `state`, `created_at`, and
  `updated_at`; profile fields are nullable. No WORKSPACE-001 migration is
  needed.
- The approved profile values are `LITIGATION`, `CONTRACT_REVIEW`, and
  `GENERAL_LEGAL`. Creation may leave profile unset.
- Timestamps are UTC ISO-8601 text with millisecond precision, for example
  `2026-07-27T16:42:18.391Z`.
- The existing `SensitivePayloadCodec` binds bytes to a
  `SensitivePayloadContext` and `WorkspaceKeyReference`. The configured
  development implementation is explicitly synthetic-fixture-only and returns
  format version 1.
- The current schema requires a display-name lookup BLOB but does not make it
  unique. Duplicate-name rejection is not a WORKSPACE-001 behavior.
- `workspace_key_records` exists, but no key lifecycle/provider is implemented.
  Production security composition already fails closed because no release-safe
  provider exists.
- Data-model section 56 describes the later complete product transaction as
  workspace + key metadata + analysis root + activity event. The approved M1
  exception limits WORKSPACE-001 creation to its workspace persistence; later
  tickets own the other three capabilities.
- Application already owns a minimal `UnitOfWork` protocol. The concrete
  `SQLiteUnitOfWork` provides begin, explicit commit, rollback on exception or
  omitted commit, connection cleanup, and reuse, but exposes no repository yet.
- `SQLiteConnectionFactory` configures named rows, WAL, foreign keys, and a busy
  timeout. Existing integration tests use migrated `tmp_path` databases.
- Bootstrap initializes migrations and returns the connection factory. No
  workspace repository, use case, or active-workspace state is composed yet.
- Architecture tests already forbid Application imports of Infrastructure and
  direct SQLite/raw-write bypasses.

## Frozen architecture decisions

1. Reuse `Workspace`, `WorkspaceId`, `WorkspaceState`, the initial migration,
   SQLite connection factory, and existing UoW. Do not create duplicates.
2. Add one `WorkspaceProfile(StrEnum)` to Domain with exactly the three approved
   values. Add optional profile plus `created_at` and `updated_at` to the
   existing `Workspace` aggregate.
3. Domain timestamps are timezone-aware UTC `datetime` values. Domain rejects
   naive/non-UTC values and `updated_at < created_at`; Infrastructure alone
   serializes/parses the documented millisecond `Z` representation.
4. Creation starts in `WorkspaceState.ACTIVE`. If a user profile is supplied,
   Infrastructure writes `profile_source='USER'` and
   `profile_confirmed_at=created_at`; otherwise both are null. Suggestion,
   archive, and deletion metadata remain null.
5. Generate ID/time at the Application boundary using injected
   `Callable[[], WorkspaceId]` and `Callable[[], datetime]`. Do not add Domain
   generation APIs or generic generator/clock frameworks.
6. Application owns one minimal `WorkspaceRepository` with `add`, `get`, and
   `list_normal`. No generic CRUD/filter/pagination or lifecycle methods.
7. `get` and `list_normal` are normal M1 access and expose only
   `WorkspaceState.ACTIVE`. `get` returns `Workspace | None`; missing and
   non-active IDs are indistinguishable at this boundary.
8. Extend the existing `UnitOfWork` with a transaction-bound `workspaces`
   repository. Do not create `WorkspaceUnitOfWork` or expose SQLite to
   Application.
9. Implement focused create, list, and select behavior, not a broad generic
   workspace service.
10. Active selection is Application-owned process memory containing zero or one
    `WorkspaceId`. It is not persisted and has no `is_active`, preference,
    session, cache, or migration representation.
11. “Selected workspace” and `WorkspaceState.ACTIVE` are distinct concepts, but
    only an `ACTIVE` aggregate may become the selected M1 scope. ARCHIVED and
    deletion states belong to later workspace lifecycle behavior.
12. Application exposes the selected typed ID through a small
    `ActiveWorkspaceScope` with `select`, `clear`, and `require_workspace_id`.
    Future ingestion/retrieval consumes this boundary without UI or
    Infrastructure coupling.
13. Application works only with logical `display_name`. It never knows
    `name_ciphertext`, lookup-token bytes, codec format, or key-reference
    representation.
14. Infrastructure owns one explicitly named
    `InsecureDevelopmentOnlyWorkspaceNamePersistence` adapter. It uses the
    existing development payload codec with deterministic synthetic context
    metadata and a development-only deterministic lookup token. It makes no
    encryption, confidentiality, HMAC, or production-safety claim.
15. M1 development/test uses a synthetic `WorkspaceKeyReference(workspace_id,
    1)` only as codec metadata and creates no `workspace_key_record`. This is
    not a real key or key lifecycle claim. SECURITY-003 owns real workspace
    keys and release enforcement in M2.
16. The SQLite repository depends on that Infrastructure adapter, while its
    public contract remains Application-owned. M2 may replace repository
    internals/Bootstrap composition without changing Workspace Application
    signatures, repository direction, or active-scope semantics.
17. WORKSPACE-001 creation writes only the workspace row in one transaction.
    It does not create placeholder key metadata, analysis root, or activity
    event. Later owning tickets add those transaction participants.
18. Bootstrap is the only layer that composes concrete repository/UoW,
    development adapter, ID/time callables, and the process-lifetime active
    scope. Production continues to fail closed before insecure composition.

## Frozen scope — IN

- `WorkspaceProfile` and the minimum profile/timestamp extension of `Workspace`.
- Application-owned repository and active-scope contracts.
- Create, ACTIVE-only list, explicit ACTIVE-only select, clear, and
  require-active behavior.
- Explicitly development-only synthetic display-name persistence required by
  the existing schema.
- SQLite workspace repository and exact row mapping without a migration.
- Minimal extension of the existing UoW for transaction-bound repository
  access.
- Minimum Bootstrap composition for development/test and one process-lifetime
  active scope.
- Focused Domain, Application, repository, temporary-DB, commit/rollback,
  selection/isolation, Bootstrap, and architecture tests.

## Frozen scope — OUT

- Real/sensitive workspace names or real user/legal data in M1.
- Production encryption, keyed/HMAC lookup fingerprints, raw-key handling,
  workspace key records, key generation/wrapping/rotation/recovery, or a fake
  release-safe provider. These belong to M2 SECURITY-003.
- Placeholder analysis roots or activity events. Their owning later tickets
  add them when the capabilities exist.
- Ingestion, PDF/OCR, processing, chunking, embeddings, vector search, RAG,
  chat, analysis execution, UI, HTTP, and presentation workflows.
- Archive listing, archive/restore, rename, deletion, profile suggestion/AI
  confirmation, or other workspace administration. WORKSPACE-002 owns archive
  behavior.
- Active-selection persistence, `is_active`, last-selected preferences, session
  or caching frameworks, and speculative multi-user permissions.
- Migration/schema redesign, generic repository/entity hierarchies, generic
  CRUD services, repository registries, a second UoW, DI/service locators,
  event buses, or plugins.
- Secrets, credentials, raw keys, real `.env` content, generated artifacts, or
  security claims based on the development adapter.

## Layer/file ownership

| Layer | Planned ownership | Immediate M1 reason |
|---|---|---|
| Domain | Extend `domain/workspace.py` with `WorkspaceProfile` and aggregate timestamps. | The existing aggregate remains the single source of business validity and required persisted fields. |
| Application ports | Add `application/ports/workspaces.py`; minimally extend `application/ports/unit_of_work.py`. | Application needs three persistence operations inside its existing transaction abstraction without SQLite knowledge. |
| Application behavior | Add focused create/list/select and `ActiveWorkspaceScope` behavior in `application/workspaces.py`. | The ticket requires use-case orchestration and one typed future workflow scope. |
| Infrastructure security | Add `infrastructure/security/insecure_development_workspace.py`. | The required schema BLOBs need an explicitly synthetic adapter around the existing development codec; this must not become an Application contract or release-safe alias. |
| Infrastructure persistence | Add `infrastructure/persistence/sqlite_workspace_repository.py`; minimally adapt `sqlite_unit_of_work.py`. | SQL, row mapping, adapter use, and connection binding are technical details. |
| Bootstrap | Extend `bootstrap/persistence.py` and the minimum startup composition point. | Only Bootstrap may construct concrete adapters/repositories and own process lifetime. |
| Tests | Extend existing Domain/UoW/Bootstrap/architecture tests and add focused Application/repository integration tests. | Each new contract and the complete synthetic vertical slice need behavioral evidence. |

New public abstractions remain limited to:

- `WorkspaceProfile`: closed business vocabulary already enforced by schema.
- `WorkspaceRepository`: exactly the operations create/list/select require.
- `ActiveWorkspaceScope`: the sole typed scope future workflows require.

The development name adapter is an Infrastructure detail, not a general public
security framework. No new UoW type is introduced.

## Workspace persistence mapping

| Domain/Application value | SQLite column(s) | M1 mapping |
|---|---|---|
| `Workspace.id` | `id` | Canonical `str(WorkspaceId)` on write; reconstruct the same typed ID on read. |
| `Workspace.display_name` | `name_ciphertext` | For synthetic development/test only, UTF-8 bytes pass through `InsecureDevelopmentOnlyPayloadCodec` using deterministic context: workspace ID, owner ID equal to canonical workspace ID, purpose `workspace-display-name`, schema version 1, and synthetic key reference version 1. Store only returned payload bytes. Reconstruct the same metadata and format version 1 for decode. |
| display-name equality material | `name_lookup_fingerprint` | Development-only SHA-256 token over a fixed versioned/domain-separated prefix plus the exact UTF-8 display-name bytes. It is deterministic only to satisfy the existing NOT NULL schema and future synthetic equality tests; it is unkeyed and makes no security/HMAC claim. M2 replaces it. |
| `Workspace.state` | `state` | Exact `WorkspaceState.value`; invalid stored values fail mapping rather than being coerced. |
| `Workspace.profile` | `profile` | `None` or exact `WorkspaceProfile.value`. |
| profile metadata | `profile_source`, `profile_confirmed_at` | Both null when profile is unset; otherwise `USER` and the creation timestamp. AI suggestion columns remain null. |
| `Workspace.created_at` | `created_at` | Aware UTC datetime serialized to ISO-8601 text with exactly millisecond precision and `Z`. |
| `Workspace.updated_at` | `updated_at` | Equal to `created_at` at creation; same serialization. |
| later lifecycle metadata | `archived_at`, `deletion_started_at` | Null in WORKSPACE-001. |

Persistence rules:

- State, ID, both synthetic name BLOBs, and timestamps are non-null; profile is
  nullable.
- Creation preserves a Domain-valid display name exactly; it does not trim,
  normalize, case-fold, or reinterpret it before UTF-8 encoding.
- The development lookup token has no uniqueness constraint. WORKSPACE-001 does
  not reject duplicate names.
- `get` and `list_normal` include `WHERE state = 'ACTIVE'`. Tests compare list
  contents by ID because no user-facing ordering contract exists.
- Primary-key conflict raises a sanitized Application-owned
  `WorkspaceConflict`; SQLite messages and display names do not escape.
- Invalid stored values raise sanitized `WorkspacePersistenceError`. A missing
  or non-ACTIVE `get` returns `None` without revealing which condition applied.
- The adapter/module/class docstrings and tests must state the four established
  exact risk labels: `DEVELOPMENT ONLY`, `SYNTHETIC FIXTURES ONLY`,
  `NOT RELEASE SAFE`, and `NOT FOR REAL USER DOCUMENTS`.

## Repository contracts

`WorkspaceRepository` is an Application-owned protocol:

- `add(workspace: Workspace) -> None`: stage one valid aggregate on the current
  transaction; never commit or generate fields.
- `get(workspace_id: WorkspaceId) -> Workspace | None`: return the exact ACTIVE
  workspace or `None` for missing/non-ACTIVE IDs.
- `list_normal() -> Sequence[Workspace]`: return ACTIVE workspaces only, with no
  ordering promise.

The same module owns only the errors the repository boundary needs:

- `WorkspaceConflict`: duplicate stable ID on add.
- `WorkspacePersistenceError`: invalid/corrupt mapping or other sanitized
  repository contract failure.

The repository exposes no arbitrary filters, raw rows, SQL/connections,
cross-workspace children, profile mutation, archive, rename, or delete methods.
All identity-based access requires `WorkspaceId`; runtime checks reject plain
strings and other typed IDs before repository behavior.

## Application use-case contracts

- `CreateWorkspace(display_name, profile=None) -> Workspace`: obtain ID and one
  UTC timestamp from injected callables, build one ACTIVE aggregate with equal
  created/updated timestamps, add inside the existing UoW, explicitly commit,
  and return it. Creation does not select implicitly.
- `ListWorkspaces() -> Sequence[Workspace]`: open a UoW, return
  `list_normal()`, and leave selection unchanged.
- `SelectWorkspace(workspace_id) -> WorkspaceId`: resolve through `get` inside
  a UoW and update active scope only after an ACTIVE workspace is returned.
  `None` raises sanitized `WorkspaceNotFound`; failed selection preserves the
  previous selection.
- `ActiveWorkspaceScope.require_workspace_id() -> WorkspaceId`: return exactly
  the selected typed ID or raise `ActiveWorkspaceRequired` when none exists.
- `ActiveWorkspaceScope.clear()`: return to no selection.

Use cases receive `Callable[[], UnitOfWork]`; each invocation obtains one UoW.
No generic service/factory framework is introduced.

## Active-workspace semantics

- Exactly zero or one workspace is selected per application process; initial
  state is none.
- Selection is explicit and in memory. Restart does not restore it.
- Selecting B replaces A only after B resolves through ACTIVE-only `get`.
  Missing, ARCHIVED, DELETING, or DELETION_RECOVERY B leaves A unchanged.
- The downstream value is only `WorkspaceId`, never a display name, aggregate,
  row string, UI index, repository, or provider.
- `clear` removes the only scope; `require_workspace_id` then fails closed.
- Future ingestion/retrieval must obtain the ID from this scope. They do not
  receive fallback IDs or implement another active-selection source.

## Unit-of-Work / transaction semantics

- Reuse `UnitOfWork`; add a `workspaces: WorkspaceRepository` property available
  only while active.
- `SQLiteUnitOfWork` constructs the repository with its active connection and
  development name adapter on entry, and releases it on commit, rollback, or
  exit. Reuse must construct a fresh transaction-bound repository.
- WORKSPACE-001 creation stages only one workspace row and commits explicitly.
  No key record, analysis root, or activity event placeholder is created.
- Repository methods never commit, roll back, or open another write connection.
- Provider/mapping/conflict failures, exceptions, or omitted commit roll back
  the workspace insert. A fresh connection then sees no new row.
- Read use cases remain within a UoW scope and do not manufacture writes.
- Existing post-finalization rejection, cleanup, and UoW reuse behavior remains
  unchanged.

## Workspace-isolation rules

- Repository identity inputs are typed `WorkspaceId`; invalid nominal types are
  rejected before SQL.
- Normal list/get/select exposes only ACTIVE workspaces.
- Active selection changes only with the exact ID returned by successful
  repository resolution.
- Once B replaces A, `require_workspace_id` exposes only B; no previous object,
  list, cache, UI, or fallback remains an alternative scope source.
- Future workspace-owned repositories must accept this caller workspace ID and
  use the existing composite `(id, workspace_id)` schema ownership constraints.
  WORKSPACE-001 validates representative existing constraints without
  implementing future repositories.
- Errors/logs never reveal synthetic name bytes, stored payloads, lookup tokens,
  SQL, paths, or inaccessible-row state.

## Test strategy

- Domain tests: exact profile vocabulary, optional profile, aware UTC-only
  timestamps, `created_at <= updated_at`, transition preservation,
  immutability, and sensitive `repr`.
- Application tests with fakes: stable generated ID, one clock value, explicit
  commit, rollback/failure behavior, ACTIVE-only list assumptions, no implicit
  selection, successful selection, failed replacement preservation, clear, no
  active scope, and exact typed-ID exposure.
- Development-adapter tests: four exact warning labels, deterministic synthetic
  token, context/key metadata reconstruction, UTF-8 round-trip, workspace
  substitution rejection, and no encryption/HMAC/security claim.
- SQLite repository tests on a migrated `tmp_path` DB: full field round-trip,
  nullable/set profile, exact UTC millisecond text, canonical ID, ACTIVE-only
  get/list, missing and every non-ACTIVE state, duplicate ID sanitization,
  corrupt mapping sanitization, and no ordering assertion.
- UoW/transaction tests: repository available only inside the transaction,
  committed insert visible through a fresh connection, exception/no-commit
  rollback, no key/analysis/activity placeholder rows, finalization cleanup,
  and reuse with a fresh repository.
- Isolation tests: only a successfully resolved ACTIVE ID changes the sole
  scope; retain representative migrated-DB evidence for existing composite
  cross-workspace foreign keys without adding future repositories.
- Bootstrap tests: development/test compose the explicit insecure adapter and
  one shared active scope; production remains fail-closed with no insecure
  fallback.
- Architecture tests: Application imports neither SQLite nor concrete
  Infrastructure; Infrastructure implements Application ports; Domain remains
  independent; existing direct-write guards remain green.
- Fixtures use anonymous synthetic names only. Errors/logs never assert or emit
  fixture names or provider payload bytes.

## Overengineering risks

- The development lookup token is intentionally not production security.
  Naming it generically or claiming encryption/HMAC would conceal M2 work.
- Adding a public workspace-name security port is unnecessary in M1: the
  logical Application/repository contracts already isolate the Infrastructure
  representation that M2 will replace.
- Creating fake key records/wrapped keys, analysis roots, or activity events
  would implement later capabilities and misrepresent security/atomicity.
- A generic repository/entity hierarchy, CRUD service, registry, second UoW,
  DI container, service locator, event bus, cache, or session has no immediate
  reason.
- Persisting selection is speculative; exposing an aggregate/UI selection
  instead of the typed ID would create a later ingestion/retrieval retrofit.
- Adding archive/list/archive/rename/delete/profile-suggestion behavior because
  schema columns exist exceeds WORKSPACE-001.
- Hard-coding list order without a requirement would turn incidental SQL/index
  behavior into a public contract.
- Application SQL, direct connections, stored-representation knowledge, or
  concrete provider imports violate existing architecture boundaries.

## Implementation steps

## 1. Complete Domain and Application workspace contracts ✅

### Purpose

Add the missing aggregate fields, repository/UoW contracts, active scope, typed
errors, and focused create/list/select behavior.

### File / files

- `src/lexlocal/domain/workspace.py`
- `src/lexlocal/application/ports/workspaces.py`
- `src/lexlocal/application/ports/unit_of_work.py`
- `src/lexlocal/application/workspaces.py`
- `tests/unit/domain/test_workspace.py`
- `tests/unit/application/ports/test_workspaces.py`
- `tests/unit/application/test_workspaces.py`

### Do

- [x] Add exact profile/timestamp Domain contracts and tests.
- [x] Define only `add`, ACTIVE-only `get`, ACTIVE-only `list_normal`, and the
  two sanitized repository errors.
- [x] Extend existing UoW with transaction-bound repository access.
- [x] Implement/test create, list, select, replace, clear, and require-selected
  behavior with fakes.
- [x] Prove failed selection preserves the old scope and failed create does not
  commit.

### Do not

- [x] Do not add persistence code, generic generators/repositories/services, a
  second UoW, UI, archive behavior, or later workflow APIs.

### Validation

```bash
uv run pytest tests/unit/domain/test_workspace.py tests/unit/application/ports/test_workspaces.py tests/unit/application/test_workspaces.py -v
uv run ruff check src/lexlocal/domain/workspace.py src/lexlocal/application/ports/workspaces.py src/lexlocal/application/ports/unit_of_work.py src/lexlocal/application/workspaces.py tests/unit/domain/test_workspace.py tests/unit/application/ports/test_workspaces.py tests/unit/application/test_workspaces.py
uv run mypy src
git diff --check
```

### Step completion

- [x] Domain/Application contracts and behavior are minimal, typed, tested, and
  independent of SQLite and concrete security providers.

## 2. Implement the synthetic workspace-name persistence adapter ✅

### Purpose

Provide the explicit development/test-only bridge from logical synthetic names
to the two existing required schema BLOBs without creating a production claim.

### File / files

- `src/lexlocal/infrastructure/security/insecure_development_workspace.py`
- `tests/unit/infrastructure/security/test_insecure_development_workspace.py`

### Do

- [x] Wrap the existing development payload codec using deterministic synthetic
  context/key metadata and format version 1 reconstruction.
- [x] Produce the versioned/domain-separated deterministic development lookup
  token over exact UTF-8 bytes.
- [x] Include and test all four exact development-risk labels.
- [x] Test deterministic token, round-trip, metadata/workspace mismatch, empty
  bytes where relevant, and sanitized failures using anonymous fixtures.

### Do not

- [x] Do not claim encryption/HMAC/confidentiality, accept real user data,
  create key records/raw keys, add a general alias/port, or change provider
  selection.

### Validation

```bash
uv run pytest tests/unit/infrastructure/security/test_insecure_development_workspace.py -v
uv run ruff check src/lexlocal/infrastructure/security/insecure_development_workspace.py tests/unit/infrastructure/security/test_insecure_development_workspace.py
uv run mypy src
git diff --check
```

### Step completion

- [x] The adapter satisfies synthetic schema mapping with unmistakable risk
  boundaries and no release-safe claim.

## 3. Implement and test the SQLite workspace repository ✅

### Purpose

Map the Domain aggregate to the existing schema through the development adapter
and prove exact repository behavior on migrated temporary databases.

### File / files

- `src/lexlocal/infrastructure/persistence/sqlite_workspace_repository.py`
- `tests/integration/persistence/test_sqlite_workspace_repository.py`

### Do

- [x] Bind to an existing active connection and implement only the frozen three
  operations.
- [x] Round-trip all required fields with exact timestamp/profile/state mapping.
- [x] Filter get/list to ACTIVE and sanitize conflict/corrupt mapping failures.
- [x] Test stable ID, nullable/set profile, all state filters, missing/duplicate
  cases, and no ordering promise.

### Do not

- [x] Do not commit, generate values, add CRUD/lifecycle methods, create later
  rows, store names outside the adapter, or modify migrations.

### Validation

```bash
uv run pytest tests/integration/persistence/test_sqlite_workspace_repository.py -v
uv run ruff check src/lexlocal/infrastructure/persistence/sqlite_workspace_repository.py tests/integration/persistence/test_sqlite_workspace_repository.py
uv run mypy src
git diff --check
```

### Step completion

- [x] The minimal repository passes complete synthetic round-trip and ACTIVE
  access tests without owning transaction finalization.

## 4. Integrate repository, Unit of Work, and Bootstrap ✅

### Purpose

Bind the repository to the existing transaction and compose one development
vertical slice/process-lifetime active scope at Bootstrap.

### File / files

- `src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py`
- `src/lexlocal/bootstrap/persistence.py`
- `src/lexlocal/bootstrap/application.py` only where lifetime wiring is needed
- `tests/integration/persistence/test_sqlite_unit_of_work.py`
- `tests/integration/persistence/test_workspace_transactions.py`
- `tests/unit/bootstrap/test_persistence.py`
- `tests/unit/bootstrap/test_application.py`
- `tests/integration/test_workspace_vertical_slice.py`

### Do

- [x] Construct/release a fresh repository with the active SQLite connection.
- [x] Prove commit, exception/no-commit rollback, post-finalization rejection,
  reuse, and absence of key/analysis/activity placeholder rows.
- [x] Compose ID/time callables, explicit development adapter, use cases, and
  one shared active scope in Bootstrap.
- [x] Prove create → list → explicit select → sole typed scope with synthetic
  data and failed replacement preservation.
- [x] Preserve production fail-closed behavior.

### Do not

- [x] Do not expose SQLite to Application, add another transaction abstraction,
  persist selection, introduce a container/registry, or add insecure production
  fallback.

### Validation

```bash
uv run pytest tests/integration/persistence/test_sqlite_unit_of_work.py tests/integration/persistence/test_workspace_transactions.py tests/unit/bootstrap/test_persistence.py tests/unit/bootstrap/test_application.py tests/integration/test_workspace_vertical_slice.py -v
uv run ruff check src/lexlocal/infrastructure/persistence/sqlite_unit_of_work.py src/lexlocal/bootstrap/persistence.py src/lexlocal/bootstrap/application.py tests/integration/persistence/test_sqlite_unit_of_work.py tests/integration/persistence/test_workspace_transactions.py tests/unit/bootstrap/test_persistence.py tests/unit/bootstrap/test_application.py tests/integration/test_workspace_vertical_slice.py
uv run mypy src
git diff --check
```

### Step completion

- [x] The complete synthetic vertical slice shares one active scope and obeys
  existing transaction and production rejection semantics.

## 5. Validate workspace and architecture isolation ✅

### Purpose

Prove active-scope replacement, existing DB ownership constraints, and layer
direction without adding future repositories or another scanner.

### File / files

- `tests/integration/persistence/test_workspace_isolation.py`
- `tests/architecture/test_layer_boundaries.py` only if existing helpers lack a
  representative proof

### Do

- [x] Prove only successfully resolved ACTIVE IDs can replace the sole scope.
- [x] Retain representative migrated-DB proof that composite workspace foreign
  keys reject cross-workspace ownership.
- [x] Confirm Application has no SQLite/concrete Infrastructure dependency and
  Infrastructure implements the Application repository.
- [x] Reuse current migration/AST helpers and preserve allowed Bootstrap and
  Infrastructure behavior.

### Do not

- [x] Do not implement child repositories, archive behavior, a second
  architecture framework, or generic isolation machinery.

### Validation

```bash
uv run pytest tests/integration/persistence/test_workspace_isolation.py tests/architecture -v
uv run ruff check tests/integration/persistence/test_workspace_isolation.py tests/architecture/test_layer_boundaries.py
uv run mypy src
git diff --check
```

### Step completion

- [x] Typed scope, representative DB ownership, and dependency direction have
  durable evidence without false-positive workarounds.

## 6. Run quality and strict scope gates ✅

### Purpose

Validate the ticket and prove no real data, production security, later
capability, framework, or unrelated work entered the diff.

### File / files

- `docs/WORKSPACE-001.md`
- Step 1–5 files only when a genuine owning defect requires correction

### Do

- [x] Run focused workspace suites, architecture tests, full pytest, Ruff,
  mypy, and whitespace validation; record actual results only.
- [x] Audit every diff hunk for IN/OUT scope, exact development warnings,
  synthetic fixtures, secrets/raw keys, generated files, and unrelated work.
- [x] Confirm each public abstraction has its immediate M1 reason.
- [x] Confirm M2 can replace adapter/repository internals without changing
  Application workspace or active-scope contracts.

### Do not

- [x] Do not weaken checks, predict counts, refactor unrelated code, or
  implement later tickets to obtain green gates.

### Validation

```bash
uv run pytest tests/unit/domain/test_workspace.py tests/unit/application tests/unit/infrastructure/security/test_insecure_development_workspace.py tests/integration/persistence tests/integration/test_workspace_vertical_slice.py -v
uv run pytest tests/architecture -v
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```

Actual results:

- Focused workspace suites: 252 passed.
- Architecture suite: 19 passed.
- Full suite: 1016 passed, 1 skipped (opt-in local Foundry smoke test).
- Ruff: passed.
- mypy: passed for 36 source files.
- Diff whitespace validation: passed.

### Step completion

- [x] All required gates pass with actual evidence and the strict scope/security
  audit is clean.

## 7. Audit Git state for human review ✅

### Purpose

Prepare the exact WORKSPACE-001 diff for human review without mixing unrelated
work or performing unapproved commit/push/PR actions.

### File / files

- Only files proven to belong to WORKSPACE-001

### Do

- [x] Inspect branch, status, unstaged/staged stats, every diff hunk, and
  whitespace.
- [x] Stage only approved ticket files after all quality gates pass.
- [x] Report proposed commit/PR metadata and stop at the required human-review
  boundary.

### Do not

- [x] Do not stage unrelated files, hide failures, commit, push, or create a PR
  without explicit authorization.

### Validation

```bash
git status --short
git diff --stat
git diff
git diff --check
git diff --cached --stat
git diff --cached
git diff --cached --check
```

### Step completion

- [x] The exact ticket diff is clean and ready for the required human review.

## Final Definition of Done ✅

- [x] Existing Domain identifiers/state, migration, connection factory,
  SECURITY-001 codec, and UoW are reused.
- [x] Existing `Workspace` represents stable ID, logical display name, optional
  profile, state, and validated UTC timestamps without a duplicate model.
- [x] Synthetic names round-trip through the unmistakably development-only
  adapter; lookup BLOB is deterministic and carries no security claim.
- [x] No real names/data, production encryption/HMAC, key lifecycle/key record,
  analysis root, or activity event placeholder is introduced.
- [x] ID, name, nullable/set profile, state, and UTC millisecond timestamps
  round-trip exactly through the existing schema.
- [x] Minimal Application-owned repository behavior and sanitized failures are
  implemented by Infrastructure.
- [x] Creation commits only its workspace row and fully rolls back on every
  failure/no-commit path.
- [x] Normal list/get/select exposes only ACTIVE workspaces; ARCHIVED and all
  other states cannot become selected scope.
- [x] Create, list, explicit select, replacement, clear, and no-active behavior
  are focused-tested.
- [x] A newly created workspace can be selected and
  `require_workspace_id()` exposes it as the sole typed Application scope for
  future ingestion/retrieval.
- [x] Existing composite database workspace-ownership constraints retain
  representative integration evidence.
- [x] Application contains no SQLite, stored-name representation, concrete
  Infrastructure/provider, raw-key, physical-path, or plaintext-write bypass.
- [x] Bootstrap alone owns concrete composition and production remains
  fail-closed.
- [x] M2 can replace the development adapter/repository internals without
  changing Workspace Application signatures, repository ownership, or active
  selection.
- [x] No migration, archive/later workflow, generic framework, or unrelated
  change leaked into WORKSPACE-001.
- [x] Focused tests, architecture tests, full pytest, Ruff, mypy, and diff gates
  pass with actual evidence.
- [x] Final ticket diff is scope-clean and human-reviewed under repository Git
  rules.

## Current position

**WORKSPACE-001 COMPLETE ✅. READY FOR THE AUTHORIZED COMMIT/PR STAGE.** The
exact ticket file set is staged, scope/security/whitespace audited, and the
human staged-diff review is explicitly approved.

Next: **Explicit authorization to create the commit and proceed with PR delivery.**
