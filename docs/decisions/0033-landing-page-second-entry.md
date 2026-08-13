# ADR 0033: The front door is a page, not the app

Date: 2026-08-13 · Status: accepted · Extends [0030](0030-callback-rename-and-visual-system.md)'s visual system

## Context

[ADR 0032](0032-custom-domain-free-subdomain.md) is about to put this project at a
readable URL, and [ADR 0029](0029-serverless-aws-deploy.md) exists because the
deploy is meant to be *read* by someone deciding whether the work is any good.
Both of those end at the same place: a stranger types the domain and sees
whatever `/` renders.

Until now `/` rendered the app, and the app opens on a file picker. The Session
that ADR 0012 designed, the Watcher of 0018, the sandboxed runner of 0016 and the
scored Evaluation of 0011 and 0020 are all invisible at that moment. A visitor
who does not already know what Callback is has to upload a résumé to find out.
`StartScreen` had grown a small pitch on top of the form to compensate, which is
the shape of the problem rather than a fix: a hero, a three-step list and a
GitHub link sitting above the control they are supposed to be selling.

The decision is *where the front door lives*, and the constraint that makes it
interesting is one this repo already imposed on itself deliberately.

**`cloudfront.tf` configures no SPA error-rewrite, on purpose.** Its comment says
why: there is no react-router and no client-side routes, and a blanket
`403/404 -> index.html` rewrite would swallow genuine `/api/*` errors from
FastAPI and hand the browser the SPA's HTML instead. So the obvious move,
"add a route for the landing page", is not free here. It would either need that
rewrite (giving up a property 0029 chose knowingly) or it would 404 on refresh
and on every shared link, which is exactly what a front door must not do.

## Decision

**Ship the landing page as a second HTML entry point. `/` is the page,
`/app.html` is the interview.**

**Two real files, not two routes.** Vite is configured for a multi-page build
(`rollupOptions.input`), so `dist/` contains `index.html` and `app.html`. Both
are real objects in the S3 bucket, so a refresh, a bookmark and a pasted link all
resolve at the origin with no rewrite and no router. **No infrastructure changes:
`default_root_object` is already `index.html`, and `aws s3 sync` picks up the
second file on its own.** The property 0029 protected stays protected because
nothing was asked of CloudFront.

A useful second effect: the entries split the bundle. The landing page does not
import CodeMirror, so it ships ~6 kB of its own JavaScript instead of the app's
~488 kB. The page a first-time visitor lands on is now the cheap one, which is
the right way round for the cold-start story 0029 tells.

**The warm-up ping moves to the landing page.** ADR 0029 and 0025 both rely on
pinging `/api/health` early so the Lambda wakes behind reading time rather than
on the Start click. That ping fired on `StartScreen`, which is now one page
later than the first thing a visitor sees. The landing page calls the same
`useApiReady` hook, so the interviewer wakes while the page is read, and the
mitigation keeps working instead of quietly regressing.

**The visual system is 0030's, unchanged.** Monochrome, white on black, no brand
hue. Notably the page spends **no** state colour: `--pass`, `--fail` and
`--pending` mean a test passed, failed or is pending, and 0030's whole argument
is that spending them elsewhere dilutes the one place colour carries information.
A landing page is exactly the temptation that argument was written against, so
there is a test asserting the page never reaches for them.

**`StartScreen` loses its pitch.** With a real landing page, the hero, the
step list and the GitHub line were a second copy of it, and clicking through
meant reading the same headline twice to start one interview. The screen is now
the form it is named for, with the brand linking back to `/`.

## Consequences

- **The app's URL changed.** Anyone who bookmarked the CloudFront root now lands
  on the pitch and needs one click. There are no known deep links to break, but
  it is a change and not a silent one. `app.html` carries `noindex` so search
  results keep pointing at the front door rather than the file picker.
- **Two entry points to keep in step.** A change to the shared shell has two
  pages to check, and the interview surface is no longer exercised by simply
  loading `/`.
- **A contrast bug in the token system surfaced.** `--text-dim` measures **2.9:1**
  against `--bg`, under WCAG AA's 4.5:1 for small text, so the landing page uses
  `--text-muted` (5.7:1) for every small label. Verified by computing the ratio
  for all fifteen text and background pairs on the rendered page. **The token
  itself is still used elsewhere in the app** (placeholders, dim metadata), so
  this ADR names a real, pre-existing defect it did not fix. Auditing those uses
  is its own change.
- **Motion is CSS only.** Reveal-on-scroll uses IntersectionObserver and a
  transition, with the observer never created under `prefers-reduced-motion`.
  No animation library was added, so the dependency list is unchanged.
- **The page has no product screenshot yet**, which is the honest gap. Real
  screenshots of the coding round and the Evaluation are what should carry this
  page, and they need a capture pass. Hand-built fake product UI was rejected
  outright as worse than nothing.
- **Dark only, still.** 0030 ships no light theme and this page inherits that.
  A visitor on a light-mode OS gets the dark page, as they do in the app.

## Alternatives considered

- **A client-side route (`/` vs `/interview`).** The conventional answer, and
  the one this repo has deliberately made expensive: it needs the CloudFront
  error-rewrite that `cloudfront.tf` argues against, or it breaks on refresh.
  Adding a router *and* a rewrite to avoid one HTML file is a bad trade.
- **Keep the pitch on top of `StartScreen`.** Zero work, and it is what exists
  today. Rejected because it puts marketing copy above a form on the same screen,
  which serves neither: the pitch is cramped and the form is pushed down.
- **A separate static site (plain HTML, its own build).** Genuinely lighter, and
  tempting for a page with no state. Rejected because it forks the styling: the
  ADR 0030 tokens, the component conventions and the test setup all live in the
  React app, and a second toolchain would drift from them within a release.
- **A marketing page hosted elsewhere** (GitHub Pages, a template host).
  Rejected for the same reason 0032 rejected moving the frontend off S3: it
  abandons the deploy that is the point in order to decorate it.
- **Adding Tailwind and Motion for the page.** The skill-standard stack for this
  kind of work, and both would need flagging as new dependencies. Native CSS on
  0030's existing tokens produced the page without either, so neither was added.
