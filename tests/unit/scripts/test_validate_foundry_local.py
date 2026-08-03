"""Unit tests for the Foundry Local validation CLI wrapper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "validate_foundry_local.py"
_SPEC = importlib.util.spec_from_file_location("validate_foundry_local", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def test_main_initializes_adapter_and_delegates_cached_inference(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = Mock()
    adapter.infer.return_value = SimpleNamespace(content="Local inference works.")
    initialize = Mock(return_value=adapter)
    monkeypatch.setattr(_MODULE.FoundryLocalAdapter, "initialize", initialize)

    result = _MODULE.main(["--model", "cached-model", "--cached-only"])

    assert result == 0
    initialize.assert_called_once_with()
    adapter.infer.assert_called_once_with(
        model_alias="cached-model",
        prompt=_MODULE._VALIDATION_PROMPT,
        cached_only=True,
        output=print,
    )
    output = capsys.readouterr().out
    assert "Validation mode: cached-only (network state not verified)" in output
    assert "Foundry Local validation completed successfully." in output


def test_main_does_not_report_success_when_adapter_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = Mock()
    adapter.infer.side_effect = RuntimeError("inference failed")
    monkeypatch.setattr(
        _MODULE.FoundryLocalAdapter,
        "initialize",
        Mock(return_value=adapter),
    )

    with pytest.raises(RuntimeError, match="inference failed"):
        _MODULE.main([])

    assert "completed successfully" not in capsys.readouterr().out
