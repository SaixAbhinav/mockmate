"""Resume ingestion (ADR 0015): turn an uploaded resume into capped plain text.

The text grounds warm-up question generation and nothing else. It is PII:
never log it, and never echo it back in error details.
"""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # a resume, not a book
MAX_RESUME_CHARS = 15_000  # bounds the generation prompt (~4K tokens)
MIN_RESUME_CHARS = 200  # below this there is nothing to ground questions in


class ResumeError(Exception):
    """The upload could not be turned into usable resume text."""


def extract_resume_text(data: bytes, filename: str, content_type: str) -> str:
    """Extract plain text from a PDF or UTF-8 text resume.

    Raises ResumeError on anything unusable; the caller maps that to a 400.
    """
    if not data:
        raise ResumeError("empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ResumeError("resume too large (2 MB max)")

    if filename.lower().endswith(".pdf") or content_type == "application/pdf":
        try:
            reader = PdfReader(BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except (PdfReadError, ValueError) as exc:
            raise ResumeError("could not read the PDF") from exc
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResumeError("only PDF or UTF-8 text resumes are supported") from exc

    text = text.strip()
    if not text:
        raise ResumeError("no text could be extracted from the resume")
    if len(text) < MIN_RESUME_CHARS:
        raise ResumeError("resume too short to ground warm-up questions")
    return text[:MAX_RESUME_CHARS]
