# LexLocal Codex Execution Rules

This document defines how Codex executes approved LexLocal engineering steps. Ticket
scope, product behavior, and public contracts remain in the relevant ticket plan.
These global rules reduce repeated prompts and reports without reducing rigor.

## 1. Authority and precedence

Resolve conflicts using this short order:

1. The current user or task instruction.
2. The current ticket's approved, frozen implementation plan.
3. This global execution policy.
4. Existing repository conventions and evidence.
5. Generic engineering preference.

This policy must not override a ticket-specific frozen decision. Use repository
evidence only for details the ticket leaves open. Report genuine higher-authority
conflicts as blockers rather than silently changing scope.

## 2. Before editing

Read the current step completely. Read prerequisite or neighboring ticket sections
only when needed to resolve a dependency, frozen decision, or ambiguity. Do not read
the entire ticket by default.

Inspect touched files, nearby patterns, relevant tests, and applicable architecture
rules. Distinguish facts from assumptions.

Keep inspection proportional: isolated changes do not require unrelated subsystem
audits; layer ownership, public contracts, and cross-cutting behavior require broader
context. Repository convention outranks generic Python preference.

Treat pre-existing or unattributed changes as outside the current task. Preserve them
unless the approved step requires modification; never revert or clean them merely to
obtain a clean worktree.

When relevant tests may already fail or changes overlap the files under work, run the
smallest useful pre-edit baseline when feasible. This is for failure attribution, not
a requirement to run the full suite before every isolated change.

## 3. The current step is the unit of work

Implement only the requested numbered step. Do not add later tests, ports, providers,
helpers, or status for convenience. Each diff must remain independently reviewable
and leave the repository coherent.

If current-step tests expose a completed prerequisite violating an approved
invariant, make and report only the minimum correction. It does not authorize
unrelated refactoring.

## 4. Frozen decisions and blockers

Treat frozen or approved scope, ownership, architecture, and public contracts as
authoritative. Style preferences and broader abstractions do not reopen them.

If following a frozen decision is impossible because of a concrete repository
conflict, correctness issue, or missing authority:

1. Stop the blocked expansion.
2. State the exact blocker and repository evidence.
3. Identify the affected approved requirement.
4. Propose the smallest correction.
5. Wait for explicit approval when required.

Repository conventions should resolve ordinary choices. A blocker is not permission
to broaden scope.

## 5. Architecture and ownership

Follow the dependency rules enforced by the repository's architecture tests and
frozen architecture documents. Do not strengthen or relax those rules without an
approved architectural change.

Current repository evidence establishes:

- Domain is independent of Application, Infrastructure, Presentation, and Bootstrap,
  using only allowed standard-library or Domain dependencies.
- Application must not depend on concrete Infrastructure, Presentation, or
  Bootstrap. Application owns use-case orchestration and its required ports.
- Infrastructure may implement approved Application- or Domain-owned ports, but it
  must not depend on Presentation or Bootstrap.
- Presentation may use approved Application and Domain types directly; it must not
  import forbidden concrete Infrastructure or Bootstrap code or bypass established
  boundaries.
- Bootstrap is the explicit composition root and may know concrete implementations
  for wiring and lifetimes. Preserve manual composition; do not add an external DI
  framework.

Do not bypass established ports for shorter technical access. Extend existing AST
architecture tests instead of creating a parallel framework. Avoid circular imports,
concrete imports in abstraction-owning layers, and unapproved package-root re-exports.

## 6. Minimal but complete implementation

Prefer explicit code, the standard library, established patterns, and small cohesive
units. Unless required, do not add generic frameworks, base hierarchies, factories,
registries, plugins, DI containers, service locators, speculative helpers, or
"future-proof" APIs.

Minimal does not mean underengineered. Preserve required validation, ownership,
typed boundaries, failure semantics, testability, and architecture guards.

Do not implement speculative future needs or API completeness. A compatibility
boundary belongs now only when the frozen contract requires it.

## 7. Testing and static typing

Test current-step behavior or invariants. Run focused tests first and broader suites
at ticket-defined final gates.

- Follow the repository's pytest layout, naming, and parametrization conventions.
- Use parametrization when it improves clarity; avoid oversized matrices.
- Test the project contract, not Python, dataclass, or library behavior itself.
- Prefer structural or behavioral checks over brittle source-string assertions.
- Do not add fake tests for later-step behavior that does not exist.
- Do not weaken a valid invariant when a test reveals a production defect; make the
  smallest authorized correction instead.

Distinguish runtime behavior from static contracts. Ensure mypy checks any required
Protocol double or assignment; if `mypy src` excludes it, check its file explicitly.
Do not hide type errors with `Any`, casts, or ignores, or weaken global configuration.

## 8. Validation and error semantics

Runtime contracts require runtime enforcement, not annotations alone. Reject invalid
values without coercion, normalization, trimming, or reinterpretation unless the
contract explicitly requires it.

Keep validation deterministic where precedence matters and validate types before
field access. Use the owning layer's error vocabulary without unnecessary hierarchy.
Errors and logs must not expose sensitive payloads or secrets.

## 9. Data and security hygiene

- Never write secrets, credentials, raw keys, or real `.env` contents to the
  repository.
- Use synthetic, anonymous, or explicitly permitted controlled fixtures for tests
  and development.
- Do not add real client or legal documents as source, fixtures, logs, or artifacts.
- Do not leak sensitive content through errors, logs, test IDs, snapshots, or final
  reports.
- Do not weaken existing redaction, isolation, or fail-closed boundaries for
  convenience.

Ticket-specific security and cryptographic requirements remain in their ticket and
security design documents, not in this global policy.

## 10. Quality gates and command failures

The ticket or step's exact validation list is authoritative. For a small step, use
this proportional sequence unless the plan says otherwise:

1. Relevant focused pytest.
2. Ruff for touched files.
3. Existing strict mypy scope and any explicit type-proof check.
4. Architecture tests when the layer boundary is affected or the plan requires them.
5. `git diff --check`.

At final ticket gates, run the full pytest, `ruff check .`, mypy, and other suites
required by the plan. Do not force the full suite after every microscopic edit when
the approved plan deliberately separates focused checks from final gates.

When a command fails, inspect the actual cause. Fix current-step failures; do not
hide unrelated pre-existing failures or attribute them to the current task. Report
the distinction clearly. Do not complete a step while a required current-step gate
fails. Report an unrun check as `NOT VERIFIED`, never `PASS`. Never predict or
hardcode test counts; report only results from commands that actually ran.

## 11. Diff and scope review

A green test suite is not sufficient evidence of completion. Before finishing,
inspect `git status --short` and the relevant diff. Check for:

- unrelated or later-step implementation;
- unexpected files, refactors, or formatting churn;
- dependency, configuration, or migration changes;
- generated, cache, or IDE artifacts;
- secrets or real sensitive data;
- abstractions or boundary bypasses outside ticket scope.

Every changed production line must be explainable by the current step or an
explicitly reported prerequisite defect correction. Preserve pre-existing or
unattributed changes, and claim only changes made for the current task.

## 12. Documentation status

Do not mark a step heading or checkbox complete until implementation and all required
checks succeed. Update only the current step's status; do not mark future steps
complete. Keep the ticket's current-position section consistent and identify exactly
one next step.

A blocked step remains incomplete. Checkboxes record evidence rather than making the
document appear finished. Change an earlier frozen requirement only through an
approved blocker correction.

## 13. Git and side-effect discipline

Do not commit, push, or create a PR unless the current task explicitly requests it.
At a commit or PR step, inspect status, staged diff, and staged diff checks; stage
only intended files and verify that no secrets or generated artifacts are included.
Keep ticket-specific branch names, commit messages, and PR titles in ticket plans.

Do not perform network downloads, package installation, destructive filesystem or
Git operations, migrations against real or user data, writes to external services,
or other irreversible actions unless the approved current step explicitly requires
and authorizes them. Prefer repository-local, reversible, controlled actions. If an
external or destructive action is necessary but not clearly authorized, report the
requirement instead of performing it silently.

Never use destructive Git operations to clean pre-existing changes without explicit
authority.

## 14. Refactoring, dependencies, files, and documentation in code

"While I'm here" refactoring is prohibited. A local refactor is allowed only when
required to implement the current behavior safely or to fix an approved prerequisite
defect exposed by the step. Keep it minimal and report it separately.

Add a dependency only when the approved step explicitly requires it, the standard
library and existing dependencies cannot satisfy the need, and the ticket permits
dependency changes. Report and justify every new dependency.

Do not create files for symmetry. Add a file when frozen ownership, repository
convention, or cohesion requires it. Do not split one focused concept arbitrarily
across `models.py`, `types.py`, `utils.py`, and `helpers.py`; likewise, do not combine
unrelated responsibilities merely to avoid creating files.

Follow repository style for comments and docstrings. Document non-obvious invariants,
safety constraints, and architectural intent rather than restating obvious code.

## 15. Completion report and explainability

Unless the step prompt requires another format, use a concise evidence-based report:

1. **VERDICT**
2. **CHANGES**
3. **TESTS / VALIDATION**
4. **SCOPE / DIFF AUDIT**
5. **FILES CHANGED**
6. **CURRENT POSITION / NEXT STEP**

Do not repeat information across sections. Report actual command evidence rather
than generic reassurance. When a decision is non-obvious, briefly explain why the
chosen layer owns it or why a broader abstraction was rejected. Do not turn every
response into a tutorial.

## 16. Token efficiency

Read this policy once per task; do not restate it in the final response. Do not copy
the ticket plan, re-derive frozen decisions when no blocker exists, or dump unrelated
repository context. Keep tool output, progress commentary, and final reporting from
repeating the same evidence.

Token efficiency must not skip validation or reasoning. Remove repetition, not
rigor.

## 17. Definition of a completed step

A step is complete only when its required implementation is finished, prior green
behavior remains intact, required runtime, static, architecture, and lint checks
have passed with actual command evidence, the diff and scope review are clean, and
status documentation matches that evidence.

Code that merely looks correct, predicted command results, or missing gates are not
completion evidence.

## Short reusable step prompt template

```text
Read and follow:

- docs/CODEX_EXECUTION_RULES.md

Then read ONLY:

- Step <N> in docs/<TICKET>.md

Read prerequisite or neighboring ticket sections only if needed to resolve a
current-step dependency or ambiguity.

Complete only:

Step <N> — <name>

Step-specific goal/invariants:

- ...

Step-specific validation:

- ...

Do not implement Step <N+1>.