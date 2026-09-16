"""Define Application-owned contracts for local evidence-sufficiency verification."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from lexlocal.application.ports.local_models import (
    LocalModelStatus,
    ModelCapability,
    ModelReadiness,
)
from lexlocal.application.ports.retrieval import (
    RetrievalEvidenceRegistration,
    RetrievalRegistration,
)
from lexlocal.domain.identifiers import EvidenceItemId
from lexlocal.domain.retrieval import EvidenceRank, EvidenceSufficiency


class EvidenceSufficiencyError(Exception):
    """Base exception for sanitized evidence-sufficiency failures."""


class InvalidEvidenceSufficiencyInput(EvidenceSufficiencyError):
    """Report invalid or inconsistent verifier and policy input."""


class EvidenceVerifierError(EvidenceSufficiencyError):
    """Report an unavailable, failed, or contract-invalid verifier result."""


class EvidenceSufficiencyCancelled(EvidenceSufficiencyError):
    """Report cooperative cancellation before a final decision exists."""


class EvidenceRelation(StrEnum):
    """Classify one selected passage against the exact QA question."""

    SUPPORTS = "SUPPORTS"
    RELATED_ONLY = "RELATED_ONLY"
    CONTRADICTS = "CONTRADICTS"
    IRRELEVANT = "IRRELEVANT"


class AggregateEvidenceCoverage(StrEnum):
    """Summarize whether every selected generation has warning-free coverage."""

    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"


@dataclass(frozen=True, slots=True)
class VerifierEvidence:
    """Carry one exact private passage under its authoritative RAG rank label."""

    evidence_item_id: EvidenceItemId = field(repr=False)
    rank: EvidenceRank
    excerpt: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.evidence_item_id, EvidenceItemId)
            or not isinstance(self.rank, EvidenceRank)
            or not isinstance(self.excerpt, str)
            or not self.excerpt
        ):
            raise InvalidEvidenceSufficiencyInput("verifier evidence is invalid")

    @property
    def label(self) -> str:
        """Return the model-facing label derived only from authoritative RAG rank."""

        return f"E{self.rank.value}"


@dataclass(frozen=True, slots=True)
class EvidenceVerifierRequest:
    """Carry the exact private question and complete ordered evidence inputs."""

    question: str = field(repr=False)
    evidence: tuple[VerifierEvidence, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.question, str)
            or not self.question.strip()
            or not isinstance(self.evidence, tuple)
            or not self.evidence
            or not all(isinstance(item, VerifierEvidence) for item in self.evidence)
            or tuple(item.rank.value for item in self.evidence)
            != tuple(range(1, len(self.evidence) + 1))
            or len({item.evidence_item_id for item in self.evidence})
            != len(self.evidence)
        ):
            raise InvalidEvidenceSufficiencyInput("verifier request is invalid")


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Bind one validated semantic relation to existing RAG evidence identity."""

    evidence_item_id: EvidenceItemId = field(repr=False)
    rank: EvidenceRank
    relation: EvidenceRelation

    def __post_init__(self) -> None:
        if (
            not isinstance(self.evidence_item_id, EvidenceItemId)
            or not isinstance(self.rank, EvidenceRank)
            or not isinstance(self.relation, EvidenceRelation)
        ):
            raise EvidenceVerifierError("verifier assessment is invalid")

    @property
    def label(self) -> str:
        """Return the validated model label for this authoritative RAG rank."""

        return f"E{self.rank.value}"


@dataclass(frozen=True, slots=True)
class EvidenceVerifierResult:
    """Return one complete SDK-free assessment set from an exact READY model."""

    request: EvidenceVerifierRequest = field(repr=False)
    status: LocalModelStatus = field(repr=False)
    verifier_contract_version: str
    assessments: tuple[EvidenceAssessment, ...]
    repair_used: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request, EvidenceVerifierRequest)
            or not _is_ready_chat_status(self.status)
            or not _is_version(self.verifier_contract_version)
            or not isinstance(self.assessments, tuple)
            or not all(
                isinstance(item, EvidenceAssessment) for item in self.assessments
            )
            or not isinstance(self.repair_used, bool)
            or tuple(
                (item.evidence_item_id, item.rank) for item in self.assessments
            )
            != tuple(
                (item.evidence_item_id, item.rank) for item in self.request.evidence
            )
        ):
            raise EvidenceVerifierError("verifier result is invalid")


@dataclass(frozen=True, slots=True)
class EvidencePolicyIdentity:
    """Bind one policy version to its exact verifier model and contract."""

    evidence_policy_version: str
    verifier_contract_version: str
    verifier_status: LocalModelStatus = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not _is_version(self.evidence_policy_version)
            or not _is_version(self.verifier_contract_version)
            or not _is_ready_chat_status(self.verifier_status)
        ):
            raise InvalidEvidenceSufficiencyInput("evidence policy identity is invalid")


@dataclass(frozen=True, slots=True)
class EvidenceRelationCounts:
    """Carry only safe aggregate counts for the exact relation vocabulary."""

    supports: int
    related_only: int
    contradicts: int
    irrelevant: int

    def __post_init__(self) -> None:
        values = (self.supports, self.related_only, self.contradicts, self.irrelevant)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise InvalidEvidenceSufficiencyInput("evidence relation counts are invalid")

    @property
    def total(self) -> int:
        """Return the complete assessment count without exposing evidence content."""

        return self.supports + self.related_only + self.contradicts + self.irrelevant


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyResult:
    """Expose one immutable CHAT-consumable decision bound to exact RAG evidence."""

    retrieval: RetrievalRegistration = field(repr=False)
    state: EvidenceSufficiency
    policy: EvidencePolicyIdentity
    assessments: tuple[EvidenceAssessment, ...]
    related_evidence: tuple[RetrievalEvidenceRegistration, ...] = field(repr=False)
    aggregate_coverage: AggregateEvidenceCoverage
    relation_counts: EvidenceRelationCounts
    repair_used: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.retrieval, RetrievalRegistration)
            or not isinstance(self.state, EvidenceSufficiency)
            or not isinstance(self.policy, EvidencePolicyIdentity)
            or not isinstance(self.assessments, tuple)
            or not all(
                isinstance(item, EvidenceAssessment) for item in self.assessments
            )
            or not isinstance(self.related_evidence, tuple)
            or not all(
                isinstance(item, RetrievalEvidenceRegistration)
                for item in self.related_evidence
            )
            or not isinstance(self.aggregate_coverage, AggregateEvidenceCoverage)
            or not isinstance(self.relation_counts, EvidenceRelationCounts)
            or not isinstance(self.repair_used, bool)
        ):
            raise InvalidEvidenceSufficiencyInput("evidence sufficiency result is invalid")

        expected = tuple(
            (item.evidence.id, item.evidence.rank) for item in self.retrieval.evidence
        )
        actual = tuple(
            (item.evidence_item_id, item.rank) for item in self.assessments
        )
        try:
            related_positions = tuple(
                self.retrieval.evidence.index(item) for item in self.related_evidence
            )
        except ValueError:
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency result is inconsistent"
            ) from None
        actual_counts = EvidenceRelationCounts(
            sum(item.relation is EvidenceRelation.SUPPORTS for item in self.assessments),
            sum(
                item.relation is EvidenceRelation.RELATED_ONLY
                for item in self.assessments
            ),
            sum(
                item.relation is EvidenceRelation.CONTRADICTS
                for item in self.assessments
            ),
            sum(item.relation is EvidenceRelation.IRRELEVANT for item in self.assessments),
        )
        if (
            actual != expected
            or self.relation_counts != actual_counts
            or related_positions != tuple(sorted(set(related_positions)))
            or (
                not self.retrieval.evidence
                and (
                    self.state is not EvidenceSufficiency.INSUFFICIENT
                    or self.assessments
                    or self.related_evidence
                    or self.relation_counts.total != 0
                    or self.repair_used
                )
            )
        ):
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency result is inconsistent"
            )


class EvidenceVerifier(Protocol):
    """Classify every supplied labelled excerpt without choosing sufficiency."""

    @property
    def status(self) -> LocalModelStatus:
        """Return the exact READY local chat-model identity."""

        ...

    def verify(self, request: EvidenceVerifierRequest) -> EvidenceVerifierResult:
        """Return one complete validated assessment for every request item."""

        ...


class EvidenceSufficiencyCancellationCheck(Protocol):
    """Raise when cooperative evidence-sufficiency cancellation is requested."""

    def raise_if_cancelled(self) -> None:
        """Raise EvidenceSufficiencyCancelled when cancellation is requested."""

        ...


def _is_ready_chat_status(value: object) -> bool:
    return (
        isinstance(value, LocalModelStatus)
        and value.readiness is ModelReadiness.READY
        and value.model.capability is ModelCapability.CHAT
    )


def _is_version(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
