"""Usage analytics and user feedback, stored in the Neon database.

Every write runs on a background thread and swallows its own errors, so a
slow or unreachable database never delays or breaks a recipe. Nothing
personal is stored: no API key, no IP address, no photo, and error messages
are reduced to their exception class.
"""

import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg2

MAX_COMMENT = 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe_runs (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    workflow TEXT,
    input_type TEXT,
    dish TEXT,
    recipe_style TEXT,
    city TEXT,
    language TEXT,
    key_source TEXT,
    duration_s REAL,
    status TEXT,
    error_type TEXT
);
CREATE TABLE IF NOT EXISTS recipe_feedback (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id TEXT,
    rating TEXT,
    comment TEXT
);
"""

# One worker: writes run in order, and two first writes cannot race on the
# CREATE TABLE (PostgreSQL rejects concurrent CREATE TABLE IF NOT EXISTS).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="telemetry")
_schema_ready = False
_schema_lock = threading.Lock()


def new_run_id() -> str:
  return uuid.uuid4().hex


def _execute(sql: str, params: tuple) -> None:
  global _schema_ready
  # Read at call time: the .env file is loaded by other modules at import.
  database_url = os.getenv("DATABASE_URL")
  if not database_url:
    return
  try:
    conn = psycopg2.connect(database_url, connect_timeout=5)
    try:
      with conn, conn.cursor() as cur:
        if not _schema_ready:
          with _schema_lock:
            cur.execute(SCHEMA)
        cur.execute(sql, params)
      # Only once the transaction is committed: a rolled back CREATE must
      # run again next time.
      _schema_ready = True
    finally:
      conn.close()
  except Exception as err:
    logging.warning(f"Telemetry write failed: {type(err).__name__}: {err}")


def log_run(
    run_id: str, workflow: str, input_type: str, dish: str | None,
    recipe_style: str, city: str, language: str, key_source: str,
    duration_s: float, status: str, error_type: str | None = None,
) -> None:
  """Record one pipeline run, in the background."""
  _executor.submit(
      _execute,
      "INSERT INTO recipe_runs (id, workflow, input_type, dish, recipe_style, city,"
      " language, key_source, duration_s, status, error_type)"
      " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
      " ON CONFLICT (id) DO NOTHING;",
      (run_id, workflow, input_type, dish, recipe_style, city, language,
       key_source, round(duration_s, 2), status, error_type),
  )


def log_feedback(run_id: str, rating: str, comment: str = "") -> None:
  """Record a user's rating of a run and their optional comment, in the background."""
  comment = (comment or "").strip()[:MAX_COMMENT] or None
  _executor.submit(
      _execute,
      "INSERT INTO recipe_feedback (run_id, rating, comment) VALUES (%s, %s, %s);",
      (run_id, rating, comment),
  )
