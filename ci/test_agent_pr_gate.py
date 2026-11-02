#!/usr/bin/env python3
"""Tests for agent_pr_gate.py, against a fake GitHub API.

Self-contained, no pytest dependency. Run: python3 ci/test_agent_pr_gate.py
Exit status is 0 only when every case passes.
"""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_gate as gate  # noqa: E402

REPO = "lentago/example"
AGENT = gate.DEFAULT_AGENT
HEAD = "a" * 40
OLD = "b" * 40
NEW = "c" * 40
RULE = {"title": r"^briefing: \d{4}-\d{2}-\d{2}$", "paths": ["briefings/*.md", "data/**"], "max_files": 3}


def human(login):
    return {"login": login, "type": "User"}


def review(login, state, commit=HEAD, kind="User"):
    return {"user": {"login": login, "type": kind}, "state": state, "commit_id": commit}


def marker(rule="briefing", head=HEAD, by=AGENT, tail="\nAuto-merge armed by `cr-automerge`."):
    return {"user": {"login": by}, "body": "<!-- cr-automerge armed rule=%s head=%s -->%s" % (rule, head, tail)}


class FakeGitHub:
    def __init__(self, reviews=(), comments=(), perms=None, policy=None, pr=None, files=(),
                 heads=None, late_comments=None):
        self.reviews = list(reviews)
        self.comments = list(comments)
        self.perms = perms if perms is not None else {"chris": "admin"}
        self.policy = policy
        self.pr = {
            "state": "open", "draft": False, "title": "briefing: 2026-11-02",
            "base": {"ref": "main"}, "user": {"login": AGENT},
            "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        }
        self.pr.update(pr or {})
        self.files = list(files) if files else [{"filename": "briefings/2026-11-02.md"}]
        self.heads = list(heads or [])  # successive head SHAs for each PR read
        self.late_comments = late_comments  # comments that appear after the first poll
        self.comment_reads = 0
        self.calls = []

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


def run(fake, author=AGENT, head=HEAD, wait=0):
    sleeps = []
    passed, msg = gate.evaluate(fake, REPO, 7, head, author, AGENT, wait, sleep=sleeps.append)
    return passed, msg, sleeps


POLICY = {"rules": {"briefing": RULE}}


class HumanAuthored(unittest.TestCase):
    def test_passes_without_reading_anything(self):
        fake = FakeGitHub()
        passed, msg, _ = run(fake, author="cpitzi")
        self.assertTrue(passed)
        self.assertIn("nothing to gate", msg)
        self.assertEqual(fake.calls, [])

    def test_other_bots_pass(self):
        self.assertTrue(run(FakeGitHub(), author="dependabot[bot]")[0])

    def test_agent_login_compare_ignores_case(self):
        self.assertFalse(run(FakeGitHub(), author="Lentago-Claude-Runner[bot]")[0])


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
        passed, msg, _ = run(FakeGitHub(comments=[marker(by="mallory")], policy=POLICY))
        self.assertFalse(passed)
        self.assertNotIn("cr-automerge", msg)

    def test_marker_must_be_the_first_line(self):
        fake = FakeGitHub(comments=[{"user": {"login": AGENT},
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
        import contextlib, io
        real = gate.evaluate
        gate.evaluate = lambda *a, **k: (False, "title 'x\n::notice::forged'\r\x1b")
        out = io.StringIO()
        old = os.environ.copy()
        os.environ["GITHUB_TOKEN"] = "t"
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        try:
            with contextlib.redirect_stdout(out):
                rc = gate.main(["--repo", REPO, "--pr", "7", "--head-sha", HEAD, "--author", AGENT])
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
        try:
            rc = gate.main(["--repo", REPO, "--pr", "7", "--head-sha", HEAD, "--author", AGENT])
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
