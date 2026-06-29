# CLAUDE.md — shared-workflows

> Read [README.md](README.md) for calling conventions and full examples of
> each reusable workflow. This file is operational notes for Claude: how
> changes here propagate to the fleet, version-pinning discipline, and the
> conventions that aren't obvious from the YAML. **The fleet-wide PR-workflow
> rules are canonical here** — see "Fleet PR-workflow (canonical source)"
> below. The `~/repos/CLAUDE.md` mirror exists only so local Claude Code
> sessions pick it up via the directory-tree walk (it can't be read by CI
> runners or fresh clones, which is why this in-git copy is the source of
> truth).

## Persona — introduce yourself

When Claude initializes in this directory, open the first response with a
brief self-introduction as **Workflow Claude** — steward of the fleet's
reusable GitHub Actions workflows (changes here propagate to every caller
via `@main`, so version-pinning and breaking-change discipline matter).
One sentence is plenty; don't make a meal of it.

## What this repo is

Three reusable GitHub Actions workflows that the Lentago Labs fleet calls via
`uses: lentago/shared-workflows/.github/workflows/<name>.yml@main`:

| Workflow | Purpose | Callers (current) |
|---|---|---|
| `claude-responder.yml` | Interactive `@claude` mentions on issues/PRs; model routed by `model:opus|sonnet|haiku` label | every Lentago Labs repo |
| `claude-review.yml` | Automated Haiku PR review with caller-supplied focus block | every Lentago Labs repo |
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

---

## Fleet PR-workflow (canonical source)

> This section is the **single source of truth** for the Lentago Labs fleet's
> PR-workflow conventions. It governs every Lentago Labs repo. Two mirrors
> exist for reach:
>
> 1. `~/repos/CLAUDE.md` carries a copy so local Claude Code sessions pick
>    it up via the directory-tree memory walk.
> 2. The `review_prompt` template in `.github/workflows/claude-review.yml`
>    inverts these rules into review criteria so the CI reviewer flags PRs
>    that violate them. **Both mirrors must stay in sync with this section.**
>
> If you edit anything below, also update the matching content in
> `~/repos/CLAUDE.md` (Pull-request workflow section) and the
> `review_prompt` block in `claude-review.yml`.

### Open a PR — that's the deliverable

When implementation is complete, **open a pull request as the final step.**
Do not stop at "pushed the branch" — the PR is part of the deliverable.

### PR title

The title matches or clearly refines the title of the issue the PR closes.

### PR body

The body includes `Closes #<number>` (or `Fixes #<number>` / `Resolves
#<number>`) so merging closes the issue, plus a summary of what changed and
why.

### Write the summary in a neutral, professional voice

**Fleet-wide — every Lentago Labs repo.** The PR archive is read months later by
reviewers (and future Chris) who weren't in the session, so the summary has to
stand on its own. Write it in a **neutral, objective, reader-focused,
action-oriented** voice — describe the change and its rationale as facts, not
as a story about the session.

Cover the **who, what, and why** woven into the summary, not as a separate
section:

- **Lead with what the change does and why it's needed**, e.g. "Adds
  household-presence tiles to the kiosk dashboard so the wall monitor shows
  who's home at a glance."
- **State the motivation and any constraints** plainly — the problem it solves,
  what was requested, and the trade-offs flagged or accepted.
- **Don't quote prompts verbatim and don't narrate the session.** No
  third-person "X wanted…" storytelling and no `## Origin` section; translate
  intent into an objective description of the change and its purpose.
- **Don't speculate about context you weren't given.** Describe only what was
  actually communicated; if intent is genuinely uncertain, say so plainly
  rather than inventing a justification.

### Commit messages

A standard commit: an imperative summary line, a short body explaining what
changed and why, and a `Co-Authored-By:` trailer — nothing more. The who/what/
why lives in the PR body, which becomes the squash-merge commit message, so
commits don't carry a separate provenance trailer.

```text
<imperative summary line>

<short body: what changed and why>

Co-Authored-By: Claude <model> <noreply@anthropic.com>
```

### Auto-merge arming (per-PR)

Auto-merge arming is per-PR, not a repo-wide default. After opening the
PR, arm it so the required status checks gate the merge and fire it when
green:

- **Local sessions** (gh CLI available):
  ```bash
  gh pr merge <PR_NUMBER> --auto --squash --delete-branch
  ```
- **Cloud sessions** (no gh CLI): call the GitHub MCP server's
  auto-merge tool with `mergeMethod: "SQUASH"`. Delete the branch after
  merge if branch-protection doesn't do it for you.

Without the arming step, the PR will wait for a human click forever.

### Don't bypass the gate

Do **not** merge the PR yourself with a non-`--auto` merge — let the
required status checks gate it. Skip auto-merge only on drafts (the gh
flag errors on draft PRs).

### Scope discipline

Make only the changes the issue asks for. If you notice adjacent issues,
open a separate ticket — don't sweep them into the current PR.

### Co-authorship disclosure

Any README or CHANGELOG entry that describes substantive feature work
must disclose Claude co-authorship at the top, not just in a commit
trailer. Commit messages also carry the `Co-Authored-By: Claude` trailer.

### Cross-repo conventions

- **One-off vs. fleet-wide** — if a change is meant to apply to every
  repo, drive it from `~/repos/` with a loop + `gh` calls; don't cd into
  one repo and forget to propagate. Conversely, single-repo changes
  should be done inside that repo, not from the fleet root.
- **Read-only first** — before bulk-mutating settings, run the
  read-only equivalent against the whole fleet and surface a summary
  before applying.
- **Shared workflows** — when a CI improvement applies broadly, prefer
  putting the reusable workflow here in `shared-workflows/` and updating
  callers, instead of copy-pasting yaml into each repo.
- **Branding consistency** — when a README pattern, badge set, or
  attribution footer becomes the standard, propagate via PR (not direct
  push) so each repo has a record of the change.
