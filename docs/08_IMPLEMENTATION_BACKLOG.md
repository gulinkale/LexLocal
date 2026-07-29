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

- PERSISTENCE-001: Establish SQLite persistence foundation
  - Validate the initial migration
  - Implement the migration runner
  - Add the SQLite connection factory
  - Add the Unit of Work foundation
  - Add persistence integration tests
  - Covers the former DB-001, DB-002, DB-003, and DB-004 tasks

## M1 — Security and Workspace Foundation

- SEC-001: Cryptography interfaces
- SEC-002: HKDF subkey derivation
- SEC-003: AES-GCM field encryption
- SEC-004: Master-key setup
- SEC-005: Workspace-key management
- WS-001: Workspace domain model
- WS-002: Workspace repository interface
- WS-003: SQLite workspace repository
- WS-004: Create workspace use case
- WS-005: List workspaces use case
- WS-006: Workspace creation UI

