"""Compose the bounded UI-001 worker session and its process lifetimes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from lexlocal.application.chat import StartSingleDocumentQuestion
from lexlocal.application.document_workflow import BuildActiveDocument
from lexlocal.application.ports.chat import (
    ChatCompletionResult,
    ChatIntakeRegistration,
    ChatIntakeResult,
)
from lexlocal.application.ports.document_workflow import (
    ActiveDocumentResult,
    DocumentWorkflowStageSink,
    SelectedPdfReference,
)
from lexlocal.application.ports.indexing import (
    ActivatedIndex,
    IndexPreparationResult,
    StagingEmbeddingHandoff,
)
from lexlocal.application.ports.ingestion import IngestionResult
from lexlocal.application.ports.local_models import (
    ChatInferenceProvider,
    EmbeddingProvider,
    LocalModelStatus,
    ModelCapability,
    ResolvedModelRecord,
)
from lexlocal.application.ports.processing import ProcessingResult
from lexlocal.bootstrap.chat import compose_chat_application
from lexlocal.bootstrap.embeddings import compose_embedding_application
from lexlocal.bootstrap.evidence_sufficiency import (
    compose_evidence_sufficiency_application,
)
from lexlocal.bootstrap.foundry import LocalModelComposition
from lexlocal.bootstrap.indexing import compose_indexing_application
from lexlocal.bootstrap.ingestion import compose_ingestion_application
from lexlocal.bootstrap.persistence import (
    WorkspaceApplicationComposition,
    compose_workspace_application,
)
from lexlocal.bootstrap.processing import compose_processing_application
from lexlocal.bootstrap.retrieval import compose_retrieval_application
from lexlocal.bootstrap.security import SecurityProviders
from lexlocal.bootstrap.settings import AppSettings
from lexlocal.domain.identifiers import (
    ChatId,
    ChatMessageId,
    LocalModelId,
    QaRequestId,
    WorkspaceId,
)
from lexlocal.domain.workspace import Workspace, WorkspaceProfile
from lexlocal.infrastructure.foundry.local_adapter import FoundryLocalRuntime
from lexlocal.infrastructure.pdf.selected_pdf import LocalSelectedPdfReader
from lexlocal.infrastructure.persistence.sqlite_connection import SQLiteConnectionFactory
from lexlocal.infrastructure.persistence.sqlite_unit_of_work import SQLiteUnitOfWork
from lexlocal.infrastructure.security.insecure_development_workspace import (
    InsecureDevelopmentOnlyWorkspaceNamePersistence,
)
from lexlocal.presentation.controller import PresentationController
from lexlocal.presentation.state import WorkerOperation
from lexlocal.presentation.windows.main_window import (
    DocumentCommandBindings,
    MainWindow,
    QuestionCommandBindings,
    ShutdownCommandBindings,
    WorkspaceCommandBindings,
)
from lexlocal.presentation.workflow_worker import (
    ChatCancellationAdapter,
    DocumentCancellationAdapter,
    EmbeddingCancellationAdapter,
    EvidenceCancellationAdapter,
    IndexingCancellationAdapter,
    ProcessingCancellationAdapter,
    SerializedWorkflowHost,
    ThreadCancellationSource,
    WorkflowWorker,
)


class _Runtime(Protocol):
    def resolve_ready(
        self,
        *,
        model_id: LocalModelId,
        requested_alias: str,
        capability: ModelCapability,
    ) -> LocalModelStatus: ...

    def adopt_persisted_record(
        self,
        status: LocalModelStatus,
        persisted: ResolvedModelRecord,
    ) -> LocalModelStatus: ...

    def chat_provider(self, status: LocalModelStatus) -> ChatInferenceProvider: ...

    def embedding_provider(self, status: LocalModelStatus) -> EmbeddingProvider: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UiApplicationComposition:
    """Own the restricted window and its one serialized worker lifetime."""

    main_window: MainWindow
    controller: PresentationController
    worker: WorkflowWorker
    host: SerializedWorkflowHost

    def start(self) -> None:
        """Start the worker and request its only model-composition attempt."""

        token = self.controller.begin(WorkerOperation.STARTUP)
        self.host.start()
        self.host.initialize_requested.emit(token)

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Cancel work, close worker-owned resources, and join its thread."""

        if not self.host.worker_thread.isRunning():
            return True
        state = self.controller.state
        if state.shutting_down and state.operation_token is not None:
            return self.host.shutdown(state.operation_token, timeout_ms)
        active_token = state.operation_token
        token = self.controller.begin_shutdown()
        return self.host.shutdown(token, timeout_ms, active_token=active_token)


class UiWorkerSessionBuilder:
    """Build one shared-scope foundation before the sole local runtime attempt."""

    def __init__(
        self,
        settings: AppSettings,
        connection_factory: SQLiteConnectionFactory,
        security: SecurityProviders,
        cancellation: ThreadCancellationSource,
        *,
        runtime_factory: Callable[[], _Runtime] | None = None,
        model_id_factory: Callable[[], LocalModelId] | None = None,
    ) -> None:
        self._settings = settings
        self._connection_factory = connection_factory
        self._security = security
        self._cancellation = cancellation
        self._runtime_factory = runtime_factory
        self._model_id_factory = model_id_factory or _new_local_model_id

    def initialize_foundation(self) -> _UiFoundation:
        """Create model-independent commands around one active workspace scope."""

        workspaces = compose_workspace_application(
            self._settings,
            self._connection_factory,
            security_providers=self._security,
        )
        return _UiFoundation(self, workspaces)

    def _initialize_runtime(self, foundation: _UiFoundation) -> _UiModelRuntime:
        runtime = (
            self._runtime_factory()
            if self._runtime_factory is not None
            else FoundryLocalRuntime.initialize(
                app_name=self._settings.app_name,
                model_cache_dir=self._settings.foundry_model_cache_dir,
            )
        )
        return _UiModelRuntime(self, foundation, runtime)

    def _bind_session(
        self,
        foundation: _UiFoundation,
        runtime: _Runtime,
        chat_status: LocalModelStatus,
        embedding_status: LocalModelStatus,
    ) -> _UiWorkerSession:
        name_persistence = InsecureDevelopmentOnlyWorkspaceNamePersistence()
        unit_of_work = SQLiteUnitOfWork(
            self._connection_factory,
            name_persistence,
            self._security.payload_codec,
        )
        with unit_of_work:
            persisted_chat = unit_of_work.local_models.get_or_add_exact(chat_status.model)
            persisted_embedding = unit_of_work.local_models.get_or_add_exact(
                embedding_status.model
            )
            rebound_chat = runtime.adopt_persisted_record(
                chat_status,
                persisted_chat,
            )
            rebound_embedding = runtime.adopt_persisted_record(
                embedding_status,
                persisted_embedding,
            )
            chat_provider = runtime.chat_provider(rebound_chat)
            embedding_provider = runtime.embedding_provider(rebound_embedding)
            unit_of_work.commit()

        local_models = LocalModelComposition(
            chat_provider,
            embedding_provider,
            rebound_chat,
            rebound_embedding,
            runtime.close,
        )
        return self._compose_session(foundation, local_models)

    def _compose_session(
        self,
        foundation: _UiFoundation,
        local_models: LocalModelComposition,
    ) -> _UiWorkerSession:
        scope = foundation.workspaces.active_scope
        processing_cancellation = ProcessingCancellationAdapter(self._cancellation)
        indexing_cancellation = IndexingCancellationAdapter(self._cancellation)
        embedding_cancellation = EmbeddingCancellationAdapter(self._cancellation)
        evidence_cancellation = EvidenceCancellationAdapter(self._cancellation)
        chat_cancellation = ChatCancellationAdapter(self._cancellation)

        ingestion = compose_ingestion_application(
            self._settings,
            self._connection_factory,
            scope,
            security_providers=self._security,
        )
        processing = compose_processing_application(
            self._settings,
            self._connection_factory,
            scope,
            ingestion,
            cancellation=processing_cancellation,
        )
        indexing = compose_indexing_application(
            self._settings,
            self._connection_factory,
            scope,
            local_models.embedding_status,
            sensitive_payload_codec=self._security.payload_codec,
            cancellation=indexing_cancellation,
            security_providers=self._security,
        )
        embeddings = compose_embedding_application(
            self._settings,
            self._connection_factory,
            scope,
            local_models,
            cancellation=embedding_cancellation,
            security_providers=self._security,
        )
        retrieval = compose_retrieval_application(
            self._settings,
            self._connection_factory,
            scope,
            embeddings,
            security_providers=self._security,
        )
        sufficiency = compose_evidence_sufficiency_application(
            local_models,
            cancellation=evidence_cancellation,
        )
        chat = compose_chat_application(
            self._settings,
            self._connection_factory,
            scope,
            local_models,
            retrieval,
            sufficiency,
            cancellation=chat_cancellation,
            security_providers=self._security,
        )
        intake = StartSingleDocumentQuestion(
            scope,
            chat.unit_of_work_factory,
            chat_cancellation,
            _new_chat_id,
            _new_chat_message_id,
            _new_qa_request_id,
            _utc_millisecond_clock,
        )
        return _UiWorkerSession(
            foundation,
            local_models,
            DocumentCancellationAdapter(self._cancellation),
            ingestion.import_pdf,
            processing.process_pdf,
            indexing.prepare_index,
            embeddings.embed_staging_chunks,
            intake,
            chat.complete_chat,
        )


class _UiFoundation:
    def __init__(
        self,
        builder: UiWorkerSessionBuilder,
        workspaces: WorkspaceApplicationComposition,
    ) -> None:
        self._builder = builder
        self.workspaces = workspaces

    def list_workspaces(self) -> Sequence[Workspace]:
        return self.workspaces.list_workspaces()

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        return self.workspaces.create_workspace(display_name, profile)

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId:
        self.workspaces.select_workspace(workspace_id)
        return workspace_id

    def initialize_model_runtime(self) -> _UiModelRuntime:
        return self._builder._initialize_runtime(self)

    def close(self) -> None:
        return None


class _UiModelRuntime:
    def __init__(
        self,
        builder: UiWorkerSessionBuilder,
        foundation: _UiFoundation,
        runtime: _Runtime,
    ) -> None:
        self._builder = builder
        self._foundation = foundation
        self._runtime = runtime
        self._chat_status: LocalModelStatus | None = None
        self._embedding_status: LocalModelStatus | None = None

    def resolve_capabilities(self) -> None:
        self._chat_status = self._runtime.resolve_ready(
            model_id=self._builder._model_id_factory(),
            requested_alias=self._builder._settings.chat_model_alias,
            capability=ModelCapability.CHAT,
        )
        self._embedding_status = self._runtime.resolve_ready(
            model_id=self._builder._model_id_factory(),
            requested_alias=self._builder._settings.embedding_model_alias,
            capability=ModelCapability.EMBEDDING,
        )

    def bind_persisted_identity(self, foundation: object) -> _UiWorkerSession:
        if (
            foundation is not self._foundation
            or self._chat_status is None
            or self._embedding_status is None
        ):
            raise RuntimeError("local model composition is incomplete")
        return self._builder._bind_session(
            self._foundation,
            self._runtime,
            self._chat_status,
            self._embedding_status,
        )

    def close(self) -> None:
        self._runtime.close()


class _UiWorkerSession:
    def __init__(
        self,
        foundation: _UiFoundation,
        local_models: LocalModelComposition,
        document_cancellation: DocumentCancellationAdapter,
        import_pdf: Callable[[bytes, str], IngestionResult],
        process_pdf: Callable[[IngestionResult], ProcessingResult],
        prepare_indexing: Callable[[ProcessingResult], IndexPreparationResult],
        embed_staging_chunks: Callable[[StagingEmbeddingHandoff], ActivatedIndex],
        intake: StartSingleDocumentQuestion,
        complete_chat: Callable[[QaRequestId], ChatCompletionResult],
    ) -> None:
        self._foundation = foundation
        self._local_models = local_models
        self._document_cancellation = document_cancellation
        self._import_pdf = import_pdf
        self._process_pdf = process_pdf
        self._prepare_indexing = prepare_indexing
        self._embed_staging_chunks = embed_staging_chunks
        self._intake = intake
        self._complete_chat = complete_chat
        self._closed = False

    def list_workspaces(self) -> Sequence[Workspace]:
        return self._foundation.list_workspaces()

    def create_workspace(
        self,
        display_name: str,
        profile: WorkspaceProfile | None = None,
    ) -> Workspace:
        return self._foundation.create_workspace(display_name, profile)

    def select_workspace(self, workspace_id: WorkspaceId) -> WorkspaceId:
        return self._foundation.select_workspace(workspace_id)

    def initialize_model_runtime(self) -> _UiModelRuntime:
        raise RuntimeError("local model runtime is already initialized")

    def build_document(
        self,
        selected: SelectedPdfReference,
        stage_sink: DocumentWorkflowStageSink,
    ) -> ActiveDocumentResult:
        coordinator = BuildActiveDocument(
            self._foundation.workspaces.active_scope,
            LocalSelectedPdfReader(),
            self._document_cancellation,
            stage_sink,
            self._import_pdf,
            self._process_pdf,
            self._prepare_indexing,
            self._embed_staging_chunks,
        )
        return coordinator(selected)

    def materialize_question(
        self,
        document: ActiveDocumentResult,
        question: str,
    ) -> ChatIntakeRegistration:
        return self._intake.materialize(document, question)

    def start_question(
        self,
        registration: ChatIntakeRegistration,
    ) -> ChatIntakeResult:
        return self._intake(registration)

    def complete_question(self, qa_request_id: QaRequestId) -> ChatCompletionResult:
        return self._complete_chat(qa_request_id)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._local_models.close()


def compose_ui_application(
    settings: AppSettings,
    connection_factory: SQLiteConnectionFactory,
    security: SecurityProviders,
    *,
    runtime_factory: Callable[[], _Runtime] | None = None,
    model_id_factory: Callable[[], LocalModelId] | None = None,
) -> UiApplicationComposition:
    """Wire one restricted shell to one shared worker-side application session."""

    cancellation = ThreadCancellationSource()
    builder = UiWorkerSessionBuilder(
        settings,
        connection_factory,
        security,
        cancellation,
        runtime_factory=runtime_factory,
        model_id_factory=model_id_factory,
    )
    worker = WorkflowWorker(builder, cancellation)
    host = SerializedWorkflowHost(worker, cancellation)
    controller = PresentationController()
    window = MainWindow(
        controller=controller,
        workspace_commands=WorkspaceCommandBindings(
            host.list_workspaces_requested.emit,
            host.create_workspace_requested.emit,
            host.select_workspace_requested.emit,
        ),
        document_commands=DocumentCommandBindings(
            host.document_requested.emit,
            host.request_cancellation,
        ),
        question_commands=QuestionCommandBindings(
            host.question_requested.emit,
            host.question_retry_requested.emit,
            host.request_cancellation,
        ),
        shutdown_commands=ShutdownCommandBindings(host.request_shutdown),
    )
    worker.initialized.connect(window.accept_capability)
    worker.workspace_listed.connect(window.accept_workspace_listed)
    worker.workspace_created.connect(window.accept_workspace_created)
    worker.workspace_selected.connect(window.accept_workspace_selected)
    worker.document_phase_changed.connect(window.accept_document_phase)
    worker.document_ready.connect(window.accept_document_ready)
    worker.question_prepared.connect(window.accept_question_prepared)
    worker.question_completed.connect(window.accept_question_completed)
    worker.operation_cancelled.connect(window.accept_cancelled)
    worker.operation_failed.connect(window.accept_failed)
    host.shutdown_finished.connect(window.accept_shutdown_complete)
    return UiApplicationComposition(window, controller, worker, host)


def _new_local_model_id() -> LocalModelId:
    return LocalModelId(str(uuid4()))


def _new_chat_id() -> ChatId:
    return ChatId(str(uuid4()))


def _new_chat_message_id() -> ChatMessageId:
    return ChatMessageId(str(uuid4()))


def _new_qa_request_id() -> QaRequestId:
    return QaRequestId(str(uuid4()))


def _utc_millisecond_clock() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)
