"""Inspect PDF container support behind the Application-owned PDF port."""

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtPdf import QPdfDocument

from lexlocal.application.ports.ingestion import (
    InvalidPdfInput,
    PdfInspectionResult,
    ProtectedPdf,
    UnreadablePdf,
    UnsupportedPdf,
)


class _Document(Protocol):
    def load(self, device: QIODevice) -> None: ...

    def status(self) -> QPdfDocument.Status: ...

    def error(self) -> QPdfDocument.Error: ...

    def pageCount(self) -> int: ...


def _create_document() -> _Document:
    return QPdfDocument()


class QtPdfInspector:
    """Translate Qt PDF container outcomes into safe Application contracts."""

    def __init__(
        self,
        document_factory: Callable[[], _Document] = _create_document,
    ) -> None:
        self._document_factory = document_factory

    def inspect(self, source: bytes) -> PdfInspectionResult:
        """Inspect exact in-memory PDF bytes without extracting or rendering pages."""

        if not isinstance(source, bytes) or not source:
            raise InvalidPdfInput("source must be non-empty bytes")

        buffer = QBuffer()
        buffer.setData(source)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            raise UnreadablePdf("PDF could not be read")

        document = self._document_factory()
        try:
            document.load(buffer)
            status = document.status()
            if status is QPdfDocument.Status.Ready:
                return PdfInspectionResult(
                    mime_type="application/pdf",
                    page_count=document.pageCount(),
                )
            if status is QPdfDocument.Status.Error:
                self._raise_document_error(document.error(), source)
            raise UnsupportedPdf("PDF document state is unsupported")
        except (InvalidPdfInput, ProtectedPdf, UnreadablePdf, UnsupportedPdf):
            raise
        except Exception:
            raise UnreadablePdf("PDF could not be read") from None
        finally:
            buffer.close()

    @staticmethod
    def _raise_document_error(
        error: QPdfDocument.Error,
        source: bytes,
    ) -> None:
        if error in {
            QPdfDocument.Error.IncorrectPassword,
            QPdfDocument.Error.UnsupportedSecurityScheme,
        }:
            raise ProtectedPdf("PDF is protected or encrypted")
        if error is QPdfDocument.Error.InvalidFileFormat:
            if source.startswith(b"%PDF-"):
                raise UnreadablePdf("PDF is corrupt or unreadable")
            raise UnsupportedPdf("input is not a supported PDF")
        raise UnreadablePdf("PDF could not be read")
