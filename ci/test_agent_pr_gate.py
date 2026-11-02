#!/usr/bin/env python3
"""Tests for agent_pr_gate.py, against a fake GitHub API.

Self-contained, no pytest dependency. Run: python3 ci/test_agent_pr_gate.py
Exit status is 0 only when every case passes.
"""
import base64
import contextlib
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_gate as gate  # noqa: E402

REPO = "lentago/example"
AGENT = gate.DEFAULT_AGENT
AGENT_USER = {"login": AGENT.login, "id": AGENT.user_id, "type": "Bot"}
CHRIS = {"login": "cpitzi", "id": 47896168, "type": "User"}
HEAD = "a" * 40
OLD = "b" * 40
NEW = "c" * 40
RULE = {"title": r"^briefing: \d{4}-\d{2}-\d{2}$", "paths": ["briefings/*.md", "data/**"], "max_files": 3}


def human(login):
    return {"login": login, "type": "User"}


def review(login, state, commit=HEAD, kind="User"):
    return {"user": {"login": login, "type": kind}, "state": state, "commit_id": commit}


def marker(rule="briefing", head=HEAD, by=AGENT_USER, app=AGENT.app_id,
           tail="\nAuto-merge armed by `cr-automerge`."):
    """A cr-automerge record. `app` is the integration id the comment was posted through, or None."""
    comment = {"user": by, "body": "<!-- cr-automerge armed rule=%s head=%s -->%s" % (rule, head, tail)}
    if app is not None:
        comment["performed_via_github_app"] = {"id": app, "slug": "lentago-claude-runner"}
    return comment


class FakeGitHub:
    def __init__(self, reviews=(), comments=(), perms=None, policy=None, pr=None, files=(),
                 heads=None, late_comments=None, post_error=None):
        self.reviews = list(reviews)
        self.comments = list(comments)
        self.perms = perms if perms is not None else {"chris": "admin"}
        self.policy = policy
        self.pr = {
            "state": "open", "draft": False, "title": "briefing: 2026-11-02",
            "base": {"ref": "main"}, "user": dict(AGENT_USER),
            "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        }
        self.pr.update(pr or {})
        self.files = list(files) if files else [{"filename": "briefings/2026-11-02.md"}]
        self.heads = list(heads or [])  # successive head SHAs for each PR read
        self.late_comments = late_comments  # comments that appear after the first poll
        self.post_error = post_error
        self.comment_reads = 0
        self.calls = []
        self.posts = []

    def post(self, path, body):
        self.calls.append("POST " + path)
        if self.post_error:
            raise RuntimeError(self.post_error)
        self.posts.append((path, body))
        return {"html_url": "https://github.com/%s/runs/%d" % (REPO, len(self.posts))}

    def get(self, path):
        self.calls.append(path)
        if path == "repos/%s" % REPO:
            return {"default_branch": "main"}
        if path.startswith("repos/%s/contents/" % REPO):
            if self.policy is None:
                raise gate.NotFound(path)
            return {"content": base64.b64encode(json.dumps(self.policy).encode()).decode()}
        if path == "repos/%s/pulls/7" % REPO:
            pr = json.loads(json.dumps(self.pr))
            if self.heads:
                pr["head"]["sha"] = self.heads.pop(0)
            return pr
        raise AssertionError("unexpected GET " + path)

    def paginate(self, path):
        self.calls.append(path)
        if path.endswith("/reviews"):
            return self.reviews
        if path.endswith("/comments"):
            self.comment_reads += 1
            if self.late_comments is not None and self.comment_reads > 1:
                return self.late_comments
            return self.comments
        if path.endswith("/files"):
            return self.files
        raise AssertionError("unexpected paginate " + path)

    def permission(self, repo, login):
        self.calls.append("permission " + login)
        return self.perms.get(login, "none")


def run(fake, author=AGENT_USER, head=HEAD, wait=0):
    sleeps = []
    passed, msg = gate.evaluate(fake, REPO, 7, head, author, AGENT, wait, sleep=sleeps.append)
    return passed, msg, sleeps


POLICY = {"rules": {"briefing": RULE}}


class HumanAuthored(unittest.TestCase):
    def test_passes_without_reading_anything(self):
        fake = FakeGitHub()
        passed, msg, _ = run(fake, author=CHRIS)
        self.assertTrue(passed)
        self.assertIn("authored by cpitzi, not %s: nothing to gate" % AGENT.login, msg)
        self.assertEqual(fake.calls, [])

    def test_other_bots_pass(self):
        self.assertTrue(run(FakeGitHub(), author={"login": "dependabot[bot]", "id": 49699333, "type": "Bot"})[0])

    def test_message_without_a_login_names_the_user_id(self):
        _, msg, _ = run(FakeGitHub(), author={"id": 47896168})
        self.assertIn("authored by user 47896168", msg)


class Identity(unittest.TestCase):
    """The runner App is matched on numeric ids, never on a login (#97)."""

    def test_author_is_matched_on_user_id_not_login(self):
        # GraphQL reports the App as `lentago-claude-runner`, which a human account could also be.
        impostor = {"login": "lentago-claude-runner", "id": 1, "type": "User"}
        passed, msg, _ = run(FakeGitHub(), author=impostor)
        self.assertTrue(passed)
        self.assertIn("nothing to gate", msg)
        # The App under any login spelling is still the App.
        self.assertFalse(run(FakeGitHub(), author={"login": "lentago-claude-runner", "id": AGENT.user_id})[0])
        self.assertFalse(run(FakeGitHub(), author={"login": "Lentago-Claude-Runner[bot]", "id": AGENT.user_id})[0])

    def test_unknown_author_id_fails_closed(self):
        for author in (None, {}, {"login": AGENT.login}, {"login": AGENT.login, "id": "293961292"}):
            passed, msg, _ = run(FakeGitHub(), author=author)
            self.assertFalse(passed, author)
            self.assertIn("user id is unknown", msg)

    def test_marker_is_matched_on_the_app_id_not_the_login(self):
        # The App's own login on a comment that no App posted: a human-looking forgery.
        fake = FakeGitHub(comments=[marker(app=None)], policy=POLICY)
        passed, msg, _ = run(fake)
        self.assertFalse(passed)
        self.assertNotIn("cr-automerge", msg)
        # Another App, same login text.
        self.assertFalse(run(FakeGitHub(comments=[marker(app=15368)], policy=POLICY))[0])
        # The runner App, whatever login the API reports for it.
        by = {"login": "lentago-claude-runner", "id": AGENT.user_id, "type": "Bot"}
        self.assertTrue(run(FakeGitHub(comments=[marker(by=by)], policy=POLICY))[0])

    def test_routine_exception_requires_the_app_as_author_by_id(self):
        pr = {"user": {"login": AGENT.login, "id": 2, "type": "Bot"}}
        _, msg, _ = run(FakeGitHub(comments=[marker()], policy=POLICY, pr=pr))
        self.assertIn("not authored by %s (user id %d)" % (AGENT.login, AGENT.user_id), msg)

    def test_custom_identity(self):
        other = gate.Agent(user_id=5, app_id=6, login="other-app[bot]")
        fake = FakeGitHub(comments=[marker(by={"login": "other-app[bot]", "id": 5}, app=6)], policy=POLICY,
                          pr={"user": {"login": "other-app[bot]", "id": 5}})
        passed, msg = gate.evaluate(fake, REPO, 7, HEAD, {"login": "other-app[bot]", "id": 5}, other)
        self.assertTrue(passed, msg)
        # The default App's PR is nothing to gate under that identity.
        passed, msg = gate.evaluate(FakeGitHub(), REPO, 7, HEAD, AGENT_USER, other)
        self.assertTrue(passed)
        self.assertIn("not other-app[bot]", msg)


class Approval(unittest.TestCase):
    def test_no_reviews_fails_and_names_what_is_missing(self):
        passed, msg, _ = run(FakeGitHub())
        self.assertFalse(passed)
        self.assertIn("needs an approving review on head %s" % HEAD[:12], msg)

    def test_approval_on_head_by_writer_passes(self):
        passed, msg, _ = run(FakeGitHub(reviews=[review("chris", "APPROVED")]))
        self.assertTrue(passed)
        self.assertIn("approved by chris", msg)

    def test_write_permission_counts(self):
        self.assertTrue(run(FakeGitHub(reviews=[review("ana", "APPROVED")], perms={"ana": "write"}))[0])

    def test_approval_on_older_head_fails(self):
        passed, msg, _ = run(FakeGitHub(reviews=[review("chris", "APPROVED", commit=OLD)]))
        self.assertFalse(passed)
        self.assertIn("chris approved %s, an older head" % OLD[:12], msg)

    def test_read_only_approver_fails(self):
        passed, msg, _ = run(FakeGitHub(reviews=[review("drive-by", "APPROVED")], perms={"drive-by": "read"}))
        self.assertFalse(passed)
        self.assertIn("drive-by has no write access", msg)

    def test_non_collaborator_approver_fails(self):
        self.assertFalse(run(FakeGitHub(reviews=[review("stranger", "APPROVED")]))[0])

    def test_bot_approval_fails_without_a_permission_lookup(self):
        fake = FakeGitHub(reviews=[review("some-app[bot]", "APPROVED", kind="Bot")],
                          perms={"some-app[bot]": "write"})
        passed, msg, _ = run(fake)
        self.assertFalse(passed)
        self.assertIn("some-app[bot] is a bot", msg)
        self.assertNotIn("permission some-app[bot]", fake.calls)

    def test_later_changes_requested_cancels_approval(self):
        fake = FakeGitHub(reviews=[review("chris", "APPROVED"), review("chris", "CHANGES_REQUESTED")])
        self.assertFalse(run(fake)[0])

    def test_dismissed_approval_does_not_count(self):
        self.assertFalse(run(FakeGitHub(reviews=[review("chris", "DISMISSED")]))[0])

    def test_comment_review_after_approval_keeps_it(self):
        fake = FakeGitHub(reviews=[review("chris", "APPROVED"), review("chris", "COMMENTED")])
        self.assertTrue(run(fake)[0])

    def test_re_approval_on_new_head_counts(self):
        fake = FakeGitHub(reviews=[review("chris", "APPROVED", commit=OLD), review("chris", "APPROVED")])
        self.assertTrue(run(fake)[0])

    def test_approval_passes_even_with_a_stale_marker(self):
        fake = FakeGitHub(reviews=[review("chris", "APPROVED")], comments=[marker(head=OLD)])
        self.assertTrue(run(fake)[0])

    def test_bad_head_fails_closed(self):
        self.assertFalse(run(FakeGitHub(), head="")[0])


class Routine(unittest.TestCase):
    def test_marker_on_head_and_rule_holds_passes(self):
        passed, msg, _ = run(FakeGitHub(comments=[marker()], policy=POLICY))
        self.assertTrue(passed, msg)
        self.assertIn("armed by cr-automerge under rule briefing", msg)

    def test_marker_on_older_head_fails(self):
        passed, msg, _ = run(FakeGitHub(comments=[marker(head=OLD)], policy=POLICY))
        self.assertFalse(passed)
        self.assertIn("cr-automerge armed head %s under rule briefing" % OLD[:12], msg)
        self.assertIn("re-opens the decision", msg)

    def test_latest_marker_wins(self):
        fake = FakeGitHub(comments=[marker(), marker(head=OLD)], policy=POLICY)
        self.assertFalse(run(fake)[0])
        fake = FakeGitHub(comments=[marker(head=OLD), marker()], policy=POLICY)
        self.assertTrue(run(fake)[0])

    def test_marker_from_anyone_else_is_ignored(self):
        passed, msg, _ = run(FakeGitHub(comments=[marker(by={"login": "mallory", "id": 3}, app=None)], policy=POLICY))
        self.assertFalse(passed)
        self.assertNotIn("cr-automerge", msg)

    def test_marker_must_be_the_first_line(self):
        fake = FakeGitHub(comments=[{"user": AGENT_USER, "performed_via_github_app": {"id": AGENT.app_id},
                                     "body": "hello\n<!-- cr-automerge armed rule=briefing head=%s -->" % HEAD}],
                          policy=POLICY)
        self.assertFalse(run(fake)[0])

    def test_no_policy_on_default_branch_fails(self):
        passed, msg, _ = run(FakeGitHub(comments=[marker()]))
        self.assertFalse(passed)
        self.assertIn("main carries no .claytonia/automerge.json", msg)

    def test_unknown_rule_fails(self):
        passed, msg, _ = run(FakeGitHub(comments=[marker(rule="drain")], policy=POLICY))
        self.assertFalse(passed)
        self.assertIn("has no rule 'drain'", msg)

    def test_malformed_rule_fails(self):
        fake = FakeGitHub(comments=[marker()], policy={"rules": {"briefing": {"title": "("}}})
        self.assertIn("malformed", run(fake)[1])

    def test_title_must_match_in_full(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY, pr={"title": "briefing: 2026-11-02 and more"})
        passed, msg, _ = run(fake)
        self.assertFalse(passed)
        self.assertIn("does not match rule", msg)

    def test_path_outside_rule_fails(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY,
                          files=[{"filename": "briefings/x.md"}, {"filename": ".github/workflows/ci.yml"}])
        passed, msg, _ = run(fake)
        self.assertFalse(passed)
        self.assertIn("'.github/workflows/ci.yml' is outside rule", msg)

    def test_single_star_stays_in_its_directory(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY, files=[{"filename": "briefings/sub/x.md"}])
        self.assertFalse(run(fake)[0])

    def test_double_star_crosses_directories(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY, files=[{"filename": "data/a/b/c.json"}])
        self.assertTrue(run(fake)[0])

    def test_rename_old_path_must_match_too(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY,
                          files=[{"filename": "briefings/x.md", "previous_filename": "src/x.py"}])
        self.assertIn("'src/x.py' is outside rule", run(fake)[1])

    def test_too_many_paths_fails(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY,
                          files=[{"filename": "data/%d.json" % i} for i in range(4)])
        self.assertIn("touches 4 paths", run(fake)[1])

    def test_no_files_fails(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY)
        fake.files = []
        self.assertIn("changes no files", run(fake)[1])

    def test_draft_fails(self):
        self.assertIn("draft", run(FakeGitHub(comments=[marker()], policy=POLICY, pr={"draft": True}))[1])

    def test_closed_fails(self):
        self.assertIn("is closed", run(FakeGitHub(comments=[marker()], policy=POLICY, pr={"state": "closed"}))[1])

    def test_wrong_base_fails(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY, pr={"base": {"ref": "release"}})
        self.assertIn("targets release, not main", run(fake)[1])

    def test_fork_branch_fails(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY,
                          pr={"head": {"sha": HEAD, "repo": {"full_name": "someone/example"}}})
        self.assertIn("is in someone/example", run(fake)[1])

    def test_head_moved_before_the_check_fails(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY, heads=[NEW])
        self.assertIn("head moved to %s" % NEW[:12], run(fake)[1])

    def test_head_moved_during_the_check_fails(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY, heads=[HEAD, NEW])
        self.assertIn("head moved to %s" % NEW[:12], run(fake)[1])


class WaitForMarker(unittest.TestCase):
    def test_no_wait_by_default(self):
        fake = FakeGitHub(policy=POLICY, late_comments=[marker()])
        passed, _, sleeps = run(fake)
        self.assertFalse(passed)
        self.assertEqual(sleeps, [])

    def test_waits_for_a_marker_posted_after_arming(self):
        fake = FakeGitHub(policy=POLICY, late_comments=[marker()])
        passed, msg, sleeps = run(fake, wait=120)
        self.assertTrue(passed, msg)
        self.assertEqual(sleeps, [gate.POLL_SECONDS])

    def test_gives_up_after_the_wait(self):
        passed, _, sleeps = run(FakeGitHub(policy=POLICY), wait=60)
        self.assertFalse(passed)
        self.assertEqual(sum(sleeps), 60)

    def test_approval_skips_the_wait(self):
        _, _, sleeps = run(FakeGitHub(reviews=[review("chris", "APPROVED")]), wait=120)
        self.assertEqual(sleeps, [])


class Glob(unittest.TestCase):
    def test_semantics_match_cr_automerge(self):
        self.assertTrue(gate.glob_re("a/*.md").fullmatch("a/b.md"))
        self.assertFalse(gate.glob_re("a/*.md").fullmatch("a/b/c.md"))
        self.assertTrue(gate.glob_re("a/**").fullmatch("a/b/c.md"))
        self.assertTrue(gate.glob_re("a/?.md").fullmatch("a/b.md"))
        self.assertFalse(gate.glob_re("a/?.md").fullmatch("a//.md"))
        self.assertFalse(gate.glob_re("a.md").fullmatch("aXmd"))


class Main(unittest.TestCase):
    def test_a_path_with_a_line_break_stays_on_one_line(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY,
                          files=[{"filename": "briefings/x.md\n::warning::forged"}])
        _, msg, _ = run(fake)
        self.assertNotIn("\n", msg)

    def test_output_is_one_line(self):

        real = gate.evaluate
        gate.evaluate = lambda *a, **k: (False, "title 'x\n::notice::forged'\r\x1b")
        out = io.StringIO()
        old = os.environ.copy()
        os.environ["GITHUB_TOKEN"] = "t"
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        try:
            with contextlib.redirect_stdout(out):
                rc = gate.main(["--repo", REPO, "--pr", "7", "--head-sha", HEAD, "--author-id", str(AGENT.user_id)])
        finally:
            gate.evaluate = real
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(rc, 1)
        self.assertEqual(out.getvalue().count("\n"), 1)
        self.assertTrue(out.getvalue().startswith("::error::"))
        self.assertNotIn("\n::", out.getvalue())  # mid-line "::" is not a command

    def test_no_token_fails(self):
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
        old = os.environ.copy()
        os.environ.clear()
        os.environ.update(env)
        out = io.StringIO()
        try:
            # Captured, so the expected ::error:: line doesn't become an
            # annotation on the ci-tests job that runs this file.
            with contextlib.redirect_stdout(out):
                rc = gate.main(["--repo", REPO, "--pr", "7", "--head-sha", HEAD, "--author-id", str(AGENT.user_id)])
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(rc, 1)
        self.assertEqual(out.getvalue(), "::error::agent-pr-gate: no GITHUB_TOKEN in the environment\n")

    def test_another_agent_named_by_login_alone_fails_closed(self):
        # v1.6.0 gated on the login. A caller naming another agent by login
        # alone must not silently gate the runner App and pass its own agent.
        old = os.environ.copy()
        os.environ["GITHUB_TOKEN"] = "t"
        try:
            for extra in ([], ["--agent-user-id", "5"], ["--agent-app-id", "6"]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = gate.main(["--repo", REPO, "--pr", "7", "--head-sha", HEAD, "--author-id", "5",
                                    "--agent-login", "other-agent[bot]"] + extra)
                self.assertEqual(rc, 2, extra)
                self.assertTrue(out.getvalue().startswith("::error::"), extra)
                self.assertIn("agent_user_id and agent_app_id", out.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_another_agent_with_its_own_ids_is_accepted(self):
        agent = gate.Agent(5, 6, "other-agent[bot]")
        self.assertEqual(gate.mixed_identity(agent), "")
        self.assertEqual(gate.mixed_identity(gate.DEFAULT_AGENT), "")
        self.assertEqual(gate.mixed_identity(gate.Agent(5, 6, "LENTAGO-claude-runner[bot]")), "")

    def test_gate_mode_needs_a_head_and_an_author_id(self):
        for argv in (["--head-sha", HEAD], ["--author-id", "1"], []):
            with self.assertRaises(SystemExit) as cm:
                with contextlib.redirect_stderr(io.StringIO()):
                    gate.main(["--repo", REPO, "--pr", "7"] + argv)
            self.assertEqual(cm.exception.code, 2)


class Verdict(unittest.TestCase):
    """`--verdict NAME`: read the PR, decide, post a check run with the gate App's token."""

    def setUp(self):
        self.old_env = os.environ.copy()
        os.environ.update({"GITHUB_TOKEN": "read-token", gate.CHECK_TOKEN_VAR: "check-token",
                           "GITHUB_RUN_ID": "42", "GITHUB_SERVER_URL": "https://github.com",
                           "GITHUB_REPOSITORY": REPO})
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        self.real_github = gate.GitHub
        self.clients = []  # (token, fake) in construction order

    def tearDown(self):
        gate.GitHub = self.real_github
        os.environ.clear()
        os.environ.update(self.old_env)

    def install(self, fake):
        clients = self.clients

        def make(token, api_url="https://api.github.com"):
            clients.append((token, api_url))
            return fake
        gate.GitHub = make
        return fake

    def verdict(self, fake, argv=()):
        self.install(fake)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = gate.main(["--repo", REPO, "--pr", "7", "--verdict", "agent-pr-verdict"] + list(argv))
        return rc, out.getvalue()

    def test_human_pr_posts_success_from_one_pr_read(self):
        fake = FakeGitHub(pr={"user": CHRIS})
        rc, out = self.verdict(fake)
        self.assertEqual(rc, 0)
        self.assertEqual(fake.calls, ["repos/%s/pulls/7" % REPO, "POST repos/%s/check-runs" % REPO])
        (path, body), = fake.posts
        self.assertEqual(body["name"], "agent-pr-verdict")
        self.assertEqual(body["head_sha"], HEAD)
        self.assertEqual((body["status"], body["conclusion"]), ("completed", "success"))
        self.assertEqual(body["details_url"], "https://github.com/%s/actions/runs/42" % REPO)
        self.assertEqual(body["external_id"], "pr-7")
        self.assertIn("nothing to gate", body["output"]["summary"])
        self.assertTrue(out.startswith("agent-pr-verdict: pass on PR #7 head %s" % HEAD[:12]), out)

    def test_runner_pr_without_approval_posts_failure_and_exits_zero(self):
        fake = FakeGitHub()
        rc, out = self.verdict(fake)
        self.assertEqual(rc, 0, "the verdict is the check run; the job only reports that one was posted")
        (_, body), = fake.posts
        self.assertEqual(body["conclusion"], "failure")
        self.assertIn("needs an approving review on head %s" % HEAD[:12], body["output"]["summary"])
        self.assertTrue(out.startswith("::warning::agent-pr-verdict: fail"), out)

    def test_approval_on_the_current_head_posts_success(self):
        fake = FakeGitHub(reviews=[review("chris", "APPROVED")])
        rc, _ = self.verdict(fake)
        self.assertEqual(rc, 0)
        self.assertEqual(fake.posts[0][1]["conclusion"], "success")

    def test_head_and_author_come_from_the_api_not_the_arguments(self):
        # The PR's current head is NEW; an approval on HEAD is stale.
        fake = FakeGitHub(reviews=[review("chris", "APPROVED", commit=HEAD)], pr={"head": {"sha": NEW, "repo": {"full_name": REPO}}})
        rc, _ = self.verdict(fake)
        self.assertEqual(rc, 0)
        (_, body), = fake.posts
        self.assertEqual(body["head_sha"], NEW)
        self.assertEqual(body["conclusion"], "failure")
        self.assertIn("chris approved %s, an older head" % HEAD[:12], body["output"]["summary"])

    def test_check_run_is_posted_with_the_check_token_and_reads_with_the_read_token(self):
        self.verdict(FakeGitHub())
        self.assertEqual([t for t, _ in self.clients], ["read-token", "check-token"])

    def test_missing_check_token_fails_before_reading_anything(self):
        os.environ.pop(gate.CHECK_TOKEN_VAR)
        fake = FakeGitHub()
        rc, out = self.verdict(fake)
        self.assertEqual(rc, 1)
        self.assertEqual(fake.calls, [])
        self.assertIn("::error::", out)
        self.assertIn(gate.CHECK_TOKEN_VAR, out)

    def test_unreadable_pr_posts_nothing_and_fails(self):
        class Broken(FakeGitHub):
            def get(self, path):
                raise RuntimeError("GET %s: HTTP 500" % path)
        fake = Broken()
        rc, out = self.verdict(fake)
        self.assertEqual(rc, 1)
        self.assertEqual(fake.posts, [])
        self.assertIn("::error::", out)
        self.assertIn("HTTP 500", out)

    def test_api_error_after_the_pr_read_posts_a_failure_on_the_head_read(self):
        class Flaky(FakeGitHub):
            def paginate(self, path):
                raise RuntimeError("GET %s: HTTP 502" % path)
        fake = Flaky()
        rc, out = self.verdict(fake)
        self.assertEqual(rc, 0)
        (_, body), = fake.posts
        self.assertEqual((body["head_sha"], body["conclusion"]), (HEAD, "failure"))
        self.assertIn("could not read the PR's state", body["output"]["summary"])
        self.assertIn("HTTP 502", body["output"]["summary"])
        self.assertTrue(out.startswith("::warning::"), out)

    def test_marker_with_a_null_app_is_not_the_runners(self):
        comment = marker(app=None)
        comment["performed_via_github_app"] = None
        fake = FakeGitHub(comments=[comment], policy=POLICY)
        self.verdict(fake)
        self.assertEqual(fake.posts[0][1]["conclusion"], "failure")
        self.assertNotIn("cr-automerge", fake.posts[0][1]["output"]["summary"])

    def test_failed_post_fails_the_job(self):
        fake = FakeGitHub(pr={"user": CHRIS}, post_error="POST check-runs: HTTP 403")
        rc, out = self.verdict(fake)
        self.assertEqual(rc, 1)
        self.assertIn("::error::", out)
        self.assertIn("could not be posted", out)
        self.assertIn("HTTP 403", out)

    def test_output_is_one_line_per_message(self):
        fake = FakeGitHub(comments=[marker()], policy=POLICY,
                          files=[{"filename": "briefings/x.md\n::warning::forged"}])
        rc, out = self.verdict(fake)
        self.assertEqual(rc, 0)
        self.assertEqual(out.count("\n"), 1)
        self.assertNotIn("\n::", out)
        self.assertNotIn("\n", fake.posts[0][1]["output"]["summary"])

    def test_verdict_mode_rejects_gate_mode_arguments(self):
        for argv in (["--head-sha", HEAD], ["--author-id", "1"]):
            with self.assertRaises(SystemExit) as cm:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.verdict(FakeGitHub(), argv)
            self.assertEqual(cm.exception.code, 2)

    def test_custom_identity_arguments_reach_the_decision(self):
        fake = FakeGitHub(pr={"user": {"login": "other-app[bot]", "id": 5}})
        rc, _ = self.verdict(fake, ["--agent-user-id", "5", "--agent-app-id", "6", "--agent-login", "other-app[bot]"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.posts[0][1]["conclusion"], "failure")
        self.assertIn("Runner-App PR #7", fake.posts[0][1]["output"]["summary"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
