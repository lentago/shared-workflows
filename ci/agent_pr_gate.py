#!/usr/bin/env python3
"""agent-pr-gate: decide whether a pull request may merge, as far as authorship goes.

Two reusable workflows run this (lentago/claytonia#117 option A; lentago/.github
ADR-0014 points 2, 4 and 5). Both read GitHub state through the REST API with a
read-only token.

  - `agent-pr-gate.yml`, the accident layer, on every pull_request and
    pull_request_review event. The event supplies the head and the author; the
    job's own result is the check.
  - `agent-pr-verdict.yml`, the trusted path (#97), on pull_request_target,
    workflow_run and issue_comment events, which run a workflow file the PR
    cannot change. It takes only the PR number from the event, reads the PR's
    current head and author from the API, and posts the result as a check run
    with a token of the gate App (`--verdict NAME`). A ruleset can require that
    check by the gate App's integration ID, which no Actions job can produce.

The decision is the same in both:

  - A PR the runner App did not author passes at once.
  - A runner-App PR passes when the latest review that decided something
    (APPROVED, CHANGES_REQUESTED or DISMISSED) from some user is APPROVED, is on
    the head commit being checked, and comes from a non-bot user with write
    access to the repository.
  - Otherwise it passes only under the routine exception (ADR-0014 point 4):
    the PR's latest `cr-automerge` record, a comment by the runner App whose
    first line is `<!-- cr-automerge armed rule=<rule> head=<sha> -->`, names
    the head being checked, and the PR still meets that rule as the default
    branch's `.claytonia/automerge.json` defines it (lentago/claytonia
    ADR-0009 conditions 2-5). The rule is checked again here because the runner
    App can write that comment itself: a forged record passes only a PR that
    the rule would have let `cr-automerge` arm.
  - Anything else fails, with one line naming what is missing. So does any API
    error: the gate fails closed.

Identity is numeric, never a login. GitHub's APIs disagree on the runner App's
login (`lentago-claude-runner[bot]` in REST, `lentago-claude-runner` in
GraphQL), and the latter is a valid login for a human account. So:

  - The PR's author is the runner App when `user.id` is the App's bot account
    (`--agent-user-id`, default 293961292). PR objects carry no
    `performed_via_github_app`.
  - A comment is the runner App's when `performed_via_github_app.id` is the
    App's integration ID (`--agent-app-id`, default 4062202).

The App's login (`--agent-login`) appears in messages only.

The glob and title semantics match `cr-automerge` (lentago/claytonia
`bin/cr-automerge`): Python `re.fullmatch` for the title, and for paths `*`
stays inside a directory, `**` crosses directories, `?` is one character other
than `/`.

Usage:
  agent_pr_gate.py --repo OWNER/REPO --pr N --head-sha SHA --author-id ID
                   [--author-login LOGIN] [--wait-for-marker SECONDS] [identity]
  agent_pr_gate.py --repo OWNER/REPO --pr N --verdict CHECK_NAME [identity]

  identity: [--agent-user-id ID] [--agent-app-id ID] [--agent-login LOGIN]

The read token comes from GITHUB_TOKEN (or GH_TOKEN); the API root from
GITHUB_API_URL (default https://api.github.com). `--verdict` posts the check
run with the token in AGENT_PR_GATE_CHECK_TOKEN, on the head it read, and
exits 0 once the check run is posted whichever way the verdict went: the
verdict lives in the check run, and the job's own result says only whether a
verdict was posted. Exit status otherwise: 0 pass, 1 fail, 2 usage error.
Tests: python3 ci/test_agent_pr_gate.py
"""
import argparse
import base64
import collections
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

Agent = collections.namedtuple("Agent", "user_id app_id login")
DEFAULT_AGENT = Agent(user_id=293961292, app_id=4062202, login="lentago-claude-runner[bot]")
CHECK_TOKEN_VAR = "AGENT_PR_GATE_CHECK_TOKEN"
POLICY_PATH = ".claytonia/automerge.json"
MARKER = re.compile(r"<!-- cr-automerge armed rule=(\S+) head=([0-9a-f]{40}) -->")
SHA = re.compile(r"[0-9a-f]{40}")
DECIDING = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
WRITE = {"admin", "write"}  # the legacy `permission` field maps maintain to write
POLL_SECONDS = 15


class NotFound(Exception):
    pass


class GitHub:
    """The few REST calls the gate needs. Tests replace it with a fake."""

    def __init__(self, token, api_url="https://api.github.com"):
        self.token = token
        self.api_url = api_url.rstrip("/")

    def _request(self, url, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer %s" % self.token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lentago-agent-pr-gate",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp), resp.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            if e.code == 404 and body is None:
                raise NotFound(url) from None
            raise RuntimeError("%s %s: HTTP %d" % (req.get_method(), url, e.code)) from None

    def get(self, path):
        return self._request("%s/%s" % (self.api_url, path))[0]

    def post(self, path, body):
        return self._request("%s/%s" % (self.api_url, path), body)[0]

    def paginate(self, path):
        sep = "&" if "?" in path else "?"
        url = "%s/%s%sper_page=100" % (self.api_url, path, sep)
        items = []
        while url:
            page, link = self._request(url)
            items.extend(page)
            url = next((part.split(";")[0].strip()[1:-1] for part in link.split(",")
                        if 'rel="next"' in part), None)
        return items

    def permission(self, repo, login):
        try:
            return self.get("repos/%s/collaborators/%s/permission" % (
                repo, urllib.parse.quote(login, safe="")))["permission"]
        except NotFound:
            return "none"


def glob_re(pat):
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("".join(out))


def is_bot(user):
    return user.get("type") == "Bot" or user.get("login", "").endswith("[bot]")


def approvals(gh, repo, number, head):
    """Return (approvers on head, notes on approvals that did not count)."""
    latest = {}
    for review in gh.paginate("repos/%s/pulls/%d/reviews" % (repo, number)):
        user = review.get("user") or {}
        if review.get("state") in DECIDING and user.get("login"):
            latest[user["login"]] = review  # the list is chronological
    approvers, notes = [], []
    for login, review in latest.items():
        if review["state"] != "APPROVED":
            continue
        if is_bot(review["user"]):
            notes.append("%s is a bot" % login)
        elif review.get("commit_id") != head:
            notes.append("%s approved %s, an older head" % (login, (review.get("commit_id") or "?")[:12]))
        elif gh.permission(repo, login) not in WRITE:
            notes.append("%s has no write access" % login)
        else:
            approvers.append(login)
    return approvers, notes


def is_agent_user(user, agent):
    """Is this user object the runner App's bot account? Matched on the numeric id."""
    return (user or {}).get("id") == agent.user_id


def is_agent_comment(comment, agent):
    """Was this comment posted through the runner App? Matched on the integration id."""
    return ((comment or {}).get("performed_via_github_app") or {}).get("id") == agent.app_id


def latest_marker(gh, repo, number, agent):
    """The runner App's latest cr-automerge record on the PR, as (rule, head), or None."""
    found = None
    for comment in gh.paginate("repos/%s/issues/%d/comments" % (repo, number)):
        if not is_agent_comment(comment, agent):
            continue
        first = (comment.get("body") or "").split("\n", 1)[0].strip()
        match = MARKER.fullmatch(first)
        if match:
            found = (match.group(1), match.group(2))
    return found


def rule_holds(gh, repo, number, head, agent, rule_name):
    """ADR-0009 conditions 2-5 for `rule_name`, as cr-automerge checks them. Returns "" or a reason."""
    default = gh.get("repos/%s" % repo)["default_branch"]
    try:
        raw = gh.get("repos/%s/contents/%s?ref=%s" % (
            repo, POLICY_PATH, urllib.parse.quote(default, safe="")))["content"]
        policy = json.loads(base64.b64decode(raw))
    except NotFound:
        return "%s carries no %s" % (default, POLICY_PATH)
    except (KeyError, TypeError, ValueError) as e:
        return "%s on %s is unreadable (%s)" % (POLICY_PATH, default, e)
    rule = (policy.get("rules") or {}).get(rule_name) if isinstance(policy, dict) else None
    if not isinstance(rule, dict):
        return "%s on %s has no rule %r" % (POLICY_PATH, default, rule_name)
    try:
        title_re = re.compile(rule["title"])
        globs = [glob_re(p) for p in rule["paths"]]
        max_files = int(rule.get("max_files", 50))
    except Exception as e:
        return "rule %r is malformed (%s)" % (rule_name, e)
    if not globs:
        return "rule %r allows no paths" % rule_name

    pr = gh.get("repos/%s/pulls/%d" % (repo, number))
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name", "")
    if pr.get("state") != "open":
        return "the PR is %s" % pr.get("state")
    if pr.get("draft"):
        return "the PR is a draft"
    if (pr.get("base") or {}).get("ref") != default:
        return "the PR targets %s, not %s" % ((pr.get("base") or {}).get("ref"), default)
    if head_repo.lower() != repo.lower():
        return "the PR's branch is in %s, not %s" % (head_repo or "a deleted repository", repo)
    if not is_agent_user(pr.get("user"), agent):
        return "the PR is not authored by %s (user id %d)" % (agent.login, agent.user_id)
    if (pr.get("head") or {}).get("sha") != head:
        return "the head moved to %s while the gate ran" % ((pr.get("head") or {}).get("sha") or "?")[:12]
    if not title_re.fullmatch(pr.get("title") or ""):
        return "the title %r does not match rule %r" % (pr.get("title"), rule_name)

    files = []
    for entry in gh.paginate("repos/%s/pulls/%d/files" % (repo, number)):
        files.extend(p for p in (entry.get("filename"), entry.get("previous_filename")) if p)
    if not files:
        return "the PR changes no files"
    if len(files) > max_files:
        return "the PR touches %d paths and rule %r allows %d" % (len(files), rule_name, max_files)
    outside = [p for p in files if not any(g.fullmatch(p) for g in globs)]
    if outside:
        return "%r is outside rule %r" % (outside[0], rule_name)
    # The files listed must be this head's.
    now = (gh.get("repos/%s/pulls/%d" % (repo, number)).get("head") or {}).get("sha")
    if now != head:
        return "the head moved to %s while the gate ran" % (now or "?")[:12]
    return ""


def evaluate(gh, repo, number, head, author, agent=DEFAULT_AGENT,
             wait_for_marker=0, sleep=time.sleep):
    """Return (passed, one-line message).

    `author` is the PR's user object, or as much of it as the caller has: `id`
    decides, `login` is for the message.
    """
    author = author or {}
    if not isinstance(author.get("id"), int):
        return False, "PR #%d: the author's user id is unknown, so the PR can't be told from the runner App's." % number
    if not is_agent_user(author, agent):
        return True, "PR #%d is authored by %s, not %s: nothing to gate." % (
            number, author.get("login") or "user %d" % author["id"], agent.login)
    if not SHA.fullmatch(head or ""):
        return False, "PR #%d: the event carries no head commit to check." % number
    short = head[:12]

    approvers, notes = approvals(gh, repo, number, head)
    if approvers:
        return True, "PR #%d head %s is approved by %s." % (number, short, ", ".join(sorted(approvers)))

    marker = latest_marker(gh, repo, number, agent)
    waited = 0
    while (marker is None or marker[1] != head) and waited < wait_for_marker:
        # Triggered by auto_merge_enabled: cr-automerge posts its record just after arming.
        sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        marker = latest_marker(gh, repo, number, agent)

    if marker and marker[1] == head:
        reason = rule_holds(gh, repo, number, head, agent, marker[0])
        if not reason:
            return True, ("PR #%d head %s was armed by cr-automerge under rule %s, "
                          "and the PR still meets that rule." % (number, short, marker[0]))
        routine = "; its cr-automerge record for rule %s does not hold: %s" % (marker[0], reason)
    elif marker:
        routine = ("; cr-automerge armed head %s under rule %s, and the push since then "
                   "re-opens the decision" % (marker[1][:12], marker[0]))
    else:
        routine = ""
    found = "; found: %s" % ", ".join(notes) if notes else ""
    return False, ("Runner-App PR #%d needs an approving review on head %s from a user "
                   "with write access%s%s." % (number, short, found, routine))


def post_verdict(checks, repo, name, head, passed, message, details_url=None, external_id=None):
    """Post the verdict as a completed check run on `head`. Returns the check run's URL."""
    body = {
        "name": name,
        "head_sha": head,
        "status": "completed",
        "conclusion": "success" if passed else "failure",
        "output": {"title": "%s: %s" % (name, "pass" if passed else "fail"), "summary": message},
    }
    if details_url:
        body["details_url"] = details_url
    if external_id:
        body["external_id"] = external_id
    return checks.post("repos/%s/check-runs" % repo, body).get("html_url", "")


def one_line(message):
    # One line, whatever a PR put in its title or paths: a line break would let
    # PR-controlled text start a workflow command of its own.
    return re.sub(r"[\x00-\x1f\x7f]", " ", message)


def write_summary(name, passed, message):
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("**%s: %s.** %s\n" % (name, "pass" if passed else "fail", message))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--head-sha", help="the head commit to check (gate mode)")
    ap.add_argument("--author-id", type=int, help="the PR author's numeric user id (gate mode)")
    ap.add_argument("--author-login", default="", help="the PR author's login, for messages only")
    ap.add_argument("--verdict", metavar="CHECK_NAME",
                    help="read the PR's head and author from the API, and post the result "
                         "as a check run of this name with the token in $%s" % CHECK_TOKEN_VAR)
    ap.add_argument("--agent-user-id", type=int, default=DEFAULT_AGENT.user_id,
                    help="the runner App's bot account user id (default %d)" % DEFAULT_AGENT.user_id)
    ap.add_argument("--agent-app-id", type=int, default=DEFAULT_AGENT.app_id,
                    help="the runner App's integration id (default %d)" % DEFAULT_AGENT.app_id)
    ap.add_argument("--agent-login", default=DEFAULT_AGENT.login, help="for messages only")
    ap.add_argument("--wait-for-marker", type=int, default=0)
    args = ap.parse_args(argv)
    if args.verdict:
        if args.head_sha or args.author_id is not None:
            ap.error("--verdict reads the head and the author from the API; drop --head-sha and --author-id")
    elif not args.head_sha or args.author_id is None:
        ap.error("--head-sha and --author-id are required without --verdict")
    agent = Agent(args.agent_user_id, args.agent_app_id, args.agent_login)
    name = args.verdict or "agent-pr-gate"

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("::error::%s: no GITHUB_TOKEN in the environment" % name)
        return 1
    check_token = os.environ.get(CHECK_TOKEN_VAR)
    if args.verdict and not check_token:
        print("::error::%s: no %s in the environment, so no verdict can be posted" % (name, CHECK_TOKEN_VAR))
        return 1
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    gh = GitHub(token, api_url)

    head, author = args.head_sha, {"id": args.author_id, "login": args.author_login}
    try:
        if args.verdict:
            pr = gh.get("repos/%s/pulls/%d" % (args.repo, args.pr))
            head, author = (pr.get("head") or {}).get("sha"), pr.get("user") or {}
        passed, message = evaluate(gh, args.repo, args.pr, head, author, agent, args.wait_for_marker)
    except Exception as e:  # fail closed
        passed, message = False, "PR #%d: the gate could not read the PR's state (%s)." % (args.pr, e)
    message = one_line(message)

    if not args.verdict:
        print("%s%s" % ("" if passed else "::error::", message))
        write_summary(name, passed, message)
        return 0 if passed else 1

    if not SHA.fullmatch(head or ""):
        print("::error::%s: PR #%d has no head commit to post a verdict on (%s)" % (name, args.pr, message))
        return 1
    run_id, server, repo_env = (os.environ.get(k, "") for k in ("GITHUB_RUN_ID", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY"))
    details = "%s/%s/actions/runs/%s" % (server, repo_env, run_id) if run_id and server and repo_env else None
    try:
        url = post_verdict(GitHub(check_token, api_url), args.repo, args.verdict, head, passed, message,
                           details_url=details, external_id="pr-%d" % args.pr)
    except Exception as e:
        print("::error::%s: the verdict (%s) could not be posted on PR #%d head %s: %s" % (
            name, "pass" if passed else "fail", args.pr, head[:12], one_line(str(e))))
        return 1
    print("%s%s: %s on PR #%d head %s. %s%s" % (
        "" if passed else "::warning::", name, "pass" if passed else "fail", args.pr, head[:12],
        message, " (%s)" % url if url else ""))
    write_summary(name, passed, "%s Posted on head `%s`%s." % (
        message, head[:12], " as [a check run](%s)" % url if url else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
