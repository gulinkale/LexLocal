"""Validate Foundry Local model inference on the development machine."""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Any

DEFAULT_MODEL_ALIAS = "qwen2.5-0.5b"
_VALIDATION_PROMPT = (
    "Reply with exactly one short sentence confirming that local inference works."
)

Output = Callable[[str], None]


class ValidationError(RuntimeError):
    """Raised when Foundry Local validation cannot prove successful inference."""


def collect_meaningful_content(chunks: Iterable[object]) -> str:
    """Collect assistant text and reject an empty or whitespace-only stream."""

    content_parts: list[str] = []

    for chunk in chunks:
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue

        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)

        if isinstance(content, str):
            content_parts.append(content)

    content = "".join(content_parts)

    if not content.strip():
        raise ValidationError(
            "Foundry Local inference returned no meaningful assistant content"
        )

    return content


def _model_metadata(model: Any) -> tuple[str, str]:
    """Return sanitized model identity and execution-provider metadata."""

    model_id = str(getattr(model, "id", "not exposed"))
    model_info = getattr(model, "info", None)
    runtime = getattr(model_info, "runtime", None)
    execution_provider = str(
        getattr(runtime, "execution_provider", None) or "not exposed"
    )
    return model_id, execution_provider


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


def validate_with_manager(
    manager: Any,
    *,
    model_alias: str = DEFAULT_MODEL_ALIAS,
    cached_only: bool = False,
    output: Output = print,
) -> str:
    """Prepare a model, run inference, require content, and unload safely."""

    _print_environment(output, cached_only=cached_only)
    output(f"Requested model alias: {model_alias}")

    if cached_only:
        output("Execution-provider download preparation: skipped in cached-only mode")
    else:
        output("Preparing execution providers...")
        manager.download_and_register_eps()

    model = manager.catalog.get_model(model_alias)
    if model is None:
        raise ValidationError(f"Model alias was not found in the catalog: {model_alias}")

    model_id, execution_provider = _model_metadata(model)
    output(f"Resolved model identity: {model_id}")
    output(f"Execution provider: {execution_provider}")

    if cached_only:
        if not model.is_cached:
            raise ValidationError(
                f"Model is not available in the local cache: {model_alias}"
            )
        output("Model download: skipped; cached model required")
    else:
        output("Downloading model if required...")
        model.download()

    loaded = False

    try:
        output("Loading model...")
        model.load()
        loaded = True

        client = model.get_chat_client()
        messages = [{"role": "user", "content": _VALIDATION_PROMPT}]
        response_content = collect_meaningful_content(
            client.complete_streaming_chat(messages)
        )
        output("Meaningful assistant content received: yes")
        output(f"Assistant content length: {len(response_content)} characters")
        return response_content
    finally:
        if loaded:
            output("Unloading model...")
            model.unload()


def create_manager() -> Any:
    """Initialize and return the real Foundry Local manager lazily."""

    from foundry_local_sdk import Configuration, FoundryLocalManager

    configuration = Configuration(app_name="lexlocal")
    FoundryLocalManager.initialize(configuration)
    return FoundryLocalManager.instance


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
    manager = create_manager()
    validate_with_manager(
        manager,
        model_alias=arguments.model,
        cached_only=arguments.cached_only,
    )
    print("Foundry Local validation completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
