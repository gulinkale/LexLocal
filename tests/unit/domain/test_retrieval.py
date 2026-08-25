from dataclasses import FrozenInstanceError

import pytest

from lexlocal.domain.documents import DocumentVersion, DocumentVersionState, VersionNumber
from lexlocal.domain.errors import (
    InvalidDomainValue,
    InvalidStateTransition,
    RelationshipMismatch,
    WorkspaceScopeViolation,
)
from lexlocal.domain.identifiers import (
    ChunkId,
    DocumentId,
    DocumentPageId,
    DocumentVersionId,
    EvidenceItemId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    RetrievalRunId,
    SourceLocatorId,
    WorkspaceId,
)
from lexlocal.domain.processing import IndexGeneration, IndexGenerationState
from lexlocal.domain.retrieval import (
    Evidence,
    EvidenceAvailability,
    EvidenceRank,
    EvidenceSufficiency,
    PageNumber,
    SimilarityScore,
    SourceLocator,
    SourceLocatorKind,
    validate_retrieval_eligibility,
)
from lexlocal.domain.workspace import Workspace, WorkspaceState

#example identifiers and values for use in tests
WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
DOCUMENT_ID = DocumentId("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
OTHER_DOCUMENT_ID = DocumentId("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
VERSION_ID = DocumentVersionId("01890f5e-7b9a-7cc0-98c8-5f89a9c83562")
OTHER_VERSION_ID = DocumentVersionId("01890f5e-7b9a-7cc0-98c8-5f89a9c83563")
PAGE_ID = DocumentPageId("10000000-0000-4000-8000-000000000001")
LOCATOR_ID = SourceLocatorId("20000000-0000-4000-8000-000000000001")
OTHER_LOCATOR_ID = SourceLocatorId("20000000-0000-4000-8000-000000000002")
EVIDENCE_ID = EvidenceItemId("30000000-0000-4000-8000-000000000001")
RETRIEVAL_RUN_ID = RetrievalRunId("40000000-0000-4000-8000-000000000001")
CHUNK_ID = ChunkId("50000000-0000-4000-8000-000000000001")
INDEX_ID = IndexGenerationId("60000000-0000-4000-8000-000000000001")
JOB_ID = ProcessingJobId("70000000-0000-4000-8000-000000000001")
MODEL_ID = LocalModelId("80000000-0000-4000-8000-000000000001")
PAGE_ONE = PageNumber(1)
RANK_ONE = EvidenceRank(1)
SCORE = SimilarityScore(0.75)


def _version(
    *,
    id: DocumentVersionId = VERSION_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    document_id: DocumentId = DOCUMENT_ID,
    state: DocumentVersionState = DocumentVersionState.ACTIVE,
) -> DocumentVersion:
    return DocumentVersion(
        id=id,
        workspace_id=workspace_id,
        document_id=document_id,
        version_number=VersionNumber(1),
        state=state,
    )


def _locator(
    *,
    id: SourceLocatorId = LOCATOR_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    document_version_id: DocumentVersionId = VERSION_ID,
    page_id: DocumentPageId = PAGE_ID,
    page_number: PageNumber = PAGE_ONE,
    kind: SourceLocatorKind = SourceLocatorKind.PAGE,
) -> SourceLocator:
    return SourceLocator(
        id=id,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        page_id=page_id,
        page_number=page_number,
        kind=kind,
    )


def _evidence(
    *,
    id: EvidenceItemId = EVIDENCE_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    retrieval_run_id: RetrievalRunId = RETRIEVAL_RUN_ID,
    document_id: DocumentId = DOCUMENT_ID,
    document_version_id: DocumentVersionId = VERSION_ID,
    page_number: PageNumber = PAGE_ONE,
    rank: EvidenceRank = RANK_ONE,
    similarity_score: SimilarityScore = SCORE,
    chunk_id: ChunkId | None = CHUNK_ID,
    source_locator_id: SourceLocatorId | None = LOCATOR_ID,
    availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE,
) -> Evidence:
    return Evidence(
        id=id,
        workspace_id=workspace_id,
        retrieval_run_id=retrieval_run_id,
        document_id=document_id,
        document_version_id=document_version_id,
        page_number=page_number,
        rank=rank,
        similarity_score=similarity_score,
        chunk_id=chunk_id,
        source_locator_id=source_locator_id,
        availability=availability,
    )


def _workspace(
    *,
    id: WorkspaceId = WORKSPACE_ID,
    state: WorkspaceState = WorkspaceState.ACTIVE,
) -> Workspace:
    return Workspace(id=id, display_name="Matter", state=state)


def _index_generation(
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    document_version_id: DocumentVersionId = VERSION_ID,
    state: IndexGenerationState = IndexGenerationState.ACTIVE,
) -> IndexGeneration:
    return IndexGeneration(
        id=INDEX_ID,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        processing_job_id=JOB_ID,
        embedding_model_id=MODEL_ID,
        chunking_profile_version="chunks-v1",
        normalization_profile_version="normalization-v1",
        embedding_dimensions=1024,
        state=state,
    )


@pytest.mark.parametrize("value", [1, 2, 1_000_000])
def test_page_number_accepts_one_based_positive_integer(value: int) -> None:
    assert PageNumber(value).value == value


@pytest.mark.parametrize("value", [0, -1, None, "1", 1.0, True, False])
def test_page_number_rejects_invalid_value(value: object) -> None:
    with pytest.raises(InvalidDomainValue):
        PageNumber(value)  # type: ignore[arg-type]


def test_page_number_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        PAGE_ONE.value = 2


def test_page_number_has_no_allocation_api() -> None:
    for name in ("next", "increment", "from_page_index"):
        assert not hasattr(PageNumber, name)


@pytest.mark.parametrize("value", [1, 2, 1_000_000])
def test_evidence_rank_accepts_positive_integer(value: int) -> None:
    assert EvidenceRank(value).value == value


@pytest.mark.parametrize("value", [0, -1, None, "1", 1.0, True, False])
def test_evidence_rank_rejects_invalid_value(value: object) -> None:
    with pytest.raises(InvalidDomainValue):
        EvidenceRank(value)  # type: ignore[arg-type]


def test_evidence_rank_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        RANK_ONE.value = 2


@pytest.mark.parametrize("value", [-1.0, -0.25, 0, 0.0, 0.75, 1.0])
def test_similarity_score_accepts_finite_value_in_cosine_interval(
    value: float,
) -> None:
    assert SimilarityScore(value).value == float(value)

def test_similarity_score_canonicalizes_integer_to_float() -> None:
    score = SimilarityScore(0)

    assert score.value == 0.0
    assert type(score.value) is float

@pytest.mark.parametrize(
    "value",
    [-1.000001, 1.000001, None, "0.5", True, False, float("nan"), float("inf"), float("-inf")],
)
def test_similarity_score_rejects_invalid_value(value: object) -> None:
    with pytest.raises(InvalidDomainValue):
        SimilarityScore(value)  # type: ignore[arg-type]


def test_similarity_score_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        SCORE.value = 0.5


def test_source_locator_kind_contains_exact_persisted_values() -> None:
    assert {kind.value for kind in SourceLocatorKind} == {
        "PAGE",
        "PDF_TEXT_BOUNDS",
        "OCR_BOUNDS",
        "IMAGE_REGION",
    }


def test_source_locator_accepts_typed_page_only_construction() -> None:
    locator = _locator()

    assert locator.id == LOCATOR_ID
    assert locator.workspace_id == WORKSPACE_ID
    assert locator.document_version_id == VERSION_ID
    assert locator.page_id == PAGE_ID
    assert locator.page_number == PageNumber(1)
    assert locator.kind is SourceLocatorKind.PAGE


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("id", str(LOCATOR_ID)),
        ("id", PAGE_ID),
        ("workspace_id", str(WORKSPACE_ID)),
        ("workspace_id", VERSION_ID),
        ("document_version_id", str(VERSION_ID)),
        ("document_version_id", WORKSPACE_ID),
        ("page_id", str(PAGE_ID)),
        ("page_id", LOCATOR_ID),
        ("page_number", 1),
        ("kind", "PAGE"),
    ],
)
def test_source_locator_rejects_invalid_construction_value(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "id": LOCATOR_ID,
        "workspace_id": WORKSPACE_ID,
        "document_version_id": VERSION_ID,
        "page_id": PAGE_ID,
        "page_number": PAGE_ONE,
        "kind": SourceLocatorKind.PAGE,
    }
    values[field_name] = invalid_value

    with pytest.raises(InvalidDomainValue):
        SourceLocator(**values)  # type: ignore[arg-type]


def test_source_locator_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        _locator().page_number = PageNumber(2)


def test_source_locator_validates_matching_document_version() -> None:
    _locator().validate_document_version(_version())


def test_source_locator_accepts_historical_archived_version_relationship() -> None:
    _locator().validate_document_version(
        _version(state=DocumentVersionState.ARCHIVED)
    )


def test_source_locator_rejects_cross_workspace_document_version() -> None:
    with pytest.raises(WorkspaceScopeViolation):
        _locator().validate_document_version(
            _version(workspace_id=OTHER_WORKSPACE_ID, id=OTHER_VERSION_ID)
        )


def test_source_locator_rejects_wrong_version_in_same_workspace() -> None:
    with pytest.raises(RelationshipMismatch):
        _locator().validate_document_version(_version(id=OTHER_VERSION_ID))


def test_evidence_availability_contains_exact_persisted_values() -> None:
    assert {availability.value for availability in EvidenceAvailability} == {
        "AVAILABLE",
        "SOURCE_DELETED",
    }


def test_evidence_sufficiency_contains_exact_classifications() -> None:
    assert {sufficiency.value for sufficiency in EvidenceSufficiency} == {
        "SUFFICIENT",
        "RELATED_BUT_INSUFFICIENT",
        "INSUFFICIENT",
    }


def test_evidence_accepts_typed_historical_source_relationships() -> None:
    evidence = _evidence()

    assert evidence.id == EVIDENCE_ID
    assert evidence.workspace_id == WORKSPACE_ID
    assert evidence.retrieval_run_id == RETRIEVAL_RUN_ID
    assert evidence.document_id == DOCUMENT_ID
    assert evidence.document_version_id == VERSION_ID
    assert evidence.page_number == PAGE_ONE
    assert evidence.rank == RANK_ONE
    assert evidence.similarity_score == SCORE
    assert evidence.chunk_id == CHUNK_ID
    assert evidence.source_locator_id == LOCATOR_ID
    assert evidence.availability is EvidenceAvailability.AVAILABLE


def test_available_evidence_accepts_absent_optional_live_references() -> None:
    evidence = _evidence(chunk_id=None, source_locator_id=None)

    assert evidence.chunk_id is None
    assert evidence.source_locator_id is None


def test_source_deleted_evidence_accepts_rehydration_without_live_references() -> None:
    evidence = _evidence(
        chunk_id=None,
        source_locator_id=None,
        availability=EvidenceAvailability.SOURCE_DELETED,
    )

    assert evidence.availability is EvidenceAvailability.SOURCE_DELETED


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("id", str(EVIDENCE_ID)),
        ("id", LOCATOR_ID),
        ("workspace_id", str(WORKSPACE_ID)),
        ("workspace_id", DOCUMENT_ID),
        ("retrieval_run_id", str(RETRIEVAL_RUN_ID)),
        ("retrieval_run_id", EVIDENCE_ID),
        ("document_id", str(DOCUMENT_ID)),
        ("document_id", VERSION_ID),
        ("document_version_id", str(VERSION_ID)),
        ("document_version_id", DOCUMENT_ID),
        ("page_number", 1),
        ("rank", 1),
        ("similarity_score", 0.75),
        ("chunk_id", str(CHUNK_ID)),
        ("chunk_id", LOCATOR_ID),
        ("source_locator_id", str(LOCATOR_ID)),
        ("source_locator_id", CHUNK_ID),
        ("availability", "AVAILABLE"),
    ],
)
def test_evidence_rejects_invalid_construction_value(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "id": EVIDENCE_ID,
        "workspace_id": WORKSPACE_ID,
        "retrieval_run_id": RETRIEVAL_RUN_ID,
        "document_id": DOCUMENT_ID,
        "document_version_id": VERSION_ID,
        "page_number": PAGE_ONE,
        "rank": RANK_ONE,
        "similarity_score": SCORE,
        "chunk_id": CHUNK_ID,
        "source_locator_id": LOCATOR_ID,
        "availability": EvidenceAvailability.AVAILABLE,
    }
    values[field_name] = invalid_value

    with pytest.raises(InvalidDomainValue):
        Evidence(**values)  # type: ignore[arg-type]


def test_source_deleted_evidence_rejects_live_references() -> None:
    with pytest.raises(InvalidDomainValue):
        _evidence(availability=EvidenceAvailability.SOURCE_DELETED)


def test_mark_source_deleted_returns_historical_snapshot_without_live_links() -> None:
    evidence = _evidence(page_number=PageNumber(27))

    deleted = evidence.mark_source_deleted()

    assert deleted.id == evidence.id
    assert deleted.workspace_id == evidence.workspace_id
    assert deleted.retrieval_run_id == evidence.retrieval_run_id
    assert deleted.document_id == evidence.document_id
    assert deleted.document_version_id == evidence.document_version_id
    assert deleted.page_number == PageNumber(27)
    assert deleted.rank == evidence.rank
    assert deleted.similarity_score == evidence.similarity_score
    assert deleted.chunk_id is None
    assert deleted.source_locator_id is None
    assert deleted.availability is EvidenceAvailability.SOURCE_DELETED
    assert evidence.chunk_id == CHUNK_ID
    assert evidence.source_locator_id == LOCATOR_ID
    assert evidence.availability is EvidenceAvailability.AVAILABLE
    assert deleted is not evidence


def test_source_deleted_evidence_is_terminal() -> None:
    deleted = _evidence().mark_source_deleted()

    with pytest.raises(InvalidStateTransition):
        deleted.mark_source_deleted()


def test_source_deleted_evidence_cannot_attach_another_locator() -> None:
    deleted = _evidence().mark_source_deleted()

    with pytest.raises(RelationshipMismatch):
        deleted.validate_source_locator(_locator(id=OTHER_LOCATOR_ID))


@pytest.mark.parametrize(
    "attribute_name",
    [
        "id",
        "workspace_id",
        "retrieval_run_id",
        "document_id",
        "document_version_id",
        "page_number",
        "rank",
        "similarity_score",
        "chunk_id",
        "source_locator_id",
        "availability",
    ],
)
def test_evidence_is_immutable(attribute_name: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(_evidence(), attribute_name, None)


def test_evidence_validates_matching_document_version() -> None:
    _evidence().validate_document_version(_version())


def test_evidence_rejects_cross_workspace_document_version_first() -> None:
    with pytest.raises(WorkspaceScopeViolation):
        _evidence().validate_document_version(
            _version(
                id=OTHER_VERSION_ID,
                workspace_id=OTHER_WORKSPACE_ID,
                document_id=OTHER_DOCUMENT_ID,
            )
        )


def test_evidence_rejects_wrong_document_version_in_same_workspace() -> None:
    with pytest.raises(RelationshipMismatch):
        _evidence().validate_document_version(_version(id=OTHER_VERSION_ID))


def test_evidence_rejects_wrong_document_identity_for_version() -> None:
    with pytest.raises(RelationshipMismatch):
        _evidence().validate_document_version(_version(document_id=OTHER_DOCUMENT_ID))


def test_evidence_validates_matching_source_locator() -> None:
    _evidence().validate_source_locator(_locator())


def test_evidence_rejects_cross_workspace_source_locator_first() -> None:
    with pytest.raises(WorkspaceScopeViolation):
        _evidence().validate_source_locator(
            _locator(
                id=OTHER_LOCATOR_ID,
                workspace_id=OTHER_WORKSPACE_ID,
                document_version_id=OTHER_VERSION_ID,
            )
        )


def test_evidence_rejects_wrong_source_locator_in_same_workspace() -> None:
    with pytest.raises(RelationshipMismatch):
        _evidence().validate_source_locator(_locator(id=OTHER_LOCATOR_ID))


def test_evidence_rejects_source_locator_for_wrong_version() -> None:
    with pytest.raises(RelationshipMismatch):
        _evidence().validate_source_locator(
            _locator(document_version_id=OTHER_VERSION_ID)
        )


def test_evidence_rejects_source_locator_for_wrong_page_snapshot() -> None:
    with pytest.raises(RelationshipMismatch):
        _evidence().validate_source_locator(_locator(page_number=PageNumber(2)))


def test_active_related_objects_are_state_eligible_for_new_retrieval() -> None:
    validate_retrieval_eligibility(_workspace(), _version(), _index_generation())


@pytest.mark.parametrize(
    "state",
    [
        WorkspaceState.ARCHIVED,
        WorkspaceState.DELETING,
        WorkspaceState.DELETION_RECOVERY,
    ],
    ids=lambda state: state.value,
)
def test_inactive_workspace_is_not_eligible_for_new_retrieval(
    state: WorkspaceState,
) -> None:
    with pytest.raises(InvalidStateTransition):
        validate_retrieval_eligibility(
            _workspace(state=state), _version(), _index_generation()
        )


@pytest.mark.parametrize(
    "state",
    [state for state in DocumentVersionState if state is not DocumentVersionState.ACTIVE],
    ids=lambda state: state.value,
)
def test_non_active_document_version_is_not_eligible_for_new_retrieval(
    state: DocumentVersionState,
) -> None:
    with pytest.raises(InvalidStateTransition):
        validate_retrieval_eligibility(
            _workspace(), _version(state=state), _index_generation()
        )


@pytest.mark.parametrize(
    "state",
    [state for state in IndexGenerationState if state is not IndexGenerationState.ACTIVE],
    ids=lambda state: state.value,
)
def test_non_active_index_generation_is_not_eligible_for_new_retrieval(
    state: IndexGenerationState,
) -> None:
    with pytest.raises(InvalidStateTransition):
        validate_retrieval_eligibility(
            _workspace(), _version(), _index_generation(state=state)
        )


def test_retrieval_eligibility_rejects_cross_workspace_version_first() -> None:
    with pytest.raises(WorkspaceScopeViolation):
        validate_retrieval_eligibility(
            _workspace(),
            _version(workspace_id=OTHER_WORKSPACE_ID, id=OTHER_VERSION_ID),
            _index_generation(document_version_id=OTHER_VERSION_ID),
        )


def test_retrieval_eligibility_rejects_cross_workspace_index() -> None:
    with pytest.raises(WorkspaceScopeViolation):
        validate_retrieval_eligibility(
            _workspace(),
            _version(),
            _index_generation(
                workspace_id=OTHER_WORKSPACE_ID,
                document_version_id=OTHER_VERSION_ID,
            ),
        )


def test_retrieval_eligibility_rejects_wrong_index_version_relationship() -> None:
    with pytest.raises(RelationshipMismatch):
        validate_retrieval_eligibility(
            _workspace(),
            _version(),
            _index_generation(document_version_id=OTHER_VERSION_ID),
        )
