# Changelog

> Substantive feature work in this file was co-authored with Claude (Anthropic).

Releases are cut per [RELEASING.md](RELEASING.md); callers pin to immutable
semver tags.

## v1.4.0 (2026-10-13)

### Changed

- `claude-responder.yml`: the `max_turns` default rises from 40 to 80. The cap
  is a runaway guard, but at 40 it failed runs that had already finished their
  work: `claude-code-action` reports "Claude reported a successful result after
  46 turns, exceeding the configured maximum of 40" and the run goes red after
  the comment or branch is already posted (lentago/claytonia#139 and #140 on
  2026-10-13; see #72). 46 turns was a normal issue-reading task, so 80 leaves
  room for one while still stopping a session that never converges. If you want
  the old cap, set `max_turns: 40`. Minor, not patch: a default changed, and the
  only effect for callers on the default is that longer runs are allowed.
- Internal `render-claude-summary` refs point at `v1.4.0`.

## v1.3.1 (2026-10-13)

### Fixed

- `claude-responder.yml`: bot-authored events are skipped at the job level
  instead of started and refused. A `@claude` mention written by a bot the
  caller has not listed in `allowed_bots` (CodeRabbit's review comments were
  the recurring case) used to start the job, which `claude-code-action` then
  failed with "Workflow initiated by non-human actor", leaving a red
  `claude / claude` check and an UNSTABLE merge state on the PR for no defect
  in the repo. The job's `if:` now mirrors the action's allow-list (`*`, or the
  sender's login with or without `[bot]`, case-insensitive), so those events
  leave the check skipped; human mentions and listed bots run as before. No
  input changed and the `allowed_bots` default stays `github-actions`. (#68)
- Internal `render-claude-summary` refs point at `v1.3.1`.

## v1.3.0 (2026-10-07)

### Added

- `site-deploy.yml`: new optional `version_file` input (default
  `public/version.json`). After checkout and before the pre-build command and
  Astro build, the workflow writes `{sha, repo, built_at, run_url}` to that
  path with `jq`, so every calling site serves its deployed commit at
  `/version.json`. Set `version_file: ""` to disable. Backwards-compatible;
  callers pick it up by bumping their `uses:` ref.
