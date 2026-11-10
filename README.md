# AI Prior-Authorization Review

Reads the PDF documents of a prior-authorization case, extracts the key facts, checks the request against the
approval criteria and returns `APPROVE` or `MANUAL_REVIEW` with a reason. Every decision traces back to specific
criteria and verbatim quotes from the documents.

## Run
Requires [uv](https://docs.astral.sh/uv/) and an Anthropic API key in `ANTHROPIC_API_KEY`.
```bash
uv run python src/main.py cases/PA-2025-847291   # writes output/PA-2025-847291.json, prints the report
uv run pytest                                    # decision-logic tests, no LLM calls
```
The full output for the provided case is in [`output/PA-2025-847291.json`](output/PA-2025-847291.json) (status: `APPROVE`).

## How the recommendation is made
```
cases/<id>/*.pdf
 1. documents.py   PDFs → text (pypdf)
 2. extraction.py  2 parallel LLM calls (claude-opus-5-5, structured output into Pydantic models):
                     A → CaseFacts       patient, request, clinical facts
                     B → CaseAssessment  4 criteria (met / not_met / unclear + verbatim quotes) + discrepancies
 3. decision.py    deterministic, no LLM:
                     quote check → rules → reason from a template
 4. main.py        output/<case_id>.json (required schema) + console report (criteria, evidence, discrepancies)
```
**Criteria** (from the assignment): `suspicious_nodule`, `tissue_sampling_recommended`,
`procedure_matches_findings`, `no_contraindication_in_workup`.

**Quote check:** every evidence quote must appear (whitespace-normalized) in the document it is attributed to.
Otherwise, the criterion is downgraded to `unclear`. This guards against the costly error: a criterion marked
`met` on invented evidence.

**Rules:** `APPROVE` only if all four criteria are `met`, no required field is missing (case ID, patient name and
DOB, procedure, CPT codes, requested date, finding) and no discrepancy is `material`. Otherwise `MANUAL_REVIEW`.
`minor` discrepancies (e.g. the age 72 vs. 73 mismatch, questionable CPT codes, the missing PET-CT report)
are printed as warnings and don't change the status.

**Reason:**
- `APPROVE`: "The submitted documentation supports tissue sampling of a {finding}." followed by the
  `procedure_matches_findings` note.
- `MANUAL_REVIEW`: "Manual review required: " followed by every rule that fired.

## Design decisions
1. **Own `LLMProvider` interface + Anthropic SDK, not LangChain/PydanticAI.** A framework is overkill for two
   fixed calls. The interface keeps the provider swappable while every line stays readable.
2. **Hybrid decision:** the LLM judges each criterion with evidence, and plain code combines the judgments into
   the status. Rejected alternatives:
   - "LLM decides": not auditable, not testable.
   - Pure rules: brittle for judgment criteria such as "procedure matches findings".
3. **Two LLM calls (facts / judgments) instead of one.**
   - *Why it came up:* we started with one combined call, but during development the API rejected its schema
     as too large for structured outputs ("compiled grammar is too large"). Probing showed each half fits on
     its own, and the whole schema fits only if no field may be null.
   - *Alternatives considered:*
     - One call with no nullable fields: weaker "missing" semantics, special-case code, and right at the size limit.
     - One call without constrained output: loses the guarantee of schema-valid output.
   - *Why the split:*
     - separation of concerns (reading vs. judging)
     - an easier job per call
     - room for each schema to grow
   - *Cost:* about twice the input tokens (cents per case); the two calls may word a fact differently, which
     doesn't affect the decision.
4. **Reason from a template, not a second LLM call.** It is built from the same data as the status, so the two
   can't contradict each other. It is deterministic, testable and free.
5. **The APPROVE reason quotes the `procedure_matches_findings` note** instead of a separately extracted
   justification. That note backs the exact judgment the rules relied on, and its quotes passed the check, so it
   can't drift from the decision.
6. **Output is exactly the required schema.** Criteria, evidence and warnings go to the console report.
7. **Tests** cover the decision logic with hand-written LLM outputs (fast, free, deterministic), plus one saved live run.
8. **No fallback model.** If the model refuses or its output is truncated, the run fails with a clear error.
   The SDK's server-side fallback to another model was left out to keep things simple.

## Prompt iteration
A good part of the work on an LLM app like this is comparing the model's output with the expected output,
using human judgment to decide what is wrong, and adjusting the prompt. Rounds on the provided case:

| Problem seen | Fix |
|---|---|
| CPT-code issue marked `material`, which would have sent the case to MANUAL_REVIEW | `material` narrowed to issues that put clinical justification in doubt; coding and admin issues are `minor` (still listed) |
| The `procedure_matches_findings` note (quoted in the reason) hedged about billing codes | Notes address only their own criterion |
| False discrepancy "both checkboxes marked", caused by our text extraction | Prompt states that checkbox state is lost |
| The reason didn't explain why the approach suits the *patient* | The note must cover both the lesion and the patient (e.g. comorbidities) |
| `finding` came out as a long sentence | Defined as a short noun phrase |

Lesson: hints in schema field descriptions were sometimes ignored; explicit prompt lines worked. With one case
this is a sanity check, not a measurement. An eval set (below) would make prompt changes measurable.

## Assumptions, limitations and reliability
- **Assumptions:**
  - A whole case fits in one LLM context.
  - Criteria judgments and discrepancy detection are done by the LLM, so they are non-deterministic; only
    combining them into a status is deterministic. The wording of the reason and the discrepancy list vary
    between runs.
- **Limitations:**
  - Text-only PDF extraction: no scanned documents, and checkbox state is lost (every box reads `■`).
  - Criteria are hard-coded for this procedure type.
  - A single test case.
  - No handling of patient-data privacy.
- **Reliability:**
  - An LLM call can miss or misread a field, and accuracy hasn't been measured.
  - The design fails safe on the common errors: a missing required field, an `unclear` criterion or an
    unverifiable quote goes to MANUAL_REVIEW.
  - Not caught: a wrong but plausible value (e.g. a misread number). The system is deliberately conservative,
    trading automation rate for safety.
  - Acceptable error rates are a business and regulatory decision.

## Improvements with more time
1. **OCR / vision models**, for scanned and faxed documents, which are common in real claims. This would also
   recover checkbox state and handwriting.
2. **A reviewer frontend**, for staff to upload a case and read a formatted report in which each criterion links
   to its quoted evidence, so they can check the AI's recommendation quickly.
3. **Scalable architecture** (blob storage, a queue + workers), for processing high volumes asynchronously:
   uploads aren't blocked by slow LLM calls, failed jobs can be retried, and the parts scale separately.
4. **Per-document extraction + deterministic cross-document checks**, for large cases, and so that consistency
   checks (e.g. DOB or MRN in each document) give the same result on every run.
5. **An eval set of labeled cases** (including MANUAL_REVIEW variants), for measuring accuracy and catching
   regressions when the prompt, model or rules change. Metrics:
   - *wrongful approval rate* (the costly error)
   - *unnecessary escalation rate* (costs reviewer time)
   - *automation rate* (the business value)
   - *per-field extraction accuracy*
6. **Self-consistency voting** (several parallel runs; any disagreement goes to MANUAL_REVIEW), for reducing
   random omissions and unstable judgments. Worth it only if the eval shows instability: it multiplies cost,
   and runs of the same model tend to repeat the same mistakes.
7. **Criteria as per-procedure config + CPT/ICD-10 validation against reference tables**, for supporting other
   procedure types without code changes, and for catching coding errors deterministically.
8. **Retry and fallback logic**, for production resilience: retry with backoff when a call returns no valid
   result, and fall back to another model on refusal. Today the SDK retries only transport errors.
9. **Data privacy controls** (de-identification before LLM calls, data residency, audit logging), for
   medical-privacy and insurance-regulation requirements.

## How this was built
Planned interactively with Claude Code (see [`PLAN.md`](PLAN.md)), then implemented in small slices, each
reviewed and committed separately (see the git history).
