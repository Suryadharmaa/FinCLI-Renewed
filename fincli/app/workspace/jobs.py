"""Bounded background jobs with cooperative cancellation and observable progress."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from fincli.app.workspace.models import json_safe


class JobCancelledError(Exception):
    pass


class JobContext:
    def __init__(self, job: dict[str, Any], lock: threading.RLock):
        self.job, self.lock = job, lock

    def checkpoint(self, progress: int, message: str) -> None:
        with self.lock:
            if self.job["cancel_requested"]:
                raise JobCancelledError()
            self.job.update(progress=max(0, min(100, progress)), message=message)


class JobManager:
    def __init__(self, workers: int = 3, capacity: int = 50):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fincli-workspace")
        self.capacity = capacity
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}

    def submit(self, operation, label: str) -> dict[str, Any]:
        with self.lock:
            for key in list(self.jobs):
                if len(self.jobs) < self.capacity:
                    break
                if self.jobs[key]["status"] in {"completed", "cancelled", "failed"}:
                    self.jobs.pop(key)
            if len(self.jobs) >= self.capacity:
                raise ValueError("Job queue is full. Wait for running jobs to finish.")
            job: dict[str, Any] = {
                "id": uuid.uuid4().hex,
                "status": "queued",
                "label": label,
                "progress": 0,
                "message": "Queued",
                "cancel_requested": False,
                "created_at": time.time(),
                "result": None,
                "error": None,
            }
            self.jobs[job["id"]] = job
            self.pool.submit(self._run, job, operation)
            return self.get(job["id"])

    def _run(self, job, operation):
        context = JobContext(job, self.lock)
        try:
            context.checkpoint(0, "Starting")
            with self.lock:
                job["status"] = "running"
            output = operation(context)
            context.checkpoint(100, "Completed")
            with self.lock:
                job.update(status="completed", result=json_safe(output))
        except JobCancelledError:
            with self.lock:
                job.update(status="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - job boundary; error messages may contain provider credentials
            with self.lock:
                job.update(
                    status="failed",
                    error=f"{type(exc).__name__}: operation failed; check inputs and provider availability.",
                    message="Failed",
                )

    def get(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("Job not found.")
            return cast("dict[str, Any]", json_safe(dict(self.jobs[job_id])))

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ValueError("Job not found.")
            if job["status"] in {"queued", "running"}:
                job.update(cancel_requested=True, message="Cancellation requested; waiting for current provider call")
            return self.get(job_id)

    def shutdown(self) -> None:
        with self.lock:
            for job in self.jobs.values():
                job["cancel_requested"] = True
        self.pool.shutdown(wait=False, cancel_futures=True)
