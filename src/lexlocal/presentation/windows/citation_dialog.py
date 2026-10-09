"""Resolve and display one immutable CHAT citation snapshot."""

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lexlocal.application.ports.chat import (
    ChatCitationRegistration,
    ChatTerminalGraph,
)
from lexlocal.application.ports.retrieval import RetrievalEvidenceRegistration


class CitationUnavailable(RuntimeError):
    """Report a sanitized invalid or unavailable in-memory citation mapping."""


@dataclass(frozen=True, slots=True)
class CitationDetail:
    """Carry only the snapshot fields approved for citation display."""

    evidence_rank: int
    document_display_name: str = field(repr=False)
    version_number: int
    page_number: int
    excerpt: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.evidence_rank, bool)
            or not isinstance(self.evidence_rank, int)
            or self.evidence_rank < 1
            or not isinstance(self.document_display_name, str)
            or not self.document_display_name.strip()
            or isinstance(self.version_number, bool)
            or not isinstance(self.version_number, int)
            or self.version_number < 1
            or isinstance(self.page_number, bool)
            or not isinstance(self.page_number, int)
            or self.page_number < 1
            or not isinstance(self.excerpt, str)
            or not self.excerpt
        ):
            raise CitationUnavailable("citation is unavailable")

    @property
    def evidence_label(self) -> str:
        """Derive the only visible evidence label from authoritative rank."""

        return f"E{self.evidence_rank}"


def resolve_citation_detail(
    graph: ChatTerminalGraph,
    selected: ChatCitationRegistration,
) -> CitationDetail:
    """Resolve one citation only inside its exact returned terminal graph."""

    if not isinstance(graph, ChatTerminalGraph) or not isinstance(
        selected, ChatCitationRegistration
    ):
        raise CitationUnavailable("citation is unavailable")
    citations = graph.citations
    if (
        tuple(item.ordinal for item in citations)
        != tuple(range(1, len(citations) + 1))
        or len({item.id for item in citations}) != len(citations)
        or len({item.evidence_item_id for item in citations}) != len(citations)
    ):
        raise CitationUnavailable("citation is unavailable")
    citation_matches = tuple(item for item in citations if item.id == selected.id)
    if (
        len(citation_matches) != 1
        or citation_matches[0] != selected
        or selected.workspace_id != graph.target.workspace_id
        or selected.answer_message_id != graph.answer.id
    ):
        raise CitationUnavailable("citation is unavailable")

    evidence_matches = tuple(
        item
        for item in graph.retrieval.evidence
        if isinstance(item, RetrievalEvidenceRegistration)
        and item.evidence.id == selected.evidence_item_id
    )
    if len(evidence_matches) != 1:
        raise CitationUnavailable("citation is unavailable")
    evidence = evidence_matches[0]
    if (
        evidence.evidence.workspace_id != graph.target.workspace_id
        or evidence.evidence.retrieval_run_id != graph.retrieval.retrieval_run_id
        or evidence.evidence.document_version_id
        != evidence.source_locator.document_version_id
        or evidence.evidence.page_number != evidence.source_locator.page_number
        or evidence.evidence.source_locator_id != evidence.source_locator.id
    ):
        raise CitationUnavailable("citation is unavailable")
    try:
        return CitationDetail(
            evidence_rank=evidence.evidence.rank.value,
            document_display_name=evidence.document_display_name,
            version_number=evidence.version_number.value,
            page_number=evidence.evidence.page_number.value,
            excerpt=evidence.excerpt,
        )
    except Exception:
        raise CitationUnavailable("citation is unavailable") from None


class CitationDialog(QDialog):
    """Show one exact retrieval-time citation snapshot without source access."""

    def __init__(self, detail: CitationDetail, parent: QWidget | None = None) -> None:
        if not isinstance(detail, CitationDetail):
            raise CitationUnavailable("citation is unavailable")
        super().__init__(parent)
        self.setObjectName("citationDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(f"Citation {detail.evidence_label}")
        self.setModal(True)
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._evidence_label = _value_label(
            detail.evidence_label,
            "citationEvidenceLabel",
            "Evidence label",
        )
        self._document = _value_label(
            detail.document_display_name,
            "citationDocumentName",
            "Citation document",
        )
        self._version = _value_label(
            str(detail.version_number),
            "citationVersion",
            "Citation document version",
        )
        self._page = _value_label(
            str(detail.page_number),
            "citationPage",
            "Citation page number",
        )
        form.addRow("Evidence", self._evidence_label)
        form.addRow("Document", self._document)
        form.addRow("Version", self._version)
        form.addRow("Page", self._page)
        layout.addLayout(form)

        excerpt_label = QLabel("Excerpt")
        self._excerpt = _value_label(
            detail.excerpt,
            "citationExcerpt",
            "Citation excerpt",
        )
        self._excerpt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._excerpt.setWordWrap(True)
        excerpt_label.setBuddy(self._excerpt)
        layout.addWidget(excerpt_label)
        scroll = QScrollArea()
        scroll.setObjectName("citationExcerptScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._excerpt)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.setObjectName("closeCitationDialog")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _value_label(value: str, object_name: str, accessible_name: str) -> QLabel:
    label = QLabel(value)
    label.setObjectName(object_name)
    label.setAccessibleName(accessible_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return label
