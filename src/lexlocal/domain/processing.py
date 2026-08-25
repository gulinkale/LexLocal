from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .documents import DocumentVersion
from .errors import (
    InvalidDomainValue,
    InvalidStateTransition,
    RelationshipMismatch,
    WorkspaceScopeViolation,
)
from .identifiers import (
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    WorkspaceId,
)


class ProcessingJobState(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IndexGenerationState(StrEnum):
    STAGING = "STAGING"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


_PROCESSING_JOB_TRANSITIONS: dict[
    ProcessingJobState, frozenset[ProcessingJobState]
] = {
    ProcessingJobState.QUEUED: frozenset(
        {ProcessingJobState.PROCESSING, ProcessingJobState.CANCELLED}
    ),
    ProcessingJobState.PROCESSING: frozenset(
        {
            ProcessingJobState.READY,
            ProcessingJobState.READY_WITH_WARNINGS,
            ProcessingJobState.FAILED,
            ProcessingJobState.CANCELLED,
        }
    ),
    ProcessingJobState.READY: frozenset(),
    ProcessingJobState.READY_WITH_WARNINGS: frozenset(),
    ProcessingJobState.FAILED: frozenset(),
    ProcessingJobState.CANCELLED: frozenset(),
}

_INDEX_GENERATION_TRANSITIONS: dict[
    IndexGenerationState, frozenset[IndexGenerationState]
] = {
    IndexGenerationState.STAGING: frozenset(
        {IndexGenerationState.ACTIVE, IndexGenerationState.FAILED}
    ),
    IndexGenerationState.ACTIVE: frozenset({IndexGenerationState.ARCHIVED}),
    IndexGenerationState.ARCHIVED: frozenset(),
    IndexGenerationState.FAILED: frozenset(),
}

_INDEX_ACTIVATION_JOB_STATES = frozenset(
    {ProcessingJobState.READY, ProcessingJobState.READY_WITH_WARNINGS}
)


@dataclass(frozen=True, slots=True)
class AttemptNumber:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 1:
            raise InvalidDomainValue("attempt number must be a positive integer")


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    id: ProcessingJobId
    workspace_id: WorkspaceId
    document_version_id: DocumentVersionId
    attempt_number: AttemptNumber
    state: ProcessingJobState = ProcessingJobState.QUEUED

    def __post_init__(self) -> None:
        if not isinstance(self.id, ProcessingJobId):
            raise InvalidDomainValue("processing job id must be a ProcessingJobId")
        if not isinstance(self.workspace_id, WorkspaceId):
            raise InvalidDomainValue("processing job workspace id must be a WorkspaceId")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise InvalidDomainValue(
                "processing job document version id must be a DocumentVersionId"
            )
        if not isinstance(self.attempt_number, AttemptNumber):
            raise InvalidDomainValue("processing job attempt number must be an AttemptNumber")
        if not isinstance(self.state, ProcessingJobState):
            raise InvalidDomainValue("processing job state must be a ProcessingJobState")

    def transition_to(self, target_state: ProcessingJobState) -> ProcessingJob:
        if target_state not in _PROCESSING_JOB_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"processing job cannot transition from {self.state} to {target_state}"
            )
        return replace(self, state=target_state)

    def validate_document_version(self, version: DocumentVersion) -> None:
        if self.workspace_id != version.workspace_id:
            raise WorkspaceScopeViolation(
                "processing job and document version must belong to the same workspace"
            )
        if self.document_version_id != version.id:
            raise RelationshipMismatch(
                "processing job must belong to the supplied document version"
            )


@dataclass(frozen=True, slots=True)
class IndexGeneration:
    id: IndexGenerationId
    workspace_id: WorkspaceId
    document_version_id: DocumentVersionId
    processing_job_id: ProcessingJobId
    embedding_model_id: LocalModelId
    chunking_profile_version: str
    normalization_profile_version: str
    embedding_dimensions: int
    state: IndexGenerationState = IndexGenerationState.STAGING

    def __post_init__(self) -> None:
        if not isinstance(self.id, IndexGenerationId):
            raise InvalidDomainValue("index generation id must be an IndexGenerationId")
        if not isinstance(self.workspace_id, WorkspaceId):
            raise InvalidDomainValue("index generation workspace id must be a WorkspaceId")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise InvalidDomainValue(
                "index generation document version id must be a DocumentVersionId"
            )
        if not isinstance(self.processing_job_id, ProcessingJobId):
            raise InvalidDomainValue(
                "index generation processing job id must be a ProcessingJobId"
            )
        if not isinstance(self.embedding_model_id, LocalModelId):
            raise InvalidDomainValue(
                "index generation embedding model id must be a LocalModelId"
            )
        if (
            not isinstance(self.chunking_profile_version, str)
            or not self.chunking_profile_version.strip()
        ):
            raise InvalidDomainValue(
                "index generation chunking profile version must not be empty"
            )
        if (
            not isinstance(self.normalization_profile_version, str)
            or not self.normalization_profile_version.strip()
        ):
            raise InvalidDomainValue(
                "index generation normalization profile version must not be empty"
            )
        if (
            isinstance(self.embedding_dimensions, bool)
            or not isinstance(self.embedding_dimensions, int)
            or self.embedding_dimensions < 1
        ):
            raise InvalidDomainValue(
                "index generation embedding dimensions must be a positive integer"
            )
        if not isinstance(self.state, IndexGenerationState):
            raise InvalidDomainValue(
                "index generation state must be an IndexGenerationState"
            )

    def transition_to(self, target_state: IndexGenerationState) -> IndexGeneration:
        if target_state is IndexGenerationState.ACTIVE:
            raise InvalidStateTransition(
                "index generation activation requires its processing job"
            )
        return self._transition_to(target_state)

    def activate(self, job: ProcessingJob) -> IndexGeneration:
        if IndexGenerationState.ACTIVE not in _INDEX_GENERATION_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"index generation cannot transition from {self.state} "
                f"to {IndexGenerationState.ACTIVE}"
            )
        self.validate_processing_job(job)
        if job.state not in _INDEX_ACTIVATION_JOB_STATES:
            raise InvalidStateTransition(
                f"processing job in state {job.state} cannot activate an index generation"
            )
        return replace(self, state=IndexGenerationState.ACTIVE)

    def validate_document_version(self, version: DocumentVersion) -> None:
        if self.workspace_id != version.workspace_id:
            raise WorkspaceScopeViolation(
                "index generation and document version must belong to the same workspace"
            )
        if self.document_version_id != version.id:
            raise RelationshipMismatch(
                "index generation must belong to the supplied document version"
            )

    def validate_processing_job(self, job: ProcessingJob) -> None:
        if self.workspace_id != job.workspace_id:
            raise WorkspaceScopeViolation(
                "index generation and processing job must belong to the same workspace"
            )
        if self.processing_job_id != job.id:
            raise RelationshipMismatch(
                "index generation must belong to the supplied processing job"
            )
        if self.document_version_id != job.document_version_id:
            raise RelationshipMismatch(
                "index generation and processing job must target the same document version"
            )

    def _transition_to(self, target_state: IndexGenerationState) -> IndexGeneration:
        if target_state not in _INDEX_GENERATION_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"index generation cannot transition from {self.state} to {target_state}"
            )
        return replace(self, state=target_state)
