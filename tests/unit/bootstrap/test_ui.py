"""Tests for the UI-001 worker-session composition and lifetimes."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QThread
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from lexlocal.application.ports.local_models import (
    ChatInferenceProfile,
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
    ResolvedModelRecord,
)
from lexlocal.bootstrap import ui as ui_bootstrap
from lexlocal.bootstrap.persistence import initialize_persistence
from lexlocal.bootstrap.security import create_security_providers
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.bootstrap.ui import UiWorkerSessionBuilder, compose_ui_application
from lexlocal.domain.identifiers import LocalModelId
from lexlocal.presentation.state import CapabilityState
from lexlocal.presentation.workflow_worker import ThreadCancellationSource

CHAT_ID = LocalModelId("10000000-0000-4000-8000-000000000001")
EMBEDDING_ID = LocalModelId("10000000-0000-4000-8000-000000000002")


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication(["lexlocal-ui-bootstrap-test"])


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="LexLocal",
        environment="test",
        log_level="INFO",
        data_dir=tmp_path,
        security_provider="insecure-development-only",
        chat_model_alias="synthetic-chat",
        embedding_model_alias="synthetic-embedding",
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
    def __init__(self, status: LocalModelStatus) -> None:
        self._status = status

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def generate(
        self,
        prompt: str,
        *,
        profile: ChatInferenceProfile | None = None,
    ) -> str:
        del prompt, profile
        return '{"answer":"synthetic","citations":["E1"]}'


class _EmbeddingProvider:
    def __init__(self, status: LocalModelStatus) -> None:
        self._status = status

    @property
    def status(self) -> LocalModelStatus:
        return self._status

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple((1.0, 0.0) for _ in texts)


class _Runtime:
    def __init__(
        self,
        *,
        resolve_error: Exception | None = None,
        adopt_error: Exception | None = None,
    ) -> None:
        self.resolve_error = resolve_error
        self.adopt_error = adopt_error
        self.resolve_calls: list[tuple[str, ModelCapability]] = []
        self.provider_ids: list[int] = []
        self.threads: list[QThread] = []
        self.close_calls = 0
        self._lock = Lock()

    def resolve_ready(
        self,
        *,
        model_id: LocalModelId,
        requested_alias: str,
        capability: ModelCapability,
    ) -> LocalModelStatus:
        with self._lock:
            self.threads.append(QThread.currentThread())
            self.resolve_calls.append((requested_alias, capability))
        if self.resolve_error is not None:
            raise self.resolve_error
        return _status(model_id, capability)

    def adopt_persisted_record(
        self,
        status: LocalModelStatus,
        persisted: ResolvedModelRecord,
    ) -> LocalModelStatus:
        if self.adopt_error is not None:
            raise self.adopt_error
        return LocalModelStatus(
            persisted,
            status.readiness,
            status.execution_provider,
        )

    def chat_provider(self, status: LocalModelStatus) -> _ChatProvider:
        provider = _ChatProvider(status)
        self.provider_ids.append(id(provider))
        return provider

    def embedding_provider(self, status: LocalModelStatus) -> _EmbeddingProvider:
        provider = _EmbeddingProvider(status)
        self.provider_ids.append(id(provider))
        return provider

    def close(self) -> None:
        self.close_calls += 1


def _model_ids():
    values = iter((CHAT_ID, EMBEDDING_ID))
    return lambda: next(values)


def _wait(application: QApplication, predicate, timeout: float = 3.0) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        application.processEvents()
        if monotonic() >= deadline:
            raise AssertionError("timed out waiting for UI composition")
        sleep(0.002)
    application.processEvents()


def test_builder_defers_one_runtime_and_persists_exact_identity(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    runtime = _Runtime()
    runtime_calls = 0

    def runtime_factory() -> _Runtime:
        nonlocal runtime_calls
        runtime_calls += 1
        return runtime

    builder = UiWorkerSessionBuilder(
        settings,
        factory,
        security,
        ThreadCancellationSource(),
        runtime_factory=runtime_factory,
        model_id_factory=_model_ids(),
    )

    foundation = builder.initialize_foundation()
    assert runtime_calls == 0
    model_runtime = foundation.initialize_model_runtime()
    assert runtime_calls == 1
    model_runtime.resolve_capabilities()
    session = model_runtime.bind_persisted_identity(foundation)

    assert runtime.resolve_calls == [
        ("synthetic-chat", ModelCapability.CHAT),
        ("synthetic-embedding", ModelCapability.EMBEDDING),
    ]
    assert len(runtime.provider_ids) == 2
    assert len(set(runtime.provider_ids)) == 2
    connection = factory.create()
    try:
        records = connection.execute(
            "SELECT purpose, requested_alias FROM local_models ORDER BY purpose"
        ).fetchall()
    finally:
        connection.close()
    assert [(row[0], row[1]) for row in records] == [
        ("CHAT", "synthetic-chat"),
        ("EMBEDDING", "synthetic-embedding"),
    ]

    session.close()
    assert runtime.close_calls == 1


def test_builder_passes_exact_cache_to_one_default_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    runtime = _Runtime()
    initializer = Mock(return_value=runtime)
    monkeypatch.setattr(
        ui_bootstrap.FoundryLocalRuntime,
        "initialize",
        initializer,
    )
    builder = UiWorkerSessionBuilder(
        settings,
        factory,
        security,
        ThreadCancellationSource(),
    )

    foundation = builder.initialize_foundation()
    model_runtime = foundation.initialize_model_runtime()

    initializer.assert_called_once_with(
        app_name=settings.app_name,
        model_cache_dir=settings.foundry_model_cache_dir,
    )
    model_runtime.close()
    assert runtime.close_calls == 1


def test_real_ui_composition_resolves_models_only_on_worker_thread(
    application: QApplication,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    runtime = _Runtime()
    runtime_calls = 0

    def runtime_factory() -> _Runtime:
        nonlocal runtime_calls
        runtime_calls += 1
        runtime.threads.append(QThread.currentThread())
        return runtime

    composition = compose_ui_application(
        settings,
        factory,
        security,
        runtime_factory=runtime_factory,
        model_id_factory=_model_ids(),
    )
    initialized = QSignalSpy(composition.worker.initialized)

    assert runtime_calls == 0
    composition.main_window.show()
    composition.start()
    try:
        _wait(
            application,
            lambda: initialized.count() == 1
            and composition.controller.state.active_operation is None,
        )
        assert runtime_calls == 1
        assert composition.controller.state.capability is CapabilityState.READY
        assert runtime.threads
        assert all(thread is composition.host.worker_thread for thread in runtime.threads)
        assert QThread.currentThread() is not composition.host.worker_thread
        composition.main_window.close()
        _wait(
            application,
            lambda: not composition.host.worker_thread.isRunning()
            and not composition.main_window.isVisible(),
        )
    finally:
        if composition.host.worker_thread.isRunning():
            assert composition.shutdown()
    assert runtime.close_calls == 1


def test_runtime_failure_is_recoverable_and_keeps_workspace_shell(
    application: QApplication,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    runtime = _Runtime(resolve_error=RuntimeError("PRIVATE-RUNTIME-SENTINEL"))
    composition = compose_ui_application(
        settings,
        factory,
        security,
        runtime_factory=lambda: runtime,
        model_id_factory=_model_ids(),
    )
    initialized = QSignalSpy(composition.worker.initialized)

    composition.start()
    try:
        _wait(
            application,
            lambda: initialized.count() == 1
            and composition.controller.state.active_operation is None,
        )
        state = composition.controller.state
        assert state.capability is CapabilityState.MODEL_UNAVAILABLE
        assert state.actions.create_workspace is True
        assert state.actions.import_pdf is False
        assert state.actions.ask is False
        assert runtime.close_calls == 1
    finally:
        assert composition.shutdown()
    assert runtime.close_calls == 1


def test_persisted_identity_failure_is_fatal_even_with_runtime_error_type(
    application: QApplication,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    factory = initialize_persistence(settings)
    security = create_security_providers(settings)
    runtime = _Runtime(adopt_error=RuntimeError("PRIVATE-IDENTITY-SENTINEL"))
    composition = compose_ui_application(
        settings,
        factory,
        security,
        runtime_factory=lambda: runtime,
        model_id_factory=_model_ids(),
    )
    initialized = QSignalSpy(composition.worker.initialized)

    composition.start()
    try:
        _wait(application, lambda: initialized.count() == 1)
        state = composition.controller.state
        assert state.capability is CapabilityState.FATAL_STARTUP
        assert state.actions.create_workspace is False
        assert state.actions.import_pdf is False
        assert runtime.close_calls == 1
        connection = factory.create()
        try:
            assert connection.execute("SELECT COUNT(*) FROM local_models").fetchone()[0] == 0
        finally:
            connection.close()
    finally:
        assert composition.shutdown()
    assert runtime.close_calls == 1
