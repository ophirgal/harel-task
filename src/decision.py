"""Turn the LLM's facts and assessments into a status and a reason, deterministically (no LLM).

1. Quote check: a criterion whose evidence can't be found in the source documents is downgraded to "unclear".
2. Rules: APPROVE only if every criterion is "met", no required field is missing and no discrepancy is material.
3. Reason: built from a string template, from the same data as the status.
"""

import re
from dataclasses import dataclass
from typing import Literal

from documents import Document
from schemas import CaseAssessment, CaseFacts, CriterionAssessment

# Fields without which the case can't be identified, or the request can't be reviewed or explained.
REQUIRED_FIELDS = {
    "case_id": lambda f: f.case_id,
    "patient.name": lambda f: f.patient.name,
    "patient.date_of_birth": lambda f: f.patient.date_of_birth,
    "request.procedure": lambda f: f.request.procedure,
    "request.cpt_codes": lambda f: f.request.cpt_codes,
    "request.requested_date": lambda f: f.request.requested_date,
    "clinical.finding": lambda f: f.clinical.finding,  # used in the APPROVE reason
}


@dataclass(frozen=True)
class Decision:
    status: Literal["APPROVE", "MANUAL_REVIEW"]
    reason: str
    criteria: dict[str, CriterionAssessment]  # after the quote check
    review_reasons: list[str]  # the rules that fired; empty on APPROVE


def decide(facts: CaseFacts, assessment: CaseAssessment, documents: list[Document]) -> Decision:
    criteria = {
        name: check_quotes(criterion, documents) for name, criterion in assessment.criteria
    }

    review_reasons = [
        f"Criterion {name} is {c.status} ({c.note})" for name, c in criteria.items() if c.status != "met"
    ]
    review_reasons += [
        f"Missing required field: {field}" for field, get in REQUIRED_FIELDS.items() if not get(facts)
    ]
    review_reasons += [
        f"Material discrepancy: {d.description}" for d in assessment.discrepancies if d.severity == "material"
    ]

    if review_reasons:
        return Decision("MANUAL_REVIEW", "Manual review required: " + "; ".join(review_reasons), criteria, review_reasons)

    reason = (
        f"The submitted documentation supports tissue sampling of {_with_article(facts.clinical.finding)}. "
        f"{criteria['procedure_matches_findings'].note}"
    )
    return Decision("APPROVE", reason, criteria, [])


def check_quotes(criterion: CriterionAssessment, documents: list[Document]) -> CriterionAssessment:
    """Downgrade a "met" criterion to "unclear" if it has no evidence or any quote isn't in its document."""
    if criterion.status != "met":
        return criterion
    if not criterion.evidence:
        return criterion.model_copy(update={"status": "unclear", "note": "No evidence given. " + criterion.note})

    texts = {doc.name: _normalize(doc.text) for doc in documents}
    for evidence in criterion.evidence:
        if _normalize(evidence.quote) not in texts.get(evidence.document, ""):
            note = f'Evidence quote not found in {evidence.document}: "{evidence.quote}". ' + criterion.note
            return criterion.model_copy(update={"status": "unclear", "note": note})
    return criterion


def _normalize(text: str) -> str:
    """Collapse whitespace, so quotes that span line breaks in the extracted PDF text still match."""
    return re.sub(r"\s+", " ", text).strip()


def _with_article(finding: str) -> str:
    """'Suspicious right upper lobe nodule' -> 'a suspicious right upper lobe nodule' (keeps acronyms like 'RUL')."""
    if finding[1:2].islower():
        finding = finding[0].lower() + finding[1:]
    return ("an " if finding[0].lower() in "aeiou" else "a ") + finding
