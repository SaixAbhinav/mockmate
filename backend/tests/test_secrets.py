import os

import boto3
import pytest
from moto import mock_aws

from app.secrets import load_secrets_from_ssm

_ENV_KEYS = ("LOAD_SECRETS_FROM_SSM", "GROQ_API_KEY", "GEMINI_API_KEY",
             "GROQ_SSM_PARAM", "GEMINI_SSM_PARAM")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Isolate from whatever the host shell/.env happens to have set, and
    # make sure a real AWS profile is never picked up by boto3.
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    yield


def _put_params(groq="groq-secret-value", gemini="gemini-secret-value"):
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(Name="/mockmate/GROQ_API_KEY", Value=groq, Type="SecureString")
    ssm.put_parameter(Name="/mockmate/GEMINI_API_KEY", Value=gemini, Type="SecureString")


@mock_aws
def test_loads_both_keys_from_ssm(monkeypatch):
    monkeypatch.setenv("LOAD_SECRETS_FROM_SSM", "1")
    _put_params()

    load_secrets_from_ssm()

    assert os.environ["GROQ_API_KEY"] == "groq-secret-value"
    assert os.environ["GEMINI_API_KEY"] == "gemini-secret-value"


@mock_aws
def test_flag_off_is_a_noop(monkeypatch):
    _put_params()

    load_secrets_from_ssm()

    assert "GROQ_API_KEY" not in os.environ
    assert "GEMINI_API_KEY" not in os.environ


@mock_aws
def test_existing_env_value_is_not_overwritten(monkeypatch):
    monkeypatch.setenv("LOAD_SECRETS_FROM_SSM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "already-set-locally")
    _put_params()

    load_secrets_from_ssm()

    assert os.environ["GROQ_API_KEY"] == "already-set-locally"
    assert os.environ["GEMINI_API_KEY"] == "gemini-secret-value"


@mock_aws
def test_placeholder_value_is_skipped(monkeypatch):
    monkeypatch.setenv("LOAD_SECRETS_FROM_SSM", "1")
    _put_params(gemini="REPLACE_ME")

    load_secrets_from_ssm()

    assert os.environ["GROQ_API_KEY"] == "groq-secret-value"
    assert "GEMINI_API_KEY" not in os.environ


@mock_aws
def test_missing_parameter_does_not_crash(monkeypatch):
    monkeypatch.setenv("LOAD_SECRETS_FROM_SSM", "1")
    # Only create the Groq parameter - Gemini's is missing entirely.
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(Name="/mockmate/GROQ_API_KEY", Value="groq-secret-value", Type="SecureString")

    load_secrets_from_ssm()

    assert os.environ["GROQ_API_KEY"] == "groq-secret-value"
    assert "GEMINI_API_KEY" not in os.environ


@mock_aws
def test_custom_parameter_names_from_env(monkeypatch):
    monkeypatch.setenv("LOAD_SECRETS_FROM_SSM", "1")
    monkeypatch.setenv("GROQ_SSM_PARAM", "/custom/groq")
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(Name="/custom/groq", Value="custom-groq-value", Type="SecureString")

    load_secrets_from_ssm()

    assert os.environ["GROQ_API_KEY"] == "custom-groq-value"
