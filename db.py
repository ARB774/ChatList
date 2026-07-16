from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_DB_PATH = Path(__file__).with_name("chatlist.db")
DEFAULT_SETTINGS: dict[str, str] = {
    "system_prompt": "",
    "temperature": "0.7",
    "request_timeout": "60",
    "window_width": "1400",
    "window_height": "900",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    tags TEXT
);

CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    api_url TEXT NOT NULL,
    api_id TEXT NOT NULL,
    api_key_env TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL,
    model_id INTEGER NOT NULL,
    response_text TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_prompts_created_at ON prompts(created_at);
CREATE INDEX IF NOT EXISTS idx_models_name ON models(name);
CREATE INDEX IF NOT EXISTS idx_models_is_active ON models(is_active);
CREATE INDEX IF NOT EXISTS idx_results_prompt_id ON results(prompt_id);
CREATE INDEX IF NOT EXISTS idx_results_model_id ON results(model_id);
CREATE INDEX IF NOT EXISTS idx_results_saved_at ON results(saved_at);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
        self.ensure_default_settings()

    def _fetch_one(
        self, query: str, parameters: Iterable[Any] = ()
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(query, tuple(parameters)).fetchone()
        return dict(row) if row is not None else None

    def _fetch_all(
        self, query: str, parameters: Iterable[Any] = ()
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [dict(row) for row in rows]

    def _execute(self, query: str, parameters: Iterable[Any] = ()) -> int:
        with self.connect() as connection:
            cursor = connection.execute(query, tuple(parameters))
            connection.commit()
            return int(cursor.lastrowid)

    def _update_by_id(
        self, table_name: str, record_id: int, fields: Mapping[str, Any]
    ) -> None:
        updates = {key: value for key, value in fields.items() if value is not None}
        if not updates:
            return

        assignments = ", ".join(f"{column} = ?" for column in updates)
        parameters = list(updates.values()) + [record_id]

        with self.connect() as connection:
            connection.execute(
                f"UPDATE {table_name} SET {assignments} WHERE id = ?",
                parameters,
            )
            connection.commit()

    def create_prompt(
        self,
        prompt_text: str,
        tags: str | None = None,
        created_at: str | None = None,
    ) -> int:
        timestamp = created_at or utc_now_iso()
        return self._execute(
            """
            INSERT INTO prompts (created_at, prompt_text, tags)
            VALUES (?, ?, ?)
            """,
            (timestamp, prompt_text, tags),
        )

    def get_prompt_by_text(self, prompt_text: str) -> dict[str, Any] | None:
        return self._fetch_one(
            """
            SELECT id, created_at, prompt_text, tags
            FROM prompts
            WHERE prompt_text = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (prompt_text,),
        )

    def list_prompts(
        self, search: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        query = """
            SELECT id, created_at, prompt_text, tags
            FROM prompts
        """
        parameters: list[Any] = []

        if search:
            query += " WHERE prompt_text LIKE ? OR COALESCE(tags, '') LIKE ?"
            like_value = f"%{search}%"
            parameters.extend([like_value, like_value])

        query += " ORDER BY created_at DESC"

        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        return self._fetch_all(query, parameters)

    def get_prompt(self, prompt_id: int) -> dict[str, Any] | None:
        return self._fetch_one(
            """
            SELECT id, created_at, prompt_text, tags
            FROM prompts
            WHERE id = ?
            """,
            (prompt_id,),
        )

    def update_prompt(
        self, prompt_id: int, prompt_text: str | None = None, tags: str | None = None
    ) -> None:
        self._update_by_id(
            "prompts",
            prompt_id,
            {
                "prompt_text": prompt_text,
                "tags": tags,
            },
        )

    def delete_prompt(self, prompt_id: int) -> None:
        self._execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))

    def create_model(
        self,
        name: str,
        api_url: str,
        api_id: str,
        api_key_env: str,
        is_active: bool = True,
    ) -> int:
        return self._execute(
            """
            INSERT INTO models (name, api_url, api_id, api_key_env, is_active)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, api_url, api_id, api_key_env, int(is_active)),
        )

    def list_models(
        self, active_only: bool | None = None, search: str | None = None
    ) -> list[dict[str, Any]]:
        query = """
            SELECT id, name, api_url, api_id, api_key_env, is_active
            FROM models
        """
        filters: list[str] = []
        parameters: list[Any] = []

        if active_only is not None:
            filters.append("is_active = ?")
            parameters.append(int(active_only))

        if search:
            filters.append(
                "(name LIKE ? OR api_url LIKE ? OR api_id LIKE ? OR api_key_env LIKE ?)"
            )
            like_value = f"%{search}%"
            parameters.extend([like_value, like_value, like_value, like_value])

        if filters:
            query += " WHERE " + " AND ".join(filters)

        query += " ORDER BY name ASC"
        return self._fetch_all(query, parameters)

    def get_model(self, model_id: int) -> dict[str, Any] | None:
        return self._fetch_one(
            """
            SELECT id, name, api_url, api_id, api_key_env, is_active
            FROM models
            WHERE id = ?
            """,
            (model_id,),
        )

    def get_active_models(self) -> list[dict[str, Any]]:
        return self.list_models(active_only=True)

    def update_model(
        self,
        model_id: int,
        *,
        name: str | None = None,
        api_url: str | None = None,
        api_id: str | None = None,
        api_key_env: str | None = None,
        is_active: bool | None = None,
    ) -> None:
        self._update_by_id(
            "models",
            model_id,
            {
                "name": name,
                "api_url": api_url,
                "api_id": api_id,
                "api_key_env": api_key_env,
                "is_active": int(is_active) if is_active is not None else None,
            },
        )

    def delete_model(self, model_id: int) -> None:
        self._execute("DELETE FROM models WHERE id = ?", (model_id,))

    def save_result(
        self,
        prompt_id: int,
        model_id: int,
        response_text: str,
        saved_at: str | None = None,
    ) -> int:
        timestamp = saved_at or utc_now_iso()
        return self._execute(
            """
            INSERT INTO results (prompt_id, model_id, response_text, saved_at)
            VALUES (?, ?, ?, ?)
            """,
            (prompt_id, model_id, response_text, timestamp),
        )

    def save_results(self, result_rows: Iterable[Mapping[str, Any]]) -> list[int]:
        result_ids: list[int] = []
        with self.connect() as connection:
            for row in result_rows:
                cursor = connection.execute(
                    """
                    INSERT INTO results (prompt_id, model_id, response_text, saved_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        row["prompt_id"],
                        row["model_id"],
                        row["response_text"],
                        row.get("saved_at", utc_now_iso()),
                    ),
                )
                result_ids.append(int(cursor.lastrowid))
            connection.commit()
        return result_ids

    def list_results(
        self,
        prompt_id: int | None = None,
        model_id: int | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                results.id,
                results.prompt_id,
                results.model_id,
                prompts.prompt_text,
                models.name AS model_name,
                results.response_text,
                results.saved_at
            FROM results
            JOIN prompts ON prompts.id = results.prompt_id
            JOIN models ON models.id = results.model_id
        """
        filters: list[str] = []
        parameters: list[Any] = []

        if prompt_id is not None:
            filters.append("results.prompt_id = ?")
            parameters.append(prompt_id)

        if model_id is not None:
            filters.append("results.model_id = ?")
            parameters.append(model_id)

        if search:
            filters.append(
                "("
                "prompts.prompt_text LIKE ? OR "
                "models.name LIKE ? OR "
                "results.response_text LIKE ?"
                ")"
            )
            like_value = f"%{search}%"
            parameters.extend([like_value, like_value, like_value])

        if filters:
            query += " WHERE " + " AND ".join(filters)

        query += " ORDER BY results.saved_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        return self._fetch_all(query, parameters)

    def delete_result(self, result_id: int) -> None:
        self._execute("DELETE FROM results WHERE id = ?", (result_id,))

    def list_settings(self, search: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT id, key, value, updated_at
            FROM settings
        """
        parameters: list[Any] = []

        if search:
            query += " WHERE key LIKE ? OR COALESCE(value, '') LIKE ?"
            like_value = f"%{search}%"
            parameters.extend([like_value, like_value])

        query += " ORDER BY key ASC"
        return self._fetch_all(query, parameters)

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        record = self._fetch_one(
            """
            SELECT value
            FROM settings
            WHERE key = ?
            """,
            (key,),
        )
        if record is None:
            return default
        return record["value"]

    def set_setting(self, key: str, value: str | None) -> None:
        timestamp = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, timestamp),
            )
            connection.commit()

    def delete_setting(self, key: str) -> None:
        self._execute("DELETE FROM settings WHERE key = ?", (key,))

    def ensure_default_settings(
        self, defaults: Mapping[str, str] = DEFAULT_SETTINGS
    ) -> None:
        with self.connect() as connection:
            for key, value in defaults.items():
                connection.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (key, value, utc_now_iso()),
                )
            connection.commit()
