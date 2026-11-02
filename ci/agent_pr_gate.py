#!/usr/bin/env python3
"""agent-pr-gate: decide whether a pull request may merge, as far as authorship goes.

The `agent-pr-gate.yml` reusable workflow runs this on every pull_request and
pull_request_review event (lentago/claytonia#117 option A; lentago/.github
ADR-0014 points 2, 4 and 5). It reads GitHub state through the REST API with a
read-only token and writes nothing.

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

The glob and title semantics match `cr-automerge` (lentago/claytonia
`bin/cr-automerge`): Python `re.fullmatch` for the title, and for paths `*`
stays inside a directory, `**` crosses directories, `?` is one character other
than `/`.

Usage:
  agent_pr_gate.py --repo OWNER/REPO --pr N --head-sha SHA --author LOGIN
                   [--agent LOGIN] [--wait-for-marker SECONDS]

The token comes from GITHUB_TOKEN (or GH_TOKEN); the API root from
GITHUB_API_URL (default https://api.github.com). Exit status: 0 pass, 1 fail,
2 usage error. Tests: python3 ci/test_agent_pr_gate.py
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_AGENT = "lentago-claude-runner[bot]"
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

    def _request(self, url):
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer %s" % self.token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lentago-agent-pr-gate",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp), resp.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url) from None
            raise RuntimeError("GET %s: HTTP %d" % (url, e.code)) from None

    def get(self, path):
        return self._request("%s/%s" % (self.api_url, path))[0]

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


def latest_marker(gh, repo, number, agent):
    """The runner App's latest cr-automerge record on the PR, as (rule, head), or None."""
    found = None
    for comment in gh.paginate("repos/%s/issues/%d/comments" % (repo, number)):
        if (comment.get("user") or {}).get("login", "").lower() != agent.lower():
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
    if (pr.get("user") or {}).get("login", "").lower() != agent.lower():
        return "the PR is not authored by %s" % agent
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
    """Return (passed, one-line message)."""
    if author.lower() != agent.lower():
        return True, "PR #%d is authored by %s, not %s: nothing to gate." % (number, author, agent)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--author", required=True)
    ap.add_argument("--agent", default=DEFAULT_AGENT)
    ap.add_argument("--wait-for-marker", type=int, default=0)
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("::error::agent-pr-gate: no GITHUB_TOKEN in the environment")
        return 1
    gh = GitHub(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    try:
        passed, message = evaluate(gh, args.repo, args.pr, args.head_sha, args.author,
                                   args.agent, args.wait_for_marker)
    except Exception as e:  # fail closed
        passed, message = False, "PR #%d: the gate could not read the PR's state (%s)." % (args.pr, e)

    # One line, whatever a PR put in its title or paths: a line break would let
    # PR-controlled text start a workflow command of its own.
    message = re.sub(r"[\x00-\x1f\x7f]", " ", message)
    print("%s%s" % ("" if passed else "::error::", message))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("**agent-pr-gate: %s.** %s\n" % ("pass" if passed else "fail", message))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
