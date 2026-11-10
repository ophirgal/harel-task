"""Load a case's PDF documents as plain text."""

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class Document:
    name: str  # file name; the LLM cites evidence by it
    text: str


def load_case_documents(case_dir: Path) -> list[Document]:
    """Read every PDF in the case directory, sorted by file name."""
    paths = sorted(case_dir.glob("*.pdf"))
    if not paths:
        raise FileNotFoundError(f"No PDF files found in {case_dir}")
    return [Document(name=path.name, text=_extract_text(path)) for path in paths]


def _extract_text(path: Path) -> str:
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)
