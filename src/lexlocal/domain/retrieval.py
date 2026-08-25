from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from math import isfinite

from .documents import DocumentVersion, DocumentVersionState
from .errors import (
    InvalidDomainValue,
    InvalidStateTransition,
    RelationshipMismatch,
    WorkspaceScopeViolation,
)
from .identifiers import (
    ChunkId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    EvidenceItemId,
    RetrievalRunId,
    SourceLocatorId,
    WorkspaceId,
)
from .processing import IndexGeneration, IndexGenerationState
from .workspace import Workspace, WorkspaceState


@dataclass(frozen=True, slots=True)
class PageNumber:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 1:
            raise InvalidDomainValue("page number must be a positive integer")


@dataclass(frozen=True, slots=True)
class EvidenceRank:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 1:
            raise InvalidDomainValue("evidence rank must be a positive integer")


@dataclass(frozen=True, slots=True)
class SimilarityScore:
    value: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not isfinite(self.value)
            or not -1.0 <= self.value <= 1.0
        ):
            raise InvalidDomainValue("similarity score must be finite and between -1 and 1")
        object.__setattr__(self, "value", float(self.value))


class SourceLocatorKind(StrEnum):
    PAGE = "PAGE"
    PDF_TEXT_BOUNDS = "PDF_TEXT_BOUNDS"
    OCR_BOUNDS = "OCR_BOUNDS"
    IMAGE_REGION = "IMAGE_REGION"


class EvidenceAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    SOURCE_DELETED = "SOURCE_DELETED"


class EvidenceSufficiency(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    RELATED_BUT_INSUFFICIENT = "RELATED_BUT_INSUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class SourceLocator:
    id: SourceLocatorId
    workspace_id: WorkspaceId
    document_version_id: DocumentVersionId
    page_id: DocumentPageId
    page_number: PageNumber
    kind: SourceLocatorKind

    def __post_init__(self) -> None:
        if not isinstance(self.id, SourceLocatorId):
            raise InvalidDomainValue("source locator id must be a SourceLocatorId")
        if not isinstance(self.workspace_id, WorkspaceId):
            raise InvalidDomainValue("source locator workspace id must be a WorkspaceId")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise InvalidDomainValue(
                "source locator document version id must be a DocumentVersionId"
            )
        if not isinstance(self.page_id, DocumentPageId):
            raise InvalidDomainValue("source locator page id must be a DocumentPageId")
        if not isinstance(self.page_number, PageNumber):
            raise InvalidDomainValue("source locator page number must be a PageNumber")
        if not isinstance(self.kind, SourceLocatorKind):
            raise InvalidDomainValue("source locator kind must be a SourceLocatorKind")

    def validate_document_version(self, version: DocumentVersion) -> None:
        if self.workspace_id != version.workspace_id:
            raise WorkspaceScopeViolation(
                "source locator and document version must belong to the same workspace"
            )
        if self.document_version_id != version.id:
            raise RelationshipMismatch(
                "source locator must belong to the supplied document version"
            )


@dataclass(frozen=True, slots=True)
class Evidence:
    id: EvidenceItemId
    workspace_id: WorkspaceId
    retrieval_run_id: RetrievalRunId
    document_id: DocumentId
    document_version_id: DocumentVersionId
    page_number: PageNumber
    rank: EvidenceRank
    similarity_score: SimilarityScore
    chunk_id: ChunkId | None = None
    source_locator_id: SourceLocatorId | None = None
    availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE

    def __post_init__(self) -> None:
        if not isinstance(self.id, EvidenceItemId):
            raise InvalidDomainValue("evidence id must be an EvidenceItemId")
        if not isinstance(self.workspace_id, WorkspaceId):
            raise InvalidDomainValue("evidence workspace id must be a WorkspaceId")
        if not isinstance(self.retrieval_run_id, RetrievalRunId):
            raise InvalidDomainValue("evidence retrieval run id must be a RetrievalRunId")
        if not isinstance(self.document_id, DocumentId):
            raise InvalidDomainValue("evidence document id must be a DocumentId")
        if not isinstance(self.document_version_id, DocumentVersionId):
            raise InvalidDomainValue(
                "evidence document version id must be a DocumentVersionId"
            )
        if not isinstance(self.page_number, PageNumber):
            raise InvalidDomainValue("evidence page number must be a PageNumber")
        if not isinstance(self.rank, EvidenceRank):
            raise InvalidDomainValue("evidence rank must be an EvidenceRank")
        if not isinstance(self.similarity_score, SimilarityScore):
            raise InvalidDomainValue(
                "evidence similarity score must be a SimilarityScore"
            )
        if self.chunk_id is not None and not isinstance(self.chunk_id, ChunkId):
            raise InvalidDomainValue("evidence chunk id must be a ChunkId or None")
        if self.source_locator_id is not None and not isinstance(
            self.source_locator_id, SourceLocatorId
        ):
            raise InvalidDomainValue(
                "evidence source locator id must be a SourceLocatorId or None"
            )
        if not isinstance(self.availability, EvidenceAvailability):
            raise InvalidDomainValue(
                "evidence availability must be an EvidenceAvailability"
            )
        if self.availability is EvidenceAvailability.SOURCE_DELETED and (
            self.chunk_id is not None or self.source_locator_id is not None
        ):
            raise InvalidDomainValue(
                "source-deleted evidence cannot retain live chunk or locator references"
            )

    def mark_source_deleted(self) -> Evidence:
        if self.availability is not EvidenceAvailability.AVAILABLE:
            raise InvalidStateTransition(
                "source-deleted evidence has no outgoing availability transition"
            )
        return replace(
            self,
            chunk_id=None,
            source_locator_id=None,
            availability=EvidenceAvailability.SOURCE_DELETED,
        )

    def validate_document_version(self, version: DocumentVersion) -> None:
        if self.workspace_id != version.workspace_id:
            raise WorkspaceScopeViolation(
                "evidence and document version must belong to the same workspace"
            )
        if (
            self.document_version_id != version.id
            or self.document_id != version.document_id
        ):
            raise RelationshipMismatch(
                "evidence must identify the supplied document and version"
            )

    def validate_source_locator(self, locator: SourceLocator) -> None:
        if self.workspace_id != locator.workspace_id:
            raise WorkspaceScopeViolation(
                "evidence and source locator must belong to the same workspace"
            )
        if self.availability is EvidenceAvailability.SOURCE_DELETED:
            raise RelationshipMismatch(
                "source-deleted evidence cannot use a live source locator"
            )
        if (
            self.source_locator_id is None
            or self.source_locator_id != locator.id
            or self.document_version_id != locator.document_version_id
            or self.page_number != locator.page_number
        ):
            raise RelationshipMismatch(
                "evidence and source locator must identify the same source snapshot"
            )


def validate_retrieval_eligibility(
    workspace: Workspace,
    version: DocumentVersion,
    index_generation: IndexGeneration,
) -> None:
    if version.workspace_id != workspace.id:
        raise WorkspaceScopeViolation(
            "document version must belong to the retrieval workspace"
        )
    if index_generation.workspace_id != workspace.id:
        raise WorkspaceScopeViolation(
            "index generation must belong to the retrieval workspace"
        )
    if index_generation.document_version_id != version.id:
        raise RelationshipMismatch(
            "index generation must target the retrieval document version"
        )
    if workspace.state is not WorkspaceState.ACTIVE:
        raise InvalidStateTransition("workspace is not eligible for new retrieval")
    if version.state is not DocumentVersionState.ACTIVE:
        raise InvalidStateTransition("document version is not eligible for new retrieval")
    if index_generation.state is not IndexGenerationState.ACTIVE:
        raise InvalidStateTransition("index generation is not eligible for new retrieval")
