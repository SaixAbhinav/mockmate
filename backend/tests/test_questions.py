import pytest

from app.questions import QuestionBankError, load_bank


def test_ml_genai_bank_has_at_least_fifteen_questions():
    questions = load_bank("ml_genai")
    assert len(questions) >= 15


def test_each_question_has_required_fields():
    questions = load_bank("ml_genai")
    for q in questions:
        assert q.domain == "ml_genai"
        assert q.topic
        assert q.difficulty in ("easy", "medium", "hard")
        assert q.question
        assert isinstance(q.follow_up_hints, list) and q.follow_up_hints


def test_unknown_domain_raises():
    with pytest.raises(QuestionBankError):
        load_bank("does_not_exist")


def test_invalid_difficulty_raises(tmp_path, monkeypatch):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "- domain: bad\n"
        "  topic: t\n"
        "  difficulty: impossible\n"
        "  question: q\n"
        "  follow_up_hints: [h]\n",
        encoding="utf-8",
    )
    with pytest.raises(QuestionBankError):
        load_bank("bad", questions_dir=tmp_path)


def test_missing_field_raises(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "- domain: bad\n"
        "  topic: t\n"
        "  difficulty: easy\n"
        "  follow_up_hints: [h]\n",
        encoding="utf-8",
    )
    with pytest.raises(QuestionBankError):
        load_bank("bad", questions_dir=tmp_path)
