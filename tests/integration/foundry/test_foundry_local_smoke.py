"""Opt-in, hardware-dependent real Foundry Local inference smoke test."""

from __future__ import annotations

import os

import pytest

from lexlocal.infrastructure.foundry import (
    DEFAULT_VALIDATION_MODEL_ALIAS,
    FoundryLocalAdapter,
)

_OPT_IN_ENVIRONMENT_VARIABLE = "LEXLOCAL_RUN_FOUNDRY_SMOKE"
_MODEL_ENVIRONMENT_VARIABLE = "LEXLOCAL_FOUNDRY_SMOKE_MODEL"

pytestmark = [
    pytest.mark.foundry_smoke,
    pytest.mark.skipif(
        os.environ.get(_OPT_IN_ENVIRONMENT_VARIABLE) != "1",
        reason=f"set {_OPT_IN_ENVIRONMENT_VARIABLE}=1 to run real local inference",
    ),
]


def test_cached_foundry_model_returns_meaningful_content() -> None:
    """Run real inference without preparing or downloading model resources."""

    model_alias = os.environ.get(
        _MODEL_ENVIRONMENT_VARIABLE,
        DEFAULT_VALIDATION_MODEL_ALIAS,
    )
    adapter = FoundryLocalAdapter.initialize()

    result = adapter.infer(
        model_alias=model_alias,
        prompt="Reply with one short sentence confirming local inference works.",
        cached_only=True,
    )

    assert result.content.strip()
