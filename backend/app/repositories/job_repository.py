from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from typing import List, Optional

from backend.app.models.job import JobRecord, JobStatus, utc_now


class JobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        # Worker threads and API handler threads share one connection.
        # CPython's sqlite3 serializes individual C calls but not Python-level
        # sequences (execute-then-commit, execute-then-fetch), and sqlite3_step
        # releases the GIL — observed races include commits clashing on
        # transaction state and SELECT rows coming back with NULL columns.
        # Every connection access goes through this lock; RLock because some
        # methods nest (claim/update -> get_job).
        self._lock = threading.RLock()

    def close(self) -> None:
        # Closing under the lock waits out any in-flight statement from a
        # worker thread; without it, close() during a concurrent execute is a
        # use-after-free that segfaults the interpreter. Late calls after this
        # raise sqlite3.ProgrammingError, which callers can handle.
        with self._lock:
            self.connection.close()

    def create_job(self, url: str, output_languages: List[str], mode: str, options: Optional[dict] = None) -> JobRecord:
        opts = options or {}
        job = JobRecord(id=str(uuid.uuid4()), url=url, output_languages=output_languages, mode=mode, options=opts)
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO jobs (
                    id, url, mode, output_languages, status, progress_stage, provider,
                    detected_language, source_metadata, transcript_segments, result_payload,
                    artifacts, error, created_at, updated_at, options
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.url,
                    job.mode,
                    json.dumps(job.output_languages),
                    job.status,
                    job.progress_stage,
                    None,
                    None,
                    json.dumps({}),
                    json.dumps([]),
                    None,
                    json.dumps({}),
                    None,
                    job.created_at,
                    job.updated_at,
                    json.dumps(opts),
                ),
            )
            self.connection.commit()
        return job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs_by_status(self, status: str) -> List[JobRecord]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC",
                (status,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def reset_running_jobs(self) -> None:
        timestamp = utc_now()
        with self._lock:
            self.connection.execute(
                """
                UPDATE jobs
                SET status = ?, progress_stage = ?, updated_at = ?
                WHERE status = ?
                """,
                (JobStatus.QUEUED, JobStatus.QUEUED, timestamp, JobStatus.RUNNING),
            )
            self.connection.commit()

    def claim_next_queued_job(self) -> Optional[JobRecord]:
        # Single atomic statement: a separate SELECT-then-UPDATE could let two
        # workers claim the same job.
        with self._lock:
            row = self.connection.execute(
                """
                UPDATE jobs
                SET status = ?, progress_stage = ?, updated_at = ?
                WHERE id = (
                    SELECT id FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1
                )
                RETURNING id
                """,
                (JobStatus.RUNNING, "inspecting_source", utc_now(), JobStatus.QUEUED),
            ).fetchone()
            self.connection.commit()
            if row is None:
                return None
            return self.get_job(row["id"])

    def list_recent_jobs(self, limit: int = 50) -> List[JobRecord]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update_job(self, job_id: str, **fields: object) -> JobRecord:
        allowed_json_fields = {"output_languages", "source_metadata", "transcript_segments", "result_payload", "artifacts", "options"}
        parts: list[str] = []
        values: list[object] = []
        for key, value in fields.items():
            parts.append(f"{key} = ?")
            values.append(json.dumps(value) if key in allowed_json_fields else value)
        parts.append("updated_at = ?")
        values.append(utc_now())
        values.append(job_id)
        with self._lock:
            self.connection.execute(f"UPDATE jobs SET {', '.join(parts)} WHERE id = ?", values)
            self.connection.commit()
            job = self.get_job(job_id)
        if job is None:
            raise KeyError(f"Job {job_id} not found after update")
        return job

    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            url=row["url"],
            mode=row["mode"],
            output_languages=json.loads(row["output_languages"]),
            status=row["status"],
            progress_stage=row["progress_stage"],
            provider=row["provider"],
            detected_language=row["detected_language"],
            source_metadata=json.loads(row["source_metadata"] or "{}"),
            transcript_segments=json.loads(row["transcript_segments"] or "[]"),
            result_payload=json.loads(row["result_payload"]) if row["result_payload"] else None,
            artifacts=json.loads(row["artifacts"] or "{}"),
            options=json.loads(row["options"] or "{}"),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
