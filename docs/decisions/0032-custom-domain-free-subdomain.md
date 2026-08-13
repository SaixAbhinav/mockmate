# ADR 0032: A readable URL for free — `callback.is-a.dev` over CloudFront

Date: 2026-08-13 · Status: accepted · in progress (phase 1 of 2) · Extends [0029](0029-serverless-aws-deploy.md)

## Context

[ADR 0029](0029-serverless-aws-deploy.md)'s cutover is complete and the app is
live — at `https://d1ukk616lu5bcc.cloudfront.net`. That name is a problem for the
one audience this project is built for. 0029 was explicit that the value here is
*resume-legible* competence; a URL that reads as a hash undercuts the thing the
deploy exists to demonstrate, on exactly the six-second skim 0029 describes.

**The default CloudFront name cannot be chosen.** `*.cloudfront.net` is AWS's
zone; `d1ukk616lu5bcc` is assigned, and there is no setting that makes it
`callback.cloudfront.net`. A readable URL therefore requires a domain *we*
control. That is the entire cost: **AWS's side of a custom domain is already
free** — ACM public certificates cost nothing, and CloudFront charges nothing for
an alias. The only price is the name itself.

So the decision is narrower than "should we have a custom domain" (obviously
yes): **what do we point at the distribution, given 0029's ~$0/month bound is a
real constraint we have held everywhere else?**

- A registered domain (`.xyz`, `.dev`, `.com`) costs ~$3–15/year, and hosting its
  DNS in **Route 53 costs $0.50/month per hosted zone** — the first standing
  charge this project would carry. Small, but it breaks a bound 0029 defends
  line-by-line, and it would need saying out loud rather than absorbing quietly.
- A **community subdomain** (`is-a.dev`, `js.org`, `eu.org`) costs nothing at all,
  including DNS hosting.

The name also matters: [ADR 0030](0030-callback-rename-and-visual-system.md)
renamed the product to **Callback**, and `callback` is unclaimed on `is-a.dev`.
The free option and the right name happen to coincide.

**What was verified before deciding, not assumed.** `is-a.dev` is a DNS-only
service (it hosts records; it does not proxy or frame the site), and the shape
this needs is already well-trodden there: their register repo contains many
existing pairs of a `<name>.json` CNAMEing to a `*.cloudfront.net` distribution
alongside a `_<hash>.<name>.json` carrying an `*.acm-validations.aws` record.
This is a supported pattern with precedent, not a workaround being attempted
blind.

## Decision

**Serve the app at `https://callback.is-a.dev`, as a CloudFront alias backed by a
free ACM certificate, with DNS hosted by is-a.dev.** No registrar, no Route 53
hosted zone, no change to 0029's ~$0/month bound.

**Nothing about the application or the topology changes.** CloudFront remains the
single origin; `/` still serves the SPA from S3 and `/api/*` still forwards to API
Gateway. The frontend's relative `/api/...` calls are unaffected, `VITE_API_BASE`
stays unset, and there is still no production CORS. This ADR adds a name and a
certificate in front of a system that is otherwise untouched.

**The cutover is two applies, on purpose.** This is the only structurally
interesting part of the decision, and it is forced by a constraint AWS does not
normally impose:

- ACM will not issue until its validation `CNAME` resolves.
- CloudFront will not accept a certificate that is not already `ISSUED`.
- **The record in between is merged by a maintainer of someone else's repository,
  on their schedule.** That is the price of the free option — DNS is a pull
  request, not an API call.

A single apply spanning that gap would have to *wait* on a human. So the phases
are split by two variables (`infra/acm.tf`, `infra/variables.tf`):

1. **`custom_domain`** (set, by default) creates the certificate and outputs the
   validation record. The certificate sits `PENDING_VALIDATION`; nothing is
   attached; **the apply does not block.**
2. **`custom_domain_active`** (false until the certificate reads `ISSUED`)
   attaches the alias and the certificate to the distribution.

**`aws_acm_certificate_validation` is deliberately not used.** It is the idiomatic
resource for exactly this and it is wrong here: it *blocks the apply* until the
record resolves. In the normal Route 53 case that is seconds. Here it could be
days — and since `deploy.yml` runs `terraform apply` on every merge to `main`, it
would hold a CI job open and, worse, **hold the DynamoDB state lock** for the
duration, blocking every other deploy. Not using it is the entire reason the
phase split exists.

**A `lifecycle` precondition guards the one likely mistake** — flipping
`custom_domain_active` before the certificate issues — turning an opaque
CloudFront API rejection into a sentence naming the next action.

**The default certificate stays live throughout.** Until phase 2, the
distribution serves `*.cloudfront.net` exactly as it does today, so a stalled or
abandoned is-a.dev PR degrades to "no change" rather than to an outage.

## Consequences

- **A readable URL at $0.** 0029's bound survives intact — no registrar, no
  hosted zone, no new line item.
- **The old URL keeps working.** `d1ukk616lu5bcc.cloudfront.net` remains a valid
  name for the distribution; the alias is added, not swapped. Nothing that links
  to the current URL breaks.
- **DNS lives outside Terraform, and that is a real gap.** Two records for this
  project are defined in a third party's Git repository rather than in `infra/`.
  The IaC story 0029 tells is now *almost* whole — a caveat worth stating plainly
  rather than eliding, and the strongest argument for the paid option if it ever
  matters more than the bound.
- **A dependency on a volunteer-run service.** If is-a.dev disappears or drops the
  record, the custom domain stops resolving. The blast radius is bounded: the
  CloudFront name still serves the app, so recovery is reverting
  `custom_domain_active` to `false`, and migrating to a paid domain later is the
  same two resources pointed at a different zone.
- **Certificate renewal depends on that record staying put.** ACM renews
  automatically *only while the validation CNAME resolves*. It must not be
  deleted after issuance — a quiet failure mode a year out, so it is named here
  and in `infra/README.md`.
- **Two applies to finish, with a human-shaped wait in the middle.** Phase 1
  ships in this PR. Phase 2 is a one-line variable change after the is-a.dev PR
  merges.
- **`callback.is-a.dev` reads as a hobbyist domain to some.** A `.dev` would read
  better. That is the honest cost of the free option, and it is still far above
  the hash it replaces.

## Alternatives considered

- **Registered domain + Route 53.** The best-reading option and the most
  conventional AWS answer, with DNS fully in Terraform (including automatic ACM
  validation, which would remove the phase split entirely). Rejected for now on
  the explicit bound: ~$10/yr plus $0.50/mo standing. Named as the upgrade path —
  it is the same certificate and the same alias, pointed at a zone we own.
- **Registered domain + Cloudflare DNS (free zone).** Avoids the $0.50/mo but not
  the registration fee, and puts DNS in a second Terraform provider (or outside
  Terraform, the same gap this ADR accepts) for a partial saving. Strictly worse
  than either endpoint of the trade.
- **`js.org` / `eu.org`.** Same free-community shape. `js.org` expects a
  JavaScript-ecosystem project — this is a Python backend with a React frontend,
  so the fit is arguable and the review stricter. `eu.org` approval is famously
  slow. `is-a.dev` is developer-portfolio-shaped by design, which is precisely
  this use case.
- **A Netlify/Vercel/Pages subdomain** (e.g. `callback.pages.dev`). Free and
  readable, but it means hosting the frontend *there* rather than on S3 +
  CloudFront — abandoning the AWS deploy that is the entire point of 0029 in
  order to improve its URL. Self-defeating.
- **Keep the CloudFront hash.** Free, zero work, and genuinely fine
  functionally. Rejected because the URL is the first thing a reader of this
  project sees, and 0029 exists to be read.
- **`aws_acm_certificate_validation` with a long timeout.** Rejected above: it
  blocks CI and holds the state lock across a human-scale wait.

## Status

**Phase 1 accepted and shipping in this PR** — `infra/acm.tf`, the two variables,
the guarded `viewer_certificate`/`aliases` wiring in `infra/cloudfront.tf`, and
the outputs that produce the validation record. `terraform validate` passes and
the plan is additive: one new certificate, no change to any existing resource,
because `custom_domain_active` defaults to `false`.

**Phase 2 is blocked on an external merge**, and the steps are written down in
`infra/README.md` so they are not reconstructed from memory:

1. Merge this PR; `deploy.yml` applies it and creates the certificate.
2. Read `terraform output acm_validation_record`.
3. Open a PR against `is-a-dev/register` adding `domains/callback.json` (CNAME →
   the distribution) and `domains/_<hash>.callback.json` (CNAME → the
   `acm-validations.aws` value). **Both files must carry the same
   `owner.username`** — their tests enforce that a nested subdomain matches its
   parent's owner.
4. Once merged and propagated, confirm `terraform output acm_certificate_status`
   reads `ISSUED`.
5. Set `custom_domain_active = true` and apply.
