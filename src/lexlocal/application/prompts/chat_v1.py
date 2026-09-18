"""Hold every versioned CHAT-001 M1 prompt and non-answer resource."""

import json

CHAT_RESOURCE_VERSION = "chat-resources-v1"
GROUNDED_CHAT_CONTRACT_VERSION = "chat-grounded-v1"
GROUNDED_REPAIR_PROMPT_VERSION = "chat-grounded-repair-v1"
RELATED_NON_ANSWER_CONTRACT_VERSION = "chat-related-non-answer-v1"
INSUFFICIENT_NON_ANSWER_CONTRACT_VERSION = "chat-insufficient-non-answer-v1"

RELATED_NON_ANSWER = (
    "The available evidence contains related passages, but it does not provide "
    "enough support to answer this question."
)
INSUFFICIENT_NON_ANSWER = (
    "The available evidence does not provide enough support to answer this question."
)

_GROUNDED_RULES = (
    "Use only the supplied question and evidence passages.",
    "Do not use general knowledge or add unsupported claims.",
    "Keep every answer claim traceable to one or more supplied evidence labels.",
    "Acknowledge when the supplied evidence lacks information needed for a claim.",
    "Do not provide authoritative legal advice.",
    "Return only the required JSON object with no commentary or additional fields.",
    "The answer must contain non-whitespace text.",
    "Citations must be an ordered non-empty list of unique supplied E{rank} labels.",
)

_REPAIR_RULES = (
    "Produce a fresh response using the same supplied question and evidence only.",
    "Return exactly two top-level fields: answer and citations.",
    "Do not repeat malformed output, commentary, source metadata, or sufficiency state.",
)


def render_grounded_prompt(
    question: str,
    evidence: tuple[tuple[str, str], ...],
    *,
    repair: bool,
) -> str:
    """Render the exact initial or constrained-repair grounded prompt."""

    envelope: dict[str, object] = {
        "task": "answer-from-supplied-evidence",
        "resource_version": CHAT_RESOURCE_VERSION,
        "completion_contract_version": GROUNDED_CHAT_CONTRACT_VERSION,
        "attempt": "repair" if repair else "initial",
        "rules": list(_GROUNDED_RULES),
        "question": question,
        "evidence": [
            {"label": label, "excerpt": excerpt} for label, excerpt in evidence
        ],
        "output_schema": {
            "answer": "<non-empty string>",
            "citations": ["E{rank}"],
        },
    }
    if repair:
        envelope["repair_prompt_version"] = GROUNDED_REPAIR_PROMPT_VERSION
        envelope["repair_rules"] = list(_REPAIR_RULES)
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
