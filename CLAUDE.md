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
reusable GitHub Actions workflows (callers pin to immutable semver tags, so
breaking-change discipline and the release process in RELEASING.md matter).
One sentence is plenty; don't make a meal of it.

## What this repo is

Reusable GitHub Actions workflows that the Lentago Labs fleet calls via
`uses: lentago/shared-workflows/.github/workflows/<name>.yml@v1.0.0` (immutable
semver tag — see [ADR-0005](docs/adr/0005-immutable-semver-tags-replace-main-consumption.md)
and [RELEASING.md](RELEASING.md)):

| Workflow | Purpose | Callers (current) |
|---|---|---|
| `claude-responder.yml` | Interactive `@claude` mentions on issues/PRs; model routed by `model:opus|sonnet|haiku` label | every Lentago Labs repo |
| `claude-review.yml` | Automated Haiku PR review with caller-supplied focus block | every Lentago Labs repo |
| `shellcheck.yml` | ShellCheck on `.sh` files, explicit list or repo-wide auto-discovery | repos with bash (`firewalla-axiom-pipeline`, `drosera`, `kalmia`, `workstation-bootstrap`) |
| `docs-check.yml` | Relative-markdown-link resolver; unconditional so it can be a required check | intended fleet-wide (adoption pending) |
| `tf-lint.yml` | Terraform quality gates: fmt, validate (no-backend), tflint, trivy config; per-gate toggles | `solidago`, `kalmia`, `claytonia`, `drosera`, `.github` (adoption pending) |
| `site-deploy.yml` | Astro site → ECR → ECS Fargate; includes Trivy scan + SLSA L3 attestation; callers migrate one at a time | `site-lentago-dev`, `site-icecreamtofightwith-com`, `site-pondviewlane-com` (pending migration) |

`docs-check.yml` runs the resolver in `ci/check_docs_links.py` (tested by
`ci/test_check_docs_links.py`) against the caller's tree. It must be triggered
with **no `paths:` filter** — it's designed as a required status check, and a
required check that never triggers deadlocks non-matching PRs
(`fleet-ops/required-checks.json`).

## Architecture / load-bearing knowledge

**Caller flow** for each workflow lives at the bottom of `README.md` — the
caller passes a thin `with:` block; the reusable workflow handles auth,
context, output format, and the heavy lifting. Callers should **never**
copy the workflow YAML into their own `.github/workflows/` — they `uses:` it.

**Callers pin to immutable semver tags.** Callers use `@v1.0.0` (or the current
release). `@main` is not a supported consumption path. See [RELEASING.md](RELEASING.md)
for how to cut a release and how callers upgrade.

**`secrets: inherit`** is required on the caller side — these workflows
expect `ANTHROPIC_API_KEY` (and any model-routing PAT) to be in the org or
repo secrets store, passed through transparently.

## Conventions specific to this repo

- **Backwards-compatible inputs only.** Adding a required input breaks
  every caller silently (workflow_call merge errors don't fire until the
  next caller run). Add inputs as optional with sensible defaults.
- **Document new inputs in README.md.** This is the only documentation
  callers see — no separate site, no schema export.
- **Test before merging to `main`.** Push to a branch, point one caller repo's
  workflow at `@<branch-name>` for one merge, then merge to `main`. Only after
  that, cut a release tag — callers pick up changes only once they bump to the
  new tag. See [RELEASING.md](RELEASING.md) for what must be green before
  tagging.

## Gotchas

- **`paths-ignore` doesn't gate the reusable workflow itself.** The caller's
  `on:` block decides what triggers the workflow; once triggered, the
  reusable workflow always runs. Filter at the caller, not here.
- **`main` is not a release.** Callers pin to semver tags, not `@main`. A
  change merged here is not live for callers until a new tag is cut and
  callers bump their `uses:` ref. `@main` continues to work mechanically but
  carries no stability guarantee.
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

## Live-state vs. code discipline (canonical source)

> Mirrored in `~/repos/CLAUDE.md` for local sessions — keep the two in
> sync, same obligation as the PR-workflow mirror above.

Several Lentago Labs systems continuously **enforce state from git via a
CI apply job**: whatever is on `main` *is* the live state, and the apply
can be triggered by a completely unrelated merge.

Known enforced surfaces (extend this list when a new one ships):

| Live surface | Owning repo / mechanism |
|---|---|
| Grafana Cloud dashboards | `drosera` — terraform workflow applies `dashboards/*.json` on **every merge to main** |
| Route 53 / `lentago.dev` DNS | `solidago` Terraform (`modules/apex-domain` — zone + ACM cert; corrected 2026-08-12, was misattributed to `site-lentago-dev`, which carries no Terraform) — never console-edit |
| GitHub repo settings, rulesets & labels (every org repo — 27 as of 2026-10-06 — incl. repo existence) | `.github` meta-repo — `terraform` workflow applies `terraform/` on **every merge to main** (plan-on-PR + required `gate`; live 2026-08-17, .github#81). `fleet-ops/fleet-apply.sh` remains only for `--prune-branches` and the required-context preflight |
| Central Alloy config (LXC 105) | `drosera` — `alloy-gitops.timer` pulls `main` every 5 min |
| Proxmox guests on `homelab-cluster` (VM/LXC existence & shape) — all except the bullpen runner pool — plus the cluster vzdump backup jobs (kalmia#30) | `kalmia` — `terraform` workflow applies `terraform/` on **every merge to main**, via the LAN self-hosted runner (LXC 115 `gha-runner`) |
| Proxmox guests — the bullpen runner pool (LXC 110–112, 116–117 in the `claytonia` PVE pool) | `claytonia` — `terraform` workflow applies `terraform/` on **every merge to main**, via a second LAN self-hosted runner agent on LXC 115 `gha-runner` (adopted from kalmia 2026-07-07, claytonia#51/kalmia#37) |
| Axiom datasets + retention (betula's archive plane: `cjp-solidago-*`) | `betula` — `terraform` workflow applies `terraform/` on **every merge to main** (plan-on-PR + `gate`; live 2026-10-06, betula#118). Datasets carry `prevent_destroy`; tokens are not yet managed (betula#119) |
| Firewalla on-box config — Fluent Bit conf, `user_crontab`, collector scripts (incl. the `device_inventory` collector) | `betula` — on-device `gitops-sync.sh` pulls `main` every 5 min and applies (crontab via `update_crontab.sh`, never a raw `crontab` install) |

Rules:

1. **Never mutate an enforced surface live** (UI, HTTP API, MCP tool)
   without codifying the identical change in the owning repo **in the
   same session** — PR opened and auto-merge armed. A live-only edit
   survives exactly until the next apply.
2. **Live-ahead-of-repo state is a fire, not a curiosity.** If live
   state doesn't match the repo (e.g. dashboard panels absent from the
   JSON), someone's un-codified work is one merge away from destruction:
   recover it into a PR *before* merging anything else to that repo.
3. Systems usually keep a recovery trail (Grafana dashboard version
   history, Route 53 change log, ruleset audit log) — check it before
   declaring live-only work lost.

Origin: 2026-07-03 — an infra-health dashboard revamp pushed live via
the Grafana API but never committed was silently reverted by the
terraform applies of five unrelated bug-fix merges
(`drosera#119` restored it from version history).

## Rename discipline (canonical source)

> Mirrored in `~/repos/CLAUDE.md` for local sessions — keep the two in
> sync, same obligation as the mirrors above.

A rename isn't done when the repo URL changes — it's done when **no
surface still carries the old name**, or every surface that does is
owned by an open tracking issue. Renames propagate through four tiers,
in order of increasing friction:

1. **Repo & docs** — repo name (GitHub redirects cover old URLs),
   README, CLAUDE.md persona, badges, concept docs.
2. **Registries & indexes** — fleet inventory in `~/repos/CLAUDE.md`,
   bullpen `projects/registry.json`, Grafana dashboards/folders, DNS
   names, memory files.
3. **Infrastructure-as-code** — terraform resource names and hostnames,
   ansible role/var/unit/user names, workflow names, OIDC role names,
   tfstate keys.
4. **Live runtime** — on-host clone paths, systemd units, service
   users, container hostnames, cloud resource names.

Rules:

1. **Never bless-and-forget.** "We'll keep the legacy name" is not a
   resolution. Documenting a legacy name is a *tracking* action — valid
   only alongside an open issue in the owning repo that owns completing
   the rename. Closing that issue with "documented, keeping legacy" is
   exactly what this rule forbids.
2. **Tiers 1–2 rename in the same session as the rename itself.**
   They're low-risk and reversible; there is no reason to defer them.
3. **Tiers 3–4 may be deferred, never dropped.** They usually need live
   migration (unit stop/rename, state moves, replays, dual-trust
   windows). Defer them into the tracking issue with a concrete
   execution plan and constraints; the issue stays open until live
   state matches the new name.
4. **Runtime renames follow the live-state discipline** (above):
   codify in the owning repo and apply/replay to live in the same
   effort — never live-rename without codifying.

Origin: 2026-07-21 — the day after the lunaria → brasenia product
rename, kalmia#61 was resolved by *blessing* the legacy runtime names,
following the then-precedent from the 2026-07-04 rebrand wave. The
policy was reversed the same morning. Grandfathered debt from that era,
now tracked: kalmia#63 (lunaria runtime), betula#89 (on-device clone
path), drosera#169 (OIDC role / tfstate key / on-host paths),
claytonia#65 (on-host bullpen names). solidago's AWS `foundry-*` rename
was *already complete* when solidago#142 was filed against it on
2026-07-21 — that ticket was written from a stale fleet-inventory
premise rather than from live state, and was closed as OBE on
2026-07-25. Check live state before filing rename debt from inventory
docs.
