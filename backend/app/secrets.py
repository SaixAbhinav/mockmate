"""Runtime SSM secrets shim (ADR 0029).

Local dev and Render (ADR 0025) get secrets from `backend/.env` via
`load_dotenv()` in `main.py` - that stays untouched. Lambda has no `.env`
file; instead the two provider API keys live in SSM Parameter Store as
SecureString params (`infra/ssm.tf`), and the Lambda's execution role can
`ssm:GetParameter` + `kms:Decrypt` them.

`load_secrets_from_ssm()` bridges the two: called once at import/startup,
right after `load_dotenv()`, it populates `os.environ` so that
`providers.py`'s `os.getenv("GROQ_API_KEY")` / `stt.py`'s equivalent keep
working unchanged regardless of where the process runs.

Gated on `LOAD_SECRETS_FROM_SSM` (set by the Lambda, `infra/lambda.tf`) so
this is a no-op everywhere else - no boto3 call, no AWS credentials
expected, existing local/Render behavior is untouched.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Terraform creates the SSM parameters with this placeholder value and
# `ignore_changes = [value]` (infra/ssm.tf) until the real secret is set
# out-of-band. Never let the placeholder leak into os.environ as if it were
# a real key - that would make provider calls fail with an auth error
# instead of the clearer "no key configured" ScriptedProvider fallback.
_PLACEHOLDER = "REPLACE_ME"

# (env var name, SSM parameter name env var, default SSM parameter name)
_SECRETS = (
    ("GROQ_API_KEY", "GROQ_SSM_PARAM", "/mockmate/GROQ_API_KEY"),
    ("GEMINI_API_KEY", "GEMINI_SSM_PARAM", "/mockmate/GEMINI_API_KEY"),
)


def load_secrets_from_ssm() -> None:
    """Populate `os.environ` from SSM, once, if `LOAD_SECRETS_FROM_SSM` is set.

    No-op when the flag is absent/falsey - local dev and Render never call
    AWS. An env var that is already set (e.g. a local `.env`, or a value
    injected some other way) always wins and is never overwritten. Missing
    parameters or SSM/network errors are logged and swallowed per key: the
    app must still boot even if, say, the Gemini key was never provisioned
    (see `get_provider()`'s Groq-only fallback).
    """
    if not os.getenv("LOAD_SECRETS_FROM_SSM"):
        return

    # Imported lazily so boto3 is only required when this flag is actually
    # set (Lambda) - it need not be on the critical path for local dev/Render
    # environments that don't have it installed.
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client("ssm")

    for env_var, param_env_var, default_param in _SECRETS:
        if os.getenv(env_var):
            continue

        param_name = os.getenv(param_env_var, default_param)
        try:
            response = client.get_parameter(Name=param_name, WithDecryption=True)
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "Could not load %s from SSM parameter %s: %s", env_var, param_name, exc
            )
            continue

        value = response["Parameter"]["Value"]
        if value == _PLACEHOLDER:
            logger.warning(
                "SSM parameter %s still holds the placeholder value - skipping %s",
                param_name,
                env_var,
            )
            continue

        os.environ[env_var] = value
