# Plan: AI Prior-Authorization Review

## Goal
Given the PDF documents of a prior-authorization case, produce the required JSON
(case/patient/request/clinical_summary/recommendation) with a status of `APPROVE` or
`MANUAL_REVIEW` and a written reason. The status must be auditable: every decision
traces back to specific criteria and quotes from the documents.

## Decisions
| Topic | Choice | Why |
|---|---|---|
| Language / tooling | Python 3.13, `uv`, Pydantic, pypdf | pypdf text extraction verified on all 5 docs |
| LLM access | Own `LLMProvider` Protocol + Anthropic SDK implementation (`claude-opus-5-5`, structured outputs into Pydantic) | No framework needed for 1 fixed call; swapping provider = one new class |
| Decision | Hybrid: LLM judges each criterion (met / not_met / unclear + evidence quotes); plain code combines them into the status | Auditable, unit-testable, judgment stays where it's needed |
| Extraction | One call over all labeled documents, returning facts, criterion assessments with evidence, and a discrepancy list | Simple; cross-document comparison comes naturally |
| Tests | Unit tests for the decision logic (no LLM) + one saved live run on the real case | Fast, free, shows the MANUAL_REVIEW path works |

## Pipeline
```
case dir of PDFs
  └─ 1. documents.py   load PDFs → [Document(name, text)]                  (pypdf, no LLM)
  └─ 2. extraction.py  LLM call #1 → CaseExtraction                        (structured output)
  └─ 3. decision.py    pure function → Decision(status, reason)            (no LLM)
                       quote check → rules → reason from a string template
  └─ 4. main.py        assemble final output, write output/<case_id>.json,
                       print criteria, evidence and warnings to the console
```

### Criteria (from the assignment)
APPROVE requires all of these to be `met`:
1. `suspicious_nodule`: there is a suspicious nodule that needs investigation
2. `tissue_sampling_recommended`: there is a medical recommendation to sample tissue
3. `procedure_matches_findings`: the requested procedure fits the findings and the patient's condition
4. `no_contraindication_in_workup`: the pre-procedure tests show no clear contraindication

Before the rules run, code checks every evidence quote against the source document's text
(after normalizing whitespace). A criterion whose quotes can't be found is downgraded to `unclear`.
This guards against the costly error: a criterion confidently marked `met` with evidence the model invented.

MANUAL_REVIEW if any of these hold:
- any criterion above is `not_met` or `unclear` (including downgraded by the quote check)
- a required field is missing (case ID, patient name/DOB, procedure, CPT codes, requested date)
- any discrepancy is marked `material`

`minor` discrepancies don't change the status. They're printed as warnings in the run log.

### Reason (string template, no LLM)
- APPROVE: `"The submitted documentation supports tissue sampling of a {finding}. {criteria.procedure_matches_findings.note}"`
  The second sentence is the LLM's justification for the exact criterion our rules depend on. Its evidence
  passed the quote check, and the APPROVE path requires that criterion to be `met`, so the sentence always
  comes from an assessment that said "met". It can't drift from the decision the way a separate field could.
- MANUAL_REVIEW: `"Manual review required: "` + the fired rules joined with `"; "`, e.g.
  `"Criterion procedure_matches_findings is unclear (<note>); Missing required field: requested_date"`

Why not an LLM: the reason is built from the same data as the status, so the two can't contradict each other;
the reasons for review are exact; and it's deterministic, testable and free.

## Schemas
These are defined as Pydantic models in `schemas.py`. The JSON Schema sent to the API is generated
from them. Below, each field shows its type; `| null` means the value may be missing from the documents.

### LLM call #1: `CaseExtraction` (structured output)
```jsonc
{
  "case_id": "string | null",                    // tracking number, e.g. "PA-2025-847291"
  "patient": {
    "name": "string | null",
    "date_of_birth": "string | null",            // YYYY-MM-DD
    "mrn": "string | null"
  },
  "requesting_provider": {
    "name": "string | null",
    "specialty": "string | null",
    "npi": "string | null"
  },
  "request": {
    "procedure": "string | null",
    "cpt_codes": ["string"],
    "diagnoses": [{ "icd10_code": "string", "description": "string" }],
    "requested_date": "string | null",           // YYYY-MM-DD
    "facility": "string | null"
  },
  "clinical": {
    "finding": "string | null",                  // one line, e.g. "Suspicious right upper lobe pulmonary nodule"
    "nodule_location": "string | null",
    "nodule_size": "string | null",              // e.g. "18 x 15 mm"
    "nodule_characteristics": ["string"],        // e.g. "part-solid", "spiculated margins"
    "lung_rads": "string | null",                // e.g. "4B"
    "pet_ct_result": "string | null",
    "suv_max": "number | null",
    "malignancy_risk": "string | null",          // e.g. "Brock 68%, Mayo 71%"
    "fev1_percent": "number | null",             // % predicted
    "dlco_percent": "number | null",             // % predicted
    "coagulation_status": "string | null",       // e.g. "Normal"
    "labs_summary": "string | null",
    "procedure_rationale": "string | null"       // why this procedure was chosen over the alternatives
  },
  "criteria": {                                  // fixed keys, so every criterion is always assessed
    "suspicious_nodule":             { "$ref": "#/CriterionAssessment" },
    "tissue_sampling_recommended":   { "$ref": "#/CriterionAssessment" },
    "procedure_matches_findings":    { "$ref": "#/CriterionAssessment" },
    "no_contraindication_in_workup": { "$ref": "#/CriterionAssessment" }
  },
  "discrepancies": [
    {
      "description": "string",
      "documents": ["string"],                   // file names involved
      "severity": "material | minor",
      "rationale": "string"                      // why this severity
    }
  ]
}

// CriterionAssessment
{
  "status": "met | not_met | unclear",
  "evidence": [{ "document": "string", "quote": "string" }],   // verbatim quotes
  "note": "string"                               // one-sentence justification; for procedure_matches_findings
                                                 // this is used verbatim in the APPROVE reason
}
```

### Final output: `output/<case_id>.json`
Exactly the shape the assignment specifies. Built in code from `CaseExtraction` and the `Decision`.
```json
{
  "case_id": "PA-2025-847291",
  "patient": {
    "name": "Margaret A. Johnson",
    "date_of_birth": "1952-03-15",
    "mrn": "847291"
  },
  "request": {
    "procedure": "Robotic-Assisted Transbronchial Lung Biopsy",
    "cpt_codes": ["31629", "31632", "77012"],
    "requested_date": "2025-12-10"
  },
  "clinical_summary": {
    "finding": "Suspicious right upper lobe pulmonary nodule",
    "nodule_size": "18 x 15 mm",
    "lung_rads": "4B",
    "suv_max": 4.2,
    "fev1_percent": 62,
    "dlco_percent": 58,
    "coagulation_status": "Normal"
  },
  "recommendation": {
    "status": "APPROVE",
    "reason": "..."
  }
}
```

## Repo layout
```
cases/PA-2025-847291/*.pdf      # the 5 case docs (moved out of docs/)
docs/task_ai_approval.pdf       # assignment
src/{documents,schemas,llm,extraction,decision,main}.py
tests/test_decision.py
output/PA-2025-847291.json      # saved live run
README.md
```
Run: `uv run python src/main.py cases/PA-2025-847291`

## Build order (commit after each)
1. Scaffold (pyproject, layout) + `documents.py`
2. `schemas.py` + `llm.py` (Protocol + Anthropic impl)
3. `extraction.py` (prompt + call), checked by hand on the real case
4. `decision.py` (quote check + rules + reason template) + `tests/test_decision.py`
5. `main.py` → save `output/PA-2025-847291.json`
6. README

## README must include
- Run instructions; how the recommendation is made (the pipeline + rules above)
- **Design decisions** (each with the alternatives considered and why we chose this one):
  1. *Own `LLMProvider` interface + Anthropic SDK, not LangChain/PydanticAI*: a framework is overkill for a
     single fixed LLM call; the interface keeps the provider swappable while every line stays readable.
  2. *Hybrid decision*: the LLM judges each criterion with evidence quotes; plain code combines the
     judgments into the status. Rejected: "LLM decides" (not auditable, not testable) and pure rules
     (brittle for judgment criteria like "procedure matches findings").
  3. *One extraction call over all documents*, not per-document extraction. Assumes cases are small and
     accepts that discrepancy checks are non-deterministic (see Assumptions).
  4. *Tests*: unit tests for the decision logic with hand-written facts (no LLM; fast, free) + one saved live run.
  5. *Output is exactly the required schema*; criteria, evidence and minor-discrepancy warnings go to the
     console log, not the output file.
  6. *Evidence quote check in code*: quotes not found in the source downgrade the criterion to `unclear`.
  7. *Reason from a string template, not a second LLM call*: the reason is built from the same data as the
     status, so they can't contradict each other; it's deterministic, testable and free.
  8. *The APPROVE reason quotes the `procedure_matches_findings` criterion note* instead of a separately
     extracted justification field, which could hedge or drift from the judgment the rules relied on.
- **Assumptions:** cases are small enough to fit in one LLM call; discrepancy detection
  and per-criterion judgments are done by the LLM and are therefore non-deterministic.
  Only how the judgments are combined into a status is deterministic.
- **Known limitations:** text-only extraction (checkbox state lost: all boxes read `■`);
  thresholds and criteria are hard-coded for this procedure type; a single test case; no PHI handling.
- **Extraction reliability:** a single LLM call can miss or misread a field, and accuracy hasn't
  been measured (one case only). The design fails safe on the common errors: a missing required field
  or an `unclear` criterion goes to MANUAL_REVIEW, and evidence quotes are checked against the source.
  An error the system can't catch today: a wrong value that is still plausible (e.g. a misread number)
  doesn't block approval. The system is deliberately conservative, trading automation rate for safety.
  Acceptable error rates are a business and regulatory decision, not something this code sets.
- **Improvements with more time:**
  1. **OCR / vision models**, for scanned and faxed documents, which are common in real
     claims and which pypdf can't read. This would also recover checkbox state and handwriting.
  2. **A reviewer frontend**, for staff to upload a case's PDFs and read a formatted report in which
     each criterion links to the quoted evidence, so they can check the AI's recommendation quickly.
  3. **Scalable architecture** (blob storage for files, a queue + workers), for handling high
     volumes asynchronously: uploads aren't blocked by slow LLM calls, failed jobs can be retried,
     and ingestion and processing can scale separately.
  4. **Per-document extraction + deterministic cross-document checks**, for large cases that
     don't fit in one call, and so that consistency checks (e.g. DOB or MRN in each document)
     give the same result on every run instead of depending on the LLM.
  5. **An eval set of labeled cases** (including MANUAL_REVIEW variants), for measuring accuracy and
     catching regressions whenever the prompt, model or rules change. Metrics to track:
     - *wrongful approval rate*: approved, but a human would have sent it to review (the costly error)
     - *unnecessary escalation rate*: sent to review, but should have been approved (costs reviewer time)
     - *automation rate*: share of cases decided without a human (the business value)
     - *field-level extraction accuracy*: per field, for spotting regressions

     With those numbers, targets can be agreed with the business, and the next item can be justified or ruled out.
  6. **Self-consistency voting** (several parallel extraction runs; any disagreement on a decision-critical
     field or criterion goes to MANUAL_REVIEW), for reducing random omissions and unstable judgments.
     Worth it only if the eval shows such instability: it multiplies cost and latency, and runs of the same
     model tend to repeat the same mistakes.
  7. **Criteria as per-procedure config + CPT/ICD-10 validation against reference tables**, for supporting
     procedure types beyond lung biopsy without code changes, and for catching coding errors such as
     an "additional lobe" CPT code when only one lobe is involved.
  8. **Data privacy controls** (de-identification before LLM calls, data residency, audit logging),
     for meeting medical-privacy and insurance-regulation requirements when handling real patient data.
