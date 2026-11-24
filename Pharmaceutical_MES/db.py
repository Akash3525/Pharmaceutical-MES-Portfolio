"""Database connection and session helpers.

Settings come from MES_DB_* environment variables; a .env file in the project
root is loaded automatically (see .env.example).
"""
import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA_FILE = HERE / "schema.sql"
load_dotenv(ROOT / ".env")


def _add_windows_libpq() -> None:
    """Let psycopg's pure-Python driver find libpq.dll from a local PostgreSQL install.

    Needed when the psycopg-binary DLL is unavailable or blocked (for example by
    Windows Smart App Control). Set PSYCOPG_IMPL=python in .env in that case.
    """
    if os.name != "nt":
        return
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
    for bin_dir in sorted(base.glob("*/bin"), key=lambda p: p.parent.name, reverse=True):
        if (bin_dir / "libpq.dll").exists():
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            return


_add_windows_libpq()

import psycopg  # noqa: E402  (after the libpq path is set)
from psycopg import sql  # noqa: E402

DEFAULT_DB = "mes_portfolio"


def conn_params(dbname: str | None = None) -> dict:
    return {
        "host": os.getenv("MES_DB_HOST", "localhost"),
        "port": int(os.getenv("MES_DB_PORT", "5432")),
        "user": os.getenv("MES_DB_USER", "postgres"),
        "password": os.getenv("MES_DB_PASSWORD") or None,
        "dbname": dbname or os.getenv("MES_DB_NAME", DEFAULT_DB),
    }


def ensure_database(dbname: str) -> None:
    """Create the database if it does not exist yet."""
    with psycopg.connect(**conn_params("postgres"), autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def connect(dbname: str | None = None) -> psycopg.Connection:
    """Autocommit connection: every `session()` block is its own transaction."""
    return psycopg.connect(**conn_params(dbname), autocommit=True)


def apply_schema(conn: psycopg.Connection) -> None:
    """Drop and recreate all tables, triggers and views."""
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


@contextmanager
def session(conn: psycopg.Connection, user: str | None = None, reason: str | None = None):
    """One transaction carrying the acting user and the reason for change.

    The database triggers read these settings for the audit trail and refuse
    updates that have no reason.
    """
    with conn.transaction():
        if user:
            conn.execute("SELECT set_config('mes.user', %s, true)", (user,))
        if reason:
            conn.execute("SELECT set_config('mes.reason', %s, true)", (reason,))
        yield conn


def error_text(exc: Exception) -> str:
    """The database's own message for a rule violation, without the SQL context."""
    diag = getattr(exc, "diag", None)
    return (diag.message_primary if diag and diag.message_primary else str(exc)).strip()
