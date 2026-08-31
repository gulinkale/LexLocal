"""Tests for Qt-backed PDF container inspection."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument

from lexlocal.application.ports.ingestion import (
    InvalidPdfInput,
    PdfInspectionResult,
    ProtectedPdf,
    UnreadablePdf,
    UnsupportedPdf,
)
from lexlocal.infrastructure.pdf.qt_pdf import QtPdfInspector


@pytest.fixture(scope="module", autouse=True)
def gui_application() -> Iterator[QGuiApplication]:
    existing = QGuiApplication.instance()
    application = existing if isinstance(existing, QGuiApplication) else QGuiApplication([])
    yield application


def _synthetic_pdf(*, image_only: bool) -> bytes:
    output = QByteArray()
    buffer = QBuffer(output)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    painter = QPainter(writer)
    assert painter.isActive()
    if image_only:
        image = QImage(24, 24, QImage.Format.Format_RGB32)
        image.fill(0x00A0B0C0)
        painter.drawImage(20, 20, image)
    else:
        painter.drawRect(20, 20, 24, 24)
    painter.end()
    buffer.close()
    return bytes(output)


@pytest.mark.parametrize("image_only", [False, True], ids=["supported", "image-only"])
def test_structurally_valid_pdf_is_accepted_without_text_inspection(
    image_only: bool,
) -> None:
    result = QtPdfInspector().inspect(_synthetic_pdf(image_only=image_only))

    assert result == PdfInspectionResult("application/pdf", 1)
    assert type(result.mime_type) is str
    assert type(result.page_count) is int


@pytest.mark.parametrize("source", [b"", b"anonymous non-PDF bytes"])
def test_empty_or_non_pdf_input_is_rejected(source: bytes) -> None:
    expected = InvalidPdfInput if not source else UnsupportedPdf

    with pytest.raises(expected) as captured:
        QtPdfInspector().inspect(source)

    assert captured.value.__cause__ is None
    assert repr(source) not in str(captured.value)


def test_corrupt_pdf_is_rejected_without_native_diagnostics() -> None:
    source = b"%PDF-1.7\nanonymous corrupt fixture"

    with pytest.raises(UnreadablePdf, match="corrupt or unreadable") as captured:
        QtPdfInspector().inspect(source)

    assert captured.value.__cause__ is None
    assert source.decode() not in str(captured.value)


class _FakeDocument:
    def __init__(
        self,
        status: QPdfDocument.Status,
        error: QPdfDocument.Error,
    ) -> None:
        self._status = status
        self._error = error
        self.loaded_device: QIODevice | None = None

    def load(self, device: QIODevice) -> None:
        self.loaded_device = device

    def status(self) -> QPdfDocument.Status:
        return self._status

    def error(self) -> QPdfDocument.Error:
        return self._error

    def pageCount(self) -> int:
        return 1


@pytest.mark.parametrize(
    "native_error",
    [
        QPdfDocument.Error.IncorrectPassword,
        QPdfDocument.Error.UnsupportedSecurityScheme,
    ],
)
def test_protected_pdf_errors_are_translated(native_error: QPdfDocument.Error) -> None:
    document = _FakeDocument(QPdfDocument.Status.Error, native_error)
    source = b"%PDF-1.7 anonymous protected fixture"

    with pytest.raises(ProtectedPdf, match="protected or encrypted") as captured:
        QtPdfInspector(lambda: document).inspect(source)

    assert document.loaded_device is not None
    assert captured.value.__cause__ is None
    assert native_error.name not in str(captured.value)
    assert source.decode() not in str(captured.value)


def test_unsupported_qt_document_state_is_translated_safely() -> None:
    document = _FakeDocument(QPdfDocument.Status.Null, QPdfDocument.Error.None_)

    with pytest.raises(UnsupportedPdf, match="state is unsupported") as captured:
        QtPdfInspector(lambda: document).inspect(b"%PDF-1.7 synthetic fixture")

    assert captured.value.__cause__ is None
    assert "Null" not in str(captured.value)
