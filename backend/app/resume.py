"""Resume ingestion (ADR 0015): turn an uploaded resume into capped plain text.

The text grounds warm-up question generation and a transcription vocabulary
digest (ADR 0026), and nothing else. It is PII: never log it, and never echo it
back in error details.
"""

import re
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # a resume, not a book
MAX_RESUME_CHARS = 15_000  # bounds the generation prompt (~4K tokens)
MIN_RESUME_CHARS = 200  # below this there is nothing to ground questions in

# Whisper's prompt window is ~224 tokens; this keeps the digest comfortably
# inside it, and short prompts are also less prone to bleeding into the
# transcript (ADR 0026).
MAX_DIGEST_CHARS = 600

# Words that are capitalised in a resume without being distinctive: section
# headings and ordinary sentence openers. A phrase made *only* of these is
# dropped; they are still allowed inside a longer phrase, so "Professional
# Studies" survives as part of an institution name.
_GENERIC_WORDS = frozenset(
    """
    a an and as at by for from in of on or the to with
    education experience projects project skills summary objective
    certifications achievements work professional technical contact
    university college institute school degree bachelor master
    present current responsibilities technologies tools languages
    i my we this that it he she they
    built used using developed trained designed implemented created
    led managed shipped owned evaluated migrated deployed wrote
    """.split()
)

# Lowercase words allowed to sit *between* capitalised words without breaking
# the phrase - "Vivekananda Institute of Professional Studies". Only words that
# occur *inside* a name belong here: "and" and friends join separate items
# ("PyTorch and TensorFlow"), so treating them as connectors would fuse two
# terms into one phrase that dedupe can never match.
_CONNECTORS = frozenset("of the de la von van".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*")


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


def _is_distinctive(word: str) -> bool:
    """A word worth biasing transcription toward: a proper noun, a CamelCase
    product name, or an alphanumeric identifier like HAM10000."""
    if any(c.isdigit() for c in word) and any(c.isalpha() for c in word):
        return True
    if not word[0].isupper():
        return False
    if word.isupper():  # ALL-CAPS section headings, not names
        return False
    if any(c.isupper() for c in word[1:]):  # SmartSignal, PyTorch
        return True
    return len(word) > 1


def vocabulary_digest(text: str, max_chars: int = MAX_DIGEST_CHARS) -> str:
    """Proper nouns and distinctive terms from a resume, as a comma-separated
    list to prime speech-to-text (ADR 0026).

    Whisper has no way to know a Candidate's name, institution or project names,
    so it mangles exactly the words the warm-up round is about. Heuristics are
    used rather than an LLM call so Session creation gains no new failure mode;
    capitalisation is what makes these terms findable.
    """
    phrases: list[str] = []
    seen: set[str] = set()

    for line in text.splitlines():
        current: list[str] = []
        for raw in _WORD.findall(line):
            word = raw.strip(".-")
            if not word:
                continue
            if _is_distinctive(word):
                current.append(word)
                continue
            # A connector continues a phrase already in progress; anything else
            # ends it. A trailing connector is dropped ("Institute of" alone).
            if current and word.lower() in _CONNECTORS:
                current.append(word)
                continue
            _flush(current, phrases, seen)
            current = []
        _flush(current, phrases, seen)

    digest = ""
    for phrase in phrases:
        candidate = f"{digest}, {phrase}" if digest else phrase
        if len(candidate) > max_chars:
            break
        digest = candidate
    return digest


def _flush(current: list[str], phrases: list[str], seen: set[str]) -> None:
    """Record a completed phrase, unless it is generic or already present."""
    while current and current[-1].lower() in _CONNECTORS:
        current.pop()
    if not current:
        return
    if all(word.lower() in _GENERIC_WORDS for word in current):
        return
    phrase = " ".join(current)
    key = phrase.lower()
    if key not in seen:
        seen.add(key)
        phrases.append(phrase)
