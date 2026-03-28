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
        assert result.completed_at is None

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
