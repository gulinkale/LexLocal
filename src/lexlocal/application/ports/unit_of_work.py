"""Define the Unit of Work contract used by application services."""

from types import TracebackType
from typing import Protocol, Self

from .workspaces import WorkspaceRepository


class UnitOfWork(Protocol):
    """Manage one atomic application-level database operation."""

    @property
    def workspaces(self) -> WorkspaceRepository:
        """Return the workspace repository bound to the active transaction."""

        ...

    def __enter__(self) -> Self:
        """Start the unit-of-work scope."""

        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Finish the scope and release its resources."""

        ...

    def commit(self) -> None:
        """Make all changes in the current scope permanent."""

        ...

    def rollback(self) -> None:
        """Discard all changes in the current scope."""

        ...
