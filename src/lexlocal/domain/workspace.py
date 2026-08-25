from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from .errors import InvalidDomainValue, InvalidStateTransition
from .identifiers import WorkspaceId


class WorkspaceState(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETING = "DELETING"
    DELETION_RECOVERY = "DELETION_RECOVERY"


_ALLOWED_TRANSITIONS: dict[WorkspaceState, frozenset[WorkspaceState]] = {
    WorkspaceState.ACTIVE: frozenset(
        {WorkspaceState.ARCHIVED, WorkspaceState.DELETING}
    ),
    WorkspaceState.ARCHIVED: frozenset(
        {WorkspaceState.ACTIVE, WorkspaceState.DELETING}
    ),
    WorkspaceState.DELETING: frozenset({WorkspaceState.DELETION_RECOVERY}),
    WorkspaceState.DELETION_RECOVERY: frozenset({WorkspaceState.DELETING}),
}


@dataclass(frozen=True, slots=True)
class Workspace:
    id: WorkspaceId
    display_name: str = field(repr=False)
    state: WorkspaceState = WorkspaceState.ACTIVE

    def __post_init__(self) -> None:
        if not isinstance(self.id, WorkspaceId):
            raise InvalidDomainValue("workspace id must be a WorkspaceId")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise InvalidDomainValue("workspace display name must not be empty")
        if not isinstance(self.state, WorkspaceState):
            raise InvalidDomainValue("workspace state must be a WorkspaceState")

    @property
    def allows_normal_read(self) -> bool:
        return self.state in {WorkspaceState.ACTIVE, WorkspaceState.ARCHIVED}

    @property
    def allows_normal_mutation(self) -> bool:
        return self.state is WorkspaceState.ACTIVE

    @property
    def allows_new_processing(self) -> bool:
        return self.state is WorkspaceState.ACTIVE

    def transition_to(self, target_state: WorkspaceState) -> Workspace:
        if target_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"workspace cannot transition from {self.state} to {target_state}"
            )
        return replace(self, state=target_state)
