from dataclasses import FrozenInstanceError

import pytest

from lexlocal.domain.documents import (
    DocumentVersion,
    DocumentVersionState,
    LogicalDocument,
    LogicalDocumentState,
    VersionNumber,
)
from lexlocal.domain.errors import (
    InvalidDomainValue,
    InvalidStateTransition,
    RelationshipMismatch,
    WorkspaceScopeViolation,
)
from lexlocal.domain.identifiers import DocumentId, DocumentVersionId, WorkspaceId

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
OTHER_WORKSPACE_ID = WorkspaceId("123e4567-e89b-12d3-a456-426614174000")
DOCUMENT_ID = DocumentId("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
OTHER_DOCUMENT_ID = DocumentId("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
VERSION_ID = DocumentVersionId("01890f5e-7b9a-7cc0-98c8-5f89a9c83562")
VERSION_NUMBER_ONE = VersionNumber(1)

LOGICAL_DOCUMENT_VALID_TRANSITIONS = (
    (LogicalDocumentState.ACTIVE, LogicalDocumentState.DELETED),
)
LOGICAL_DOCUMENT_INVALID_TRANSITIONS = tuple(
    (current, target)
    for current in LogicalDocumentState
    for target in LogicalDocumentState
    if (current, target) not in LOGICAL_DOCUMENT_VALID_TRANSITIONS
)

DOCUMENT_VERSION_VALID_TRANSITIONS = (
    (DocumentVersionState.CANDIDATE_PROCESSING, DocumentVersionState.CANDIDATE_READY),
    (DocumentVersionState.CANDIDATE_PROCESSING, DocumentVersionState.CANDIDATE_WARNING),
    (DocumentVersionState.CANDIDATE_PROCESSING, DocumentVersionState.CANDIDATE_FAILED),
    (DocumentVersionState.CANDIDATE_PROCESSING, DocumentVersionState.CANDIDATE_CANCELLED),
    (DocumentVersionState.CANDIDATE_READY, DocumentVersionState.ACTIVE),
    (DocumentVersionState.CANDIDATE_WARNING, DocumentVersionState.ACTIVE),
    (DocumentVersionState.ACTIVE, DocumentVersionState.ARCHIVED),
    (DocumentVersionState.ACTIVE, DocumentVersionState.DELETED),
    (DocumentVersionState.ARCHIVED, DocumentVersionState.DELETED),
)
DOCUMENT_VERSION_INVALID_TRANSITIONS = tuple(
    (current, target)
    for current in DocumentVersionState
    for target in DocumentVersionState
    if (current, target) not in DOCUMENT_VERSION_VALID_TRANSITIONS
)


def _logical_document(
    *,
    id: DocumentId = DOCUMENT_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    state: LogicalDocumentState = LogicalDocumentState.ACTIVE,
) -> LogicalDocument:
    return LogicalDocument(id=id, workspace_id=workspace_id, state=state)


def _document_version(
    *,
    id: DocumentVersionId = VERSION_ID,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    document_id: DocumentId = DOCUMENT_ID,
    version_number: VersionNumber = VERSION_NUMBER_ONE,
    state: DocumentVersionState = DocumentVersionState.CANDIDATE_PROCESSING,
) -> DocumentVersion:
    return DocumentVersion(
        id=id,
        workspace_id=workspace_id,
        document_id=document_id,
        version_number=version_number,
        state=state,
    )


@pytest.mark.parametrize("value", [1, 2, 1_000_000])
def test_version_number_accepts_positive_integer(value: int) -> None:
    assert VersionNumber(value).value == value


@pytest.mark.parametrize("value", [0, -1, -999, None, "1", 1.0, True, False])
def test_version_number_rejects_invalid_value(value: object) -> None:
    with pytest.raises(InvalidDomainValue):
        VersionNumber(value)  # type: ignore[arg-type]


def test_version_number_is_immutable_hashable_value() -> None:
    first = VersionNumber(2)
    second = VersionNumber(2)

    assert first == second
    assert hash(first) == hash(second)
    with pytest.raises(FrozenInstanceError):
        first.value = 3


def test_logical_document_state_contains_exact_persisted_states() -> None:
    assert {state.value for state in LogicalDocumentState} == {"ACTIVE", "DELETED"}


def test_logical_document_defaults_to_active_with_typed_identity() -> None:
    document = LogicalDocument(id=DOCUMENT_ID, workspace_id=WORKSPACE_ID)

    assert document.id == DOCUMENT_ID
    assert document.workspace_id == WORKSPACE_ID
    assert document.state is LogicalDocumentState.ACTIVE


def test_logical_document_accepts_deleted_tombstone_for_rehydration() -> None:
    assert _logical_document(state=LogicalDocumentState.DELETED).state is LogicalDocumentState.DELETED


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("id", str(DOCUMENT_ID)),
        ("id", WORKSPACE_ID),
        ("workspace_id", str(WORKSPACE_ID)),
        ("workspace_id", DOCUMENT_ID),
        ("state", "ACTIVE"),
    ],
)
def test_logical_document_rejects_invalid_construction_value(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "id": DOCUMENT_ID,
        "workspace_id": WORKSPACE_ID,
        "state": LogicalDocumentState.ACTIVE,
    }
    values[field_name] = invalid_value

    with pytest.raises(InvalidDomainValue):
        LogicalDocument(**values)  # type: ignore[arg-type]


def test_logical_document_deletion_returns_new_tombstone() -> None:
    document = _logical_document()

    deleted = document.transition_to(LogicalDocumentState.DELETED)

    assert deleted.id == document.id
    assert deleted.workspace_id == document.workspace_id
    assert deleted.state is LogicalDocumentState.DELETED
    assert document.state is LogicalDocumentState.ACTIVE
    assert deleted is not document


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    LOGICAL_DOCUMENT_INVALID_TRANSITIONS,
    ids=lambda value: value.value,
)
def test_logical_document_rejects_unapproved_transition(
    current_state: LogicalDocumentState,
    target_state: LogicalDocumentState,
) -> None:
    document = _logical_document(state=current_state)

    with pytest.raises(InvalidStateTransition):
        document.transition_to(target_state)


def test_deleted_logical_document_cannot_reopen() -> None:
    document = _logical_document(state=LogicalDocumentState.DELETED)

    with pytest.raises(InvalidStateTransition):
        document.transition_to(LogicalDocumentState.ACTIVE)


@pytest.mark.parametrize(
    ("state", "allows_mutation"),
    [(LogicalDocumentState.ACTIVE, True), (LogicalDocumentState.DELETED, False)],
)
def test_logical_document_mutation_capability(
    state: LogicalDocumentState,
    allows_mutation: bool,
) -> None:
    assert _logical_document(state=state).allows_mutation is allows_mutation


def test_document_version_state_contains_exact_persisted_states() -> None:
    assert {state.value for state in DocumentVersionState} == {
        "CANDIDATE_PROCESSING",
        "CANDIDATE_READY",
        "CANDIDATE_WARNING",
        "CANDIDATE_FAILED",
        "CANDIDATE_CANCELLED",
        "ACTIVE",
        "ARCHIVED",
        "DELETED",
    }


def test_document_version_defaults_to_candidate_processing() -> None:
    version = DocumentVersion(
        id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_ID,
        version_number=VersionNumber(1),
    )

    assert version.state is DocumentVersionState.CANDIDATE_PROCESSING


@pytest.mark.parametrize("state", tuple(DocumentVersionState), ids=lambda state: state.value)
def test_document_version_accepts_persisted_state(state: DocumentVersionState) -> None:
    assert _document_version(state=state).state is state


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("id", str(VERSION_ID)),
        ("id", DOCUMENT_ID),
        ("workspace_id", str(WORKSPACE_ID)),
        ("workspace_id", DOCUMENT_ID),
        ("document_id", str(DOCUMENT_ID)),
        ("document_id", WORKSPACE_ID),
        ("version_number", 1),
        ("state", "CANDIDATE_PROCESSING"),
    ],
)
def test_document_version_rejects_invalid_construction_value(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "id": VERSION_ID,
        "workspace_id": WORKSPACE_ID,
        "document_id": DOCUMENT_ID,
        "version_number": VersionNumber(1),
        "state": DocumentVersionState.CANDIDATE_PROCESSING,
    }
    values[field_name] = invalid_value

    with pytest.raises(InvalidDomainValue):
        DocumentVersion(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    DOCUMENT_VERSION_VALID_TRANSITIONS,
    ids=[f"{current.value}-to-{target.value}" for current, target in DOCUMENT_VERSION_VALID_TRANSITIONS],
)
def test_document_version_applies_valid_transition_without_mutating_original(
    current_state: DocumentVersionState,
    target_state: DocumentVersionState,
) -> None:
    version = _document_version(state=current_state, version_number=VersionNumber(7))

    transitioned = version.transition_to(target_state)

    assert transitioned.id == version.id
    assert transitioned.workspace_id == version.workspace_id
    assert transitioned.document_id == version.document_id
    assert transitioned.version_number == version.version_number
    assert transitioned.state is target_state
    assert version.state is current_state
    assert transitioned is not version


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    DOCUMENT_VERSION_INVALID_TRANSITIONS,
    ids=[
        f"{current.value}-to-{target.value}"
        for current, target in DOCUMENT_VERSION_INVALID_TRANSITIONS
    ],
)
def test_document_version_rejects_unapproved_transition(
    current_state: DocumentVersionState,
    target_state: DocumentVersionState,
) -> None:
    version = _document_version(state=current_state)

    with pytest.raises(InvalidStateTransition):
        version.transition_to(target_state)


@pytest.mark.parametrize("target_state", tuple(DocumentVersionState), ids=lambda state: state.value)
def test_deleted_document_version_is_terminal(target_state: DocumentVersionState) -> None:
    version = _document_version(state=DocumentVersionState.DELETED)

    with pytest.raises(InvalidStateTransition):
        version.transition_to(target_state)


@pytest.mark.parametrize(
    "candidate_state",
    [DocumentVersionState.CANDIDATE_FAILED, DocumentVersionState.CANDIDATE_CANCELLED],
)
def test_failed_or_cancelled_candidate_cannot_activate(
    candidate_state: DocumentVersionState,
) -> None:
    version = _document_version(state=candidate_state)

    with pytest.raises(InvalidStateTransition):
        version.transition_to(DocumentVersionState.ACTIVE)


def test_document_version_validates_matching_logical_document() -> None:
    _document_version().validate_document(_logical_document())


def test_document_version_rejects_cross_workspace_document() -> None:
    version = _document_version()
    document = _logical_document(workspace_id=OTHER_WORKSPACE_ID)

    with pytest.raises(WorkspaceScopeViolation):
        version.validate_document(document)

def test_workspace_violation_takes_precedence_over_document_mismatch() -> None:
    version = _document_version()

    document = _logical_document(
        id=OTHER_DOCUMENT_ID,
        workspace_id=OTHER_WORKSPACE_ID,
    )

    with pytest.raises(WorkspaceScopeViolation):
        version.validate_document(document)

def test_document_version_rejects_wrong_document_in_same_workspace() -> None:
    version = _document_version(document_id=OTHER_DOCUMENT_ID)

    with pytest.raises(RelationshipMismatch):
        version.validate_document(_logical_document())


def test_document_version_relationship_accepts_deleted_document_tombstone() -> None:
    version = _document_version(state=DocumentVersionState.DELETED)
    document = _logical_document(state=LogicalDocumentState.DELETED)

    version.validate_document(document)


@pytest.mark.parametrize(
    ("entity", "attribute_name"),
    [
        (_logical_document(), "id"),
        (_logical_document(), "workspace_id"),
        (_logical_document(), "state"),
        (_document_version(), "id"),
        (_document_version(), "workspace_id"),
        (_document_version(), "document_id"),
        (_document_version(), "version_number"),
        (_document_version(), "state"),
    ],
)
def test_document_entities_are_immutable(entity: object, attribute_name: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(entity, attribute_name, None)


def test_document_models_do_not_generate_ids_or_version_numbers() -> None:
    for entity_type in (LogicalDocument, DocumentVersion):
        assert not hasattr(entity_type, "new")
        assert not hasattr(entity_type, "create")
