import os

import psycopg
import pytest

import db
import mes
import seed

TEST_DB = os.getenv("MES_TEST_DB_NAME", "mes_portfolio_test")


@pytest.fixture(scope="session")
def conn():
    """A dedicated test database, rebuilt and seeded once per test run.

    Tests that change data create their own new batch, so they do not depend
    on each other's leftovers.
    """
    db.ensure_database(TEST_DB)
    with db.connect(TEST_DB) as c:
        seed.seed_all(c)
        yield c


def recipe_id(conn, product="PCM-500") -> int:
    return conn.execute("SELECT recipe_id FROM recipes JOIN products USING (product_id) WHERE code = %s",
                        (product,)).fetchone()[0]


def material(conn, code: str) -> int:
    return conn.execute("SELECT material_id FROM materials WHERE code = %s", (code,)).fetchone()[0]


def lot(conn, lot_no: str) -> int:
    return conn.execute("SELECT lot_id FROM material_lots WHERE lot_no = %s", (lot_no,)).fetchone()[0]


@pytest.fixture
def new_batch(conn):
    return mes.create_batch(conn, "sup.chen", recipe_id(conn))


def dispense_all(conn, batch_id, dispenser="op.patel", verifier="op.garcia"):
    for material_id, _, _, _, target, _ in mes.materials_to_dispense(conn, batch_id):
        mes.dispense(conn, dispenser, verifier, batch_id, material_id,
                     mes.suggest_lot(conn, material_id, float(target)), float(target))


def run_all_steps(conn, batch_id, executor="op.garcia"):
    while step := mes.next_step(conn, batch_id):
        step_no, _, _, _, lo, hi = step
        mes.record_step(conn, executor, batch_id, step_no, float(lo + hi) / 2)


@pytest.fixture
def completed_batch(conn, new_batch):
    dispense_all(conn, new_batch)
    run_all_steps(conn, new_batch)
    return new_batch


RuleViolation = psycopg.errors.RaiseException
