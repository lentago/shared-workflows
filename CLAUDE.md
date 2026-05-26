# CLAUDE.md — shared-workflows

> Read [README.md](README.md) for calling conventions and full examples of
> each reusable workflow. This file is operational notes for Claude: how
> changes here propagate to the fleet, version-pinning discipline, and the
> conventions that aren't obvious from the YAML. Fleet-wide rules (PR
> workflow, attribution) live in `~/repos/CLAUDE.md`.

## What this repo is

Three reusable GitHub Actions workflows that the PitziLabs fleet calls via
`uses: PitziLabs/shared-workflows/.github/workflows/<name>.yml@main`:

| Workflow | Purpose | Callers (current) |
|---|---|---|
| `claude-responder.yml` | Interactive `@claude` mentions on issues/PRs; model routed by `model:opus|sonnet|haiku` label | every PitziLabs repo |
| `claude-review.yml` | Automated Haiku PR review with caller-supplied focus block | every PitziLabs repo |
| `shellcheck.yml` | ShellCheck on `.sh` files, explicit list or repo-wide auto-discovery | repos with bash (`firewalla-axiom-pipeline`, `homelab-observability`, `workstation-bootstrap`) |

## Architecture / load-bearing knowledge

**Caller flow** for each workflow lives at the bottom of `README.md` — the
caller passes a thin `with:` block; the reusable workflow handles auth,
context, output format, and the heavy lifting. Callers should **never**
copy the workflow YAML into their own `.github/workflows/` — they `uses:` it.

**Floating `@main` is the default.** Callers use `@main` for the tip. Once
a workflow contract solidifies, tag a stable version (`v0.1.0`, `v1`) and
migrate callers to the tag — this isn't done yet (no tags shipped).

**`secrets: inherit`** is required on the caller side — these workflows
expect `ANTHROPIC_API_KEY` (and any model-routing PAT) to be in the org or
repo secrets store, passed through transparently.

## Conventions specific to this repo

- **Backwards-compatible inputs only.** Adding a required input breaks
  every caller silently (workflow_call merge errors don't fire until the
  next caller run). Add inputs as optional with sensible defaults.
- **Document new inputs in README.md.** This is the only documentation
  callers see — no separate site, no schema export.
- **Test before publishing on `main`.** Push to a branch, point one repo's
  workflow at `@<branch-name>` for one merge, then merge to `main`. Once
  on `main`, every caller picks it up on their next workflow run.

## Gotchas

- **`paths-ignore` doesn't gate the reusable workflow itself.** The caller's
  `on:` block decides what triggers the workflow; once triggered, the
  reusable workflow always runs. Filter at the caller, not here.
- **`@main` floats.** A breaking change in this repo's `main` will break
  every caller's next run. Treat `main` changes as if they were releases
  until tagged versions exist.
- **`workflow_call` jobs don't show up in `gh workflow run` lists** on
  caller repos — they appear as `Called by:` in the caller workflow's run
  page, not as standalone runs in this repo's Actions tab.

## When in doubt

- **Calling pattern for a workflow?** `README.md` has the canonical example.
- **What inputs does X accept?** Look at the `inputs:` block in
  `.github/workflows/<name>.yml`.
- **Why is a caller failing?** Check the caller's Actions tab — the reusable
  workflow runs in the caller's context, not here.
