"""Prove the complete anonymous UI-001 desktop workflow through real adapters."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QPainter, QPdfWriter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
)

from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.security import create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.bootstrap.ui import compose_ui_application
from lexlocal.domain.identifiers import LocalModelId
from lexlocal.domain.retrieval import EvidenceSufficiency
from lexlocal.presentation.state import (
    CapabilityState,
    DocumentDisplayState,
    QuestionDisplayState,
    WorkspaceDisplayState,
)
from lexlocal.presentation.windows.citation_dialog import CitationDialog
from lexlocal.presentation.windows.main_window import MainWindow


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-m1-desktop-workflow-test"])


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        chat_model_alias="synthetic-chat",
        embedding_model_alias="synthetic-embedding",
        index_chunk_size=1000,
        index_chunk_overlap=200,
        embedding_batch_size=2,
        retrieval_top_k=5,
        retrieval_min_similarity=0.0,
    )


def _status(model_id: LocalModelId, capability: ModelCapability) -> LocalModelStatus:
    alias = "synthetic-chat" if capability is ModelCapability.CHAT else "synthetic-embedding"
    return LocalModelStatus(
        ResolvedModelRecord(
            model_id,
            alias,
            f"{alias}:1",
            "1",
            capability,
            "synthetic-local",
            None if capability is ModelCapability.CHAT else 2,
        ),
        ModelReadiness.READY,
        "SyntheticExecutionProvider",
    )


class _ChatProvider:
    def __init__(
        self,
        status: LocalModelStatus,
        relation: str,
        *,
        mode: str = "normal",
    ) -> None:
        self._status = status
        self.relation = relation
        self.mode = mode
        self.tasks: list[str] = []
        self.started = Event()
        self.release = Event()

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def generate(
        self,
        prompt: str,
        *,
        profile: ChatInferenceProfile | None = None,
    ) -> str:
        self.started.set()
        if self.mode == "blocked":
            assert self.release.wait(5)
        if self.mode == "failure":
            raise RuntimeError("PRIVATE-PROVIDER-SENTINEL")
        envelope = json.loads(prompt)
        task = envelope["task"]
        self.tasks.append(task)
        if task == "classify-evidence-relations":
            return json.dumps(
                {
                    "assessments": [
                        {
                            "evidence": item["label"],
                            "relation": self.relation,
                        }
                        for item in envelope["evidence"]
                    ]
                },
                separators=(",", ":"),
            )
        assert task == "answer-from-supplied-evidence"
        return '{"answer":"The archive code is amber.","citations":["E1"]}'

    def substitute_status(self) -> None:
        self._status = _status(
            LocalModelId("10000000-0000-4000-8000-000000000099"),
            ModelCapability.CHAT,
        )


class _EmbeddingProvider:
    def __init__(self, status: LocalModelStatus) -> None:
        self._status = status
        self.calls: list[tuple[str, ...]] = []

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        batch = tuple(texts)
        self.calls.append(batch)
        return tuple((1.0, 0.0) for _ in batch)


class _Runtime:
    def __init__(self, relation: str, *, mode: str = "normal") -> None:
        self.relation = relation
        self.mode = mode
        self.chat: _ChatProvider | None = None
        self.embedding: _EmbeddingProvider | None = None
        self.close_calls = 0

    def resolve_ready(
        self,
        *,
        model_id: LocalModelId,
        requested_alias: str,
        capability: ModelCapability,
    ) -> LocalModelStatus:
        del requested_alias
        return _status(model_id, capability)

    def adopt_persisted_record(
        self,
        status: LocalModelStatus,
        persisted: ResolvedModelRecord,
    ) -> LocalModelStatus:
        return LocalModelStatus(persisted, status.readiness, status.execution_provider)

    def chat_provider(self, status: LocalModelStatus) -> _ChatProvider:
        self.chat = _ChatProvider(status, self.relation, mode=self.mode)
        return self.chat

    def embedding_provider(self, status: LocalModelStatus) -> _EmbeddingProvider:
        self.embedding = _EmbeddingProvider(status)
        return self.embedding

    def close(self) -> None:
        self.close_calls += 1


def _synthetic_pdf(text: str) -> bytes:
    output = QByteArray()
    buffer = QBuffer(output)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    painter = QPainter(writer)
    assert painter.isActive()
    painter.drawText(40, 80, text)
    painter.end()
    buffer.close()
    data = output.data()
    return data if isinstance(data, bytes) else bytes(data)


def _wait(application: QApplication, predicate, timeout: float = 8.0) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        application.processEvents()
        if monotonic() >= deadline:
            raise AssertionError("timed out waiting for desktop workflow")
        sleep(0.005)
    application.processEvents()


def _widget(window: MainWindow, widget_type, name: str):
    value = window.findChild(widget_type, name)
    assert value is not None
    return value


def _drive_to_ready_document(
    application: QApplication,
    window: MainWindow,
    composition,
) -> None:
    _wait(
        application,
        lambda: composition.controller.state.capability is CapabilityState.READY
        and composition.controller.state.active_operation is None,
    )
    workspace_name = _widget(window, QLineEdit, "workspaceName")
    workspace_name.setText("Anonymous Desktop Workspace")
    _widget(window, QPushButton, "createWorkspace").click()
    _wait(application, lambda: len(composition.controller.state.workspaces) == 1)
    workspace_list = _widget(window, QComboBox, "workspaceList")
    workspace_list.setCurrentIndex(0)
    _widget(window, QPushButton, "selectWorkspace").click()
    _wait(
        application,
        lambda: composition.controller.state.workspace
        is WorkspaceDisplayState.SELECTED,
    )
    _widget(window, QPushButton, "importPdf").click()
    _wait(
        application,
        lambda: composition.controller.state.document
        in (DocumentDisplayState.READY, DocumentDisplayState.READY_WITH_WARNINGS),
    )


@pytest.mark.parametrize(
    ("relation", "expected_state", "citation_count", "provider_tasks"),
    [
        (
            "SUPPORTS",
            QuestionDisplayState.GROUNDED,
            1,
            ["classify-evidence-relations", "answer-from-supplied-evidence"],
        ),
        (
            "RELATED_ONLY",
            QuestionDisplayState.RELATED_NON_ANSWER,
            1,
            ["classify-evidence-relations"],
        ),
        (
            "IRRELEVANT",
            QuestionDisplayState.INSUFFICIENT_NON_ANSWER,
            0,
            ["classify-evidence-relations"],
        ),
    ],
)
def test_complete_real_desktop_slice_reaches_each_terminal_outcome(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relation: str,
    expected_state: QuestionDisplayState,
    citation_count: int,
    provider_tasks: list[str],
) -> None:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    runtime = _Runtime(relation)
    model_ids = iter(
        (
            LocalModelId("10000000-0000-4000-8000-000000000001"),
            LocalModelId("10000000-0000-4000-8000-000000000002"),
        )
    )
    composition = compose_ui_application(
        settings,
        factory,
        security,
        runtime_factory=lambda: runtime,
        model_id_factory=lambda: next(model_ids),
    )
    window = composition.main_window
    pdf_path = tmp_path / "anonymous-synthetic.pdf"
    pdf_path.write_bytes(_synthetic_pdf("The archive code is amber."))
    monkeypatch.setattr(
        "lexlocal.presentation.windows.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(pdf_path), "PDF files (*.pdf)"),
    )

    composition.start()
    _drive_to_ready_document(application, window, composition)
    question = _widget(window, QPlainTextEdit, "questionInput")
    question.setPlainText("What is the archive code?")
    _widget(window, QPushButton, "askQuestion").click()
    _wait(application, lambda: composition.controller.state.question is expected_state)

    result = composition.controller.state.chat_result
    assert result is not None
    assert len(result.graph.citations) == citation_count
    assert runtime.chat is not None
    assert runtime.chat.tasks == provider_tasks
    assert runtime.embedding is not None
    assert runtime.embedding.calls
    assert result.graph.evidence_state is {
        QuestionDisplayState.GROUNDED: EvidenceSufficiency.SUFFICIENT,
        QuestionDisplayState.RELATED_NON_ANSWER:
            EvidenceSufficiency.RELATED_BUT_INSUFFICIENT,
        QuestionDisplayState.INSUFFICIENT_NON_ANSWER:
            EvidenceSufficiency.INSUFFICIENT,
    }[expected_state]

    citations = _widget(window, QListWidget, "citationList")
    assert citations.count() == citation_count
    if citation_count:
        assert citations.item(0).text() == "E1"
    if expected_state is QuestionDisplayState.GROUNDED:
        citations.setCurrentRow(0)
        _widget(window, QPushButton, "openCitation").click()
        dialog = window.findChild(CitationDialog)
        assert dialog is not None
        excerpt = dialog.findChild(QLabel, "citationExcerpt")
        assert excerpt is not None
        assert "The archive code is amber." in excerpt.text()
        dialog.close()

    connection = factory.create()
    try:
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM qa_requests").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM qa_verifier_snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == citation_count
    finally:
        connection.close()

    assert composition.shutdown()
    assert runtime.close_calls == 1


@pytest.mark.parametrize("mode", ["failure", "substitution", "blocked"])
def test_desktop_failures_and_cancellation_leave_no_partial_completion(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    runtime = _Runtime("SUPPORTS", mode="blocked" if mode == "blocked" else mode)
    model_ids = iter(
        (
            LocalModelId("10000000-0000-4000-8000-000000000001"),
            LocalModelId("10000000-0000-4000-8000-000000000002"),
        )
    )
    composition = compose_ui_application(
        settings,
        factory,
        security,
        runtime_factory=lambda: runtime,
        model_id_factory=lambda: next(model_ids),
    )
    window = composition.main_window
    pdf_path = tmp_path / "anonymous-failure.pdf"
    pdf_path.write_bytes(_synthetic_pdf("The archive code is amber."))
    monkeypatch.setattr(
        "lexlocal.presentation.windows.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(pdf_path), "PDF files (*.pdf)"),
    )

    composition.start()
    try:
        _drive_to_ready_document(application, window, composition)
        assert runtime.chat is not None
        if mode == "substitution":
            runtime.chat.substitute_status()
        question = _widget(window, QPlainTextEdit, "questionInput")
        question.setPlainText("What is the archive code?")
        _widget(window, QPushButton, "askQuestion").click()
        if mode == "blocked":
            assert runtime.chat.started.wait(3)
            application.processEvents()
            _widget(window, QPushButton, "cancelQuestion").click()
            runtime.chat.release.set()
            expected = QuestionDisplayState.CANCELLED
        else:
            expected = QuestionDisplayState.FAILED
        _wait(application, lambda: composition.controller.state.question is expected)

        assert composition.controller.state.chat_result is None
        connection = factory.create()
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM qa_verifier_snapshots"
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM citations"
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE role = 'ASSISTANT'"
            ).fetchone()[0] == 0
            state = connection.execute(
                "SELECT state FROM qa_requests"
            ).fetchone()[0]
            assert state == ("CANCELLED" if mode == "blocked" else "FAILED")
        finally:
            connection.close()
    finally:
        if runtime.chat is not None:
            runtime.chat.release.set()
        assert composition.shutdown()
    assert runtime.close_calls == 1
