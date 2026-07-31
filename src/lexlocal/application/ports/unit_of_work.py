"""Define the Unit of Work contract used by application services."""

from types import TracebackType
from typing import Protocol, Self


class UnitOfWork(Protocol):
    """Manage one atomic application-level database operation."""

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
