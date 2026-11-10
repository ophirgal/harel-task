"""Pydantic models: the LLMs' structured outputs (CaseFacts, CaseAssessment) and the final output (CaseOutput).

Field descriptions are part of the JSON Schema sent to the LLM, so they double as extraction instructions.
"""

from typing import Literal

from pydantic import BaseModel, Field

# ---------- LLM structured output ----------


class Evidence(BaseModel):
    document: str = Field(description="File name of the source document.")
    quote: str = Field(description="Verbatim quote copied exactly from that document.")


class CriterionAssessment(BaseModel):
    status: Literal["met", "not_met", "unclear"]
    evidence: list[Evidence]
    note: str = Field(
        description="One-sentence justification of the status, grounded in the evidence. Address only this "
        "criterion; report coding, administrative or other side issues as discrepancies instead."
    )


class Criteria(BaseModel):
    suspicious_nodule: CriterionAssessment = Field(
        description="There is a suspicious nodule that requires investigation."
    )
    tissue_sampling_recommended: CriterionAssessment = Field(
        description="There is a medical recommendation to sample tissue."
    )
    procedure_matches_findings: CriterionAssessment = Field(
        description="The requested procedure fits the findings and the patient's condition."
    )
    no_contraindication_in_workup: CriterionAssessment = Field(
        description="The pre-procedure tests (labs, coagulation, pulmonary function) show no clear "
        "contraindication to the procedure."
    )


class Discrepancy(BaseModel):
    description: str
    documents: list[str] = Field(description="File names of the documents involved.")
    severity: Literal["material", "minor"] = Field(
        description="'material' only if it puts in doubt whether the procedure is clinically justified for "
        "this patient: e.g. the documents describe different patients, a different side or lobe, a different "
        "procedure, or contradictory key findings. Coding, billing and administrative issues are 'minor' "
        "(still listed, so a human can see them)."
    )
    rationale: str = Field(description="Why this severity.")


class Patient(BaseModel):
    name: str | None = Field(description="Full name in natural order, e.g. 'Margaret A. Johnson'.")
    date_of_birth: str | None = Field(description="YYYY-MM-DD")
    mrn: str | None = Field(description="Medical record number.")


class Provider(BaseModel):
    name: str | None
    specialty: str | None
    npi: str | None


class Diagnosis(BaseModel):
    icd10_code: str
    description: str


class Request(BaseModel):
    procedure: str | None
    cpt_codes: list[str] = Field(description="Codes only, e.g. '31629'.")
    diagnoses: list[Diagnosis]
    requested_date: str | None = Field(description="Requested date of service, YYYY-MM-DD.")
    facility: str | None


class Clinical(BaseModel):
    finding: str | None = Field(
        description="Short noun phrase: suspicion level + location + lesion type, no further details."
    )
    nodule_location: str | None
    nodule_size: str | None = Field(description="As reported, e.g. '18 x 15 mm'.")
    nodule_characteristics: list[str] = Field(description="e.g. 'part-solid', 'spiculated margins'.")
    lung_rads: str | None = Field(description="Category only, e.g. '4B'.")
    pet_ct_result: str | None
    suv_max: float | None
    malignancy_risk: str | None = Field(description="e.g. 'Brock 68%, Mayo 71%'.")
    fev1_percent: int | None = Field(description="FEV1 as % predicted (pre-bronchodilator).")
    dlco_percent: int | None = Field(description="DLCO as % predicted.")
    coagulation_status: str | None = Field(description="'Normal' or 'Abnormal', based on PT/INR/PTT.")
    labs_summary: str | None
    procedure_rationale: str | None = Field(
        description="Why this procedure was chosen over the alternatives."
    )


class CaseFacts(BaseModel):
    """LLM call A: what the documents say."""

    case_id: str | None = Field(description="Prior-authorization tracking number, e.g. 'PA-2025-847291'.")
    patient: Patient
    requesting_provider: Provider
    request: Request
    clinical: Clinical


class CaseAssessment(BaseModel):
    """LLM call B: judgments on the documents."""

    criteria: Criteria
    discrepancies: list[Discrepancy] = Field(
        description="Inconsistencies between documents. Empty list if none."
    )


# ---------- Final output (the shape the assignment specifies) ----------


class OutputPatient(BaseModel):
    name: str | None
    date_of_birth: str | None
    mrn: str | None


class OutputRequest(BaseModel):
    procedure: str | None
    cpt_codes: list[str]
    requested_date: str | None


class ClinicalSummary(BaseModel):
    finding: str | None
    nodule_size: str | None
    lung_rads: str | None
    suv_max: float | None
    fev1_percent: int | None
    dlco_percent: int | None
    coagulation_status: str | None


class Recommendation(BaseModel):
    status: Literal["APPROVE", "MANUAL_REVIEW"]
    reason: str


class CaseOutput(BaseModel):
    case_id: str | None
    patient: OutputPatient
    request: OutputRequest
    clinical_summary: ClinicalSummary
    recommendation: Recommendation
