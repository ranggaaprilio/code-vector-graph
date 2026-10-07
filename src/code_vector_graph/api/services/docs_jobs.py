"""In-memory background job tracking for dashboard-triggered doc operations.

Two job kinds share this manager:

* ``"generate"`` — a full Feature-doc build for an app (one at a time per
  app; a second `generate` request while one is `queued`/`running` is
  rejected with 409 rather than queued behind it).
* ``"index_document"`` — creating/updating/reindexing one manually-authored
  Document page (locked per document via ``key=doc_id``, so document jobs
  for different documents — or a `generate` build — can run concurrently).

State is process-local and lost on restart, which is fine: Neo4j/Qdrant are
the durable state, and a lost job record just means re-clicking the action
(a Document's ``needs_reembed`` flag stays true until a successful reindex,
so a lost embedding job is never silently forgotten).
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class DocsJob:
    job_id: str
    app: str
    repo: str | None
    kind: str = "generate"  # "generate" | "index_document"
    status: str = "queued"  # queued | running | done | failed
    stage: str | None = None
    stages: list[str] = field(default_factory=list)
    message: str | None = None
    progress: dict[str, int] | None = None  # {"done": n, "total": m}
    target: dict[str, Any] | None = None  # e.g. {"doc_id", "slug", "title"}
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def report(
        self,
        stage: str | None = None,
        *,
        message: str | None = None,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        """Called from the worker thread to update the job's progress fields
        as it moves through its stages — read back by ``GET .../jobs/{id}``."""
        if stage is not None:
            self.stage = stage
        if message is not None:
            self.message = message
        if done is not None or total is not None:
            progress = dict(self.progress or {"done": 0, "total": 0})
            if done is not None:
                progress["done"] = done
            if total is not None:
                progress["total"] = total
            self.progress = progress


class DocsJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, DocsJob] = {}
        self._latest_by_app: dict[str, str] = {}  # latest "generate" job per app (back-compat)
        self._latest_by_key: dict[str, str] = {}  # latest job per (app, kind, key)

    @staticmethod
    def _key(app: str, kind: str = "generate", key: str | None = None) -> str:
        return f"{app}:{kind}" if key is None else f"{app}:{kind}:{key}"

    def is_running(self, app: str, kind: str = "generate", key: str | None = None) -> bool:
        with self._lock:
            job = self._jobs.get(self._latest_by_key.get(self._key(app, kind, key), ""))
            return bool(job and job.status in ("queued", "running"))

    def start(
        self,
        app: str,
        repo: str | None,
        fn: Callable[..., dict[str, Any]],
        *,
        kind: str = "generate",
        key: str | None = None,
        stages: tuple[str, ...] = (),
        target: dict[str, Any] | None = None,
    ) -> str:
        """Launch `fn` on a daemon thread; returns the new job's id immediately.

        ``fn`` is called with ``job.report`` as its sole argument when it
        accepts one, else with no arguments — so existing zero-arg callers
        (and their tests) keep working unchanged.
        """
        job_id = str(uuid.uuid4())
        job = DocsJob(job_id=job_id, app=app, repo=repo, kind=kind, stages=list(stages), target=target)
        lock_key = self._key(app, kind, key)
        with self._lock:
            self._jobs[job_id] = job
            self._latest_by_key[lock_key] = job_id
            if kind == "generate":
                self._latest_by_app[app] = job_id

        accepts_report = len(inspect.signature(fn).parameters) >= 1

        def _run() -> None:
            job.status = "running"
            job.started_at = time.time()
            if job.stages:
                job.stage = job.stages[0]
            try:
                job.result = fn(job.report) if accepts_report else fn()
                job.status = "done"
                if job.stages:
                    job.stage = job.stages[-1]
            except Exception as exc:  # a build failure is data, not a crash — surfaced via GET .../jobs
                logger.exception("Docs job %s (app=%s, kind=%s) failed", job_id, app, kind)
                job.error = str(exc)
                job.status = "failed"
            finally:
                job.finished_at = time.time()

        threading.Thread(target=_run, daemon=True, name=f"docs-job-{job_id[:8]}").start()
        return job_id

    def get(self, job_id: str) -> DocsJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self, app: str) -> DocsJob | None:
        """The latest ``"generate"`` job for ``app`` (back-compat with the
        original single-kind API)."""
        with self._lock:
            return self._jobs.get(self._latest_by_app.get(app, ""))

    def latest_for(self, app: str, kind: str, key: str | None = None) -> DocsJob | None:
        with self._lock:
            return self._jobs.get(self._latest_by_key.get(self._key(app, kind, key), ""))
