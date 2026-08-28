from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from lexlocal.domain.errors import InvalidDomainValue, InvalidStateTransition
from lexlocal.domain.identifiers import DocumentId, WorkspaceId
from lexlocal.domain.workspace import Workspace, WorkspaceProfile, WorkspaceState

WORKSPACE_ID = WorkspaceId("550e8400-e29b-41d4-a716-446655440000")
DISPLAY_NAME = "Matter Workspace"
CREATED_AT = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)
UPDATED_AT = datetime(2026, 8, 28, 10, 45, tzinfo=UTC)

VALID_TRANSITIONS = (
    (WorkspaceState.ACTIVE, WorkspaceState.ARCHIVED),
    (WorkspaceState.ACTIVE, WorkspaceState.DELETING),
    (WorkspaceState.ARCHIVED, WorkspaceState.ACTIVE),
    (WorkspaceState.ARCHIVED, WorkspaceState.DELETING),
    (WorkspaceState.DELETING, WorkspaceState.DELETION_RECOVERY),
    (WorkspaceState.DELETION_RECOVERY, WorkspaceState.DELETING),
)
VALID_TRANSITION_IDS = tuple(
    f"{current.value}-to-{target.value}" for current, target in VALID_TRANSITIONS
)
INVALID_TRANSITIONS = tuple(
    (current, target)
    for current in WorkspaceState
    for target in WorkspaceState
    if (current, target) not in VALID_TRANSITIONS
)
INVALID_TRANSITION_IDS = tuple(
    f"{current.value}-to-{target.value}" for current, target in INVALID_TRANSITIONS
)


def make_workspace(
    *,
    workspace_id: WorkspaceId = WORKSPACE_ID,
    display_name: str = DISPLAY_NAME,
    profile: WorkspaceProfile | None = None,
    state: WorkspaceState = WorkspaceState.ACTIVE,
    created_at: datetime = CREATED_AT,
    updated_at: datetime = UPDATED_AT,
) -> Workspace:
    return Workspace(
        id=workspace_id,
        display_name=display_name,
        created_at=created_at,
        updated_at=updated_at,
        profile=profile,
        state=state,
    )


def test_workspace_state_contains_exact_persisted_states() -> None:
    assert {state.value for state in WorkspaceState} == {
        "ACTIVE",
        "ARCHIVED",
        "DELETING",
        "DELETION_RECOVERY",
    }
    assert "DELETED" not in {state.name for state in WorkspaceState}


def test_workspace_defaults_to_active() -> None:
    workspace = make_workspace()

    assert workspace.id == WORKSPACE_ID
    assert workspace.display_name == DISPLAY_NAME
    assert workspace.profile is None
    assert workspace.created_at == CREATED_AT
    assert workspace.updated_at == UPDATED_AT
    assert workspace.state is WorkspaceState.ACTIVE


def test_workspace_profile_contains_exact_persisted_values() -> None:
    assert {profile.value for profile in WorkspaceProfile} == {
        "LITIGATION",
        "CONTRACT_REVIEW",
        "GENERAL_LEGAL",
    }


@pytest.mark.parametrize("profile", tuple(WorkspaceProfile), ids=lambda value: value.value)
def test_workspace_accepts_approved_profile(profile: WorkspaceProfile) -> None:
    assert make_workspace(profile=profile).profile is profile


@pytest.mark.parametrize("state", tuple(WorkspaceState), ids=lambda state: state.value)
def test_workspace_accepts_explicit_persisted_state(state: WorkspaceState) -> None:
    workspace = make_workspace(state=state)

    assert workspace.state is state


@pytest.mark.parametrize("display_name", ["", "   "])
def test_workspace_rejects_empty_semantic_display_name(display_name: str) -> None:
    with pytest.raises(InvalidDomainValue):
        make_workspace(display_name=display_name)


@pytest.mark.parametrize("invalid_name", [None, 123])
def test_workspace_rejects_non_string_display_name(invalid_name: object) -> None:
    with pytest.raises(InvalidDomainValue):
        make_workspace(display_name=invalid_name)  # type: ignore[arg-type]


def test_workspace_preserves_valid_display_text() -> None:
    display_name = "  Özel Çalışma Alanı  "

    assert make_workspace(display_name=display_name).display_name == display_name


@pytest.mark.parametrize("invalid_id", [str(WORKSPACE_ID), DocumentId(str(WORKSPACE_ID))])
def test_workspace_rejects_non_workspace_identifier(invalid_id: object) -> None:
    with pytest.raises(InvalidDomainValue):
        make_workspace(workspace_id=invalid_id)  # type: ignore[arg-type]


def test_workspace_rejects_non_profile_value() -> None:
    with pytest.raises(InvalidDomainValue):
        make_workspace(profile="LITIGATION")  # type: ignore[arg-type]


def test_workspace_rejects_non_workspace_state() -> None:
    with pytest.raises(InvalidDomainValue):
        make_workspace(state="ACTIVE")  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["created_at", "updated_at"])
@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        datetime(2026, 8, 28, 9, 30),
        datetime(2026, 8, 28, 12, 30, tzinfo=timezone(timedelta(hours=3))),
        "2026-08-28T09:30:00Z",
    ],
)
def test_workspace_rejects_timestamp_that_is_not_aware_utc(
    field_name: str,
    invalid_timestamp: object,
) -> None:
    values = {field_name: invalid_timestamp}

    with pytest.raises(InvalidDomainValue):
        make_workspace(**values)  # type: ignore[arg-type]


def test_workspace_rejects_updated_at_before_created_at() -> None:
    with pytest.raises(InvalidDomainValue):
        make_workspace(created_at=UPDATED_AT, updated_at=CREATED_AT)


def test_workspace_accepts_equal_creation_and_update_timestamps() -> None:
    workspace = make_workspace(updated_at=CREATED_AT)

    assert workspace.created_at == workspace.updated_at


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    VALID_TRANSITIONS,
    ids=VALID_TRANSITION_IDS,
)
def test_workspace_applies_valid_transition_without_mutating_original(
    current_state: WorkspaceState,
    target_state: WorkspaceState,
) -> None:
    workspace = make_workspace(state=current_state)

    transitioned = workspace.transition_to(target_state)

    assert transitioned.state is target_state
    assert transitioned.id == workspace.id
    assert transitioned.display_name == workspace.display_name
    assert transitioned.profile == workspace.profile
    assert transitioned.created_at == workspace.created_at
    assert transitioned.updated_at == workspace.updated_at
    assert workspace.state is current_state
    assert transitioned is not workspace


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    INVALID_TRANSITIONS,
    ids=INVALID_TRANSITION_IDS,
)
def test_workspace_rejects_unapproved_transition(
    current_state: WorkspaceState,
    target_state: WorkspaceState,
) -> None:
    workspace = make_workspace(state=current_state)

    with pytest.raises(InvalidStateTransition):
        workspace.transition_to(target_state)

    assert workspace.state is current_state


@pytest.mark.parametrize(
    ("deletion_state", "normal_state"),
    [
        (WorkspaceState.DELETING, WorkspaceState.ACTIVE),
        (WorkspaceState.DELETING, WorkspaceState.ARCHIVED),
        (WorkspaceState.DELETION_RECOVERY, WorkspaceState.ACTIVE),
        (WorkspaceState.DELETION_RECOVERY, WorkspaceState.ARCHIVED),
    ],
)
def test_deletion_state_cannot_reopen_as_normal_workspace(
    deletion_state: WorkspaceState,
    normal_state: WorkspaceState,
) -> None:
    workspace = make_workspace(state=deletion_state)

    with pytest.raises(InvalidStateTransition):
        workspace.transition_to(normal_state)


@pytest.mark.parametrize(
    ("state", "allows_read", "allows_mutation", "allows_processing"),
    [
        (WorkspaceState.ACTIVE, True, True, True),
        (WorkspaceState.ARCHIVED, True, False, False),
        (WorkspaceState.DELETING, False, False, False),
        (WorkspaceState.DELETION_RECOVERY, False, False, False),
    ],
    ids=lambda value: value.value if isinstance(value, WorkspaceState) else None,
)
def test_workspace_capability_matrix(
    state: WorkspaceState,
    allows_read: bool,
    allows_mutation: bool,
    allows_processing: bool,
) -> None:
    workspace = make_workspace(state=state)

    assert workspace.allows_normal_read is allows_read
    assert workspace.allows_normal_mutation is allows_mutation
    assert workspace.allows_new_processing is allows_processing


@pytest.mark.parametrize(
    "attribute_name",
    ["id", "display_name", "profile", "state", "created_at", "updated_at"],
)
def test_workspace_is_immutable(attribute_name: str) -> None:
    workspace = make_workspace()

    with pytest.raises(FrozenInstanceError):
        setattr(workspace, attribute_name, None)


def test_workspace_repr_does_not_expose_sensitive_display_name() -> None:
    sensitive_name = "Highly Sensitive Matter Name"
    workspace = make_workspace(display_name=sensitive_name)

    assert sensitive_name not in repr(workspace)
    assert str(WORKSPACE_ID) in repr(workspace)
    assert WorkspaceState.ACTIVE.value in repr(workspace)


def test_workspace_has_no_identifier_generation_api() -> None:
    assert not hasattr(Workspace, "new")
    assert not hasattr(Workspace, "create")
