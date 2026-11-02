# ADR-0004: Backwards-compatible `workflow_call` contracts only, dogfooded via a local-path ref

**Status:** Accepted (2026-05-26; extended 2026-07-25; reconstructed 2026-08-13)

## Context

Every workflow in this repo is a `workflow_call` reusable consumed by every
Lentago Labs repo via `@main` ([ADR-0002](0002-reusables-called-by-reference-float-on-main.md)).
Because callers float on `main` with no version pin, a contract-breaking
change reaches every caller on its next run with no staging window. GitHub
Actions' `workflow_call` merge behavior compounds this: a newly *required*
input breaks every caller silently, and the failure doesn't surface until
that caller's next run — not at merge time here.

A second, separate gap showed up once `docs-check.yml` shipped
([#28](https://github.com/lentago/shared-workflows/pull/28)): this repo's
own PRs had no status checks at all. `fleet-ops/required-checks.json` had
carried `shared-workflows` as a permanent exception, on the reasoning that
every workflow here is a `workflow_call` definition, not a caller — so
nothing had ever run on this repo's own PRs, and `gh pr merge --auto` could
not even be armed here.

## Decision

**Contract discipline:** `CLAUDE.md` has required, from the earliest
version of this file
([`53af2bd`](https://github.com/lentago/shared-workflows/commit/53af2bd),
2026-05-26), that new `workflow_call` inputs be added as optional with
sensible defaults — never required — specifically because "adding a
required input breaks every caller silently." The same original commit
also established "test before publishing on `main`": push to a branch,
point one caller repo's `uses:` at `@<branch-name>` for one merge, then
merge to `main` only once that's verified.

**Self-dogfooding:** [#29](https://github.com/lentago/shared-workflows/pull/29)
(merged 2026-07-25) added `docs-check-self.yml`, a caller inside this repo
that invokes `docs-check.yml` via the local path ref
(`uses: ./.github/workflows/docs-check.yml`) rather than `@main`. This
gives a PR here its first self-running check, checked against the version
of the resolver *inside that PR* rather than whatever is on `main` — and
makes `shared-workflows` mappable in `required-checks.json` for the first
time, closing the permanent-exception gap.

The self-referential test path immediately proved incomplete, not just
theoretically riskier: [#30](https://github.com/lentago/shared-workflows/pull/30)
(merged 2026-07-25) found that the "Checkout docs-check tooling" step
resolved its ref from `github.workflow_ref` — the *entry* workflow context,
which for an external caller resolves to that caller's own PR ref, not a
ref that exists in `shared-workflows`. Every external caller failed with
`fatal: couldn't find remote ref refs/pull/97/merge`. The bug was invisible
in this repo's own self-referential test because here the caller's ref
*is* valid in the repo being checked out; it only surfaced once real
external callers exercised the reusable, in the fleet-wide `docs-check`
rollout (`lentago/.github#57`). The fix — resolving `github.job_workflow_ref`
instead — is a one-token change, but the incident is recorded because it
demonstrates a limit of self-testing.

## Alternatives

- **Recorded at the time:** the original contract rule itself — optional-with-default inputs, branch-test-before-merge — adopted from this repo's first `CLAUDE.md` and unchanged since.
- **Recorded at the time (#29):** dogfood via the local-path ref specifically so "a change that breaks the link checker fails its own pull request instead of passing against the old copy on main" — adopted as the self-check mechanism.
- *Retrospective — not considered at the time:* **A contract schema/lint step** (e.g., a CI job that diffs each workflow's `inputs:` block against the previous commit and fails if a previously-optional input becomes required, or a new input lacks a default). This would be strictly better than the current discipline, which relies entirely on the author remembering the rule and a human reviewer catching a violation — a schema check would catch it mechanically, before merge, the same way `docs-check-self.yml` catches broken links in its own PR. It was not built; given how rarely inputs change in this repo, the manual discipline has been judged sufficient so far, but a single missed review would break every caller silently with no test to catch it.
- *Retrospective — not considered at the time:* **Test external-caller behavior with a second, real caller repo in CI** (e.g., a workflow here that also exercises the reusable against a throwaway branch in a real caller repo, not just the local-path self-call). This would have caught the exact bug #30 fixed — a self-referential test structurally cannot exercise the `workflow_ref` vs. `job_workflow_ref` distinction, since that distinction only exists when the calling repo and the called repo differ. It's a better test in principle, but meaningfully more expensive to build and maintain (cross-repo credentials, a disposable caller branch, cleanup) than the local-path dogfood, and the fleet-wide rollout in #30 ended up serving as exactly this kind of real-world test anyway — just after merge instead of before.

## Consequences

- Callers have never broken from a `shared-workflows` input change (per
  this repo's own history) — the optional-default discipline has held.
  Nothing mechanically enforces it beyond code review, though.
- This repo now carries its own required check (`docs-check / docs-check`
  via `docs-check-self.yml`), closing the `required-checks.json` exception
  and giving PRs here the same auto-merge-arming path as every other fleet
  repo.
- The #30 incident is the concrete evidence that a self-referential test
  can mask a cross-repo-caller bug; the fix comment in `docs-check.yml`
  records the trap directly at the line it applies to, not only here.

## Addendum (2026-11-02): the #30 fix read an empty value

The fix recorded in Context resolved `github.job_workflow_ref`, but that is
not a property of the `github` context. It evaluated empty, and the tooling
checkout then took this repository's default branch. The fatal error went away,
but every external caller ran `main`'s resolver whatever tag it pinned, which
ADR-0005's tags were meant to prevent.
[#95](https://github.com/lentago/shared-workflows/issues/95) moved the checkout
to `job.workflow_sha` and added a step that checks the commit on every run.
The self-referential test hid this second bug the same way it hid the first,
which strengthens the case for the retrospective's second-caller test.
Validation for #95 used a real caller repository on a branch ref before merge.
