class DomainError(Exception):
    """Base exception for LexLocal domain rule violations."""


class InvalidDomainValue(DomainError):
    """Raised when a domain value cannot be constructed."""


class InvalidStateTransition(DomainError):
    """Raised when a requested domain state transition is not allowed."""


class WorkspaceScopeViolation(DomainError):
    """Raised when an operation crosses a workspace boundary."""


class RelationshipMismatch(DomainError):
    """Raised when domain objects do not satisfy their required relationship."""
