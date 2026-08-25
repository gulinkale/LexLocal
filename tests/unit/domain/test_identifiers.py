from uuid import UUID

import pytest

from lexlocal.domain.errors import InvalidDomainValue
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

IDENTIFIER_TYPES = (
    WorkspaceId,
    DocumentId,
    DocumentVersionId,
    ProcessingJobId,
    IndexGenerationId,
    DocumentPageId,
    SourceLocatorId,
    ChunkId,
    LocalModelId,
    RetrievalRunId,
    EvidenceItemId,
)
IDENTIFIER_TYPE_IDS = tuple(identifier_type.__name__ for identifier_type in IDENTIFIER_TYPES)

UUID_TEXT = "550e8400-e29b-41d4-a716-446655440000"
OTHER_UUID_TEXT = "123e4567-e89b-12d3-a456-426614174000"


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
def test_identifier_accepts_valid_uuid_string(identifier_type: type) -> None:
    identifier = identifier_type(UUID_TEXT)

    assert identifier.value == UUID_TEXT
    assert str(identifier) == UUID_TEXT


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
def test_identifier_rejects_empty_value(identifier_type: type) -> None:
    with pytest.raises(InvalidDomainValue):
        identifier_type("")


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
@pytest.mark.parametrize("malformed_value", ["not-a-uuid", "550e8400-e29b-41d4"])
def test_identifier_rejects_malformed_uuid(
    identifier_type: type,
    malformed_value: str,
) -> None:
    with pytest.raises(InvalidDomainValue):
        identifier_type(malformed_value)


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
@pytest.mark.parametrize("invalid_value", [None, 123, UUID(UUID_TEXT)])
def test_identifier_rejects_non_string_value(
    identifier_type: type,
    invalid_value: object,
) -> None:
    with pytest.raises(InvalidDomainValue):
        identifier_type(invalid_value)


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
@pytest.mark.parametrize(
    "alternate_text",
    [
        "550E8400-E29B-41D4-A716-446655440000",
        "550E8400E29B41D4A716446655440000",
    ],
)
def test_identifier_normalizes_valid_uuid_text(
    identifier_type: type,
    alternate_text: str,
) -> None:
    alternate = identifier_type(alternate_text)
    canonical = identifier_type(UUID_TEXT)

    assert alternate.value == UUID_TEXT
    assert alternate == canonical


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
@pytest.mark.parametrize(
    "uuid_text",
    [
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "550e8400-e29b-41d4-a716-446655440000",
    ],
    ids=["uuid-v1", "uuid-v4"],
)
def test_identifier_does_not_restrict_uuid_version(
    identifier_type: type,
    uuid_text: str,
) -> None:
    assert identifier_type(uuid_text).value == uuid_text


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
def test_same_type_identifiers_with_same_uuid_are_equal(identifier_type: type) -> None:
    first = identifier_type(UUID_TEXT)
    second = identifier_type(UUID_TEXT)

    assert first == second


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
def test_same_type_identifiers_with_different_uuids_are_unequal(
    identifier_type: type,
) -> None:
    assert identifier_type(UUID_TEXT) != identifier_type(OTHER_UUID_TEXT)


@pytest.mark.parametrize(
    ("first_type", "second_type"),
    list(zip(IDENTIFIER_TYPES, IDENTIFIER_TYPES[1:] + IDENTIFIER_TYPES[:1], strict=True)),
    ids=IDENTIFIER_TYPE_IDS,
)
def test_different_identifier_types_are_not_equal(
    first_type: type,
    second_type: type,
) -> None:
    assert first_type(UUID_TEXT) != second_type(UUID_TEXT)


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
def test_identifier_is_not_equal_to_raw_uuid_string(identifier_type: type) -> None:
    assert identifier_type(UUID_TEXT) != UUID_TEXT


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
def test_equal_identifiers_have_equal_hashes(identifier_type: type) -> None:
    first = identifier_type(UUID_TEXT)
    second = identifier_type(UUID_TEXT)

    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_different_identifier_types_can_coexist_in_a_set() -> None:
    identifiers = {WorkspaceId(UUID_TEXT), DocumentId(UUID_TEXT)}

    assert len(identifiers) == 2


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
@pytest.mark.parametrize("attribute_name", ["value", "_value"])
def test_identifier_is_immutable(identifier_type: type, attribute_name: str) -> None:
    identifier = identifier_type(UUID_TEXT)

    with pytest.raises(AttributeError):
        setattr(identifier, attribute_name, OTHER_UUID_TEXT)

    assert identifier.value == UUID_TEXT


def test_identifier_repr_identifies_type_and_value() -> None:
    identifier = WorkspaceId(UUID_TEXT)

    assert repr(identifier) == f"WorkspaceId(value={UUID_TEXT!r})"


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES, ids=IDENTIFIER_TYPE_IDS)
def test_identifier_has_no_uuid_generation_api(identifier_type: type) -> None:
    assert not hasattr(identifier_type, "new")
