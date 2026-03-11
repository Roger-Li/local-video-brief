from __future__ import annotations

import json
import sqlite3
import uuid
from typing import List, Optional

from backend.app.models.job import JobRecord, JobStatus, utc_now


class JobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_job(self, url: str, output_languages: List[str], mode: str) -> JobRecord:
        job = JobRecord(id=str(uuid.uuid4()), url=url, output_languages=output_languages, mode=mode)
        self.connection.execute(
            """
            INSERT INTO jobs (
                id, url, mode, output_languages, status, progress_stage, provider,
                detected_language, source_metadata, transcript_segments, result_payload,
                artifacts, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self.connection.commit()
        return job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs_by_status(self, status: str) -> List[JobRecord]:
        rows = self.connection.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def reset_running_jobs(self) -> None:
        timestamp = utc_now()
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
        job = self.connection.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1",
            (JobStatus.QUEUED,),
        ).fetchone()
        if job is None:
            return None
        timestamp = utc_now()
        self.connection.execute(
            """
            UPDATE jobs
            SET status = ?, progress_stage = ?, updated_at = ?
            WHERE id = ?
            """,
            (JobStatus.RUNNING, "inspecting_source", timestamp, job["id"]),
        )
        self.connection.commit()
        return self.get_job(job["id"])

    def update_job(self, job_id: str, **fields: object) -> JobRecord:
        allowed_json_fields = {"output_languages", "source_metadata", "transcript_segments", "result_payload", "artifacts"}
        parts: list[str] = []
        values: list[object] = []
        for key, value in fields.items():
            parts.append(f"{key} = ?")
            values.append(json.dumps(value) if key in allowed_json_fields else value)
        parts.append("updated_at = ?")
        values.append(utc_now())
        values.append(job_id)
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
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
