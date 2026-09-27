"""Background rebuild worker: build_raw -> run_all -> load_db, one run at a time."""
from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def default_commands():
    python = sys.executable
    return [
        [python, "-m", "pipeline.build_raw"],
        [python, "geo/run_all.py"],
        [python, "api/load_db.py", "--source", "processed"],
    ]


class Rebuilder:
    def __init__(self, commands=None, cwd=ROOT, timeout=900):
        self.commands = commands if commands is not None else default_commands()
        self.cwd = cwd
        self.timeout = timeout
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._queue: list[str] = []
        self._running = False

    def request(self) -> str:
        """Queue a rebuild and return its job id at once. Jobs queued during a run share one follow-up run."""
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {"status": "queued", "message": ""}
            self._queue.append(job_id)
            if not self._running:
                self._running = True
                threading.Thread(target=self._work, daemon=True).start()
        return job_id

    def status(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _work(self):
        while True:
            with self._lock:
                batch, self._queue = self._queue, []
                if not batch:
                    self._running = False
                    return
                for job_id in batch:
                    self._jobs[job_id]["status"] = "running"
            ok, message = self._run()
            with self._lock:
                for job_id in batch:
                    self._jobs[job_id].update(status="done" if ok else "failed", message=message)

    def _run(self):
        for command in self.commands:
            try:
                result = subprocess.run(command, cwd=self.cwd, capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                return False, f"Timed out after {self.timeout} seconds: {' '.join(command[-2:])}"
            except OSError as error:
                return False, f"Could not start {command[0]}: {error}"
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[-500:]
                return False, f"{' '.join(command[-2:])} failed (exit {result.returncode}): {detail}"
        return True, ""
