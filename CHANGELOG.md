# Changelog

> Substantive feature work in this file was co-authored with Claude (Anthropic).

Releases are cut per [RELEASING.md](RELEASING.md); callers pin to immutable
semver tags.

## v1.3.0 (2026-10-07)

### Added

- `site-deploy.yml`: new optional `version_file` input (default
  `public/version.json`). After checkout and before the pre-build command and
  Astro build, the workflow writes `{sha, repo, built_at, run_url}` to that
  path with `jq`, so every calling site serves its deployed commit at
  `/version.json`. Set `version_file: ""` to disable. Backwards-compatible;
  callers pick it up by bumping their `uses:` ref.
