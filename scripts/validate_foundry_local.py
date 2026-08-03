"""Validate Foundry Local model inference on the development machine."""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
from collections.abc import Callable, Sequence
from datetime import datetime

from lexlocal.infrastructure.foundry import (
    DEFAULT_VALIDATION_MODEL_ALIAS,
    FoundryLocalAdapter,
)

DEFAULT_MODEL_ALIAS = DEFAULT_VALIDATION_MODEL_ALIAS
_VALIDATION_PROMPT = (
    "Reply with exactly one short sentence confirming that local inference works."
)

Output = Callable[[str], None]


def _print_environment(output: Output, *, cached_only: bool) -> None:
    """Print non-sensitive environment information for a validation record."""

    try:
        sdk_version = importlib.metadata.version("foundry-local-sdk")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = "not installed"

    mode = (
        "cached-only (network state not verified)"
        if cached_only
        else "online preparation"
    )
    output(f"Validation timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    output(f"Validation mode: {mode}")
    output(f"Python version: {platform.python_version()}")
    output(f"Foundry Local SDK version: {sdk_version}")
    output(f"Operating system: {platform.system()} {platform.release()}")
    output(f"Machine architecture: {platform.machine()}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for hardware validation."""

    parser = argparse.ArgumentParser(
        description="Validate meaningful local chat inference through Foundry Local.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_ALIAS,
        help=f"Foundry Local model alias (default: {DEFAULT_MODEL_ALIAS})",
    )
    parser.add_argument(
        "--cached-only",
        action="store_true",
        help="Require a cached model and skip intentional EP/model download preparation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run Foundry Local validation from the command line."""

    arguments = build_parser().parse_args(argv)
    _print_environment(print, cached_only=arguments.cached_only)
    print(f"Requested model alias: {arguments.model}")
    adapter = FoundryLocalAdapter.initialize()
    adapter.infer(
        model_alias=arguments.model,
        prompt=_VALIDATION_PROMPT,
        cached_only=arguments.cached_only,
        output=print,
    )
    print("Foundry Local validation completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
