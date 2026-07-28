"""Cold arrival is established, not assumed, and it may legitimately be zero (A18.8, A18.9).

"We did not measure it because it does not happen" is an acceptable answer only if the "it
does not happen" part was checked. The check is the deployment's own uptime clock against an
idle window nobody sent traffic through — polling to see whether it went cold is what keeps
it warm.
"""

from __future__ import annotations

import json
import time

import pytest

from eval import idleprobe


@pytest.fixture()
def marked(tmp_path, monkeypatch):
    """A mark placed `age` seconds ago, with the deployment's answers scripted."""
    state = tmp_path / "idle-mark.json"

    def place(age: float, uptime: float, git_sha: str = "abc123",
              run: dict | None = None):
        state.write_text(json.dumps({"at_epoch": time.time() - age, "at": "then",
                                     "git_sha": "abc123", "uptime_seconds": 1.0}))
        monkeypatch.setattr(idleprobe, "get_json", lambda base, path, **kw: (
            (200, {"git_sha": git_sha, "uptime_seconds": uptime}) if path == "/healthz"
            else (200, run or {"state": "done", "terminal_status": "succeeded_verified",
                               "latency": {"run_seconds": 1.4}})))
        monkeypatch.setattr(idleprobe, "post_form",
                            lambda base, path, fields, **kw: (202, {"run_id": "run_1"}))
        return state

    return place


def test_a_process_that_ran_through_the_window_has_no_cold_arrival_to_measure(marked):
    state = marked(age=4 * 3600, uptime=5 * 3600)
    report = idleprobe.probe("http://test", state)

    assert report["process_ran_through_the_window"] is True
    assert report["cold_arrival"]["value"] == 0.0
    # The window it was established over travels with the zero, so nobody has to take the
    # claim on trust or guess how long "idle" meant.
    assert "4.00 h" in report["cold_arrival"]["measured_under"]
    assert "not assumed" in report["cold_arrival"]["measured_under"]


def test_a_container_that_was_evicted_gives_a_real_cold_arrival(marked):
    """Uptime shorter than the window on the *same build* means something restarted it,
    and then the first request after idle is the cold start a grader would experience."""
    state = marked(age=4 * 3600, uptime=30.0)
    report = idleprobe.probe("http://test", state)

    assert report["outcome"] == "restarted_during_window"
    assert report["cold_arrival"]["value"] >= 0.0
    assert "a real cold arrival" in report["cold_arrival"]["measured_under"]


def test_a_deploy_during_the_window_is_not_a_cold_arrival(marked):
    """This one was live: a deploy landed inside the window, uptime came back short, and
    the tool reported the next request as a cold arrival — a number produced by a container
    that had been up for hours. A deploy explains a short uptime; it is not an eviction,
    and the request after it is warm."""
    state = marked(age=4 * 3600, uptime=3 * 3600, git_sha="def456")
    report = idleprobe.probe("http://test", state)

    assert report["outcome"] == "redeployed_during_window"
    assert report["cold_arrival"]["value"] is None
    assert "not an eviction" in report["cold_arrival"]["measured_under"]
    # What the reading does establish is the tail: three hours of idle with no eviction.
    assert report["idle_established_seconds"] == 3 * 3600
    assert "warm one" in report["cold_arrival"]["measured_under"]


def test_the_first_task_after_idle_is_reported_outside_any_median(marked):
    """A18.9. It is one request and it is labelled as one; the moment it is averaged into
    the steady state it describes nobody's experience."""
    state = marked(age=3600, uptime=7200)
    report = idleprobe.probe("http://test", state)

    first = report["first_task_after_idle"]
    assert first["terminal_status"] == "succeeded_verified"
    assert first["client_observed_seconds"] is not None
    assert "not part of any median" in first["measured_under"]
    assert "1.00 h with no traffic" in first["measured_under"]


def test_there_is_no_window_without_a_mark(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        idleprobe.probe("http://test", tmp_path / "absent.json")
    assert "no idle mark" in str(exit_info.value)
