from uuid import UUID

from .errors import InvalidDomainValue


class _UuidIdentifier:
    __slots__ = ("_value",)
    _value: str

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise InvalidDomainValue(f"{type(self).__name__} must be a valid UUID")

        try:
            canonical_value = str(UUID(value))
        except ValueError as error:
            raise InvalidDomainValue(
                f"{type(self).__name__} must be a valid UUID"
            ) from error

        object.__setattr__(self, "_value", canonical_value)

    @property
    def value(self) -> str:
        return self._value

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _UuidIdentifier) or type(self) is not type(other):
            return False
        return self.value == other.value

    def __hash__(self) -> int:
        return hash((type(self), self.value))

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"{type(self).__name__}(value={self.value!r})"


class WorkspaceId(_UuidIdentifier):
    __slots__ = ()


class DocumentId(_UuidIdentifier):
    __slots__ = ()


class DocumentVersionId(_UuidIdentifier):
    __slots__ = ()


class ProcessingJobId(_UuidIdentifier):
    __slots__ = ()


class IndexGenerationId(_UuidIdentifier):
    __slots__ = ()


class DocumentPageId(_UuidIdentifier):
    __slots__ = ()


class SourceLocatorId(_UuidIdentifier):
    __slots__ = ()


class ChunkId(_UuidIdentifier):
    __slots__ = ()


class LocalModelId(_UuidIdentifier):
    __slots__ = ()


class RetrievalRunId(_UuidIdentifier):
    __slots__ = ()


class EvidenceItemId(_UuidIdentifier):
    __slots__ = ()
