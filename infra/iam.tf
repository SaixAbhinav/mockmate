# Lambda execution role (ADR 0029). PR 2b's Lambda function assumes this
# role; created here so it (and the DynamoDB table/SSM parameters it
# references) exist independently of the function.

# The account's default SSM SecureString KMS key. Looked up by alias
# rather than hard-coded so the ARN is always correct for this account/
# region without guessing the key ID.
data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

resource "aws_iam_role" "lambda_exec" {
  name = "mockmate-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "mockmate-lambda-exec"
  }
}

# AWS-managed policy covering CloudWatch Logs (CreateLogGroup/Stream,
# PutLogEvents) - the baseline every Lambda function needs.
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Everything the app itself needs, scoped to exactly the resources this
# PR created - no wildcards, no actions the code doesn't call.
resource "aws_iam_role_policy" "lambda_app_access" {
  name = "mockmate-lambda-app-access"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # backend/app/session_store.py's DynamoDBSessionStore calls exactly
        # get_item, put_item, and delete_item (the latter two also used,
        # with ConditionExpression, for claim_evaluation /
        # release_evaluation_claim - conditional writes need no extra IAM
        # action beyond PutItem/DeleteItem). No Query/Scan/UpdateItem.
        Sid    = "DynamoDBSessionStoreAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = aws_dynamodb_table.sessions.arn
      },
      {
        Sid    = "ReadSecretParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
        ]
        Resource = [
          aws_ssm_parameter.groq_api_key.arn,
          aws_ssm_parameter.gemini_api_key.arn,
        ]
      },
      {
        # SecureString parameters are encrypted with the account's default
        # SSM KMS key; reading them requires Decrypt on that key too.
        Sid      = "DecryptSecretParameters"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}
