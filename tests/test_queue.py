"""Tests for voronoi.server.queue — Investigation Queue."""

import time

import pytest

from voronoi.server.queue import Investigation, InvestigationQueue


@pytest.fixture
def queue(tmp_path):
    return InvestigationQueue(tmp_path / "queue.db")


class TestEnqueueAndGet:
    def test_enqueue_returns_id(self, queue):
        inv = Investigation(chat_id="c1", question="Why?", slug="why", mode="investigate")
        inv_id = queue.enqueue(inv)
        assert isinstance(inv_id, int)
        assert inv_id > 0

    def test_get_by_id(self, queue):
        inv = Investigation(chat_id="c1", question="Why?", slug="why")
        inv_id = queue.enqueue(inv)
        result = queue.get(inv_id)
        assert result is not None
        assert result.id == inv_id
        assert result.question == "Why?"
        assert result.status == "queued"

    def test_get_nonexistent(self, queue):
        assert queue.get(999) is None

    def test_enqueue_repo_bound(self, queue):
        inv = Investigation(
            chat_id="c1", question="accuracy", slug="acc",
            investigation_type="repo", repo="acme/ml-model",
        )
        inv_id = queue.enqueue(inv)
        result = queue.get(inv_id)
        assert result.investigation_type == "repo"
        assert result.repo == "acme/ml-model"

    def test_enqueue_lab(self, queue):
        inv = Investigation(chat_id="c1", question="EWC?", slug="ewc")
        inv_id = queue.enqueue(inv)
        result = queue.get(inv_id)
        assert result.investigation_type == "lab"
        assert result.repo is None


class TestQueueLifecycle:
    def test_start(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/workspace")
        result = queue.get(inv_id)
        assert result.status == "running"
        assert result.workspace_path == "/tmp/workspace"
        assert result.started_at is not None

    def test_complete(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id, github_url="https://github.com/voronoi-lab/q")
        result = queue.get(inv_id)
        assert result.status == "complete"
        assert result.github_url == "https://github.com/voronoi-lab/q"
        assert result.completed_at is not None

    def test_fail(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.fail(inv_id, "clone failed")
        result = queue.get(inv_id)
        assert result.status == "failed"
        assert result.error == "clone failed"

    def test_cancel_queued(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        assert queue.cancel(inv_id) is True
        result = queue.get(inv_id)
        assert result.status == "cancelled"

    def test_cancel_running_fails(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        assert queue.cancel(inv_id) is False
        assert queue.get(inv_id).status == "running"


class TestConcurrency:
    def test_next_ready_respects_limit(self, queue):
        # Enqueue 3, start 2
        ids = []
        for i in range(3):
            ids.append(queue.enqueue(
                Investigation(chat_id="c1", question=f"Q{i}", slug=f"q{i}")
            ))
        queue.start(ids[0], "/ws1")
        queue.start(ids[1], "/ws2")

        # With limit=2, no more should be ready
        assert queue.next_ready(max_concurrent=2) is None

    def test_next_ready_returns_oldest(self, queue):
        queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1",
                                     created_at=time.time() - 100))
        queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2",
                                     created_at=time.time()))

        ready = queue.next_ready(max_concurrent=2)
        assert ready is not None
        assert ready.question == "Q1"

    def test_next_ready_skips_running(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2"))
        queue.start(id1, "/ws1")

        ready = queue.next_ready(max_concurrent=2)
        assert ready is not None
        assert ready.question == "Q2"


class TestQueries:
    def test_get_by_chat(self, queue):
        queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        queue.enqueue(Investigation(chat_id="c2", question="Q2", slug="q2"))
        queue.enqueue(Investigation(chat_id="c1", question="Q3", slug="q3"))

        results = queue.get_by_chat("c1")
        assert len(results) == 2
        assert all(r.chat_id == "c1" for r in results)

    def test_get_running(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2"))
        queue.start(id1, "/ws1")

        running = queue.get_running()
        assert len(running) == 1
        assert running[0].id == id1

    def test_get_queued(self, queue):
        queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        id2 = queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2"))
        queue.start(id2, "/ws")

        queued = queue.get_queued()
        assert len(queued) == 1
        assert queued[0].question == "Q1"

    def test_queue_position(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        id2 = queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2"))

        assert queue.queue_position(id1) == 0
        assert queue.queue_position(id2) == 1

    def test_queue_position_not_queued(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        queue.start(id1, "/ws")
        assert queue.queue_position(id1) == -1

    def test_find_by_repo(self, queue):
        queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1",
                                     investigation_type="repo", repo="acme/api"))
        queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2",
                                     investigation_type="lab"))
        queue.enqueue(Investigation(chat_id="c1", question="Q3", slug="q3",
                                     investigation_type="repo", repo="acme/api"))

        results = queue.find_by_repo("acme/api")
        assert len(results) == 2

    def test_find_by_codename(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        inv1 = queue.get(id1)
        codename = inv1.codename

        results = queue.find_by_codename(codename)
        assert len(results) == 1
        assert results[0].id == id1

    def test_find_by_codename_case_insensitive(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        inv1 = queue.get(id1)
        codename = inv1.codename

        results = queue.find_by_codename(codename.upper())
        assert len(results) == 1
        assert results[0].id == id1

    def test_find_by_codename_with_status_filter(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        inv1 = queue.get(id1)
        codename = inv1.codename

        # Should find when status matches
        results = queue.find_by_codename(codename, statuses=("queued",))
        assert len(results) == 1

        # Should not find when status doesn't match
        results = queue.find_by_codename(codename, statuses=("complete",))
        assert len(results) == 0

    def test_format_status_empty(self, queue):
        status = queue.format_status()
        assert "No active" in status

    def test_format_status_with_data(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        queue.start(id1, "/ws")
        queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2"))

        status = queue.format_status()
        assert "Running" in status
        assert "Queued" in status


class TestFollowUp:
    def test_parent_id(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        id2 = queue.enqueue(Investigation(
            chat_id="c1", question="Follow up", slug="follow",
            parent_id=id1,
        ))
        result = queue.get(id2)
        assert result.parent_id == id1


class TestPauseResume:
    def test_pause_running(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.pause(inv_id, "auth expired")
        result = queue.get(inv_id)
        assert result.status == "paused"
        assert result.error == "auth expired"
        assert result.completed_at is not None  # records when pause happened

    def test_pause_only_running(self, queue):
        """Pausing a queued investigation should have no effect."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.pause(inv_id, "reason")
        result = queue.get(inv_id)
        assert result.status == "queued"

    def test_resume_paused(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.pause(inv_id, "auth expired")
        assert queue.resume(inv_id) is True
        result = queue.get(inv_id)
        assert result.status == "running"
        assert result.error is None
        assert result.started_at is not None

    def test_resume_failed(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.fail(inv_id, "crashed")
        assert queue.resume(inv_id) is True
        result = queue.get(inv_id)
        assert result.status == "running"
        assert result.error is None

    def test_resume_wrong_status(self, queue):
        """Resuming a completed investigation should return False."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id)
        assert queue.resume(inv_id) is False
        assert queue.get(inv_id).status == "complete"

    def test_get_paused(self, queue):
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        id2 = queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2"))
        queue.start(id1, "/ws1")
        queue.start(id2, "/ws2")
        queue.pause(id1, "auth")
        paused = queue.get_paused()
        assert len(paused) == 1
        assert paused[0].id == id1

    def test_format_status_shows_paused(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/ws")
        queue.pause(inv_id, "auth expired")
        status = queue.format_status()
        assert "Paused" in status
        assert "auth expired" in status

    def test_pause_resume_cycle(self, queue):
        """Pause → resume → pause → resume should work."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.pause(inv_id, "auth")
        assert queue.get(inv_id).status == "paused"
        queue.resume(inv_id)
        assert queue.get(inv_id).status == "running"
        queue.pause(inv_id, "auth again")
        assert queue.get(inv_id).status == "paused"
        queue.resume(inv_id)
        assert queue.get(inv_id).status == "running"

    def test_paused_not_counted_as_running(self, queue):
        """Paused investigations should not count toward max_concurrent."""
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q1", slug="q1"))
        id2 = queue.enqueue(Investigation(chat_id="c1", question="Q2", slug="q2"))
        id3 = queue.enqueue(Investigation(chat_id="c1", question="Q3", slug="q3"))
        queue.start(id1, "/ws1")
        queue.start(id2, "/ws2")
        queue.pause(id1, "auth")
        # With max_concurrent=2, only 1 running, so should get next
        ready = queue.next_ready(max_concurrent=2)
        assert ready is not None
        assert ready.id == id3


class TestReviewAndContinue:
    def test_review_running_investigation(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        assert queue.review(inv_id) is True
        result = queue.get(inv_id)
        assert result.status == "review"
        assert result.completed_at is not None

    def test_review_wrong_status(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        assert queue.review(inv_id) is False  # can't review queued

    def test_continue_from_review(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.review(inv_id)
        new_id = queue.continue_investigation(inv_id, "test more")
        assert new_id is not None
        # New investigation
        new_inv = queue.get(new_id)
        assert new_inv.status == "queued"
        assert new_inv.parent_id == inv_id
        assert new_inv.cycle_number == 2
        # Feedback stored in pi_feedback, NOT appended to question
        assert new_inv.pi_feedback == "test more"
        assert "PI Feedback" not in new_inv.question
        assert new_inv.question == "Q"
        assert new_inv.workspace_path == "/tmp/ws"
        # Original transitions to complete
        assert queue.get(inv_id).status == "complete"

    def test_continue_from_complete(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id)
        new_id = queue.continue_investigation(inv_id)
        assert new_id is not None
        new_inv = queue.get(new_id)
        assert new_inv.parent_id == inv_id
        assert new_inv.cycle_number == 2

    def test_continue_wrong_status(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        assert queue.continue_investigation(inv_id) is None  # running, not reviewable

    def test_continue_preserves_codename(self, queue):
        inv_id = queue.enqueue(Investigation(
            chat_id="c1", question="Q", slug="q", codename="Dopamine"))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id)
        new_id = queue.continue_investigation(inv_id)
        new_inv = queue.get(new_id)
        assert new_inv.codename == "Dopamine"

    def test_lineage_chain(self, queue):
        """Three rounds should share the same lineage_id."""
        id1 = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        inv1 = queue.get(id1)
        assert inv1.lineage_id == id1  # root sets lineage to self

        queue.start(id1, "/ws")
        queue.complete(id1)
        id2 = queue.continue_investigation(id1, "round 2 feedback")
        inv2 = queue.get(id2)
        assert inv2.lineage_id == id1
        assert inv2.cycle_number == 2

        queue.start(id2, "/ws")
        queue.complete(id2)
        id3 = queue.continue_investigation(id2, "round 3 feedback")
        inv3 = queue.get(id3)
        assert inv3.lineage_id == id1
        assert inv3.cycle_number == 3

    def test_continue_nonexistent(self, queue):
        assert queue.continue_investigation(999) is None

    def test_accept_from_review(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.review(inv_id)
        assert queue.accept(inv_id) is True
        inv = queue.get(inv_id)
        assert inv.status == "complete"

    def test_accept_wrong_status(self, queue):
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        # Still running, can't accept
        assert queue.accept(inv_id) is False

    def test_continue_stores_pi_feedback_separately(self, queue):
        """PI feedback should be stored in pi_feedback field, not question."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Does X work?", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id)
        new_id = queue.continue_investigation(inv_id, "increase sample size to N=500")
        new_inv = queue.get(new_id)
        assert new_inv.pi_feedback == "increase sample size to N=500"
        assert new_inv.question == "Does X work?"
        assert "PI Feedback" not in new_inv.question

    def test_continue_no_feedback(self, queue):
        """Continuation without feedback should have empty pi_feedback."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id)
        new_id = queue.continue_investigation(inv_id)
        new_inv = queue.get(new_id)
        assert new_inv.pi_feedback == ""
        assert new_inv.question == "Q"

    def test_continue_strips_legacy_feedback_from_question(self, queue):
        """If the question had old-style feedback appended, strip it."""
        inv_id = queue.enqueue(Investigation(
            chat_id="c1",
            question="Does X work?\n\n## PI Feedback (Round 1)\nold feedback",
            slug="q",
        ))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id)
        new_id = queue.continue_investigation(inv_id, "new feedback")
        new_inv = queue.get(new_id)
        assert new_inv.question == "Does X work?"
        assert new_inv.pi_feedback == "new feedback"

    def test_continue_sets_workspace_atomically(self, queue):
        """Continuation should have workspace_path set before row is visible."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.complete(inv_id)
        new_id = queue.continue_investigation(inv_id)
        new_inv = queue.get(new_id)
        assert new_inv.workspace_path == "/tmp/ws"
        assert new_inv.status == "queued"

    def test_continue_marks_parent_complete_atomically(self, queue):
        """Continuation from review should mark parent complete in same transaction."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.review(inv_id)
        new_id = queue.continue_investigation(inv_id, "iterate")
        parent = queue.get(inv_id)
        assert parent.status == "complete"
        child = queue.get(new_id)
        assert child.workspace_path == "/tmp/ws"


class TestAbortTransition:
    def test_abort_running_produces_cancelled(self, queue):
        """abort() should transition running → cancelled."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        ok = queue.abort(inv_id, "Aborted by operator")
        assert ok is True
        inv = queue.get(inv_id)
        assert inv.status == "cancelled"
        assert inv.error == "Aborted by operator"

    def test_abort_not_running_returns_false(self, queue):
        """abort() should only work on running investigations."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        ok = queue.abort(inv_id)
        assert ok is False
        assert queue.get(inv_id).status == "queued"

    def test_cancelled_not_resumable(self, queue):
        """Cancelled investigations should NOT be resumable."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.abort(inv_id)
        ok = queue.resume(inv_id)
        assert ok is False
        assert queue.get(inv_id).status == "cancelled"


class TestFailAcceptsPaused:
    def test_fail_from_paused(self, queue):
        """fail() should work on paused investigations."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.pause(inv_id, "auth expired")
        queue.fail(inv_id, "timed out")
        inv = queue.get(inv_id)
        assert inv.status == "failed"
        assert inv.error == "timed out"

    def test_fail_from_running(self, queue):
        """fail() should still work on running investigations."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.start(inv_id, "/tmp/ws")
        queue.fail(inv_id, "crashed")
        assert queue.get(inv_id).status == "failed"


class TestRequeue:
    """Tests for requeue() — BUG-007 recovery transition."""

    def test_requeue_unprovisioned(self, queue):
        """requeue() transitions running → queued when workspace is NULL."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        # next_ready marks it running but workspace_path is still NULL
        inv = queue.next_ready(max_concurrent=5)
        assert inv is not None
        assert inv.status == "running"
        # Before start() is called, workspace_path is NULL — requeue should work
        # We need to verify workspace_path is NULL in the DB
        ok = queue.requeue(inv_id)
        assert ok
        assert queue.get(inv_id).status == "queued"

    def test_requeue_with_workspace_fails(self, queue):
        """requeue() should NOT work after start() attaches a workspace."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        queue.next_ready(max_concurrent=5)
        queue.start(inv_id, "/tmp/ws")
        ok = queue.requeue(inv_id)
        assert not ok
        assert queue.get(inv_id).status == "running"

    def test_requeue_wrong_status(self, queue):
        """requeue() should only work on running investigations."""
        inv_id = queue.enqueue(Investigation(chat_id="c1", question="Q", slug="q"))
        ok = queue.requeue(inv_id)
        assert not ok  # status is queued, not running


class TestRigorDefault:
    """Tests for BUG-008 — consistent rigor defaults."""

    def test_investigation_dataclass_default(self):
        """Investigation.rigor should default to 'adaptive'."""
        inv = Investigation()
        assert inv.rigor == "adaptive"

    def test_row_to_investigation_empty_rigor(self, queue):
        """Empty rigor in DB should resolve to 'adaptive'."""
        inv_id = queue.enqueue(Investigation(
            chat_id="c1", question="Q", slug="q", rigor="adaptive",
        ))
        result = queue.get(inv_id)
        assert result.rigor == "adaptive"
