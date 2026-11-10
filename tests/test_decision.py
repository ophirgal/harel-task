"""Unit tests for the decision logic, using hand-written LLM outputs (no LLM calls)."""

from decision import decide
from documents import Document
from schemas import CaseAssessment, CaseFacts

DOCUMENTS = [
    Document("ct.pdf", "Lung-RADS Category: 4B\nRecommendation: PET-CT and tissue sampling\nrecommended."),
    Document("labs.pdf", "PT 12.1 seconds\nAll values within normal limits."),
    Document("notes.pdf", "Recommend robotic-assisted transbronchial biopsy."),
]


def make_facts(**clinical_overrides) -> dict:
    return {
        "case_id": "PA-1",
        "patient": {"name": "Jane Doe", "date_of_birth": "1950-01-01", "mrn": "123"},
        "requesting_provider": {"name": "Dr. X", "specialty": None, "npi": None},
        "request": {
            "procedure": "Robotic-Assisted Transbronchial Lung Biopsy",
            "cpt_codes": ["31629"],
            "diagnoses": [],
            "requested_date": "2025-12-10",
            "facility": None,
        },
        "clinical": {
            "finding": "Suspicious right upper lobe pulmonary nodule",
            "nodule_location": None,
            "nodule_size": None,
            "nodule_characteristics": [],
            "lung_rads": "4B",
            "pet_ct_result": None,
            "suv_max": None,
            "malignancy_risk": None,
            "fev1_percent": None,
            "dlco_percent": None,
            "coagulation_status": "Normal",
            "labs_summary": None,
            "procedure_rationale": None,
            **clinical_overrides,
        },
    }


def criterion(document: str, quote: str, status: str = "met", note: str = "Supported.") -> dict:
    return {"status": status, "evidence": [{"document": document, "quote": quote}], "note": note}


def make_assessment() -> dict:
    return {
        "criteria": {
            "suspicious_nodule": criterion("ct.pdf", "Lung-RADS Category: 4B"),
            # The quote spans a line break in the document text.
            "tissue_sampling_recommended": criterion("ct.pdf", "PET-CT and tissue sampling recommended."),
            "procedure_matches_findings": criterion(
                "notes.pdf", "Recommend robotic-assisted transbronchial biopsy.", note="The approach fits."
            ),
            "no_contraindication_in_workup": criterion("labs.pdf", "All values within normal limits."),
        },
        "discrepancies": [],
    }


def run(facts: dict, assessment: dict):
    return decide(CaseFacts.model_validate(facts), CaseAssessment.model_validate(assessment), DOCUMENTS)


def test_all_criteria_met_approves_with_template_reason():
    decision = run(make_facts(), make_assessment())
    assert decision.status == "APPROVE"
    assert decision.reason == (
        "The submitted documentation supports tissue sampling of a suspicious right upper lobe pulmonary nodule. "
        "The approach fits."
    )
    assert decision.review_reasons == []


def test_minor_discrepancy_does_not_block_approval():
    assessment = make_assessment()
    assessment["discrepancies"] = [
        {"description": "Age 72 vs 73.", "documents": ["a.pdf"], "severity": "minor", "rationale": "Clerical."}
    ]
    assert run(make_facts(), assessment).status == "APPROVE"


def test_contraindication_in_workup_requires_review():
    # e.g. the LLM judged an abnormal INR to be a contraindication
    assessment = make_assessment()
    assessment["criteria"]["no_contraindication_in_workup"] = criterion(
        "labs.pdf", "PT 12.1 seconds", status="not_met", note="INR is elevated."
    )
    decision = run(make_facts(coagulation_status="Abnormal"), assessment)
    assert decision.status == "MANUAL_REVIEW"
    assert decision.reason == (
        "Manual review required: Criterion no_contraindication_in_workup is not_met (INR is elevated.)"
    )


def test_unclear_criterion_requires_review():
    assessment = make_assessment()
    assessment["criteria"]["tissue_sampling_recommended"]["status"] = "unclear"
    assert run(make_facts(), assessment).status == "MANUAL_REVIEW"


def test_quote_not_in_document_downgrades_criterion():
    assessment = make_assessment()
    assessment["criteria"]["suspicious_nodule"] = criterion("ct.pdf", "Lung-RADS Category: 4X")  # invented
    decision = run(make_facts(), assessment)
    assert decision.status == "MANUAL_REVIEW"
    assert decision.criteria["suspicious_nodule"].status == "unclear"
    assert "Evidence quote not found in ct.pdf" in decision.reason


def test_quote_attributed_to_wrong_document_downgrades_criterion():
    assessment = make_assessment()
    assessment["criteria"]["suspicious_nodule"] = criterion("labs.pdf", "Lung-RADS Category: 4B")
    assert run(make_facts(), assessment).status == "MANUAL_REVIEW"


def test_met_without_evidence_downgrades_criterion():
    assessment = make_assessment()
    assessment["criteria"]["suspicious_nodule"]["evidence"] = []
    assert run(make_facts(), assessment).status == "MANUAL_REVIEW"


def test_missing_required_field_requires_review():
    facts = make_facts()
    facts["request"]["requested_date"] = None
    decision = run(facts, make_assessment())
    assert decision.status == "MANUAL_REVIEW"
    assert decision.review_reasons == ["Missing required field: request.requested_date"]


def test_material_discrepancy_requires_review():
    assessment = make_assessment()
    assessment["discrepancies"] = [
        {"description": "CT says left lobe, form says right.", "documents": ["ct.pdf"], "severity": "material",
         "rationale": "Different side."}
    ]
    decision = run(make_facts(), assessment)
    assert decision.status == "MANUAL_REVIEW"
    assert decision.review_reasons == ["Material discrepancy: CT says left lobe, form says right."]
