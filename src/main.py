"""Review one prior-authorization case: python src/main.py <case_dir>

Writes output/<case_id>.json in the required schema and prints the criteria, evidence and discrepancies.
"""

import argparse
from pathlib import Path

from decision import Decision, decide
from documents import load_case_documents
from extraction import extract_case
from llm import AnthropicProvider
from schemas import CaseAssessment, CaseFacts, CaseOutput, ClinicalSummary, OutputPatient, OutputRequest, Recommendation

OUTPUT_DIR = Path("output")


def review_case(case_dir: Path) -> tuple[CaseOutput, Decision, CaseAssessment]:
    documents = load_case_documents(case_dir)
    facts, assessment = extract_case(documents, AnthropicProvider())
    decision = decide(facts, assessment, documents)
    return build_output(facts, decision), decision, assessment


def build_output(facts: CaseFacts, decision: Decision) -> CaseOutput:
    c = facts.clinical
    return CaseOutput(
        case_id=facts.case_id,
        patient=OutputPatient(**facts.patient.model_dump()),
        request=OutputRequest(
            procedure=facts.request.procedure,
            cpt_codes=facts.request.cpt_codes,
            requested_date=facts.request.requested_date,
        ),
        clinical_summary=ClinicalSummary(
            finding=c.finding,
            nodule_size=c.nodule_size,
            lung_rads=c.lung_rads,
            suv_max=c.suv_max,
            fev1_percent=c.fev1_percent,
            dlco_percent=c.dlco_percent,
            coagulation_status=c.coagulation_status,
        ),
        recommendation=Recommendation(status=decision.status, reason=decision.reason),
    )


def print_report(decision: Decision, assessment: CaseAssessment) -> None:
    print("CRITERIA (after quote check)")
    for name, criterion in decision.criteria.items():
        print(f"  [{criterion.status}] {name}: {criterion.note}")
        for evidence in criterion.evidence:
            print(f'      - {evidence.document}: "{evidence.quote}"')
    print("\nDISCREPANCIES (minor ones are warnings and don't change the status)")
    for d in assessment.discrepancies or []:
        print(f"  [{d.severity}] {d.description}")
    print(f"\nRECOMMENDATION: {decision.status}\n  {decision.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a prior-authorization case directory of PDFs.")
    parser.add_argument("case_dir", type=Path)
    case_dir = parser.parse_args().case_dir

    output, decision, assessment = review_case(case_dir)
    print_report(decision, assessment)

    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{output.case_id or case_dir.name}.json"
    path.write_text(output.model_dump_json(indent=2) + "\n")
    print(f"\nOutput written to {path}")


if __name__ == "__main__":
    main()
