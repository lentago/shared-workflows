# ADR-0005: Callers migrate from `@main` to immutable semver tags; `@main` is no longer a supported consumption path

**Status:** Accepted (2026-08-16) · Supersedes [ADR-0002](0002-reusables-called-by-reference-float-on-main.md)

## Context

From this repo's first commit, all 16 Lentago Labs fleet repos have consumed
reusable workflows at `@main` — 50 caller references total. ADR-0002 recorded
that decision, named its primary consequence explicitly ("a single merged PR
here changes CI behavior across every caller on their next run, with no
per-repo redeploy step"), and noted that tagging stable versions and migrating
callers was deferred, not rejected.

Two developments since ADR-0002 make that deferral the wrong ongoing posture:

1. **The `@main` risk became real enough to measure.** The fleet grew to 16
   repos and the workflows grew meaningfully: `claude-responder.yml`,
   `claude-review.yml`, `docs-check.yml`, `shellcheck.yml`. The single trust
   point that originally looked convenient now means a merge here —
   including by an agentic runner, not only a human — changes every caller's
   CI on its next run with no staging window and no opt-out. The
   SLSA Source-track lens on unversioned refs made this concrete in the
   2026-08 architecture review (item R09).

2. **SHA-pinning third-party actions established the fleet's stated posture on
   mutable refs.** [lentago/.github#113](https://github.com/lentago/.github/issues/113)
   SHA-pinned every third-party action reference across the fleet because tags
   are mutable. Consuming our own reusable workflows through a mutable pointer
   — `@main`, or a moving major tag — would contradict that reasoning in the
   one place a compromise reaches everything at once.

[v1.0.0](https://github.com/lentago/shared-workflows/releases/tag/v1.0.0) was
cut from `main` at the point where every third-party action inside these
workflows is SHA-pinned ([#42](https://github.com/lentago/shared-workflows/pull/42))
and the repo carries its own Scorecard posture
([#43](https://github.com/lentago/shared-workflows/pull/43)) — a defensible
baseline from which to freeze.

## Decision

Callers migrate from `@main` to **immutable semver tags** (`@v1.0.0`, `@v1.1.0`,
etc.). Each release is a fixed point; changing what a caller runs requires an
explicit, reviewable bump in that caller's repo. `@main` is not a supported
consumption path going forward.

This repo's own internal references (it consumes its own
`render-claude-summary` composite action) are updated to `@v1.0.0` as the first
migration and a worked example. Fleet callers are staged per repo behind the
in-flight pinning and Dependabot rollout to avoid two writers on one workflow
file.

## Alternatives

**Moving major tag (`@v1`).** This is the standard GitHub Actions convention:
point `v1` at each new v1.x release so callers that pin `@v1` get the latest
v1.x automatically. Rejected. A moving tag is *mutable*: repointing it changes
CI in all 16 repos at once, silently. That is the same failure mode as `@main`
— it differs only in requiring a deliberate retag rather than a merge. The
fleet just SHA-pinned every third-party action precisely because tags are
mutable; consuming our own reusables through a moving tag would reproduce
exactly the risk that versioning is supposed to remove, only with more
ceremony. Immutability is the whole point of the exercise.

**SHA-pin every caller** (`uses: .../claude-review.yml@<full-sha>`). This is
strictly higher hygiene than semver tags and was considered in ADR-0002 (as a
retrospective alternative). The same reasoning that rejected it there applies
here: SHA pinning kills the "one PR changes CI everywhere" property entirely
— every bump becomes a commit in every caller rather than a Dependabot PR.
For a lab-scale, single-operator fleet without third-party contributors to this
repo, the supply-chain risk difference between SHA and semver tag is marginal;
the coordination cost is not. Semver tags with Dependabot coverage deliver the
useful immutability property at acceptable overhead.

**Keep `@main`.** The status quo that motivated the 2026-08 review. Rejected:
the architecture review flagged undocumented as the only wrong state
(issue #40), the SHA-pinning wave made `@main` consumption inconsistent with
the fleet's stated posture on mutable refs, and v1.0.0 now exists as a
baseline to move from.

## Consequences

- **Releases no longer propagate for free.** A new version of a workflow
  requires callers to bump their `uses:` ref. This is the core trade-off.
- **Dependabot covers the bump as a reviewable PR.** Dependabot's
  `github-actions` ecosystem updates reusable-workflow references, so bumps
  arrive as reviewable PRs in each caller repo once Dependabot is enabled
  there. The fleet-wide Dependabot rollout
  ([lentago/.github#114](https://github.com/lentago/.github/issues/114)) is in
  flight; where it has not landed yet, bumps are manual until it does.
- **`@main` continues working during migration.** Nothing breaks if a repo
  migrates late — the change is additive and the migration is staged per repo.
- **The release process gains weight.** Cutting a version now means writing
  release notes and thinking about semver: what's a breaking change vs. a
  minor addition vs. a patch. See [RELEASING.md](../../RELEASING.md) for the
  standing process.
- **ADR-0002 is superseded**, not reversed. The reasoning in ADR-0002 for
  `@main` was sound at repo inception; this decision reflects the fleet
  reaching a scale and posture where the deferred tagging work becomes the
  right next step, exactly as ADR-0002 described.

## Addendum 2026-11-01

On 2026-11-01 the GitHub release API reported `immutable: false` for `v1.5.0`,
and no repository ruleset or tag protection covered tags. The immutability this
ADR relies on is therefore a convention until the tag ruleset tracked in
[lentago/.github#305](https://github.com/lentago/.github/issues/305) is applied.
Until then, a `v*` tag can still be moved or deleted, and the guarantee in the
Decision section holds only by operator discipline.

**Decision (not to adopt full-SHA pinning fleet-wide).** Callers keep the
semver-tag form described above and do not move to full-commit-SHA pins across
the fleet. Both the caller and the reusable workflow are owned by one
organization, so the supply-chain distance that SHA pinning guards against is
small. A tag ruleset that forbids deleting or moving `v*` tags provides the same
guarantee as a SHA pin, without a bump in every caller on every release. The
Alternatives section's cost argument therefore still holds, and the ruleset
(not SHA pinning) is the mechanism that closes the gap noted above.
