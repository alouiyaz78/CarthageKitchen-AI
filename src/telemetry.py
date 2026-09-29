"""Usage analytics and user feedback, stored in the Neon table app_analytics.

Both functions catch every error, so an unreachable database never breaks a
recipe. Nothing personal is stored: no API key, no IP address, no photo. The
session id is Gradio's anonymous per-tab hash.
"""

import logging
import os

import psycopg2

MAX_COMMENT = 1000
MAX_ERROR = 2000
# feedback_rating values
AUTHENTIC, HALLUCINATION = 1, -1


def _connect():
  database_url = os.getenv("DATABASE_URL")
  if not database_url:
    return None
  return psycopg2.connect(database_url, connect_timeout=5)


def log_execution(
    input_type: str, selected_dish: str | None, clinical_profile: str,
    grocer_city: str, model_used: str | None, execution_time_sec: float,
    status: str, error_message: str | None = None, session_id: str | None = None,
) -> int | None:
  """Insert one pipeline run and return its id, or None if it could not be saved."""
  try:
    conn = _connect()
    if conn is None:
      return None
    try:
      with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_analytics (session_id, input_type, selected_dish,"
            " clinical_profile, grocer_city, model_used, execution_time_sec,"
            " status, error_message)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;",
            (session_id, input_type, selected_dish, clinical_profile, grocer_city,
             model_used, round(execution_time_sec, 2), status,
             error_message[:MAX_ERROR] if error_message else None),
        )
        return cur.fetchone()[0]
    finally:
      conn.close()
  except Exception as err:
    logging.warning(f"Telemetry: run not saved: {type(err).__name__}: {err}")
    return None


def save_feedback(log_id: int, feedback_rating: int, comment: str | None = None) -> bool:
  """Store a user's rating on a run, and append their comment to error_message.

  Without a comment, error_message is left as it is (appending NULL in SQL
  would erase it).
  """
  comment = (comment or "").strip()[:MAX_COMMENT] or None
  try:
    conn = _connect()
    if conn is None:
      return False
    try:
      with conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE app_analytics SET feedback_rating = %s,"
            " error_message = CASE WHEN %s::text IS NULL THEN error_message"
            " ELSE COALESCE(error_message, '') || ' | Feedback: ' || %s END"
            " WHERE id = %s;",
            (feedback_rating, comment, comment, log_id),
        )
        return cur.rowcount == 1
    finally:
      conn.close()
  except Exception as err:
    logging.warning(f"Telemetry: feedback not saved: {type(err).__name__}: {err}")
    return False
