"""Integration tests for citation opening from the current terminal graph."""

from dataclasses import fields

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton
from tests.unit.application.ports.test_chat import QA_REQUEST_ID
from tests.unit.presentation.test_chat_workflow_ui import (
    _ready_window,
    _result,
    _start_question,
)
from tests.unit.presentation.test_citation_dialog import (
    _reversed_two_citation_graph,
)

from lexlocal.application.ports.chat import ChatCompletionResult, ChatIntakeResult
from lexlocal.domain.retrieval import EvidenceSufficiency
from lexlocal.presentation.state import QuestionCompletedEvent, QuestionPreparedEvent
from lexlocal.presentation.windows.citation_dialog import CitationDialog


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-citation-workflow-test"])


def _complete(
    application: QApplication,
    state: EvidenceSufficiency,
):
    window, controller, _commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    window.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(QA_REQUEST_ID, False))
    )
    window.accept_question_completed(QuestionCompletedEvent(token, _result(state)))
    application.processEvents()
    return window, controller


@pytest.mark.parametrize(
    "state",
    [
        EvidenceSufficiency.SUFFICIENT,
        EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
    ],
)
def test_current_graph_citation_opens_exact_snapshot_and_can_reopen(
    application: QApplication,
    state: EvidenceSufficiency,
) -> None:
    window, _controller = _complete(application, state)
    citations = window.findChild(QListWidget, "citationList")
    open_citation = window.findChild(QPushButton, "openCitation")
    assert citations is not None and open_citation is not None
    assert citations.count() == 1
    assert citations.item(0).text() == "E1"
    assert open_citation.isEnabled() is False

    citations.setCurrentRow(0)
    assert open_citation.isEnabled() is True
    open_citation.click()
    application.processEvents()
    dialog = window.findChild(CitationDialog, "citationDialog")
    assert dialog is not None and dialog.isVisible()
    assert dialog.findChild(QLabel, "citationEvidenceLabel").text() == "E1"
    assert dialog.findChild(QLabel, "citationDocumentName").text() == (
        "Synthetic document"
    )
    assert dialog.findChild(QLabel, "citationVersion").text() == "1"
    assert dialog.findChild(QLabel, "citationPage").text() == "1"
    assert dialog.findChild(QLabel, "citationExcerpt").text() == (
        "Private synthetic excerpt 1 Ω"
    )

    dialog.close()
    application.processEvents()
    open_citation.click()
    application.processEvents()
    reopened = window.findChild(CitationDialog, "citationDialog")
    assert reopened is not None and reopened.isVisible()
    reopened.close()
    window.close()


def test_insufficient_result_has_no_citation_opening(
    application: QApplication,
) -> None:
    window, _controller = _complete(
        application,
        EvidenceSufficiency.INSUFFICIENT,
    )
    citations = window.findChild(QListWidget, "citationList")
    open_citation = window.findChild(QPushButton, "openCitation")
    status = window.findChild(QLabel, "citationStatus")
    assert citations is not None and citations.count() == 0
    assert open_citation is not None and open_citation.isEnabled() is False
    assert status is not None and status.text() == ""
    window.close()


def test_visible_labels_follow_evidence_rank_without_reordering_citations(
    application: QApplication,
) -> None:
    window, controller, _commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    window.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(QA_REQUEST_ID, False))
    )
    result = ChatCompletionResult(_reversed_two_citation_graph(), False)
    window.accept_question_completed(QuestionCompletedEvent(token, result))
    application.processEvents()

    citations = window.findChild(QListWidget, "citationList")
    assert citations is not None
    assert [citations.item(index).text() for index in range(citations.count())] == [
        "E2",
        "E1",
    ]
    window.close()


def test_corrupt_terminal_mapping_is_not_rendered_or_opened(
    application: QApplication,
) -> None:
    window, controller, _commands = _ready_window(application)
    token = _start_question(application, window, controller, "Synthetic question?")
    window.accept_question_prepared(
        QuestionPreparedEvent(token, ChatIntakeResult(QA_REQUEST_ID, False))
    )
    result = _result(EvidenceSufficiency.SUFFICIENT)
    retrieval = object.__new__(type(result.graph.retrieval))
    for item in fields(result.graph.retrieval):
        object.__setattr__(
            retrieval,
            item.name,
            () if item.name == "evidence" else getattr(result.graph.retrieval, item.name),
        )
    graph = object.__new__(type(result.graph))
    for item in fields(result.graph):
        object.__setattr__(
            graph,
            item.name,
            retrieval if item.name == "retrieval" else getattr(result.graph, item.name),
        )
    corrupt = ChatCompletionResult(graph, False)

    window.accept_question_completed(QuestionCompletedEvent(token, corrupt))
    application.processEvents()

    citations = window.findChild(QListWidget, "citationList")
    open_citation = window.findChild(QPushButton, "openCitation")
    status = window.findChild(QLabel, "citationStatus")
    assert citations is not None and citations.count() == 0
    assert open_citation is not None and open_citation.isEnabled() is False
    assert status is not None and status.text() == "Citation is unavailable."
    assert window.findChild(CitationDialog, "citationDialog") is None
    window.close()
