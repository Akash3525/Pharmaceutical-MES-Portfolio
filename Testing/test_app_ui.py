"""The Streamlit app, driven headlessly with Streamlit's AppTest against the test database."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import TEST_DB

APP = str(Path(__file__).resolve().parents[1] / "Pharmaceutical_MES" / "app.py")
PAGES = ["Batch Overview", "Create Batch", "Dispensing", "Step Execution",
         "Review by Exception", "Traceability", "Process Signals", "Audit Trail"]


@pytest.fixture
def app(conn, monkeypatch):
    monkeypatch.setenv("MES_DB_NAME", TEST_DB)  # conn has already built and seeded it
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    return at


def sign_in(at, username):
    picker = at.sidebar.selectbox[0]
    picker.set_value(next(o for o in picker.options if o.startswith({
        "op.patel": "Ravi Patel", "op.garcia": "Maria Garcia", "sup.chen": "Li Chen", "qa.okafor": "Grace Okafor",
    }[username]))).run()


def go_to(at, page):
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception


def test_user_picker_offers_operator_supervisor_and_qa(app):
    roles = {o.rsplit("(", 1)[1].rstrip(")") for o in app.sidebar.selectbox[0].options}
    assert {"OPERATOR", "SUPERVISOR", "QA"} <= roles
    assert app.sidebar.selectbox[0].label == "Signed in as (simulated)"


def test_every_page_renders(app):
    for page in PAGES:
        go_to(app, page)
        assert app.header[0].value.startswith(page.split()[0]), page


def test_dispensing_page_records_a_released_lot_and_shows_database_refusals(app, conn, new_batch):
    sign_in(app, "op.patel")
    go_to(app, "Dispensing")
    app.selectbox(key="disp_batch").set_value(new_batch).run()
    verifier = next(s for s in app.selectbox if s.label.startswith("Verified by"))

    verifier.set_value("(none)").run()
    app.button[0].click().run()
    assert any("second-person verification" in e.value for e in app.error)

    next(s for s in app.selectbox if s.label.startswith("Verified by")).set_value("op.garcia").run()
    app.button[0].click().run()
    assert any("Dispense recorded" in s.value for s in app.success)
    assert conn.execute("SELECT count(*) FROM dispensing WHERE batch_id = %s", (new_batch,)).fetchone()[0] == 1


def test_traceability_page_shows_both_directions(app):
    go_to(app, "Traceability")
    forward, backward = app.dataframe[0].value, app.dataframe[1].value
    assert len(forward) > 0 and "batch_no" in forward.columns
    assert len(backward) > 0 and "lot_no" in backward.columns
