# LexLocal

LexLocal is a local-first legal document intelligence desktop application.

## Requirements

- Python 3.11
- uv

## Setup

```bash
uv sync
```

## Run

```bash
uv run python -m lexlocal
```

## Test

```bash
uv run pytest
```

## Lint

```bash
uv run ruff check .
```

## Type checking

```bash
uv run mypy src
```