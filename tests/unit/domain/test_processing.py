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
    DocumentId,
    DocumentVersionId,
    IndexGenerationId,
    LocalModelId,
    ProcessingJobId,
    WorkspaceId,
)
from lexlocal.domain.processing import (
    AttemptNumber,
    IndexGeneration,
    IndexGenerationState,
    ProcessingJob,
    ProcessingJobState,
)

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
DOCUMENT_ID = DocumentId("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
VERSION_ID = DocumentVersionId("01890f5e-7b9a-7cc0-98c8-5f89a9c83562")
OTHER_VERSION_ID = DocumentVersionId("01890f5e-7b9a-7cc0-98c8-5f89a9c83563")
JOB_ID = ProcessingJobId("9f1c42ab-31f4-4f64-9f42-b58d0a4e09e1")
OTHER_JOB_ID = ProcessingJobId("9f1c42ab-31f4-4f64-9f42-b58d0a4e09e2")
INDEX_GENERATION_ID = IndexGenerationId("a8ef08be-b21d-42c7-b9f1-c6bd32ecf875")
EMBEDDING_MODEL_ID = LocalModelId("c1c23b69-f208-48b1-b947-5964b36399e0")
ATTEMPT_ONE = AttemptNumber(1)
VERSION_ONE = VersionNumber(1)
CHUNKING_PROFILE_VERSION = "page-aware-v1"
NORMALIZATION_PROFILE_VERSION = "legal-text-v1"
EMBEDDING_DIMENSIONS = 1024

VALID_TRANSITIONS = (
    (ProcessingJobState.QUEUED, ProcessingJobState.PROCESSING),
    (ProcessingJobState.QUEUED, ProcessingJobState.CANCELLED),
    (ProcessingJobState.PROCESSING, ProcessingJobState.READY),
    (ProcessingJobState.PROCESSING, ProcessingJobState.READY_WITH_WARNINGS),
    (ProcessingJobState.PROCESSING, ProcessingJobState.FAILED),
    (ProcessingJobState.PROCESSING, ProcessingJobState.CANCELLED),
)
INVALID_TRANSITIONS = tuple(
    (current, target)
    for current in ProcessingJobState
    for target in ProcessingJobState
    if (current, target) not in VALID_TRANSITIONS
)
TERMINAL_STATES = (
    ProcessingJobState.READY,
    ProcessingJobState.READY_WITH_WARNINGS,
    ProcessingJobState.FAILED,
    ProcessingJobState.CANCELLED,
)

INDEX_GENERATION_VALID_TRANSITIONS = (
    (IndexGenerationState.STAGING, IndexGenerationState.ACTIVE),
    (IndexGenerationState.STAGING, IndexGenerationState.FAILED),
    (IndexGenerationState.ACTIVE, IndexGenerationState.ARCHIVED),
)
INDEX_GENERATION_INVALID_TRANSITIONS = tuple(
    (current, target)
    for current in IndexGenerationState
    for target in IndexGenerationState
    if (current, target) not in INDEX_GENERATION_VALID_TRANSITIONS
)


def _document_version(
    *,
    id: DocumentVersionId = VERSION_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    state: DocumentVersionState = DocumentVersionState.CANDIDATE_PROCESSING,
) -> DocumentVersion:
    return DocumentVersion(
        id=id,
        workspace_id=workspace_id,
        document_id=DOCUMENT_ID,
        version_number=VERSION_ONE,
        state=state,
    )


def _processing_job(
    *,
    id: ProcessingJobId = JOB_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    document_version_id: DocumentVersionId = VERSION_ID,
    attempt_number: AttemptNumber = ATTEMPT_ONE,
    state: ProcessingJobState = ProcessingJobState.QUEUED,
) -> ProcessingJob:
    return ProcessingJob(
        id=id,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        attempt_number=attempt_number,
        state=state,
    )


def _index_generation(
    *,
    id: IndexGenerationId = INDEX_GENERATION_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    document_version_id: DocumentVersionId = VERSION_ID,
    processing_job_id: ProcessingJobId = JOB_ID,
    embedding_model_id: LocalModelId = EMBEDDING_MODEL_ID,
    chunking_profile_version: str = CHUNKING_PROFILE_VERSION,
    normalization_profile_version: str = NORMALIZATION_PROFILE_VERSION,
    embedding_dimensions: int = EMBEDDING_DIMENSIONS,
    state: IndexGenerationState = IndexGenerationState.STAGING,
) -> IndexGeneration:
    return IndexGeneration(
        id=id,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        processing_job_id=processing_job_id,
        embedding_model_id=embedding_model_id,
        chunking_profile_version=chunking_profile_version,
        normalization_profile_version=normalization_profile_version,
        embedding_dimensions=embedding_dimensions,
        state=state,
    )


@pytest.mark.parametrize("value", [1, 2, 1_000_000])
def test_attempt_number_accepts_positive_integer(value: int) -> None:
    assert AttemptNumber(value).value == value


@pytest.mark.parametrize("value", [0, -1, -999, None, "1", 1.0, True, False])
def test_attempt_number_rejects_invalid_value(value: object) -> None:
    with pytest.raises(InvalidDomainValue):
        AttemptNumber(value)  # type: ignore[arg-type]


def test_attempt_number_is_immutable_hashable_value() -> None:
    first = AttemptNumber(2)
    second = AttemptNumber(2)

    assert first == second
    assert hash(first) == hash(second)
    with pytest.raises(FrozenInstanceError):
        first.value = 3


def test_attempt_number_has_no_allocation_api() -> None:
    for method_name in ("next", "increment", "allocate", "from_repository"):
        assert not hasattr(AttemptNumber, method_name)


def test_processing_job_state_contains_exact_persisted_states() -> None:
    assert {state.value for state in ProcessingJobState} == {
        "QUEUED",
        "PROCESSING",
        "READY",
        "READY_WITH_WARNINGS",
        "FAILED",
        "CANCELLED",
    }


def test_processing_job_defaults_to_queued_with_typed_context() -> None:
    job = ProcessingJob(
        id=JOB_ID,
        workspace_id=WORKSPACE_ID,
        document_version_id=VERSION_ID,
        attempt_number=ATTEMPT_ONE,
    )

    assert job.id == JOB_ID
    assert job.workspace_id == WORKSPACE_ID
    assert job.document_version_id == VERSION_ID
    assert job.attempt_number == ATTEMPT_ONE
    assert job.state is ProcessingJobState.QUEUED


@pytest.mark.parametrize("state", tuple(ProcessingJobState), ids=lambda state: state.value)
def test_processing_job_accepts_persisted_state(state: ProcessingJobState) -> None:
    assert _processing_job(state=state).state is state


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("id", str(JOB_ID)),
        ("id", VERSION_ID),
        ("workspace_id", str(WORKSPACE_ID)),
        ("workspace_id", VERSION_ID),
        ("document_version_id", str(VERSION_ID)),
        ("document_version_id", JOB_ID),
        ("attempt_number", 1),
        ("state", "QUEUED"),
    ],
)
def test_processing_job_rejects_invalid_construction_value(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "id": JOB_ID,
        "workspace_id": WORKSPACE_ID,
        "document_version_id": VERSION_ID,
        "attempt_number": ATTEMPT_ONE,
        "state": ProcessingJobState.QUEUED,
    }
    values[field_name] = invalid_value

    with pytest.raises(InvalidDomainValue):
        ProcessingJob(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    VALID_TRANSITIONS,
    ids=[f"{current.value}-to-{target.value}" for current, target in VALID_TRANSITIONS],
)
def test_processing_job_applies_valid_transition_without_mutating_original(
    current_state: ProcessingJobState,
    target_state: ProcessingJobState,
) -> None:
    job = _processing_job(state=current_state, attempt_number=AttemptNumber(7))

    transitioned = job.transition_to(target_state)

    assert transitioned.id == job.id
    assert transitioned.workspace_id == job.workspace_id
    assert transitioned.document_version_id == job.document_version_id
    assert transitioned.attempt_number == AttemptNumber(7)
    assert transitioned.state is target_state
    assert job.state is current_state
    assert transitioned is not job


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    INVALID_TRANSITIONS,
    ids=[f"{current.value}-to-{target.value}" for current, target in INVALID_TRANSITIONS],
)
def test_processing_job_rejects_unapproved_transition(
    current_state: ProcessingJobState,
    target_state: ProcessingJobState,
) -> None:
    job = _processing_job(state=current_state)

    with pytest.raises(InvalidStateTransition):
        job.transition_to(target_state)


@pytest.mark.parametrize("terminal_state", TERMINAL_STATES, ids=lambda state: state.value)
@pytest.mark.parametrize(
    "target_state",
    [ProcessingJobState.QUEUED, ProcessingJobState.PROCESSING],
    ids=lambda state: state.value,
)
def test_terminal_job_cannot_start_another_attempt(
    terminal_state: ProcessingJobState,
    target_state: ProcessingJobState,
) -> None:
    job = _processing_job(state=terminal_state)

    with pytest.raises(InvalidStateTransition):
        job.transition_to(target_state)


def test_attempt_number_is_preserved_through_job_lifecycle() -> None:
    queued = _processing_job(attempt_number=AttemptNumber(7))

    processing = queued.transition_to(ProcessingJobState.PROCESSING)
    failed = processing.transition_to(ProcessingJobState.FAILED)

    assert queued.attempt_number == AttemptNumber(7)
    assert processing.attempt_number == AttemptNumber(7)
    assert failed.attempt_number == AttemptNumber(7)


def test_processing_job_validates_matching_document_version() -> None:
    _processing_job().validate_document_version(_document_version())


def test_processing_job_rejects_cross_workspace_document_version() -> None:
    version = _document_version(workspace_id=OTHER_WORKSPACE_ID)

    with pytest.raises(WorkspaceScopeViolation):
        _processing_job().validate_document_version(version)


def test_processing_job_rejects_wrong_version_in_same_workspace() -> None:
    version = _document_version(id=OTHER_VERSION_ID)

    with pytest.raises(RelationshipMismatch):
        _processing_job().validate_document_version(version)


def test_workspace_violation_takes_precedence_over_version_mismatch() -> None:
    version = _document_version(id=OTHER_VERSION_ID, workspace_id=OTHER_WORKSPACE_ID)

    with pytest.raises(WorkspaceScopeViolation):
        _processing_job().validate_document_version(version)


def test_terminal_job_relationship_survives_document_version_lifecycle_change() -> None:
    job = _processing_job(state=ProcessingJobState.READY)
    version = _document_version(state=DocumentVersionState.ACTIVE)

    job.validate_document_version(version)


@pytest.mark.parametrize(
    "attribute_name",
    ["id", "workspace_id", "document_version_id", "attempt_number", "state"],
)
def test_processing_job_is_immutable(attribute_name: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(_processing_job(), attribute_name, None)


def test_processing_job_has_no_retry_or_generation_api() -> None:
    for method_name in ("retry", "reset", "requeue", "restart", "new", "create"):
        assert not hasattr(ProcessingJob, method_name)


def test_index_generation_state_contains_exact_persisted_states() -> None:
    assert {state.value for state in IndexGenerationState} == {
        "STAGING",
        "ACTIVE",
        "ARCHIVED",
        "FAILED",
    }


def test_index_generation_defaults_to_staging_with_reproducibility_metadata() -> None:
    generation = IndexGeneration(
        id=INDEX_GENERATION_ID,
        workspace_id=WORKSPACE_ID,
        document_version_id=VERSION_ID,
        processing_job_id=JOB_ID,
        embedding_model_id=EMBEDDING_MODEL_ID,
        chunking_profile_version=CHUNKING_PROFILE_VERSION,
        normalization_profile_version=NORMALIZATION_PROFILE_VERSION,
        embedding_dimensions=EMBEDDING_DIMENSIONS,
    )

    assert generation.id == INDEX_GENERATION_ID
    assert generation.workspace_id == WORKSPACE_ID
    assert generation.document_version_id == VERSION_ID
    assert generation.processing_job_id == JOB_ID
    assert generation.embedding_model_id == EMBEDDING_MODEL_ID
    assert generation.chunking_profile_version == CHUNKING_PROFILE_VERSION
    assert generation.normalization_profile_version == NORMALIZATION_PROFILE_VERSION
    assert generation.embedding_dimensions == EMBEDDING_DIMENSIONS
    assert generation.state is IndexGenerationState.STAGING


@pytest.mark.parametrize("state", tuple(IndexGenerationState), ids=lambda state: state.value)
def test_index_generation_accepts_persisted_state(state: IndexGenerationState) -> None:
    assert _index_generation(state=state).state is state


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("id", str(INDEX_GENERATION_ID)),
        ("id", JOB_ID),
        ("workspace_id", str(WORKSPACE_ID)),
        ("workspace_id", VERSION_ID),
        ("document_version_id", str(VERSION_ID)),
        ("document_version_id", JOB_ID),
        ("processing_job_id", str(JOB_ID)),
        ("processing_job_id", VERSION_ID),
        ("embedding_model_id", str(EMBEDDING_MODEL_ID)),
        ("embedding_model_id", JOB_ID),
        ("chunking_profile_version", ""),
        ("chunking_profile_version", "   "),
        ("chunking_profile_version", None),
        ("normalization_profile_version", ""),
        ("normalization_profile_version", "   "),
        ("normalization_profile_version", 1),
        ("embedding_dimensions", 0),
        ("embedding_dimensions", -1),
        ("embedding_dimensions", None),
        ("embedding_dimensions", "1024"),
        ("embedding_dimensions", 1024.0),
        ("embedding_dimensions", True),
        ("embedding_dimensions", False),
        ("state", "STAGING"),
    ],
)
def test_index_generation_rejects_invalid_construction_value(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "id": INDEX_GENERATION_ID,
        "workspace_id": WORKSPACE_ID,
        "document_version_id": VERSION_ID,
        "processing_job_id": JOB_ID,
        "embedding_model_id": EMBEDDING_MODEL_ID,
        "chunking_profile_version": CHUNKING_PROFILE_VERSION,
        "normalization_profile_version": NORMALIZATION_PROFILE_VERSION,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "state": IndexGenerationState.STAGING,
    }
    values[field_name] = invalid_value

    with pytest.raises(InvalidDomainValue):
        IndexGeneration(**values)  # type: ignore[arg-type]


def test_index_generation_preserves_valid_profile_text_without_trimming() -> None:
    generation = _index_generation(
        chunking_profile_version="  chunks-v2  ",
        normalization_profile_version="  normalization-v3  ",
    )

    assert generation.chunking_profile_version == "  chunks-v2  "
    assert generation.normalization_profile_version == "  normalization-v3  "


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    INDEX_GENERATION_VALID_TRANSITIONS,
    ids=[
        f"{current.value}-to-{target.value}"
        for current, target in INDEX_GENERATION_VALID_TRANSITIONS
    ],
)
def test_index_generation_applies_valid_transition_without_mutating_original(
    current_state: IndexGenerationState,
    target_state: IndexGenerationState,
) -> None:
    generation = _index_generation(state=current_state)

    if target_state is IndexGenerationState.ACTIVE:
        transitioned = generation.activate(
            _processing_job(state=ProcessingJobState.READY)
        )
    else:
        transitioned = generation.transition_to(target_state)

    assert transitioned.id == generation.id
    assert transitioned.workspace_id == generation.workspace_id
    assert transitioned.document_version_id == generation.document_version_id
    assert transitioned.processing_job_id == generation.processing_job_id
    assert transitioned.embedding_model_id == generation.embedding_model_id
    assert transitioned.chunking_profile_version == generation.chunking_profile_version
    assert (
        transitioned.normalization_profile_version
        == generation.normalization_profile_version
    )
    assert transitioned.embedding_dimensions == generation.embedding_dimensions
    assert transitioned.state is target_state
    assert generation.state is current_state
    assert transitioned is not generation


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    INDEX_GENERATION_INVALID_TRANSITIONS,
    ids=[
        f"{current.value}-to-{target.value}"
        for current, target in INDEX_GENERATION_INVALID_TRANSITIONS
    ],
)
def test_index_generation_rejects_unapproved_transition(
    current_state: IndexGenerationState,
    target_state: IndexGenerationState,
) -> None:
    generation = _index_generation(state=current_state)

    with pytest.raises(InvalidStateTransition):
        if target_state is IndexGenerationState.ACTIVE:
            generation.activate(_processing_job(state=ProcessingJobState.READY))
        else:
            generation.transition_to(target_state)

    assert generation.state is current_state


@pytest.mark.parametrize("target_state", tuple(IndexGenerationState))
def test_failed_index_generation_has_no_outgoing_transition(
    target_state: IndexGenerationState,
) -> None:
    generation = _index_generation(state=IndexGenerationState.FAILED)

    with pytest.raises(InvalidStateTransition):
        if target_state is IndexGenerationState.ACTIVE:
            generation.activate(_processing_job(state=ProcessingJobState.READY))
        else:
            generation.transition_to(target_state)


@pytest.mark.parametrize("target_state", tuple(IndexGenerationState))
def test_archived_index_generation_has_no_outgoing_transition(
    target_state: IndexGenerationState,
) -> None:
    generation = _index_generation(state=IndexGenerationState.ARCHIVED)

    with pytest.raises(InvalidStateTransition):
        if target_state is IndexGenerationState.ACTIVE:
            generation.activate(_processing_job(state=ProcessingJobState.READY))
        else:
            generation.transition_to(target_state)


def test_index_generation_validates_matching_document_version() -> None:
    _index_generation().validate_document_version(_document_version())


def test_index_generation_rejects_cross_workspace_document_version() -> None:
    with pytest.raises(WorkspaceScopeViolation):
        _index_generation().validate_document_version(
            _document_version(workspace_id=OTHER_WORKSPACE_ID)
        )

def test_index_generation_workspace_violation_takes_precedence_over_version_mismatch() -> None:
    version = _document_version(
        id=OTHER_VERSION_ID,
        workspace_id=OTHER_WORKSPACE_ID,
    )

    with pytest.raises(WorkspaceScopeViolation):
        _index_generation().validate_document_version(version)

def test_index_generation_rejects_wrong_document_version_in_same_workspace() -> None:
    with pytest.raises(RelationshipMismatch):
        _index_generation().validate_document_version(
            _document_version(id=OTHER_VERSION_ID)
        )


def test_index_generation_validates_matching_processing_job() -> None:
    _index_generation().validate_processing_job(_processing_job())


def test_index_generation_rejects_cross_workspace_processing_job_first() -> None:
    job = _processing_job(
        id=OTHER_JOB_ID,
        workspace_id=OTHER_WORKSPACE_ID,
        document_version_id=OTHER_VERSION_ID,
    )

    with pytest.raises(WorkspaceScopeViolation):
        _index_generation().validate_processing_job(job)


def test_index_generation_rejects_wrong_processing_job_in_same_workspace() -> None:
    with pytest.raises(RelationshipMismatch):
        _index_generation().validate_processing_job(_processing_job(id=OTHER_JOB_ID))


def test_index_generation_rejects_job_targeting_wrong_document_version() -> None:
    with pytest.raises(RelationshipMismatch):
        _index_generation().validate_processing_job(
            _processing_job(document_version_id=OTHER_VERSION_ID)
        )


@pytest.mark.parametrize(
    "job_state",
    [ProcessingJobState.READY, ProcessingJobState.READY_WITH_WARNINGS],
    ids=lambda state: state.value,
)
def test_index_generation_activation_accepts_successful_matching_job(
    job_state: ProcessingJobState,
) -> None:
    generation = _index_generation()

    active = generation.activate(_processing_job(state=job_state))

    assert active.state is IndexGenerationState.ACTIVE
    assert generation.state is IndexGenerationState.STAGING


@pytest.mark.parametrize(
    "job_state",
    [
        ProcessingJobState.QUEUED,
        ProcessingJobState.PROCESSING,
        ProcessingJobState.FAILED,
        ProcessingJobState.CANCELLED,
    ],
    ids=lambda state: state.value,
)
def test_index_generation_activation_rejects_ineligible_matching_job(
    job_state: ProcessingJobState,
) -> None:
    generation = _index_generation()

    with pytest.raises(InvalidStateTransition):
        generation.activate(_processing_job(state=job_state))

    assert generation.state is IndexGenerationState.STAGING


def test_index_generation_activation_preserves_workspace_error_semantics() -> None:
    job = _processing_job(
        id=OTHER_JOB_ID,
        workspace_id=OTHER_WORKSPACE_ID,
        document_version_id=OTHER_VERSION_ID,
        state=ProcessingJobState.FAILED,
    )

    with pytest.raises(WorkspaceScopeViolation):
        _index_generation().activate(job)


def test_index_generation_activation_preserves_relationship_error_semantics() -> None:
    with pytest.raises(RelationshipMismatch):
        _index_generation().activate(
            _processing_job(id=OTHER_JOB_ID, state=ProcessingJobState.FAILED)
        )


def test_index_generation_has_no_unchecked_transition_to_active() -> None:
    with pytest.raises(InvalidStateTransition):
        _index_generation().transition_to(IndexGenerationState.ACTIVE)


@pytest.mark.parametrize(
    "attribute_name",
    [
        "id",
        "workspace_id",
        "document_version_id",
        "processing_job_id",
        "embedding_model_id",
        "chunking_profile_version",
        "normalization_profile_version",
        "embedding_dimensions",
        "state",
    ],
)
def test_index_generation_is_immutable(attribute_name: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(_index_generation(), attribute_name, None)


def test_index_generation_has_no_generation_or_rebuild_api() -> None:
    for method_name in ("retry", "reset", "restart", "rebuild", "new", "create"):
        assert not hasattr(IndexGeneration, method_name)
