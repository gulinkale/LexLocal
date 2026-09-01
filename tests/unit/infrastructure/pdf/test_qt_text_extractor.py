"""Tests for Qt-backed exact native PDF page-text extraction."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument

from lexlocal.application.ports.processing import (
    NativePdfExtractionError,
    NativePdfPage,
    NativePdfTextExtractor,
)
from lexlocal.infrastructure.pdf.qt_text_extractor import QtNativePdfTextExtractor


@pytest.fixture(scope="module", autouse=True)
def gui_application() -> Iterator[QGuiApplication]:
    existing = QGuiApplication.instance()
    application = existing if isinstance(existing, QGuiApplication) else QGuiApplication([])
    yield application


def _synthetic_text_pdf() -> bytes:
    output = QByteArray()
    buffer = QBuffer(output)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    painter = QPainter(writer)
    assert painter.isActive()
    painter.drawText(40, 80, "Anonymous first page")
    assert writer.newPage()
    painter.drawText(40, 80, "Anonymous second page")
    painter.end()
    buffer.close()
    data = output.data()
    return data if isinstance(data, bytes) else bytes(data)


def test_real_synthetic_pdf_returns_exact_one_based_page_order() -> None:
    pages = tuple(QtNativePdfTextExtractor().extract(_synthetic_text_pdf()))

    assert tuple(page.page_number.value for page in pages) == (1, 2)
    assert tuple(page.text for page in pages) == (
        "Anonymous first page",
        "Anonymous second page",
    )
    assert all(type(page) is NativePdfPage for page in pages)
    assert all(not type(page).__module__.startswith("PySide6") for page in pages)


class _Selection:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _FakeDocument:
    def __init__(
        self,
        *,
        status: QPdfDocument.Status = QPdfDocument.Status.Ready,
        error: QPdfDocument.Error = QPdfDocument.Error.None_,
        texts: tuple[str, ...] = ("synthetic",),
        fail_at: int | None = None,
        page_count: int | None = None,
    ) -> None:
        self._status = status
        self._error = error
        self._texts = texts
        self._fail_at = fail_at
        self._page_count = len(texts) if page_count is None else page_count
        self.device: QIODevice | None = None
        self.closed = False
        self.requested_pages: list[int] = []

    def load(self, device: QIODevice) -> None:
        self.device = device

    def status(self) -> QPdfDocument.Status:
        return self._status

    def error(self) -> QPdfDocument.Error:
        return self._error

    def pageCount(self) -> int:
        return self._page_count

    def getAllText(self, page: int) -> _Selection:
        assert self.device is not None and self.device.isOpen()
        self.requested_pages.append(page)
        if page == self._fail_at:
            raise RuntimeError("native object and extracted secret text")
        return _Selection(self._texts[page])

    def close(self) -> None:
        self.closed = True


def test_exact_unicode_newlines_whitespace_and_empty_page_are_unchanged() -> None:
    exact = "  Türkçe İÇERİK\nİkinci satır\t "
    document = _FakeDocument(texts=(exact, ""))

    pages = tuple(
        QtNativePdfTextExtractor(lambda: document).extract(b"%PDF-synthetic")
    )

    assert tuple(page.text for page in pages) == (exact, "")
    assert document.requested_pages == [0, 1]
    assert document.closed
    assert document.device is not None and not document.device.isOpen()


def test_empty_source_is_rejected_without_content_leak() -> None:
    source = b""

    with pytest.raises(NativePdfExtractionError, match="source is invalid") as captured:
        tuple(QtNativePdfTextExtractor().extract(source))

    assert repr(source) not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    ("source", "native_error", "safe_message"),
    [
        (b"anonymous non-PDF", QPdfDocument.Error.InvalidFileFormat, "unsupported"),
        (b"%PDF-corrupt", QPdfDocument.Error.InvalidFileFormat, "unreadable"),
        (b"%PDF-protected", QPdfDocument.Error.IncorrectPassword, "protected"),
        (
            b"%PDF-protected",
            QPdfDocument.Error.UnsupportedSecurityScheme,
            "protected",
        ),
    ],
)
def test_native_document_errors_are_translated_safely(
    source: bytes,
    native_error: QPdfDocument.Error,
    safe_message: str,
) -> None:
    document = _FakeDocument(
        status=QPdfDocument.Status.Error,
        error=native_error,
    )

    with pytest.raises(NativePdfExtractionError, match=safe_message) as captured:
        tuple(QtNativePdfTextExtractor(lambda: document).extract(source))

    assert captured.value.__cause__ is None
    assert native_error.name not in str(captured.value)
    assert source.decode() not in str(captured.value)
    assert document.closed


def test_unsupported_native_status_is_sanitized() -> None:
    document = _FakeDocument(status=QPdfDocument.Status.Null)

    with pytest.raises(NativePdfExtractionError, match="state is unsupported") as captured:
        tuple(
            QtNativePdfTextExtractor(lambda: document).extract(b"%PDF-synthetic")
        )

    assert captured.value.__cause__ is None
    assert "Null" not in str(captured.value)
    assert document.closed


def test_zero_page_document_is_rejected() -> None:
    document = _FakeDocument(page_count=0)

    with pytest.raises(NativePdfExtractionError, match="has no pages"):
        tuple(
            QtNativePdfTextExtractor(lambda: document).extract(b"%PDF-synthetic")
        )

    assert document.closed


def test_later_page_failure_closes_resources_without_native_detail() -> None:
    document = _FakeDocument(texts=("first", "sensitive second"), fail_at=1)
    pages = QtNativePdfTextExtractor(lambda: document).extract(b"%PDF-synthetic")

    assert next(pages).text == "first"
    assert not document.closed
    with pytest.raises(NativePdfExtractionError, match="page extraction failed") as captured:
        next(pages)

    assert captured.value.__cause__ is None
    assert "native object" not in str(captured.value)
    assert "sensitive second" not in str(captured.value)
    assert document.closed
    assert document.device is not None and not document.device.isOpen()


def test_native_factory_failure_is_sanitized() -> None:
    def fail_factory() -> _FakeDocument:
        raise RuntimeError("native factory object and source detail")

    with pytest.raises(NativePdfExtractionError, match="extraction failed") as captured:
        tuple(QtNativePdfTextExtractor(fail_factory).extract(b"%PDF-synthetic"))

    assert captured.value.__cause__ is None
    assert "native factory" not in str(captured.value)


_extractor_contract: NativePdfTextExtractor = QtNativePdfTextExtractor()


def test_adapter_satisfies_application_protocol() -> None:
    assert _extractor_contract.__class__ is QtNativePdfTextExtractor
