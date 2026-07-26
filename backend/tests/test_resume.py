from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.resume import (
    MAX_DIGEST_CHARS,
    MAX_RESUME_CHARS,
    ResumeError,
    extract_resume_text,
    vocabulary_digest,
)


# The digest biases Whisper toward the proper nouns it otherwise mangles
# (ADR 0026). Cases below are the real misreadings from a deployed Session.

_RESUME = """\
Sai Abhinav
Machine Learning Engineer

EDUCATION
Vivekananda Institute of Professional Studies

PROJECTS
Workflow Copilot: automates email triage.
SmartSignal: anomaly detection over sensor streams.
Trained a classifier on the HAM10000 dataset using PyTorch.
"""


def test_digest_includes_the_candidate_name():
    assert "Sai Abhinav" in vocabulary_digest(_RESUME)


def test_digest_keeps_a_multi_word_institution_together():
    # "Vivekan and the Institute" was the real misreading; connectors like "of"
    # must not split the phrase.
    assert "Vivekananda Institute of Professional Studies" in vocabulary_digest(_RESUME)


def test_digest_includes_camel_case_product_names():
    digest = vocabulary_digest(_RESUME)
    assert "Workflow Copilot" in digest
    assert "SmartSignal" in digest


def test_digest_includes_alphanumeric_terms():
    assert "HAM10000" in vocabulary_digest(_RESUME)


def test_digest_drops_section_headings():
    digest = vocabulary_digest(_RESUME)
    assert "EDUCATION" not in digest
    assert "PROJECTS" not in digest


def test_digest_does_not_repeat_terms():
    digest = vocabulary_digest("PyTorch and PyTorch and PyTorch again.")
    assert digest.count("PyTorch") == 1


def test_digest_is_capped():
    text = " ".join(f"Alphaterm{i}" for i in range(500))
    assert len(vocabulary_digest(text)) <= MAX_DIGEST_CHARS


def test_digest_of_unremarkable_prose_is_empty():
    # Nothing distinctive to bias toward; sentence-initial words are not names.
    assert vocabulary_digest("the quick brown fox jumped over it") == ""


def test_digest_of_empty_text_is_empty():
    assert vocabulary_digest("") == ""


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
