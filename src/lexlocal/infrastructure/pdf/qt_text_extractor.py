"""Extract exact native PDF page text behind the Application-owned port."""

from collections.abc import Callable, Iterator
from typing import Protocol

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtPdf import QPdfDocument

from lexlocal.application.ports.processing import (
    NativePdfExtractionError,
    NativePdfPage,
)
from lexlocal.domain.retrieval import PageNumber


class _Selection(Protocol):
    def text(self) -> str: ...


class _Document(Protocol):
    def load(self, device: QIODevice) -> None: ...

    def status(self) -> QPdfDocument.Status: ...

    def error(self) -> QPdfDocument.Error: ...

    def pageCount(self) -> int: ...

    def getAllText(self, page: int) -> _Selection: ...

    def close(self) -> None: ...


def _create_document() -> _Document:
    return QPdfDocument()


class QtNativePdfTextExtractor:
    """Yield exact native page text without exposing Qt-owned values."""

    def __init__(
        self,
        document_factory: Callable[[], _Document] = _create_document,
    ) -> None:
        self._document_factory = document_factory

    def extract(self, source: bytes) -> Iterator[NativePdfPage]:
        """Yield one-based pages while retaining Qt resources for iteration."""

        if not isinstance(source, bytes) or not source:
            raise NativePdfExtractionError("native PDF source is invalid")

        buffer = QBuffer()
        buffer.setData(source)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            raise NativePdfExtractionError("native PDF could not be read")

        document: _Document | None = None
        try:
            document = self._document_factory()
            document.load(buffer)
            self._require_ready_document(document, source)
            page_count = document.pageCount()
            if isinstance(page_count, bool) or not isinstance(page_count, int):
                raise NativePdfExtractionError("native PDF page count is invalid")
            if page_count < 1:
                raise NativePdfExtractionError("native PDF has no pages")

            for page_index in range(page_count):
                try:
                    text = document.getAllText(page_index).text()
                except Exception:
                    raise NativePdfExtractionError(
                        "native PDF page extraction failed"
                    ) from None
                if not isinstance(text, str):
                    raise NativePdfExtractionError(
                        "native PDF page extraction returned invalid data"
                    )
                yield NativePdfPage(PageNumber(page_index + 1), text)
        except NativePdfExtractionError:
            raise
        except Exception:
            raise NativePdfExtractionError("native PDF extraction failed") from None
        finally:
            if document is not None:
                try:
                    document.close()
                except Exception:
                    pass
            buffer.close()

    @staticmethod
    def _require_ready_document(document: _Document, source: bytes) -> None:
        status = document.status()
        if status is QPdfDocument.Status.Ready:
            return
        if status is QPdfDocument.Status.Error:
            error = document.error()
            if error in {
                QPdfDocument.Error.IncorrectPassword,
                QPdfDocument.Error.UnsupportedSecurityScheme,
            }:
                raise NativePdfExtractionError("native PDF is protected")
            if error is QPdfDocument.Error.InvalidFileFormat:
                message = (
                    "native PDF is unreadable"
                    if source.startswith(b"%PDF-")
                    else "native PDF input is unsupported"
                )
                raise NativePdfExtractionError(message)
            raise NativePdfExtractionError("native PDF could not be read")
        raise NativePdfExtractionError("native PDF state is unsupported")
