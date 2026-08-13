# ADR 0029: Serverless AWS deploy — Terraform IaC and idempotent state at scale

Date: 2026-07-29 · Status: accepted · shipped · Supersedes [0025](0025-deploy-render-static-plus-api.md)'s host on cutover

## Context

[ADR 0025](0025-deploy-render-static-plus-api.md) deployed MockMate on Render as a
static SPA plus one long-lived API container, and **explicitly ruled serverless
out**: "the in-memory sessions and the subprocess runner together also rule out a
serverless host… MockMate's backend is a *server, not a set of functions*."

This ADR reopens that decision, but **not on the axis 0025 optimised for.** 0025
chased first-impression latency at a portfolio's demo exposure. This one is driven
by a different, explicit goal: **a legibly real serverless AWS deployment that
demonstrates cloud-architecture competence, kept inside the free tier.** Cost is a
*bound here, not the point* — the point is what the build proves.

That reframing is load-bearing, so it is stated plainly. The resume-legible value
of this project is **not "used AWS"** — Lambda-as-a-noun is commodity and "$0/mo"
can read as "toy with no traffic." The value is two things Render *structurally
cannot generate*:

1. **Everything defined in Terraform, deployed by an OIDC-authenticated CI/CD
   pipeline** — reproducible infrastructure as the actual day-job skill, with a
   keyword recruiters search for.
2. **Distributed-state correctness under horizontal scale** — replacing an
   in-process lock with a DynamoDB conditional write so a Session is evaluated
   exactly once even when requests fan out across containers. A single always-on
   process *never forces this problem*, which is exactly why solving it signals
   something a Render deploy can't.

Two of 0025's three objections to serverless have since changed, and the third was
never true:

- **The session dict is no longer read directly.** When 0025 was written, 0021's
  `SessionStore` seam was "not wired." It is now: every access in `main.py` goes
  through `get_store()` ([`main.py:351`](../../backend/app/main.py), `:372`, `:474`,
  `:501`, `:597`, `:626`, `:650`, `:675`, `:686`). A DynamoDB-backed store is
  exactly the "single new class implementing `SessionStore` plus a one-line edit to
  `get_store()`" ADR 0021 promised. Stateless invocations no longer lose state,
  because no invocation holds it.
- **The runner fits Lambda, it doesn't fight it.** `runner.py` runs candidate code
  as `subprocess.run(python -I, …)` in a temp dir under a timeout
  ([`runner.py:139`](../../backend/app/runner.py)). Lambda gives each invocation a
  writable `/tmp` and permits child processes; a 5–10s per-submission timeout sits
  far inside Lambda's 15-minute ceiling. Same soft subprocess sandbox as on Render.
- **The third objection — the runner "fights serverless limits" — does not survive
  contact with what the runner actually does.**

**The near-free bound, verified against pulled pricing (2026-07-29):**

| Component | Choice | Cost at demo scale (~200 interviews/mo) |
|---|---|---|
| Lambda (x86) | backend + runner in one function | $0 — ~12k invocations vs 1M always-free |
| DynamoDB on-demand | sessions + evaluations | $0 — inside 25 GB + free ops |
| S3 + CloudFront | static frontend | $0 — inside 1M req / 100 GB egress |
| API Gateway (HTTP API) | `/api/*` origin | $0 for 12 months (1M req), then ~$0.01/mo |
| Terraform / GitHub Actions | IaC + CI/CD | $0 — code + CLI; Actions free at this scale |
| CloudWatch | 1 dashboard, ~10 alarms, logs | $0 — inside 3-dashboard / 10-alarm / 5 GB free |
| SSM Parameter Store | secrets (SecureString) | $0 — free standard parameters |

The bound holds at ~$0/month. Three lines are where it *stops* being free and are
watched, not assumed: **CloudWatch is the trap** (dashboards past 3 cost $3/mo
each, so we hold to one), **API Gateway's free tier is 12-month** (year-two cents),
and the **new-account Free plan auto-closes at 6 months** — persisting requires
upgrading to the Paid plan, which keeps every always-free allowance and just needs
a card on file. LLM inference stays on Groq/Gemini free tiers (ADR 0014) and never
touches this bill — the reason Bedrock is rejected below.

## Decision

**Deploy MockMate fully serverless on AWS, defined entirely in Terraform and
deployed by CI/CD: CloudFront in front of an S3 static frontend and an API Gateway
HTTP API, the FastAPI backend on Lambda, session state in DynamoDB.**

**Topology (one apparent origin, preserved from 0025).**
- **CloudFront** is the single edge. `/` → **S3** (the Vite build). `/api/*` →
  **API Gateway HTTP API** → **Lambda**. Because everything is one CloudFront
  origin, the frontend's relative `fetch('/api/...')` paths keep working and
  **production needs no CORS** — the exact property 0025's rewrite held.
- **API Gateway HTTP API**, not REST (cheaper, simpler) and not a bare Function URL
  (a Function URL is near-invisible on a resume; API Gateway is the recognizable,
  still-near-free noun and the realistic production shape).

**Backend on Lambda — reuse the image, don't rewrite the app.**
- The existing `Dockerfile` from 0025 runs on Lambda via the **Lambda Web Adapter**
  as a **container image**. *The same image runs locally, on Render, and on
  Lambda*, zero application-code change. Mangum + zip is rejected: langgraph +
  langchain almost certainly bust the 250 MB unzipped zip limit (0025 measured a
  309 MB image), and a zip would fork the packaging.
- **Region: us-east-1** — cheapest, all services present, CloudFront's native home.
- **The runner stays inside the backend Lambda.** It already runs via
  `asyncio.to_thread` over `subprocess`; Lambda's `/tmp` is writable. A separate
  runner-Lambda is a *future* hardening/decomposition, not now — splitting it
  prematurely is complexity for its own sake.

**Session state — the swap 0007/0021 were built to make cheap.**
- A new `DynamoDBSessionStore` implements the `SessionStore` Protocol (ADR 0021),
  selected by `get_store()` behind an env flag. One table, `session_id` partition
  key, Sessions and Evaluations as items. **No endpoint in `main.py` changes.**

**Distributed state — the headline. Two races; one solved, one reasoned.**
- **Race A — double Evaluation.** `_evaluation_locks` is a
  `dict[str, asyncio.Lock]` in module memory ([`main.py:112`](../../backend/app/main.py),
  taken at `:694`) that serialises the Evaluation fan-out so a Session is scored
  once. ADR 0021 deliberately kept it *out* of the store as "live in-process
  coordination, not state." That was right for one process and is **fatal under
  Lambda**: two invocations run in two containers with two separate lock dicts, so
  the lock guards nothing and a double-submitted Session is evaluated twice.
  **Fix:** replace the lock with a **DynamoDB conditional write** — create the
  evaluation item under `attribute_not_exists(session_id)` (or a `status`
  compare-and-set), letting the store's atomicity do what the in-process lock no
  longer can. This is the single largest piece of work and the headline sentence.
- **Race B — Watcher poll last-writer-wins.** Concurrent `save`s of `watch` state
  ([`main.py:597`](../../backend/app/main.py), `:650`, `:675`) can clobber each
  other. **Deliberately deferred, not ignored:** it is bounded to near-impossible
  by the frontend's idle-poll gating (ADR 0028), and the upgrade path — a `version`
  attribute with optimistic-concurrency conditional writes — is named so it's a
  one-class change if usage ever demands it. Fixing it now is scope creep; knowing
  *which* race to fix and which to consciously carry is the point.

**Infrastructure as code — Terraform, and why.**
- **Terraform**, not SAM/CDK/Serverless Framework. SAM would be less code but reads
  as the AWS-tutorial path and is AWS-only; Terraform is the transferable keyword
  and the cloud-agnostic tool real infra roles list. Its cost — hand-wiring every
  IAM role, Lambda permission, and API Gateway integration that SAM would
  generate — **is the learning**, and demonstrating you understand what's underneath
  is worth more here than SAM's convenience.

**CI/CD — GitHub Actions with OIDC.**
- Actions assumes a scoped IAM role via **OIDC federation — no long-lived AWS keys
  in GitHub secrets** (a real security-competence signal, and free). Pipeline:
  `terraform plan` on PR, `terraform apply` + frontend build/deploy on merge to
  `main`.

**Secrets — SSM Parameter Store SecureString** (free), not Secrets Manager
($0.40/secret/mo would dent the ceiling for no benefit). `GROQ_API_KEY` / Gemini
key live there; the runner timeout and origins stay env-driven as 0025 set up.

**Cold starts — accept, mitigate for free.**
- Reuse 0025's landing-page warm-up ping (`GET /api/health` on mount) so the cold
  start happens behind reading time, not on the Start click. **Provisioned
  concurrency is rejected** (pays for always-warm capacity — the exact always-on
  cost serverless avoids). **SnapStart is rejected too**, cleanly: Python SnapStart
  is near-free but **incompatible with container images**, and the container was
  chosen (above) for Dockerfile reuse. A documented trade, not an oversight.

## Consequences

- **~$0/month, and the bound is watched not assumed** — the three cost-cliff lines
  (CloudWatch dashboards, API Gateway's 12-month tier, the 6-month account close)
  are named above and held to.
- **Redeploys no longer drop live Sessions** — state lives in DynamoDB, not the
  process. This *closes* the 0007/0025 "a redeploy interrupts any live interview"
  liability rather than carrying it.
- **Horizontal scale becomes free and automatic** — Lambda fans out per request.
  MockMate stops being "a server that cannot be scaled" (0025) and becomes the set
  of functions 0025 said it wasn't. That reframing is the whole ADR.
- **Cold starts move to the first API call, not the page.** The S3/CloudFront
  frontend is always instant; the warm-up ping hides the ~1–3s LangGraph init
  during reading. A visitor who lands and immediately clicks Start still waits; no
  free fix exists and none is bought.
- **Every Watcher poll is now a DynamoDB round-trip** — trivially inside the free
  tier, but Race B's residual last-writer-wins is a real, named, accepted risk
  (bounded by ADR 0028's idle gating).
- **More infrastructure surface than Render's two services** — S3, CloudFront, API
  Gateway, Lambda, a DynamoDB table, IAM, an OIDC provider. That surface *is the
  deliverable here*: it's what Terraform describes and what the resume claims.
- **The runner's soft-sandbox risk is unchanged and re-accepted** (0025). Lambda's
  per-invocation isolation is a modest improvement on a shared container, not the
  egress-firewall / gVisor hardening 0025 deferred. Still a later day.
- **Response streaming needs a check before PR 3 lands.** The TTS audio path relies
  on API Gateway / CloudFront carrying a streamed response; supported but
  unverified for this app. If an endpoint buffers, first audio is delayed, not
  broken — a test, not a redesign.

## Why this over ADR 0025 (the honest resume rationale)

Recorded because it is the *actual decision driver*, not a side effect. On a
six-second resume skim, "Deployed on Render" and "Serverless on AWS (Lambda,
DynamoDB, CloudFront, Terraform)" are not equally legible — but the signal is
carried by specific words, and this ADR is built to earn the strong ones and not
oversell the weak ones:

- **Strong, and Render-impossible:** *"replaced in-process locking with DynamoDB
  conditional writes to make Session evaluation idempotent under horizontal
  scale"* (Race A) and *"defined the infrastructure in Terraform with an
  OIDC-authenticated CI/CD pipeline."* These are the load-bearing lines. A single
  always-on process never forces the first, and `render.yaml` never reads as the
  second.
- **Weak, not oversold:** "serverless/Lambda" as a bare noun is commodity, and
  "cost-optimised to $0" can read as *toy*. They are supporting cast, framed as
  architecture decisions, never the headline.

The one-line claim this ADR is built to justify: *"Migrated a stateful FastAPI
service to serverless AWS (Lambda, DynamoDB, CloudFront) defined in Terraform with
an OIDC CI/CD pipeline; replaced in-process locking with DynamoDB conditional
writes to make evaluation idempotent under horizontal scale."*

## Alternatives considered

- **Stay on Render (ADR 0025).** Simpler ops, no cold-start-on-first-call. Rejected
  as the *primary* deploy because it structurally cannot produce this ADR's two
  headline resume lines. Kept in-repo as a documented fallback — the Web Adapter
  container means one image runs both places, so it costs nothing to retain.
- **App Runner / ECS Fargate.** The container-shaped AWS options. Rejected: no free
  tier (~$5–25/mo and ~$10–15/mo), and both reintroduce 0007's single-instance
  dropped-session problem this path removes for free.
- **Bare Lambda Function URL instead of API Gateway.** Cheaper still, but
  near-invisible on a resume and not the realistic production shape. API Gateway
  HTTP API is ~free at this scale and the recognizable noun.
- **SAM / CDK / Serverless Framework instead of Terraform.** Rejected: SAM is
  AWS-only and reads as the tutorial path; CDK is niche for this size; Serverless
  Framework has declining relevance and licensing friction. Terraform's
  hand-wiring is the learning and the transferable keyword.
- **Bedrock as the LLM provider.** Rejected hard: no free tier, per-token billing,
  and one voice interview is many turns — it could dwarf all infra combined.
  Hosting on AWS and inferring on Groq/Gemini (ADR 0014) is the cheapest
  combination and they are independent choices.
- **Provisioned concurrency / SnapStart for cold starts.** Provisioned concurrency
  pays for always-warm capacity, defeating the near-free bound. SnapStart is
  near-free but incompatible with the container image chosen for Dockerfile reuse.
  The warm-up ping is the free mitigation.
- **Fix Race B now (optimistic concurrency on all session saves).** Rejected as
  scope creep: bounded to near-impossible by ADR 0028's idle gating, with a named
  one-class upgrade path. Deliberately carried, not overlooked.
- **Separate runner Lambda.** Deferred: the in-process subprocess already isolates
  and fits Lambda; decomposing now is complexity without payoff. A future
  hardening bullet.
- **Secrets Manager instead of SSM Parameter Store.** Rejected: $0.40/secret/mo for
  no benefit at this scale; SecureString parameters are free and sufficient.

## Status

Accepted; shipping as the **five scoped PRs** below, matching the DSA round's
~5-PR precedent, backend-state first so the headline landed independent of any
AWS deploy:

1. `DynamoDBSessionStore` + the **Race A** idempotency guard — pure backend,
   tested against DynamoDB Local, ships without touching AWS deploy. The
   double-evaluation race is **proven by reproduction** (two concurrent
   evaluations, assert exactly one wins), per ADR 0028's evidence-not-assertion
   ethos.
2. Lambda packaging (Web Adapter handler) + Terraform for Lambda / API Gateway /
   DynamoDB / IAM.
3. S3 + CloudFront + frontend deploy + single-origin routing (and the streaming
   check above).
4. GitHub Actions OIDC pipeline (`plan` on PR, `apply` on merge).
5. CloudWatch dashboard/alarms + README/deploy docs (this PR).

**Fully live on AWS, and the supersession of [ADR 0025](0025-deploy-render-static-plus-api.md)'s
host is complete.** The CloudFront-account verification that held PR 3 back has
since cleared, the distribution was created, and `deploy.yml` has been applying
the whole stack — including the frontend sync and invalidation — on every merge
to `main` since. Verified end to end against the live distribution:

| Check | Result |
|---|---|
| `GET /` (SPA from S3 via CloudFront) | 200 |
| `GET /api/health` (same origin → API Gateway → Lambda) | 200, `{"status":"ok","provider":"groq+gemini"}` |
| `terraform apply` in CI | clean — `0 added, 0 changed, 0 destroyed` |

Both halves through one CloudFront origin, so the no-production-CORS property
this ADR carried over from 0025 holds in the deployed system, not just on paper.

**Consciously deferred, not forgotten:**

- **Race B** — Watcher-poll last-writer-wins, per the Decision section above.
  Bounded to near-impossible by ADR 0028's idle gating; the named
  optimistic-concurrency (`version` attribute) upgrade is the fix if usage
  ever demands it.
- **A separate, lower-privilege CI plan role.** PR 4's OIDC pipeline (written,
  not yet merged) runs `plan` and `apply` under one role; splitting a read-only
  `plan` role from the mutating `apply` role is real hardening this ADR didn't
  need to block cutover on.
- **Least-privilege tightening of the deploy role.** The role Terraform
  applies as is scoped to this project's resources but not yet audited down
  to the minimum action set the way `iam.tf`'s Lambda execution role already
  is — a later hardening pass, not a known hole.
