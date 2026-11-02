# Changelog

> Substantive feature work in this file was co-authored with Claude (Anthropic).

Releases are cut per [RELEASING.md](RELEASING.md); callers pin to immutable
semver tags.

## v1.7.0 (unreleased)

### Added

- **`agent-pr-verdict.yml`, the agent PR gate's trusted path (#97).** v1.6.0's
  `agent-pr-gate.yml` runs as an Actions job, and the runner App holds
  `workflows: write`, so a PR it opens could add a job that reports a passing
  check under the gate's name from the same source. The 2026-11-02 decision on
  #84 keeps that permission and adds a check the runner App cannot produce.
  - The verdict is the same decision as `agent-pr-gate.yml`, through the same
    `ci/agent_pr_gate.py`, posted as a check run named `agent-pr-verdict` by a
    second GitHub App, the gate App. The ruleset requires it by the gate App's
    integration ID, which no Actions job reports from.
  - It is computed only in runs whose workflow file and code the PR cannot
    change: `pull_request_target` (the base branch's file), `workflow_run` on
    completion of the repo's `agent-pr-gate` caller (the default branch's
    file; reviews arrive this way, since `pull_request_review` has no `_target`
    form), and `issue_comment` for the cr-automerge record (the default
    branch's file; this replaces the gate's 120-second poll on that path). The
    job takes only the PR number from the event, reads the PR's current state
    with the read-only `GITHUB_TOKEN`, and posts on the PR's current head. It
    never checks out or runs the PR's code.
  - The gate App's key is the `AGENT_PR_GATE_APP_KEY` secret of an
    `agent-pr-gate` environment, one per gated repo, with deployment branches
    limited to `main` and no admin bypass; `AGENT_PR_GATE_APP_ID` is the
    environment's variable. The job mints an installation token for its one
    repository with `checks: write` only, revoked when the job ends. A run
    from a pull-request merge ref, or from a branch the runner App pushed, is
    refused the environment. Because GitHub auto-creates an unprotected
    environment on first reference, the job reads the environment before
    minting a token and refuses one without custom branch policies or with an
    admin bypass; the environment is created by Terraform before any caller
    references it.
  - The job's own result says whether a verdict was posted; the verdict is the
    check run. A missing secret or variable, an unreadable PR, or a refused
    check run fails the job, and a PR with no verdict on its head stays
    blocked.
  - The README lists the conditions that keep it unfakeable, the environment,
    secret and variable names, and the caller snippet. This repo runs it on its
    own PRs through `agent-pr-verdict-self.yml`, the pilot. Creating the
    environment and requiring the check are lentago/.github's follow-up.
- This repo's own `ci/test_*.py` now run on every PR, through `ci-tests.yml`
  (#99). Before this, nothing ran them. It is not a reusable workflow, so
  callers have nothing to change.

### Changed

- **`agent-pr-gate.yml` and `ci/agent_pr_gate.py` identify the runner App by
  numeric ID, never by login (#97).** REST reports the App as
  `lentago-claude-runner[bot]` and GraphQL as `lentago-claude-runner`, which is
  also a valid login for a human account. The PR's author is matched on the
  App's bot-account user ID (`pull_request.user.id`), and a cr-automerge
  record on the comment's `performed_via_github_app.id`, the App's
  integration ID.
  - New optional inputs `agent_user_id` (default `293961292`) and
    `agent_app_id` (default `4062202`) on both workflows. `agent_author` stays
    as an input; it now names the App in messages only. A caller that sets it
    to another agent while either ID is still the default fails the job,
    rather than gating the runner App and passing its own agent's PRs: set
    `agent_user_id` and `agent_app_id` for that agent.
  - The script's gate-mode arguments are `--author-id` and `--author-login`
    in place of `--author`, with `--agent-user-id`, `--agent-app-id` and
    `--agent-login` in place of `--agent`. The script ships with the workflow
    at the same commit, so no caller runs a mismatched pair.
  - A human-authored PR still passes without an API call: the job compares
    the event's author ID to the input before anything else.

Minor, not patch, because `agent-pr-verdict.yml` is a new workflow file and
both workflows gain inputs. Callers of `agent-pr-gate.yml` that use the
defaults, which is every caller in the fleet, have nothing to change; the only
effect for them is that identity no longer depends on how an API spells a
login. A caller that named another agent by `agent_author` alone fails loudly
until it sets that agent's IDs, rather than silently passing that agent's PRs.

## v1.6.0 (2026-11-02)

### Added

- **`agent-pr-gate.yml`, a required check that holds runner-App PRs for a
  human approval (#84).** lentago/claytonia#117 chose option A on 2026-10-30,
  and lentago/.github ADR-0014 records the rule: a PR the bullpen's runner App
  authored merges only after a human with write access approves its current
  head, or under `cr-automerge`'s routine exception.
  - A PR the App did not author passes at once, without an API call.
  - A runner-App PR passes when a non-bot user with write access has approved
    the head commit being checked. A push re-runs the gate on the new head,
    where the old approval no longer counts.
  - Under the routine exception, it passes when the App's latest
    `<!-- cr-automerge armed rule=<rule> head=<sha> -->` record
    (lentago/claytonia#178) names that head and the PR still meets the rule in
    the default branch's `.claytonia/automerge.json`. A push after arming fails
    the gate. Records from any other author are ignored.
  - Anything else fails with one line naming what is missing, and so does a
    failed API call.
  - The token is read-only: `contents: read` and `pull-requests: read`. The
    logic is in `ci/agent_pr_gate.py`, with tests in `ci/test_agent_pr_gate.py`.
  - This repo runs it on its own PRs through `agent-pr-gate-self.yml`, with the
    script taken from the PR's base commit so a PR can't edit the script that
    checks it. Making the context required is lentago/.github#289.
  - Its limit is recorded in the README. The runner App holds
    `workflows: write`, so a PR it opens can add a workflow with a job named
    like this one that passes, and required contexts are matched by name.
    Until that permission goes, the gate stops a merge the App attempts by
    mistake, not one it is trying to force.
- Internal `render-claude-summary` refs point at `v1.6.0`.

### Fixed

- **`docs-check.yml` runs the resolver from the tag the caller pinned (#95).**
  The tooling checkout read `github.job_workflow_ref`, which is not a property
  of the `github` context. It evaluated empty, so `actions/checkout` took this
  repository's default branch. Every caller therefore ran `main`'s
  `ci/check_docs_links.py`, whatever tag it pinned (ADR-0005). This repo's own
  self-caller hid the bug, because there an empty ref resolves to the PR under
  test.
  - The checkout now uses `job.workflow_repository` at `job.workflow_sha`, the
    reusable workflow's own commit. If either is empty, the job fails instead
    of falling back to a default branch.
  - A new step, "Verify the resolver is the pinned commit", fails the job when
    the checkout isn't that commit, or when the caller pinned a tag that
    resolves to another commit. Its log line names the commit and the pinned
    ref.
  - No input or job name changed. The only effect for callers is that a tag
    pin now holds for the resolver too.
  - A caller keeps running `main`'s resolver until it bumps to this release,
    because earlier tags carry the old `docs-check.yml`. Each caller's bump PR
    runs the new verify step before that caller merges.

Minor, not patch, because `agent-pr-gate.yml` is a new workflow file. The
`docs-check.yml` fix on its own would be a patch. Callers of the other
workflows have nothing to change.

## v1.5.1 (2026-11-02)

### Fixed

- **`site-deploy.yml` fails the job when ECS rolls the deployment back
  (#92).** lentago/solidago#253 turned on the ECS deployment circuit breaker
  with `rollback = true` for every platform service. When a deployment's tasks
  never become healthy, ECS now rolls back to the last completed deployment.
  The service stabilizes on the old image, and `aws ecs wait services-stable`
  succeeds, so the job went green although the new image never went live.
  - "Force new ECS deployment" records the id of the PRIMARY deployment in the
    `update-service` response. That is the deployment this run started.
  - "Wait for deployment and verify rollout" replaces "Wait for deployment to
    stabilize". After the wait, it requires that same deployment to be PRIMARY
    with `rolloutState` `COMPLETED`. An `IN_PROGRESS` rollout gets up to two
    minutes to finish.
  - Any other outcome fails the job and prints the service's last 15 events:
    a rollback or another update replacing the deployment, a `FAILED` rollout,
    or a waiter timeout.
  - The check reads only `ecs:DescribeServices`, which the waiter already
    needs. Callers need no new IAM.
- RELEASING.md records how `site-deploy.yml` can be validated, given that the
  deploy role's OIDC trust admits only a caller's `main` branch.
- Internal `render-claude-summary` refs point at `v1.5.1`.

Patch, not minor: no input, permission or job name changed. The effect for
callers is that a deploy whose image did not go live now reports red, as it did
before the breaker was turned on.

A deployment that another update replaces before it completes also reports
red, because the job can't confirm its own image went live. Overlapping merges
don't trigger this: each calling site repo holds a workflow-level `deploy-main`
concurrency group with `cancel-in-progress: true`, so the older run is
cancelled, not failed. What does trigger it is an out-of-band `update-service`
on the same service during the wait, such as a Terraform apply or a console
change.

## v1.5.0 (2026-10-29)

### Changed

- **`claude-review.yml` now posts the review (fixes #80).** Since the workflow
  was added in April, the model ran with only `gh pr diff`, `gh pr view` and
  `Read`, which is correct for a reviewer, but nothing posted its answer. Every
  review reached the job's step summary and never the PR.
  - A new step, "Post the review (or a soft-fail notice)", reads the run's final
    result from the execution file and posts it as one PR comment headed
    `Review (<model>, claude-review.yml)`, with a hidden
    `<!-- claude-review run=… model=… -->` marker.
  - The model stays read-only. Its `@mentions` are defused so a review can't
    ping anyone.
  - Bodies over 60,000 characters are truncated, below GitHub's 65,536 cap.
  - The step is `continue-on-error` and skips cancelled runs, so a failed post
    never reddens the check (ADR-0003).
- **The soft-fail notice now covers every run that produced no review,** not
  only a failed action step: turn exhaustion, an error result, an unreadable
  execution file, and `claude-code-action`'s silent self-skip on PRs that change
  the caller workflow. Before, a skipped or result-less run was a green check
  with nothing posted. The notice says plainly that it is not a review
  (lentago/.github ADR-0013's arming rule). Draft PRs remain skipped at the job
  level, with no comment.
- The review prompt's output instructions tell the model that its final message
  is posted verbatim, and that it has no posting tool.
- Internal `render-claude-summary` refs point at `v1.5.0`.

Minor, not patch: no input, secret or permission changed, but callers on this
version start receiving a PR comment on every non-draft review run, where before
they received none. That is a visible behaviour change, which RELEASING.md files
under minor.

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
