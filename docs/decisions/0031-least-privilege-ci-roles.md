# ADR 0031: Split the CI role in two — main-only deploy, read-only PR plan

Date: 2026-08-11 · Status: accepted · shipped · Hardens [0029](0029-serverless-aws-deploy.md)'s PR 4

## Context

[ADR 0029](0029-serverless-aws-deploy.md)'s PR 4 gave GitHub Actions a single
IAM role, `mockmate-github-deploy`, with `PowerUserAccess` plus a narrow
project-scoped IAM top-up, trusted by:

```
repo:SaixAbhinav/mockmate:*
```

That wildcard was a deliberate, documented shortcut — both workflows needed a
role, and `infra/iam_github_oidc.tf` recorded the intent to tighten it "once
the pipeline is proven out." As of 2026-08-11 that condition is met: three
`Deploy` runs on `main` have gone green end to end, including image build,
`terraform apply`, frontend sync, CloudFront invalidation, and the
`/api/health` smoke test.

The shortcut is worth stating plainly as a security property, because it is
sharper than "broad permissions":

- `terraform-plan.yml` runs on `pull_request`, and PR workflows execute the
  workflow definition **from the PR's own branch**.
- That job assumed a `PowerUserAccess` role.
- So anyone who could open a pull request could edit `terraform-plan.yml` to
  run arbitrary AWS commands with near-account-wide power.

For a personal repo with no outside contributors the practical exposure is
low, and nothing suggests it was ever used. But the gap is structural rather
than theoretical, and it is cheap to close now that the pipeline works.

## Decision

**Split the single role into two, one per workflow context.**

| Role | Assumed by | Trust (`sub`) | Permissions |
|---|---|---|---|
| `mockmate-github-deploy` | `deploy.yml` | `repo:SaixAbhinav/mockmate:ref:refs/heads/main` | `PowerUserAccess` + existing IAM top-up (unchanged) |
| `mockmate-github-plan` | `terraform-plan.yml` | `repo:SaixAbhinav/mockmate:pull_request` | `ReadOnlyAccess` + state-lock + `kms:Decrypt` |

Both trust conditions are `StringEquals`, not `StringLike`. There is no
remaining wildcard in either `sub`: a fork PR, or a branch named to resemble
`main`, cannot mint either subject. Between the two, every workflow context in
this repo maps to exactly one role, and the mapping is exhaustive — a new
workflow in some other context gets no credentials at all until it is granted
them deliberately.

`plan` needs two things `ReadOnlyAccess` does not cover, both scoped as
tightly as the operation allows:

- **State locking.** Terraform takes the DynamoDB lock before refreshing, even
  for a read-only plan, so the role needs `GetItem`/`PutItem`/`DeleteItem` —
  on `mockmate-tflock` only, never the app's session table.
- **SecureString decryption.** The two SSM parameters are SecureString and the
  provider reads them with decryption on every refresh. `ReadOnlyAccess`
  grants `ssm:GetParameter` but not `kms:Decrypt`, so plans would fail on those
  two resources. Scoped to the account's default SSM key.

The IAM top-up on the deploy role is left exactly as PR 4 wrote it — it was
already resource-scoped to `mockmate-*` with `iam:PassRole` separated out and
conditioned on `lambda.amazonaws.com`. Nothing there needs loosening or
tightening.

## Consequences

**Good.** The blast radius of a malicious or careless PR drops from
"near-account-wide write" to "read, plus one lock row." Mutating AWS now
requires a merge to `main`, which is what branch protection already governs —
so the security boundary and the review boundary finally coincide.

**Cost: one more bootstrap step.** The same chicken-and-egg as PR 4, one layer
down. `terraform-plan.yml` on *this* PR will reference `mockmate-github-plan`
before that role exists, so its own plan check fails until the role is created.
Options, in preference order:

1. Create the role out-of-band before opening the PR, matching how PR 4's role
   and the state backend were bootstrapped:
   `terraform apply -target=aws_iam_role.github_plan -target=aws_iam_role_policy_attachment.github_plan_read_only -target=aws_iam_role_policy.github_plan_state_access`
2. Merge with the failing check overridden, and let `deploy.yml` create it on
   the first post-merge run.

Option 1 is preferred: it keeps `main` green and matches the precedent already
documented in `infra/README.md`.

**Ordering constraint.** The deploy role's trust narrows in the same apply that
creates the plan role. That apply runs *as* the deploy role, from `main`, whose
`sub` already satisfies the new tighter condition — so it does not saw off the
branch it is sitting on. A `deploy.yml` run triggered from anywhere other than
`main` would lose access, but the workflow only triggers on `main` pushes.

**Deferred.** `PowerUserAccess` on the deploy role stays. Enumerating
least-privilege across ECR, Lambda, API Gateway, CloudFront, S3, DynamoDB, SSM,
KMS and CloudWatch for an unattended full-stack apply is a large, brittle job,
and with trust now pinned to `main` the remaining exposure requires merge
access — i.e. the account owner. If this repo ever takes outside contributors,
revisit that before anything else here.
