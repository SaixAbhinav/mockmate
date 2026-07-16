from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.resume import MAX_RESUME_CHARS, ResumeError, extract_resume_text


def test_txt_resume_is_returned_as_text():
    data = b"Experienced ML engineer who built MockMate with LangGraph. " * 5
    text = extract_resume_text(data, "resume.txt", "text/plain")
    assert text == data.decode().strip()


def test_too_short_resume_is_rejected():
    # Nothing to ground warm-up questions in (grilling decision): fail honestly
    # at upload, before any LLM quota is spent.
    with pytest.raises(ResumeError):
        extract_resume_text(b"See my LinkedIn.", "resume.txt", "text/plain")


def test_empty_upload_is_rejected():
    with pytest.raises(ResumeError):
        extract_resume_text(b"", "resume.txt", "text/plain")


def test_oversized_upload_is_rejected():
    with pytest.raises(ResumeError):
        extract_resume_text(b"x" * (2 * 1024 * 1024 + 1), "resume.txt", "text/plain")


def test_unreadable_pdf_is_rejected():
    with pytest.raises(ResumeError):
        extract_resume_text(b"not a pdf at all", "resume.pdf", "application/pdf")


def test_pdf_with_no_extractable_text_is_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)

    with pytest.raises(ResumeError):
        extract_resume_text(buf.getvalue(), "resume.pdf", "application/pdf")


def test_text_is_capped_to_bound_the_prompt():
    text = extract_resume_text(b"a" * (MAX_RESUME_CHARS + 500), "resume.txt", "text/plain")
    assert len(text) == MAX_RESUME_CHARS
