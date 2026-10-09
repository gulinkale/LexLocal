"""Tests for the local selected-PDF reader."""

from pathlib import Path

import pytest

from lexlocal.application.ports.document_workflow import (
    SelectedPdfReadError,
    SelectedPdfReference,
)
from lexlocal.infrastructure.pdf.selected_pdf import LocalSelectedPdfReader


def test_reader_preserves_exact_bytes_and_returns_basename_only(tmp_path: Path) -> None:
    exact = b"%PDF-\x00exact\nsynthetic"
    selected_path = tmp_path / "anonymous.pdf"
    selected_path.write_bytes(exact)

    result = LocalSelectedPdfReader().read(SelectedPdfReference(str(selected_path)))

    assert result.source == exact
    assert result.logical_filename == "anonymous.pdf"
    assert str(selected_path) not in repr(result)
    assert repr(exact) not in repr(result)


@pytest.mark.parametrize("kind", ["missing", "directory", "empty"])
def test_reader_rejects_unreadable_nonregular_or_empty_input_without_path_leak(
    tmp_path: Path,
    kind: str,
) -> None:
    selected_path = tmp_path / f"private-{kind}.pdf"
    if kind == "directory":
        selected_path.mkdir()
    elif kind == "empty":
        selected_path.write_bytes(b"")

    with pytest.raises(SelectedPdfReadError) as captured:
        LocalSelectedPdfReader().read(SelectedPdfReference(str(selected_path)))

    assert str(selected_path) not in str(captured.value)
    assert str(selected_path) not in repr(captured.value)
