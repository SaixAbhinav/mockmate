# ADR 0034: Buy the name with a student benefit, and own the DNS

Date: 2026-08-21 · Status: accepted · in progress (phase 1 of 2) · Supersedes [0032](0032-custom-domain-free-subdomain.md)'s domain and DNS

## Context

[ADR 0032](0032-custom-domain-free-subdomain.md) chose `callback.is-a.dev`: free,
including DNS, and it kept [ADR 0029](0029-serverless-aws-deploy.md)'s ~$0/month
bound intact. Phase 1 shipped and the certificate was created. Phase 2 needed a
pull request against `is-a-dev/register` carrying two records.

**That pull request was denied and closed** on 2026-08-15 by their review bot:

> Not Related to Software Development. All root subdomains *must be related to
> software development*.

The verdict is arguable (Callback is an open-source developer tool with a
sandboxed Python coding round) and at the moment it was reviewed the site was
still a bare résumé-upload form, since [ADR 0033](0033-landing-page-second-entry.md)'s
landing page had not yet been deployed. But arguing it is not a plan. The
subdomain is unclaimed again, the certificate is stranded in
`PENDING_VALIDATION`, and the fallback 0032 designed for exactly this held: the
distribution kept serving its own certificate and nothing broke.

The real lesson is not "that particular reviewer said no." It is a property of
the option 0032 chose, which that ADR named as an accepted risk and which has
now happened: **the DNS was a pull request against a volunteer-run repository.**
That made the record a decision someone else got to make, and it is also why
0032 could not use `aws_acm_certificate_validation` at all: a resource that
blocks until DNS resolves would have held a CI job and the DynamoDB state lock
across a wait of unbounded length. The two-phase variable gate exists to work
around a constraint that only exists because we did not own the zone.

Meanwhile a cheaper option than any of 0032's alternatives turned out to be
available: the author is a **student**, and the GitHub Student Developer Pack
includes a registered domain free for the first year (Namecheap `.me`, a
Name.com selection across 25+ extensions, `.tech`).

## Decision

**Serve the app at a registered domain from the GitHub Student Developer Pack,
with DNS in Route 53 and the ACM validation record created by Terraform.**

**The name is bought, not petitioned.** No reviewer, no eligibility rules, no
category judgement. The registration is free for the first year through the
Pack.

**DNS moves into Terraform.** `route53.tf` creates the hosted zone, the
validation record for the certificate, and the apex alias to CloudFront. This is
the change that matters, and it closes the gap 0032 recorded as a real hole:
"two records for this project are defined in a third party's Git repository
rather than in `infra/`. The IaC story 0029 tells is now *almost* whole." It is
whole now.

**Automatic certificate renewal stops being a manual worry.** ACM re-validates
through a record Terraform owns, so 0032's named failure mode (someone deletes
the record after issuance and the renewal breaks quietly, a year later) is gone.

**The cutover stays two applies, but the wait changes character.** It is no
longer "a stranger merges a PR, or does not" but "paste four nameservers into
the registrar", which takes a minute and is entirely ours:

1. `custom_domain` set: zone, certificate, and validation record created.
   Nothing attached, nothing blocks. `terraform output route53_name_servers`
   gives the four values to paste at the registrar.
2. `custom_domain_active = true`: `aws_acm_certificate_validation` confirms
   ISSUED, the apex alias is created and the certificate attached.

`aws_acm_certificate_validation` is now used, where 0032 rejected it. The
objection was never the resource, it was blocking on someone else's schedule.
It is deliberately gated on the *active* flag rather than merely on the domain
being set, so an ordinary apply on an unrelated change can never sit waiting on
delegation while holding the state lock.

**The apex is an alias record, not a CNAME.** DNS forbids a CNAME at a zone apex
alongside the SOA and NS records that must live there. An alias also resolves
without the extra lookup a CNAME costs.

## Consequences

- **ADR 0029's ~$0/month bound is broken, by $0.50/month.** A Route 53 hosted
  zone is the first standing charge this project carries, and this is the ADR
  that spends it. It buys the IaC completeness above, plus automatic renewal.
  0029's bound was always "watched, not assumed", and this is what watching it
  looks like: the line is named rather than absorbed.
- **Year two costs money.** The Pack's free year ends and the domain renews at
  the registrar's rate, which is why the extension matters more than it looks:
  a `.me` renews around $4.88 while a `.tech` renews at roughly ten times that.
  A domain on a résumé that lapses is worse than one never registered.
- **The stale is-a.dev certificate is destroyed.** `custom_domain` defaults to
  `""` until a domain is registered, so the next apply removes the certificate
  stranded by the denied PR rather than leaving it pending forever.
- **A new dependency on the registrar's nameserver setting.** If delegation is
  removed, the domain stops resolving. The blast radius is the same as before:
  the CloudFront name still serves the app, and reverting
  `custom_domain_active` to `false` is the recovery.
- **Only the apex is covered.** No `www` subject alternative name and no
  redirect. Adding one is a SAN on the certificate plus a second alias record,
  and `route53.tf` iterates `domain_validation_options` specifically so that
  needs no change to the validation wiring.
- **CI can manage all of this.** The deploy role's `PowerUserAccess` already
  covers Route 53, and the read-only plan role covers the `Get`/`List` calls a
  plan needs, so ADR 0031's split holds with no new grants.

## Alternatives considered

- **Appeal the denial, or resubmit to is-a.dev.** Nearly free, and the case is
  genuinely stronger now that ADR 0033's landing page leads with the open-source
  and architecture story rather than a file picker. Rejected as the primary path
  because it still ends with DNS we do not own, the same blocking problem, and a
  second reviewer who may agree with the first. Worth trying only if the Pack
  route had failed.
- **Another free registry** (`is-a-good.dev`, and others). Alive, and `callback`
  was unclaimed. Same shape as is-a.dev and therefore the same risks: rules set
  by volunteers, DNS by pull request. Notably **Open Domains, one of the better
  known ones, is archived on GitHub**, which is the argument against this whole
  category in one fact.
- **`eu.org`.** Free permanently and it delegates real nameservers, so it would
  have given the same Terraform-owned DNS as this decision at no cost. Rejected
  on the name: approval takes around two weeks, and `callback.eu.org` reads more
  obscure than what the Pack offers for free this year.
- **`js.org`.** Rejected on eligibility: they now accept only genuine JavaScript
  libraries and tools, not projects that merely have a React frontend. That is
  the same class of denial we just received.
- **Buy a domain outright at Cloudflare Registrar** (~$10-12/yr at cost). The
  honest baseline, and what this becomes anyway once the free year ends.
  Rejected only because the Pack makes year one free for the same result.
- **Keep the CloudFront hash.** Still free, still works. Rejected for the reason
  0032 gave: the URL is the first thing a reader of this project sees.
- **DNS at Cloudflare, free, instead of Route 53.** Saves the $0.50/month but
  either puts DNS outside Terraform (the exact hole this ADR set out to close)
  or adds a second provider and an API token to store. Paying $6/year to keep
  one tool and one state file is the better trade.

## Status

**Phase 1 is this PR**, and it is inert until a domain exists: `custom_domain`
defaults to `""`, so the plan creates no zone and destroys the stranded
certificate. `terraform validate` passes.

**Phase 2, once the domain is registered:**

1. Set `custom_domain` to the registered apex, apply.
2. `terraform output route53_name_servers`, paste the four values into the
   registrar as custom DNS.
3. Wait for delegation, then confirm `terraform output acm_certificate_status`
   reads `ISSUED`.
4. Set `custom_domain_active = true`, apply. `terraform output -raw site_url`
   then prints the real URL.
