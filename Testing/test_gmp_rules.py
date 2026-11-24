"""The GMP rules are enforced by the database itself, whatever front end writes to it."""
import psycopg
import pytest
from conftest import RuleViolation, dispense_all, lot, material, recipe_id, run_all_steps

import db
import mes


def open_deviations(conn, batch_id, source=None):
    return conn.execute("SELECT count(*) FROM deviations WHERE batch_id = %s AND status = 'OPEN' "
                        "AND (%s::text IS NULL OR source = %s)", (batch_id, source, source)).fetchone()[0]


# ---------------------------------------------------------------- seed data
def test_seed_has_12_batches_and_3_with_deviations(conn):
    statuses = dict(conn.execute("SELECT status, count(*) FROM batches WHERE batch_id <= 12 GROUP BY status"))
    assert statuses == {"RELEASED": 5, "COMPLETED": 5, "IN_PROGRESS": 1, "CREATED": 1}
    sources = {r[0] for r in conn.execute("SELECT source FROM deviations WHERE batch_id <= 12")}
    assert sources == {"DISPENSING", "STEP", "PROCESS_SIGNAL"}
    assert conn.execute("SELECT count(DISTINCT batch_id) FROM deviations WHERE batch_id <= 12").fetchone()[0] == 3


# ---------------------------------------------------------------- dispensing
def test_cannot_dispense_from_quarantined_lot(conn, new_batch):
    with pytest.raises(RuleViolation, match="only RELEASED lots"):
        mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "API-PCM"),
                     lot(conn, "L24-PCM-003"), 50.0)


def test_cannot_dispense_from_expired_lot(conn, new_batch):
    with pytest.raises(RuleViolation, match="expired"):
        mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "EXC-MCC"),
                     lot(conn, "L23-MCC-009"), 35.0)


def test_dispensing_requires_second_person_verification(conn, new_batch):
    args = (new_batch, material(conn, "EXC-STA"), lot(conn, "L24-STA-001"), 10.0)
    with pytest.raises(RuleViolation, match="second-person verification"):
        mes.dispense(conn, "op.patel", None, *args)
    with pytest.raises(RuleViolation, match="different person"):
        mes.dispense(conn, "op.patel", "op.patel", *args)


def test_cannot_dispense_wrong_material(conn, new_batch):
    with pytest.raises(RuleViolation, match="not in the recipe"):  # ibuprofen is not in the paracetamol recipe
        mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "API-IBU"),
                     lot(conn, "L24-IBU-001"), 32.0)
    with pytest.raises(RuleViolation, match="not the requested material"):  # starch requested, stearate lot scanned
        mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "EXC-STA"),
                     lot(conn, "L24-MGS-001"), 10.0)


def test_cannot_dispense_more_than_stock_on_hand(conn, new_batch):
    with pytest.raises(RuleViolation, match="available"):
        mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "EXC-MCC"),
                     lot(conn, "L24-MCC-002"), 5000.0)


def test_dispensed_weight_cannot_be_edited(conn, new_batch):
    mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "EXC-STA"),
                 lot(conn, "L24-STA-001"), 10.0)
    with pytest.raises(RuleViolation, match="cannot be edited"):
        with db.session(conn, "op.patel", "Scale reading typed wrongly"):
            conn.execute("UPDATE dispensing SET actual_qty = 9.5 WHERE batch_id = %s", (new_batch,))


def test_out_of_tolerance_dispense_raises_deviation(conn, new_batch):
    mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "EXC-MGS"),
                 lot(conn, "L24-MGS-001"), 1.10)  # target 1.0 kg, tolerance 5 %
    assert open_deviations(conn, new_batch, "DISPENSING") == 1


# ---------------------------------------------------------------- execution
def test_steps_need_full_dispensing_and_run_in_order(conn, new_batch):
    with pytest.raises(RuleViolation, match="CREATED: steps cannot be executed"):
        mes.record_step(conn, "op.garcia", new_batch, 1, 7)
    mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "EXC-STA"),
                 lot(conn, "L24-STA-001"), 10.0)  # 1 of 5 materials
    with pytest.raises(RuleViolation, match="4 material\\(s\\) not yet dispensed"):
        mes.record_step(conn, "op.garcia", new_batch, 1, 7)
    dispense_all(conn, new_batch)
    with pytest.raises(RuleViolation, match="must be completed before"):
        mes.record_step(conn, "op.garcia", new_batch, 2, 200)


def test_last_step_completes_the_batch(conn, new_batch):
    def status():
        return conn.execute("SELECT status FROM batches WHERE batch_id = %s", (new_batch,)).fetchone()[0]
    dispense_all(conn, new_batch)
    assert status() == "DISPENSING"
    mes.record_step(conn, "op.garcia", new_batch, 1, 7)
    assert status() == "IN_PROGRESS"
    run_all_steps(conn, new_batch)
    assert status() == "COMPLETED"
    assert conn.execute("SELECT completed_at FROM batches WHERE batch_id = %s", (new_batch,)).fetchone()[0]


def test_out_of_limit_step_raises_deviation_and_in_limit_does_not(conn, new_batch):
    dispense_all(conn, new_batch)
    mes.record_step(conn, "op.garcia", new_batch, 1, 7)  # limits 5-10 min
    assert open_deviations(conn, new_batch) == 0
    mes.record_step(conn, "op.garcia", new_batch, 2, 280)  # limits 150-250 rpm
    assert open_deviations(conn, new_batch, "STEP") == 1


def test_signal_excursion_raises_one_deviation_per_tag(conn, new_batch):
    from datetime import datetime, timezone

    import simulator
    rows = simulator.generate(datetime.now(timezone.utc), minutes=20, seed=1,
                              excursion=("FBD-201/TIC-201/PV.CV", 5, 4, 11.0))
    mes.add_signals(conn, new_batch, rows)
    assert open_deviations(conn, new_batch, "PROCESS_SIGNAL") == 1


# ---------------------------------------------------------------- audit trail
def test_audit_trail_is_append_only(conn):
    with pytest.raises(RuleViolation, match="append-only"):
        conn.execute("UPDATE audit_trail SET reason = 'tampered' WHERE audit_id = 1")
    with pytest.raises(RuleViolation, match="append-only"):
        conn.execute("DELETE FROM audit_trail WHERE audit_id = 1")
    with pytest.raises(RuleViolation, match="append-only"):
        conn.execute("TRUNCATE audit_trail")


def test_gmp_records_cannot_be_deleted(conn, completed_batch):
    with pytest.raises(RuleViolation, match="cannot be deleted"):
        conn.execute("DELETE FROM step_executions WHERE batch_id = %s", (completed_batch,))


def test_change_without_reason_is_rejected(conn, completed_batch):
    with pytest.raises(RuleViolation, match="reason for change is required"):
        mes.correct_step(conn, "op.garcia", completed_batch, 1, 8, reason=None)


def test_change_with_reason_is_audited_with_old_and_new_value(conn, completed_batch):
    mes.correct_step(conn, "op.garcia", completed_batch, 1, 8, reason="Wrong value typed")
    row = conn.execute("""
        SELECT a.changed_by, a.reason, a.old_data ->> 'recorded_value', a.new_data ->> 'recorded_value'
        FROM audit_trail a JOIN step_executions s ON a.record_id = s.exec_id::text
        WHERE a.table_name = 'step_executions' AND a.action = 'UPDATE' AND s.batch_id = %s""",
                       (completed_batch,)).fetchone()
    assert row == ("op.garcia", "Wrong value typed", "7.5", "8")


def test_inserts_are_audited_with_user_and_time(conn, new_batch):
    row = conn.execute("""SELECT changed_by, changed_at, new_data ->> 'batch_id' FROM audit_trail
                          WHERE table_name = 'batches' AND action = 'INSERT' AND record_id = %s""",
                       (str(new_batch),)).fetchone()
    assert row[0] == "sup.chen" and row[1] is not None and row[2] == str(new_batch)


# ---------------------------------------------------------------- deviations
def test_closing_a_deviation_needs_a_resolution_and_closed_is_final(conn, new_batch):
    mes.dispense(conn, "op.patel", "op.garcia", new_batch, material(conn, "EXC-MGS"),
                 lot(conn, "L24-MGS-001"), 1.10)  # out of tolerance -> deviation
    dev_id = conn.execute("SELECT deviation_id FROM deviations WHERE batch_id = %s", (new_batch,)).fetchone()[0]
    with pytest.raises(RuleViolation, match="Only an active QA user"):
        mes.close_deviation(conn, "op.patel", dev_id, "Looks fine")
    with pytest.raises(RuleViolation, match="resolution is required"):
        mes.close_deviation(conn, "qa.okafor", dev_id, "  ")
    mes.close_deviation(conn, "qa.okafor", dev_id, "Scale recalibrated, impact assessed as none")
    with pytest.raises(RuleViolation, match="closed and cannot be changed"):
        with db.session(conn, "qa.okafor", "Reopen"):
            conn.execute("UPDATE deviations SET status = 'OPEN' WHERE deviation_id = %s", (dev_id,))


# ---------------------------------------------------------------- QA signature
def test_only_qa_can_sign(conn, completed_batch):
    for user in ("op.patel", "sup.chen"):
        with pytest.raises(RuleViolation, match="Only an active QA user"):
            mes.sign_batch(conn, user, completed_batch)


def test_rejecting_a_batch_needs_a_reason(conn, completed_batch):
    with pytest.raises(RuleViolation, match="reason is required to reject"):
        mes.sign_batch(conn, "qa.okafor", completed_batch, meaning="REJECT")
    mes.sign_batch(conn, "qa.okafor", completed_batch, meaning="REJECT", reason="Granule moisture trend")
    assert conn.execute("SELECT status FROM batches WHERE batch_id = %s",
                        (completed_batch,)).fetchone()[0] == "REJECTED"


def test_signatures_cannot_be_modified(conn, completed_batch):
    mes.sign_batch(conn, "qa.okafor", completed_batch)
    with pytest.raises(RuleViolation, match="cannot be modified"):
        with db.session(conn, "qa.okafor", "Change meaning"):
            conn.execute("UPDATE batch_signatures SET meaning = 'REJECT' WHERE batch_id = %s", (completed_batch,))


def test_qa_cannot_sign_a_batch_they_executed(conn, new_batch):
    dispense_all(conn, new_batch, verifier="qa.berg")  # qa.berg verified a dispense
    run_all_steps(conn, new_batch)
    with pytest.raises(RuleViolation, match="took part in executing"):
        mes.sign_batch(conn, "qa.berg", new_batch)
    mes.sign_batch(conn, "qa.okafor", new_batch)  # an independent QA user can


def test_open_deviation_blocks_release_until_closed(conn, new_batch):
    dispense_all(conn, new_batch)
    run_all_steps(conn, new_batch)
    mes.correct_step(conn, "op.garcia", new_batch, 3, 3.2, reason="Re-test result")  # LOD limit 2.5 %
    with pytest.raises(RuleViolation, match="open deviations"):
        mes.sign_batch(conn, "qa.okafor", new_batch)
    dev_id = conn.execute("SELECT deviation_id FROM deviations WHERE batch_id = %s", (new_batch,)).fetchone()[0]
    with pytest.raises(RuleViolation, match="Only an active QA user"):
        mes.close_deviation(conn, "sup.chen", dev_id, "Investigated")
    mes.close_deviation(conn, "qa.okafor", dev_id, "Granules re-dried, LOD retest 1.8 %, no impact")
    mes.sign_batch(conn, "qa.okafor", new_batch)
    assert conn.execute("SELECT status FROM batches WHERE batch_id = %s", (new_batch,)).fetchone()[0] == "RELEASED"
    with pytest.raises(RuleViolation, match="locked"):
        mes.correct_step(conn, "op.garcia", new_batch, 1, 6, reason="After release")


# ---------------------------------------------------------------- traceability
def test_genealogy_traces_lot_to_batches_and_back(conn, new_batch):
    dispense_all(conn, new_batch)
    batch_no = conn.execute("SELECT batch_no FROM batches WHERE batch_id = %s", (new_batch,)).fetchone()[0]
    lots = {r[0] for r in conn.execute("SELECT lot_no FROM v_genealogy WHERE batch_no = %s", (batch_no,))}
    assert len(lots) == 5  # backward: one lot per recipe material
    api_lot = next(lot_no for lot_no in lots if "PCM" in lot_no)
    batches = {r[0] for r in conn.execute("SELECT batch_no FROM v_genealogy WHERE lot_no = %s", (api_lot,))}
    assert batch_no in batches and len(batches) > 1  # forward: the lot also went into seeded batches


def test_rule_violations_are_database_errors_not_app_checks(conn):
    # Writing directly with SQL (no Python service layer) hits the same rules.
    with pytest.raises(psycopg.errors.RaiseException, match="second-person verification"):
        with conn.transaction():
            conn.execute("""INSERT INTO dispensing (batch_id, material_id, lot_id, actual_qty, dispensed_by)
                            SELECT b.batch_id, m.material_id, l.lot_id, 1, 1
                            FROM batches b, materials m, material_lots l
                            WHERE b.status = 'CREATED' AND m.code = 'EXC-MGS' AND l.lot_no = 'L24-MGS-001'
                            LIMIT 1""")
    assert conn.execute("SELECT count(*) FROM dispensing d JOIN batches b USING (batch_id) "
                        "WHERE b.recipe_id = %s AND d.verified_by IS NULL", (recipe_id(conn),)).fetchone()[0] == 0
