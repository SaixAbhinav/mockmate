# The Lambda function itself (ADR 0029, PR 2b). Runs the backend image built
# from the repo-root Dockerfile (with the AWS Lambda Web Adapter extension),
# pushed to PR 2a's ECR repository. This resource does not build or push
# that image - see infra/README.md's deploy runbook for the ordered steps;
# the image must already exist at `image_uri` before `apply` can create the
# function.

resource "aws_lambda_function" "backend" {
  function_name = "mockmate-backend"
  role          = aws_iam_role.lambda_exec.arn

  package_type = "Image"
  image_uri    = "${aws_ecr_repository.backend.repository_url}:${var.image_tag}"

  architectures = ["x86_64"]
  memory_size   = 1024

  # Deliberately > API Gateway HTTP APIs' ~30s integration timeout cap. A
  # full Evaluation is ~9 LLM calls and can run long enough for the gateway
  # to give up and return 504 to the caller - that is tolerated by design
  # (ADR 0029, "Race A"): letting the Lambda run to 60s means the winner of
  # the race still finishes and CACHES the Evaluation (DynamoDBSessionStore,
  # claim_evaluation) even after its own HTTP response was lost to the
  # gateway timeout. The frontend's retry (or whichever request lost the
  # claim race) then reads the cached result fast. Do not "fix" the 504 by
  # trying to make API Gateway wait longer - it can't, past its own cap.
  timeout = 60

  environment {
    variables = {
      # ADR 0029: Lambda has no local disk state across invocations/across
      # concurrent instances, so the in-memory SessionStore (ADR 0007) is
      # replaced with the DynamoDB-backed one for this deploy target.
      SESSION_STORE      = "dynamodb"
      MOCKMATE_DDB_TABLE = aws_dynamodb_table.sessions.name

      # Tells backend/app/secrets.py to populate GROQ_API_KEY/GEMINI_API_KEY
      # from SSM (infra/ssm.tf) at startup - local dev/Render don't set this
      # and keep reading from .env, untouched.
      LOAD_SECRETS_FROM_SSM = "1"

      # AWS Lambda Web Adapter (Dockerfile) configuration: proxy API Gateway
      # traffic to uvicorn on 8080, and poll /api/health as the readiness
      # check before the adapter reports the extension healthy.
      AWS_LWA_PORT                 = "8080"
      PORT                         = "8080"
      AWS_LWA_READINESS_CHECK_PATH = "/api/health"

      # NOTE: do not set AWS_REGION here - it is a reserved Lambda runtime
      # environment variable and `apply` will fail if it's declared.
    }
  }

  tags = {
    Name = "mockmate-backend"
  }
}
