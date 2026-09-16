"""Evaluate one exact RAG result under the deterministic evidence policy."""

from lexlocal.application.ports.evidence_sufficiency import (
    AggregateEvidenceCoverage,
    EvidenceAssessment,
    EvidencePolicyIdentity,
    EvidenceRelation,
    EvidenceRelationCounts,
    EvidenceSufficiencyCancellationCheck,
    EvidenceSufficiencyCancelled,
    EvidenceSufficiencyError,
    EvidenceSufficiencyResult,
    EvidenceVerifier,
    EvidenceVerifierError,
    EvidenceVerifierRequest,
    EvidenceVerifierResult,
    InvalidEvidenceSufficiencyInput,
    VerifierEvidence,
)
from lexlocal.application.ports.retrieval import (
    RetrievalEvidenceRegistration,
    RetrievalRegistration,
)
from lexlocal.domain.processing import ProcessingJobState
from lexlocal.domain.retrieval import EvidenceSufficiency


class EvaluateEvidenceSufficiency:
    """Map one complete retrieval to one immutable CHAT-consumable decision."""

    def __init__(
        self,
        verifier: EvidenceVerifier,
        policy: EvidencePolicyIdentity,
        cancellation: EvidenceSufficiencyCancellationCheck,
    ) -> None:
        if not isinstance(policy, EvidencePolicyIdentity):
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency policy is invalid"
            )
        self._verifier = verifier
        self._policy = policy
        self._cancellation = cancellation
        self._require_verifier_binding()

    def __call__(self, retrieval: RetrievalRegistration) -> EvidenceSufficiencyResult:
        """Evaluate the exact persisted RAG handoff without persistence or retry work."""

        self._checkpoint()
        if not isinstance(retrieval, RetrievalRegistration):
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency retrieval is invalid"
            )
        self._require_verifier_binding()
        coverage = self._coverage(retrieval)

        if not retrieval.evidence:
            result = self._result(
                retrieval,
                EvidenceSufficiency.INSUFFICIENT,
                (),
                (),
                coverage,
                EvidenceRelationCounts(0, 0, 0, 0),
                repair_used=False,
            )
            self._checkpoint()
            return result

        request = self._request(retrieval)
        self._checkpoint()
        verifier_result = self._verify(request)
        self._checkpoint()
        self._require_verifier_binding()
        self._require_result_binding(request, verifier_result)

        counts = self._counts(verifier_result)
        state = self._state(coverage, counts)
        related = self._related_evidence(retrieval, verifier_result, state)
        result = self._result(
            retrieval,
            state,
            verifier_result.assessments,
            related,
            coverage,
            counts,
            verifier_result.repair_used,
        )
        self._checkpoint()
        return result

    def _require_verifier_binding(self) -> None:
        try:
            status = self._verifier.status
        except Exception:
            raise EvidenceVerifierError("evidence verifier is unavailable") from None
        if status != self._policy.verifier_status:
            raise InvalidEvidenceSufficiencyInput(
                "evidence verifier policy binding is invalid"
            )

    @staticmethod
    def _coverage(retrieval: RetrievalRegistration) -> AggregateEvidenceCoverage:
        states = tuple(
            generation.coverage_state for generation in retrieval.scope.generations
        )
        if not states or any(
            state not in (
                ProcessingJobState.READY,
                ProcessingJobState.READY_WITH_WARNINGS,
            )
            for state in states
        ):
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency coverage is invalid"
            )
        if ProcessingJobState.READY_WITH_WARNINGS in states:
            return AggregateEvidenceCoverage.READY_WITH_WARNINGS
        return AggregateEvidenceCoverage.READY

    @staticmethod
    def _request(retrieval: RetrievalRegistration) -> EvidenceVerifierRequest:
        try:
            return EvidenceVerifierRequest(
                retrieval.scope.request.query,
                tuple(
                    VerifierEvidence(
                        item.evidence.id,
                        item.evidence.rank,
                        item.excerpt,
                    )
                    for item in retrieval.evidence
                ),
            )
        except EvidenceSufficiencyError:
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency retrieval binding is invalid"
            ) from None
        except Exception:
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency retrieval binding is invalid"
            ) from None

    def _verify(self, request: EvidenceVerifierRequest) -> EvidenceVerifierResult:
        try:
            result = self._verifier.verify(request)
        except EvidenceSufficiencyCancelled:
            raise EvidenceSufficiencyCancelled(
                "evidence sufficiency evaluation was cancelled"
            ) from None
        except Exception:
            raise EvidenceVerifierError("evidence verification failed") from None
        if not isinstance(result, EvidenceVerifierResult):
            raise EvidenceVerifierError("evidence verifier result is invalid")
        return result

    def _require_result_binding(
        self,
        request: EvidenceVerifierRequest,
        result: EvidenceVerifierResult,
    ) -> None:
        if (
            result.request != request
            or result.status != self._policy.verifier_status
            or result.verifier_contract_version
            != self._policy.verifier_contract_version
            or tuple(
                (item.evidence_item_id, item.rank) for item in result.assessments
            )
            != tuple(
                (item.evidence_item_id, item.rank) for item in request.evidence
            )
        ):
            raise EvidenceVerifierError("evidence verifier result binding is invalid")

    @staticmethod
    def _counts(result: EvidenceVerifierResult) -> EvidenceRelationCounts:
        return EvidenceRelationCounts(
            sum(
                item.relation is EvidenceRelation.SUPPORTS
                for item in result.assessments
            ),
            sum(
                item.relation is EvidenceRelation.RELATED_ONLY
                for item in result.assessments
            ),
            sum(
                item.relation is EvidenceRelation.CONTRADICTS
                for item in result.assessments
            ),
            sum(
                item.relation is EvidenceRelation.IRRELEVANT
                for item in result.assessments
            ),
        )

    @staticmethod
    def _state(
        coverage: AggregateEvidenceCoverage,
        counts: EvidenceRelationCounts,
    ) -> EvidenceSufficiency:
        if (
            coverage is AggregateEvidenceCoverage.READY
            and counts.supports > 0
            and counts.contradicts == 0
        ):
            return EvidenceSufficiency.SUFFICIENT
        if counts.supports > 0 or counts.related_only > 0 or counts.contradicts > 0:
            return EvidenceSufficiency.RELATED_BUT_INSUFFICIENT
        return EvidenceSufficiency.INSUFFICIENT

    @staticmethod
    def _related_evidence(
        retrieval: RetrievalRegistration,
        result: EvidenceVerifierResult,
        state: EvidenceSufficiency,
    ) -> tuple[RetrievalEvidenceRegistration, ...]:
        if state is not EvidenceSufficiency.RELATED_BUT_INSUFFICIENT:
            return ()
        return tuple(
            evidence
            for evidence, assessment in zip(
                retrieval.evidence,
                result.assessments,
                strict=True,
            )
            if assessment.relation is not EvidenceRelation.IRRELEVANT
        )

    def _result(
        self,
        retrieval: RetrievalRegistration,
        state: EvidenceSufficiency,
        assessments: tuple[EvidenceAssessment, ...],
        related_evidence: tuple[RetrievalEvidenceRegistration, ...],
        coverage: AggregateEvidenceCoverage,
        counts: EvidenceRelationCounts,
        repair_used: bool,
    ) -> EvidenceSufficiencyResult:
        try:
            return EvidenceSufficiencyResult(
                retrieval,
                state,
                self._policy,
                assessments,
                related_evidence,
                coverage,
                counts,
                repair_used,
            )
        except EvidenceSufficiencyError:
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency result creation failed"
            ) from None
        except Exception:
            raise InvalidEvidenceSufficiencyInput(
                "evidence sufficiency result creation failed"
            ) from None

    def _checkpoint(self) -> None:
        try:
            self._cancellation.raise_if_cancelled()
        except EvidenceSufficiencyCancelled:
            raise EvidenceSufficiencyCancelled(
                "evidence sufficiency evaluation was cancelled"
            ) from None
        except Exception:
            raise EvidenceVerifierError(
                "evidence sufficiency cancellation check failed"
            ) from None
