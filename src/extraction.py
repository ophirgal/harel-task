"""LLM calls over all of a case's documents, run in parallel:
A) extract the facts, B) assess the approval criteria and list discrepancies."""

from concurrent.futures import ThreadPoolExecutor

from documents import Document
from llm import LLMProvider
from schemas import CaseAssessment, CaseFacts

_CONTEXT = """\
You assist an insurance reviewer with a prior-authorization request. You receive all documents of one case,
as text extracted from PDFs. Checkbox state is lost in extraction: every box appears as "■", checked or not.
"""

FACTS_PROMPT = _CONTEXT + """\
Extract the requested fields using only what the documents state.
- If a value is not in the documents, use null (or an empty list). Never guess or infer missing values.
- When documents disagree on a value, use the one from the most authoritative source for it
  (e.g. the radiology report for imaging findings, the lab report for lab values).
"""

ASSESSMENT_PROMPT = _CONTEXT + """\
Criteria:
- Assess each criterion independently: "met" only if the documents clearly support it, "not_met" if they
  clearly contradict it, otherwise "unclear".
- Evidence quotes must be copied character-for-character from the named document: short, contiguous spans of
  text (a phrase or one sentence). Do not paraphrase, merge or shorten quotes.

Discrepancies:
- Compare the documents with each other and list every inconsistency you find (identifiers, dates, ages,
  findings, codes, history, missing referenced documents).

You do not decide whether the request is approved; that is done separately from your assessments.
"""


def extract_case(documents: list[Document], llm: LLMProvider) -> tuple[CaseFacts, CaseAssessment]:
    text = _format_documents(documents)
    with ThreadPoolExecutor(max_workers=2) as pool:
        facts = pool.submit(llm.generate_structured, FACTS_PROMPT, text, CaseFacts)
        assessment = pool.submit(llm.generate_structured, ASSESSMENT_PROMPT, text, CaseAssessment)
        return facts.result(), assessment.result()


def _format_documents(documents: list[Document]) -> str:
    return "\n\n".join(f'<document name="{doc.name}">\n{doc.text}\n</document>' for doc in documents)
