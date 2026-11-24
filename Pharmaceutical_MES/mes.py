"""MES operations used by the Streamlit app, the seed script and the tests.

These functions only write data. Every GMP rule (released lots, second-person
verification, limits, signatures, audit trail) is enforced by triggers in
schema.sql, so a rule violation surfaces as a psycopg error raised by the
database.
"""
from __future__ import annotations

from datetime import datetime

import psycopg

from db import session


def user_id(conn: psycopg.Connection, username: str) -> int:
    row = conn.execute("SELECT user_id FROM app_users WHERE username = %s", (username,)).fetchone()
    if not row:
        raise ValueError(f"Unknown user {username!r}")
    return row[0]


def next_batch_no(conn: psycopg.Connection, recipe_id: int) -> str:
    code = conn.execute("""SELECT p.code FROM recipes r JOIN products p USING (product_id)
                           WHERE r.recipe_id = %s""", (recipe_id,)).fetchone()[0]
    n = conn.execute("SELECT count(*) FROM batches b JOIN recipes r USING (recipe_id) "
                     "JOIN products p USING (product_id) WHERE p.code = %s", (code,)).fetchone()[0]
    return f"{code}-{n + 1:04d}"


def create_batch(conn, user: str, recipe_id: int, batch_no: str | None = None,
                 created_at: datetime | None = None) -> int:
    with session(conn, user):
        batch_no = batch_no or next_batch_no(conn, recipe_id)
        return conn.execute(
            "INSERT INTO batches (batch_no, recipe_id, created_by, created_at) "
            "VALUES (%s, %s, %s, coalesce(%s, now())) RETURNING batch_id",
            (batch_no, recipe_id, user_id(conn, user), created_at)).fetchone()[0]


def suggest_lot(conn, material_id: int, qty: float) -> int | None:
    """First-expiry-first-out: the released, unexpired lot that expires first and has enough stock."""
    row = conn.execute("""
        SELECT lot_id FROM material_lots
        WHERE material_id = %s AND status = 'RELEASED' AND expiry_date >= current_date
          AND qty_available >= %s
        ORDER BY expiry_date, lot_no LIMIT 1""", (material_id, qty)).fetchone()
    return row[0] if row else None


def dispense(conn, user: str, verifier: str | None, batch_id: int, material_id: int, lot_id: int,
             qty: float, at: datetime | None = None) -> int:
    with session(conn, user):
        return conn.execute(
            "INSERT INTO dispensing (batch_id, material_id, lot_id, actual_qty, dispensed_by, verified_by, "
            "dispensed_at) VALUES (%s, %s, %s, %s, %s, %s, coalesce(%s, now())) RETURNING dispense_id",
            (batch_id, material_id, lot_id, qty, user_id(conn, user),
             user_id(conn, verifier) if verifier else None, at)).fetchone()[0]


def record_step(conn, user: str, batch_id: int, step_no: int, value: float,
                at: datetime | None = None, comment: str | None = None) -> int:
    with session(conn, user):
        return conn.execute(
            "INSERT INTO step_executions (batch_id, step_no, recorded_value, executed_by, executed_at, comment) "
            "VALUES (%s, %s, %s, %s, coalesce(%s, now()), %s) RETURNING exec_id",
            (batch_id, step_no, value, user_id(conn, user), at, comment)).fetchone()[0]


def correct_step(conn, user: str, batch_id: int, step_no: int, new_value: float, reason: str | None) -> None:
    with session(conn, user, reason):
        cur = conn.execute("UPDATE step_executions SET recorded_value = %s WHERE batch_id = %s AND step_no = %s",
                           (new_value, batch_id, step_no))
        if cur.rowcount == 0:
            raise ValueError(f"Step {step_no} has not been executed for this batch")


def add_signals(conn, batch_id: int, rows: list[tuple[str, float, datetime]]) -> int:
    with session(conn, "SIMULATOR"):
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO process_signals (batch_id, tag, value, ts) VALUES (%s, %s, %s, %s)",
                            [(batch_id, tag, round(value, 3), ts) for tag, value, ts in rows])
    return len(rows)


def close_deviation(conn, qa_user: str, deviation_id: int, resolution: str) -> None:
    with session(conn, qa_user, f"Deviation closed: {resolution}"):
        conn.execute("UPDATE deviations SET status = 'CLOSED', resolution = %s, closed_by = %s "
                     "WHERE deviation_id = %s", (resolution, user_id(conn, qa_user), deviation_id))


def sign_batch(conn, qa_user: str, batch_id: int, meaning: str = "RELEASE", reason: str | None = None,
               at: datetime | None = None) -> int:
    with session(conn, qa_user):
        return conn.execute(
            "INSERT INTO batch_signatures (batch_id, signed_by, meaning, reason, signed_at) "
            "VALUES (%s, %s, %s, %s, coalesce(%s, now())) RETURNING signature_id",
            (batch_id, user_id(conn, qa_user), meaning, reason, at)).fetchone()[0]


def next_step(conn, batch_id: int):
    """The next recipe step to execute, or None if all steps are done."""
    return conn.execute("""
        SELECT rs.step_no, rs.instruction, rs.parameter_name, rs.unit, rs.lower_limit, rs.upper_limit
        FROM batches b JOIN recipe_steps rs USING (recipe_id)
        WHERE b.batch_id = %s
          AND NOT EXISTS (SELECT 1 FROM step_executions s WHERE s.batch_id = b.batch_id AND s.step_no = rs.step_no)
        ORDER BY rs.step_no LIMIT 1""", (batch_id,)).fetchone()


def materials_to_dispense(conn, batch_id: int):
    return conn.execute("""
        SELECT m.material_id, m.code, m.name, m.uom, rm.qty_per_batch, rm.tolerance_pct
        FROM batches b JOIN recipe_materials rm USING (recipe_id) JOIN materials m USING (material_id)
        WHERE b.batch_id = %s
          AND NOT EXISTS (SELECT 1 FROM dispensing d WHERE d.batch_id = b.batch_id AND d.material_id = m.material_id)
        ORDER BY m.code""", (batch_id,)).fetchall()
