"""Focused tests for in-memory citation resolution and display."""

from dataclasses import fields, replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit
from tests.unit.application.ports.test_chat import (
    ANSWER_MESSAGE_ID,
    CHAT_MODEL_ID,
    NOW,
    WORKSPACE_ID,
    _activity,
    _answer,
    _completion,
    _sufficiency,
    _target,
    _terminal_graph,
)

from lexlocal.application.ports.chat import (
    ChatCitationRegistration,
    ChatCompletionRegistration,
    ChatResponseContractVersion,
    ChatTerminalGraph,
)
from lexlocal.domain.identifiers import CitationId, RetrievalRunId
from lexlocal.domain.retrieval import EvidenceSufficiency
from lexlocal.presentation.windows.citation_dialog import (
    CitationDetail,
    CitationDialog,
    CitationUnavailable,
    resolve_citation_detail,
)


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-citation-dialog-test"])


def _graph(
    state: EvidenceSufficiency = EvidenceSufficiency.SUFFICIENT,
) -> ChatTerminalGraph:
    return _terminal_graph(_completion(state))


def _reversed_two_citation_graph() -> ChatTerminalGraph:
    sufficiency = _sufficiency(EvidenceSufficiency.SUFFICIENT)
    citations = tuple(
        ChatCitationRegistration(
            CitationId(f"12000000-0000-4000-8000-{ordinal:012d}"),
            WORKSPACE_ID,
            evidence.evidence.id,
            ANSWER_MESSAGE_ID,
            ordinal,
            NOW,
        )
        for ordinal, evidence in enumerate(
            reversed(sufficiency.retrieval.evidence),
            start=1,
        )
    )
    return _terminal_graph(
        ChatCompletionRegistration(
            _target(),
            sufficiency,
            _answer(),
            ChatResponseContractVersion("chat-answer-v1"),
            CHAT_MODEL_ID,
            citations,
            NOW,
            _activity(),
        )
    )


def _unsafe_replace(value: object, **changes: object):
    """Fault-inject an otherwise immutable boundary value without revalidation."""

    result = object.__new__(type(value))
    for item in fields(value):
        object.__setattr__(
            result,
            item.name,
            changes.get(item.name, getattr(value, item.name)),
        )
    return result


def test_resolver_returns_only_exact_snapshot_fields_and_authoritative_rank() -> None:
    graph = _graph()

    detail = resolve_citation_detail(graph, graph.citations[0])

    evidence = graph.retrieval.evidence[0]
    assert detail == CitationDetail(
        evidence.evidence.rank.value,
        evidence.document_display_name,
        evidence.version_number.value,
        evidence.evidence.page_number.value,
        evidence.excerpt,
    )
    assert detail.evidence_label == "E1"
    assert evidence.document_display_name not in repr(detail)
    assert evidence.excerpt not in repr(detail)


def test_persisted_citation_order_is_preserved_while_labels_use_evidence_rank() -> None:
    graph = _reversed_two_citation_graph()

    details = tuple(
        resolve_citation_detail(graph, citation) for citation in graph.citations
    )

    assert tuple(citation.ordinal for citation in graph.citations) == (1, 2)
    assert tuple(detail.evidence_label for detail in details) == ("E2", "E1")


def test_dialog_is_read_only_and_displays_exact_approved_snapshot(
    application: QApplication,
) -> None:
    graph = _graph()
    detail = resolve_citation_detail(graph, graph.citations[0])
    dialog = CitationDialog(detail)
    dialog.show()
    application.processEvents()

    assert dialog.windowTitle() == "Citation E1"
    assert dialog.findChild(QLabel, "citationEvidenceLabel").text() == "E1"
    assert (
        dialog.findChild(QLabel, "citationDocumentName").text()
        == detail.document_display_name
    )
    assert dialog.findChild(QLabel, "citationVersion").text() == "1"
    assert dialog.findChild(QLabel, "citationPage").text() == "1"
    excerpt = dialog.findChild(QLabel, "citationExcerpt")
    assert excerpt.text() == detail.excerpt
    assert excerpt.textFormat() is Qt.TextFormat.PlainText
    assert excerpt.textInteractionFlags() is Qt.TextInteractionFlag.NoTextInteraction
    assert dialog.findChild(QPlainTextEdit) is None
    visible = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "0.9" not in visible
    assert str(graph.citations[0].id) not in visible
    assert str(graph.citations[0].evidence_item_id) not in visible
    dialog.close()


def test_missing_or_duplicate_evidence_mapping_fails_closed() -> None:
    graph = _graph()
    selected = graph.citations[0]
    missing_retrieval = _unsafe_replace(graph.retrieval, evidence=())
    missing_graph = _unsafe_replace(graph, retrieval=missing_retrieval)
    duplicate_retrieval = _unsafe_replace(
        graph.retrieval,
        evidence=(graph.retrieval.evidence[0], graph.retrieval.evidence[0]),
    )
    duplicate_graph = _unsafe_replace(graph, retrieval=duplicate_retrieval)

    with pytest.raises(CitationUnavailable, match="citation is unavailable"):
        resolve_citation_detail(missing_graph, selected)
    with pytest.raises(CitationUnavailable, match="citation is unavailable"):
        resolve_citation_detail(duplicate_graph, selected)


def test_cross_result_and_corrupt_ownership_fail_closed_without_values() -> None:
    graph = _graph()
    selected = graph.citations[0]
    cross_result = replace(
        selected,
        id=CitationId("11000000-0000-4000-8000-000000000099"),
    )
    evidence = graph.retrieval.evidence[0]
    corrupt_evidence = _unsafe_replace(
        evidence.evidence,
        retrieval_run_id=RetrievalRunId(
            "50000000-0000-4000-8000-000000000099"
        ),
    )
    corrupt_registration = _unsafe_replace(evidence, evidence=corrupt_evidence)
    corrupt_retrieval = _unsafe_replace(
        graph.retrieval,
        evidence=(corrupt_registration,),
    )
    corrupt_graph = _unsafe_replace(graph, retrieval=corrupt_retrieval)

    for candidate_graph, citation in (
        (graph, cross_result),
        (corrupt_graph, selected),
    ):
        with pytest.raises(CitationUnavailable) as raised:
            resolve_citation_detail(candidate_graph, citation)
        message = str(raised.value)
        assert str(selected.id) not in message
        assert str(selected.evidence_item_id) not in message
