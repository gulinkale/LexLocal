from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .errors import (
    InvalidDomainValue,
    InvalidStateTransition,
    RelationshipMismatch,
    WorkspaceScopeViolation,
)
from .identifiers import DocumentId, DocumentVersionId, WorkspaceId


class LogicalDocumentState(StrEnum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class DocumentVersionState(StrEnum):
    CANDIDATE_PROCESSING = "CANDIDATE_PROCESSING"
    CANDIDATE_READY = "CANDIDATE_READY"
    CANDIDATE_WARNING = "CANDIDATE_WARNING"
    CANDIDATE_FAILED = "CANDIDATE_FAILED"
    CANDIDATE_CANCELLED = "CANDIDATE_CANCELLED"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


_LOGICAL_DOCUMENT_TRANSITIONS: dict[
    LogicalDocumentState, frozenset[LogicalDocumentState]
] = {
    LogicalDocumentState.ACTIVE: frozenset({LogicalDocumentState.DELETED}),
    LogicalDocumentState.DELETED: frozenset(),
}

_DOCUMENT_VERSION_TRANSITIONS: dict[
    DocumentVersionState, frozenset[DocumentVersionState]
] = {
    DocumentVersionState.CANDIDATE_PROCESSING: frozenset(
        {
            DocumentVersionState.CANDIDATE_READY,
            DocumentVersionState.CANDIDATE_WARNING,
            DocumentVersionState.CANDIDATE_FAILED,
            DocumentVersionState.CANDIDATE_CANCELLED,
        }
    ),
    DocumentVersionState.CANDIDATE_READY: frozenset(
        {DocumentVersionState.ACTIVE}
    ),
    DocumentVersionState.CANDIDATE_WARNING: frozenset(
        {DocumentVersionState.ACTIVE}
    ),
    DocumentVersionState.CANDIDATE_FAILED: frozenset(),
    DocumentVersionState.CANDIDATE_CANCELLED: frozenset(),
    DocumentVersionState.ACTIVE: frozenset(
        {DocumentVersionState.ARCHIVED, DocumentVersionState.DELETED}
    ),
    DocumentVersionState.ARCHIVED: frozenset({DocumentVersionState.DELETED}),
    DocumentVersionState.DELETED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class VersionNumber:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 1:
            raise InvalidDomainValue("version number must be a positive integer")


@dataclass(frozen=True, slots=True)
class LogicalDocument:
    id: DocumentId
    workspace_id: WorkspaceId
    state: LogicalDocumentState = LogicalDocumentState.ACTIVE

    def __post_init__(self) -> None:
        if not isinstance(self.id, DocumentId):
            raise InvalidDomainValue("logical document id must be a DocumentId")
        if not isinstance(self.workspace_id, WorkspaceId):
            raise InvalidDomainValue("logical document workspace id must be a WorkspaceId")
        if not isinstance(self.state, LogicalDocumentState):
            raise InvalidDomainValue("logical document state must be a LogicalDocumentState")

    @property
    def allows_mutation(self) -> bool:
        return self.state is LogicalDocumentState.ACTIVE

    def transition_to(self, target_state: LogicalDocumentState) -> LogicalDocument:
        if target_state not in _LOGICAL_DOCUMENT_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"logical document cannot transition from {self.state} to {target_state}"
            )
        return replace(self, state=target_state)


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: DocumentVersionId
    workspace_id: WorkspaceId
    document_id: DocumentId
    version_number: VersionNumber
    state: DocumentVersionState = DocumentVersionState.CANDIDATE_PROCESSING

    def __post_init__(self) -> None:
        if not isinstance(self.id, DocumentVersionId):
            raise InvalidDomainValue("document version id must be a DocumentVersionId")
        if not isinstance(self.workspace_id, WorkspaceId):
            raise InvalidDomainValue("document version workspace id must be a WorkspaceId")
        if not isinstance(self.document_id, DocumentId):
            raise InvalidDomainValue("document version document id must be a DocumentId")
        if not isinstance(self.version_number, VersionNumber):
            raise InvalidDomainValue("document version number must be a VersionNumber")
        if not isinstance(self.state, DocumentVersionState):
            raise InvalidDomainValue("document version state must be a DocumentVersionState")

    def transition_to(self, target_state: DocumentVersionState) -> DocumentVersion:
        if target_state not in _DOCUMENT_VERSION_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"document version cannot transition from {self.state} to {target_state}"
            )
        return replace(self, state=target_state)

    def validate_document(self, document: LogicalDocument) -> None:
        if self.workspace_id != document.workspace_id:
            raise WorkspaceScopeViolation(
                "document version and logical document must belong to the same workspace"
            )
        if self.document_id != document.id:
            raise RelationshipMismatch(
                "document version must belong to the supplied logical document"
            )
