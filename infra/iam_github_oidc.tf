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

# The role deploy.yml assumes to apply this stack and push images/frontend
# assets. Trust is scoped to this one repo via the `sub` claim; `aud` is
# pinned to STS per AWS's standard GitHub OIDC guidance.
#
# Trust is restricted to the `main` branch ref specifically (ADR 0031). It
# was `repo:SaixAbhinav/mockmate:*` through PR 4, which meant any branch or
# PR context in the repo could assume a PowerUserAccess role - so anyone who
# could open a PR could run arbitrary AWS actions by editing a workflow. The
# pipeline is now proven out, which was the stated condition for tightening.
# PR plans use `github_plan` below instead.
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
          # Both keys must sit inside StringEquals - a condition key placed
          # directly under Condition is read as an operator name and IAM
          # rejects the document with "Invalid condition prefix".
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            # Exact match on the main-branch ref, not a StringLike wildcard:
            # a PR from a fork or a branch named to look like main cannot
            # produce this `sub`. GitHub mints it from the ref that triggered
            # the run, so only a push to main yields it.
            "token.actions.githubusercontent.com:sub" = "repo:SaixAbhinav/mockmate:ref:refs/heads/main"
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

# The role terraform-plan.yml assumes on pull requests (ADR 0031).
#
# Separate from the deploy role because the two jobs need genuinely
# different power: `plan` only reads the world and compares it to the
# config, while `apply` mutates it. Since PR workflows run code from the
# PR's own branch, whatever this role can do is effectively what any
# contributor can do - so it gets read-only plus the narrow state-backend
# access `plan` needs, and nothing else.
resource "aws_iam_role" "github_plan" {
  name = "mockmate-github-plan"

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
            # `pull_request` is the sub GitHub mints for pull_request-event
            # runs, regardless of the head branch's name. Pairs with the
            # deploy role's main-only ref: between them, every workflow
            # context in this repo maps to exactly one role.
            "token.actions.githubusercontent.com:sub" = "repo:SaixAbhinav/mockmate:pull_request"
          }
        }
      }
    ]
  })

  tags = {
    Name = "mockmate-github-plan"
  }
}

# `terraform plan` refreshes every resource in the stack, so it needs broad
# *read* across the same services the deploy role writes. ReadOnlyAccess is
# the mirror of PowerUserAccess's role here: service-wide, but incapable of
# mutating anything.
resource "aws_iam_role_policy_attachment" "github_plan_read_only" {
  role       = aws_iam_role.github_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Two things `plan` needs that ReadOnlyAccess does not cover.
resource "aws_iam_role_policy" "github_plan_state_access" {
  name = "mockmate-github-plan-state-access"
  role = aws_iam_role.github_plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # State locking is a *write* to the lock table even on a read-only
        # plan - Terraform takes the lock before refreshing and releases it
        # after. Without this, every PR plan fails to acquire the lock.
        # Scoped to the lock table alone, not the app's session table.
        Sid    = "AcquireAndReleaseStateLock"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = "arn:aws:dynamodb:${var.region}:356252962813:table/mockmate-tflock"
      },
      {
        # The two SSM parameters are SecureString. The provider reads them
        # with decryption on every refresh, and ReadOnlyAccess grants
        # ssm:GetParameter but not the kms:Decrypt that SecureString needs
        # - so a plan would fail on those two resources without this.
        # Scoped to the account's default SSM key only.
        Sid      = "DecryptSsmSecureStrings"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}
