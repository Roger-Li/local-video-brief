from __future__ import annotations

import sqlite3
from pathlib import Path


def get_connection(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            mode TEXT NOT NULL,
            output_languages TEXT NOT NULL,
            status TEXT NOT NULL,
            progress_stage TEXT NOT NULL,
            provider TEXT,
            detected_language TEXT,
            source_metadata TEXT,
            transcript_segments TEXT,
            result_payload TEXT,
            artifacts TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()

