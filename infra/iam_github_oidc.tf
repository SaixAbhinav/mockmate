# GitHub Actions OIDC federation + deploy role (ADR 0029, PR 4).
#
# Headline property: GitHub Actions authenticates to AWS by exchanging a
# short-lived OIDC token for temporary STS credentials via
# AssumeRoleWithWebIdentity - no long-lived AWS access key is ever stored
# in a GitHub secret. See infra/README.md's "CI/CD" section for the
# one-time bootstrap this depends on (this provider + role must exist
# before any workflow can assume the role, so the first `apply` creating
# them has to run locally, not from a workflow that needs them to run).

# The GitHub Actions OIDC identity provider. `thumbprint_list` is
# deliberately omitted: GitHub is one of the IdPs the AWS provider (v5.x)
# documents as using its own trusted root CA bundle for validation
# regardless of any configured thumbprint, and IAM will auto-populate a
# thumbprint from GitHub's server certificate if none is given. Hardcoding
# one would be dead weight that could silently go stale as GitHub rotates
# its TLS certificate chain.
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = ["sts.amazonaws.com"]

  tags = {
    Name = "mockmate-github-oidc"
  }
}

# The role GitHub Actions assumes to plan/apply this stack and push
# images/frontend assets. Trust is scoped to this one repo via the `sub`
# claim; `aud` is pinned to STS per AWS's standard GitHub OIDC guidance.
resource "aws_iam_role" "github_deploy" {
  name = "mockmate-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          # Any branch/ref/PR/environment in this repo can assume the
          # role. Deliberately broad for now (both terraform-plan.yml on
          # PRs and deploy.yml on main need it) - tighten to
          # "repo:SaixAbhinav/mockmate:ref:refs/heads/main" (deploy) plus
          # a separate, lower-privileged role for PR plans once the
          # pipeline is proven out.
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:SaixAbhinav/mockmate:*"
          }
        }
      }
    ]
  })

  tags = {
    Name = "mockmate-github-deploy"
  }
}

# The deploy role runs an unattended `terraform apply` over the entire
# stack (ECR, Lambda, API Gateway, CloudFront, S3, DynamoDB, SSM, KMS,
# CloudWatch Logs) plus pushes images and syncs the frontend bundle - it
# needs broad service access, not a hand-enumerated action list per
# resource. PowerUserAccess is the pragmatic fit: every AWS-service action
# short of IAM itself. The primary guardrail against misuse is the
# repo-scoped trust policy above, not fine-grained permissions here;
# tightening this to least-privilege is deferred, tracked as follow-up
# hardening once the pipeline is proven out.
resource "aws_iam_role_policy_attachment" "github_deploy_power_user" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# PowerUserAccess explicitly excludes IAM. Terraform manages three IAM
# resources as part of this stack (the Lambda execution role in iam.tf,
# this OIDC provider, and this deploy role itself), so the deploy role
# needs a narrow, project-scoped top-up for exactly those IAM actions -
# never `iam:*` on `*`.
resource "aws_iam_role_policy" "github_deploy_iam_management" {
  name = "mockmate-github-deploy-iam-management"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Deliberately does NOT include iam:PassRole - that's granted
        # below, narrowly, only for the one role Terraform actually
        # passes to another service. Keeping PassRole out of this
        # wildcard statement means a future mockmate-* role with more
        # power doesn't automatically become passable too.
        Sid    = "ManageMockmateRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:UpdateRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
        ]
        Resource = "arn:aws:iam::356252962813:role/mockmate-*"
      },
      {
        # Terraform passes this role to the Lambda function (PR 2b) on
        # every apply - scoped to exactly this one role, not the
        # mockmate-* wildcard above.
        Sid      = "PassLambdaExecRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.lambda_exec.arn
        # Only Lambda may receive this role - a holder of these creds can't
        # pass mockmate-lambda-exec to some other service.
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "lambda.amazonaws.com"
          }
        }
      },
      {
        Sid    = "ManageGithubOidcProvider"
        Effect = "Allow"
        Action = [
          "iam:CreateOpenIDConnectProvider",
          "iam:DeleteOpenIDConnectProvider",
          "iam:GetOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:AddClientIDToOpenIDConnectProvider",
          "iam:RemoveClientIDFromOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider",
          "iam:UntagOpenIDConnectProvider",
        ]
        Resource = "arn:aws:iam::356252962813:oidc-provider/token.actions.githubusercontent.com"
      },
    ]
  })
}
