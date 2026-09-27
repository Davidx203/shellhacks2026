import sys
import time

from api.rebuild import Rebuilder, default_commands


def wait_for(rebuilder, job_ids, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        states = [rebuilder.status(j)["status"] for j in job_ids]
        if all(s in ("done", "failed") for s in states):
            return states
        time.sleep(0.05)
    raise AssertionError(f"jobs did not finish: {[rebuilder.status(j) for j in job_ids]}")


def script(code):
    return [sys.executable, "-c", code]


def test_successful_rebuild_runs_every_command_in_order(tmp_path):
    log = tmp_path / "log.txt"
    commands = [script(f"open({str(log)!r}, 'a').write('1')"), script(f"open({str(log)!r}, 'a').write('2')")]
    rebuilder = Rebuilder(commands, cwd=tmp_path)
    job = rebuilder.request()
    assert wait_for(rebuilder, [job]) == ["done"]
    assert log.read_text() == "12"


def test_failure_reports_the_error_and_stops_the_chain(tmp_path):
    log = tmp_path / "log.txt"
    commands = [script("import sys; sys.stderr.write('boom: no cache'); sys.exit(3)"), script(f"open({str(log)!r}, 'a').write('x')")]
    rebuilder = Rebuilder(commands, cwd=tmp_path)
    job = rebuilder.request()
    assert wait_for(rebuilder, [job]) == ["failed"]
    assert "boom: no cache" in rebuilder.status(job)["message"]
    assert not log.exists()


def test_a_failed_rebuild_can_be_retried(tmp_path):
    flag = tmp_path / "flag"
    rebuilder = Rebuilder([script(f"import os, sys; sys.exit(0 if os.path.exists({str(flag)!r}) else 1)")], cwd=tmp_path)
    first = rebuilder.request()
    assert wait_for(rebuilder, [first]) == ["failed"]
    flag.write_text("ok")
    second = rebuilder.request()
    assert wait_for(rebuilder, [second]) == ["done"]


def test_requests_during_a_run_are_coalesced_into_one_follow_up(tmp_path):
    log = tmp_path / "log.txt"
    rebuilder = Rebuilder([script(f"import time; open({str(log)!r}, 'a').write('x'); time.sleep(0.5)")], cwd=tmp_path)
    jobs = [rebuilder.request()]
    time.sleep(0.15)                                  # the first run has started
    jobs += [rebuilder.request() for _ in range(4)]   # all arrive while it is running
    assert wait_for(rebuilder, jobs) == ["done"] * 5
    assert log.read_text() == "xx"                    # one run, plus exactly one follow-up


def test_unknown_job_and_default_commands():
    assert Rebuilder([script("pass")]).status("nope") is None
    commands = default_commands()
    assert [c[-1] for c in commands][-1] == "processed" and "pipeline.build_raw" in commands[0]
