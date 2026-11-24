"""Pharmaceutical MES / electronic batch record: Streamlit front end.

Run:  streamlit run Pharmaceutical_MES/app.py

The app only collects input and shows data. Every GMP rule is enforced by the
PostgreSQL triggers in schema.sql, and a rejected action shows the database's
own message. Learning project, not a validated GxP system. The user picker
simulates login and is not real authentication.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg
import streamlit as st

import db
import mes
import simulator

st.set_page_config(page_title="Pharma MES Portfolio", page_icon="💊", layout="wide")


# ---------------------------------------------------------------- data access
# One connection per script run, closed at the end of the run. Streamlit can
# start a new run while an older one is still finishing, so runs must not
# share a connection.
CONN = db.connect()


def conn() -> psycopg.Connection:
    return CONN


def df(query: str, params: tuple = ()) -> pd.DataFrame:
    cur = conn().execute(query, params)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def run_action(label: str, fn, *args, **kwargs) -> bool:
    """Run a write. Show the database's message if a GMP rule rejects it."""
    try:
        fn(conn(), *args, **kwargs)
    except psycopg.Error as exc:
        st.error(f"Rejected by the database: {db.error_text(exc)}")
        return False
    except ValueError as exc:
        st.error(str(exc))
        return False
    st.session_state["flash"] = label
    st.rerun()
    return True


def batch_picker(statuses: tuple[str, ...], key: str, label: str = "Batch"):
    batches = df("SELECT batch_id, batch_no, status FROM batches WHERE status = ANY(%s) ORDER BY batch_no",
                 (list(statuses),))
    if batches.empty:
        st.info(f"No batches with status {', '.join(statuses)}.")
        return None
    # Options are batch ids, so the selection survives a status change. The status is
    # shown separately because Streamlit keeps option labels while the options are unchanged.
    names = dict(zip(batches.batch_id.astype(int), batches.batch_no))
    batch_id = st.selectbox(label, list(names), key=key, format_func=names.get)
    status = batches.set_index("batch_id").loc[batch_id, "status"]
    st.caption(f"Status: **{status}**")
    return batch_id


# ---------------------------------------------------------------- sidebar
users = df("SELECT username, full_name, role FROM app_users WHERE active ORDER BY role, username")
st.sidebar.title("💊 Pharma MES")
labels = {f"{r.full_name} ({r.role})": r.username for r in users.itertuples()}
current_label = st.sidebar.selectbox("Signed in as (simulated)", list(labels))
USER = labels[current_label]
ROLE = users.set_index("username").loc[USER, "role"]

PAGES = ["Batch Overview", "Create Batch", "Dispensing", "Step Execution",
         "Review by Exception", "Traceability", "Process Signals", "Audit Trail"]
page = st.sidebar.radio("Go to", PAGES)
st.sidebar.caption("Learning project, not a validated GxP system. All data is fictional.")

if msg := st.session_state.pop("flash", None):
    st.success(msg)


# ---------------------------------------------------------------- pages
def page_overview():
    st.header("Batch Overview")
    progress = df("SELECT * FROM v_batch_progress ORDER BY batch_no")
    c = st.columns(4)
    c[0].metric("Batches", len(progress))
    c[1].metric("In progress", int(progress.status.isin(["DISPENSING", "IN_PROGRESS"]).sum()))
    c[2].metric("Awaiting QA", int((progress.status == "COMPLETED").sum()))
    c[3].metric("Open deviations", int(progress.open_deviations.sum()))
    st.dataframe(
        progress[["batch_no", "product_name", "status", "pct_complete", "materials_dispensed",
                  "materials_required", "steps_done", "steps_total", "open_deviations", "created_at",
                  "completed_at", "disposition_at"]],
        hide_index=True, width="stretch",
        column_config={"pct_complete": st.column_config.ProgressColumn("Progress", format="%d%%",
                                                                       min_value=0, max_value=100)})


def page_create():
    st.header("Create Batch")
    recipes = df("""SELECT r.recipe_id, p.code, p.name, r.version, r.batch_size, r.batch_uom
                    FROM recipes r JOIN products p USING (product_id) WHERE r.status = 'APPROVED'
                    ORDER BY p.code""")
    options = {f"{r.code} {r.name} (v{r.version}, {float(r.batch_size):g} {r.batch_uom})": int(r.recipe_id)
               for r in recipes.itertuples()}
    recipe_id = options[st.selectbox("Master recipe", list(options))]
    st.subheader("Bill of materials")
    st.dataframe(df("""SELECT m.code, m.name, rm.qty_per_batch, m.uom, rm.tolerance_pct
                       FROM recipe_materials rm JOIN materials m USING (material_id)
                       WHERE recipe_id = %s ORDER BY m.code""", (recipe_id,)),
                 hide_index=True, width="stretch")
    st.subheader("Process steps")
    st.dataframe(df("""SELECT step_no, instruction, parameter_name, lower_limit, upper_limit, unit
                       FROM recipe_steps WHERE recipe_id = %s ORDER BY step_no""", (recipe_id,)),
                 hide_index=True, width="stretch")
    batch_no = mes.next_batch_no(conn(), recipe_id)
    if st.button(f"Create batch {batch_no}", type="primary"):
        run_action(f"Batch {batch_no} created.", mes.create_batch, USER, recipe_id, batch_no)


def page_dispensing():
    st.header("Dispensing")
    batch_id = batch_picker(("CREATED", "DISPENSING"), "disp_batch")
    if batch_id is None:
        return
    remaining = mes.materials_to_dispense(conn(), batch_id)
    done = df("""SELECT m.code, l.lot_no, d.target_qty, d.actual_qty, m.uom,
                        u1.username AS dispensed_by, u2.username AS verified_by, d.dispensed_at
                 FROM dispensing d JOIN materials m USING (material_id) JOIN material_lots l USING (lot_id)
                 JOIN app_users u1 ON u1.user_id = d.dispensed_by
                 LEFT JOIN app_users u2 ON u2.user_id = d.verified_by
                 WHERE d.batch_id = %s ORDER BY d.dispensed_at""", (batch_id,))
    if not done.empty:
        st.subheader("Dispensed")
        st.dataframe(done, hide_index=True, width="stretch")
    if not remaining:
        st.success("All materials dispensed. Continue in Step Execution.")
        return

    st.subheader("Dispense next material")
    mats = {f"{code} {name} (target {float(q):g} {uom}, ±{float(tol):g}%)": (mid, float(q), uom)
            for mid, code, name, uom, q, tol in remaining}
    material_id, target, uom = mats[st.selectbox("Material", list(mats))]
    lots = df("""SELECT lot_id, lot_no, status, expiry_date, qty_available FROM material_lots
                 WHERE material_id = %s ORDER BY expiry_date""", (material_id,))
    st.caption("All lots are listed, including quarantined and expired ones, so you can see the database "
               "refuse them.")
    suggested = mes.suggest_lot(conn(), material_id, target)
    lot_labels = {f"{r.lot_no}: {r.status}, expires {r.expiry_date}, {float(r.qty_available):g} {uom} available":
                  int(r.lot_id) for r in lots.itertuples()}
    ids = list(lot_labels.values())
    lot_label = st.selectbox("Lot (first expiry, first out is preselected)", list(lot_labels),
                             index=ids.index(suggested) if suggested in ids else 0)
    qty = st.number_input(f"Actual weight ({uom})", min_value=0.001, value=target, step=0.001, format="%.3f")
    others = [u for u in users.username if u != USER]
    verifier = st.selectbox("Verified by (second person)", ["(none)"] + others + [USER])
    if st.button("Record dispense", type="primary"):
        run_action("Dispense recorded.", mes.dispense, USER, None if verifier == "(none)" else verifier,
                   batch_id, material_id, lot_labels[lot_label], qty)


def page_steps():
    st.header("Step Execution")
    batch_id = batch_picker(("DISPENSING", "IN_PROGRESS", "COMPLETED"), "step_batch")
    if batch_id is None:
        return
    executed = df("""SELECT s.step_no, rs.instruction, rs.parameter_name, s.recorded_value, rs.unit,
                            rs.lower_limit, rs.upper_limit,
                            s.recorded_value BETWEEN rs.lower_limit AND rs.upper_limit AS in_limits,
                            u.username AS executed_by, s.executed_at
                     FROM step_executions s JOIN batches b USING (batch_id)
                     JOIN recipe_steps rs ON rs.recipe_id = b.recipe_id AND rs.step_no = s.step_no
                     JOIN app_users u ON u.user_id = s.executed_by
                     WHERE s.batch_id = %s ORDER BY s.step_no""", (batch_id,))
    if not executed.empty:
        st.subheader("Executed steps")
        st.dataframe(executed, hide_index=True, width="stretch")

    step = mes.next_step(conn(), batch_id)
    if step:
        step_no, instruction, param, unit, lo, hi = step
        st.subheader(f"Step {step_no}: {instruction}")
        st.write(f"Record **{param}** in {unit}. Limits: {float(lo):g} to {float(hi):g} {unit}. "
                 "A value outside the limits is accepted but raises a deviation automatically.")
        value = st.number_input(f"{param} ({unit})", value=float(lo + hi) / 2, key=f"val_{batch_id}_{step_no}")
        comment = st.text_input("Comment (optional)")
        if st.button(f"Record step {step_no}", type="primary"):
            run_action(f"Step {step_no} recorded.", mes.record_step, USER, batch_id, step_no, value,
                       comment=comment or None)
    else:
        st.success("All steps executed. The batch is waiting for QA review.")

    if not executed.empty:
        with st.expander("Correct a recorded value (reason required, audited)"):
            step_no = st.selectbox("Step", executed.step_no.tolist())
            new_value = st.number_input("Corrected value", value=float(
                executed.set_index("step_no").loc[step_no, "recorded_value"]))
            reason = st.text_input("Reason for change")
            if st.button("Save correction"):
                run_action(f"Step {step_no} corrected.", mes.correct_step, USER, batch_id, int(step_no),
                           new_value, reason.strip() or None)


def page_review():
    st.header("Review by Exception")
    st.write("QA reviews only what deviates from the expected record: deviations, changed entries and process "
             "alarms. A batch with no exceptions can be released without reading every entry.")
    summary = df("""SELECT b.batch_no, b.status, count(x.batch_id) AS exceptions,
                           count(*) FILTER (WHERE x.exception_type = 'DEVIATION OPEN') AS open_deviations
                    FROM batches b LEFT JOIN v_review_by_exception x USING (batch_id)
                    WHERE b.status IN ('COMPLETED', 'RELEASED', 'REJECTED')
                    GROUP BY b.batch_no, b.status ORDER BY b.batch_no""")
    st.dataframe(summary, hide_index=True, width="stretch")

    batch_id = batch_picker(("COMPLETED", "RELEASED", "REJECTED"), "rbe_batch", "Review batch")
    if batch_id is None:
        return
    exceptions = df("""SELECT exception_type, severity, detail, occurred_at FROM v_review_by_exception
                       WHERE batch_id = %s ORDER BY occurred_at""", (batch_id,))
    if exceptions.empty:
        st.success("No exceptions recorded for this batch.")
    else:
        st.dataframe(exceptions, hide_index=True, width="stretch")

    status = conn().execute("SELECT status FROM batches WHERE batch_id = %s", (batch_id,)).fetchone()[0]
    open_devs = df("SELECT deviation_id, severity, description FROM deviations "
                   "WHERE batch_id = %s AND status = 'OPEN' ORDER BY deviation_id", (batch_id,))
    if not open_devs.empty:
        st.subheader("Close a deviation (QA)")
        devs = {f"DEV-{r.deviation_id:05d} [{r.severity}] {r.description}": int(r.deviation_id)
                for r in open_devs.itertuples()}
        dev = st.selectbox("Deviation", list(devs))
        resolution = st.text_area("Investigation outcome and resolution")
        if st.button("Close deviation"):
            run_action("Deviation closed.", mes.close_deviation, USER, devs[dev], resolution.strip())

    if status == "COMPLETED":
        st.subheader("Batch disposition (electronic signature)")
        st.caption(f"Signing as {USER} ({ROLE}). The database checks the role, independence from execution "
                   "and open deviations.")
        meaning = st.radio("Decision", ["RELEASE", "REJECT"], horizontal=True)
        reason = st.text_input("Reason (required to reject)")
        confirm = st.checkbox("I confirm this signature has the meaning shown above.")
        if st.button("Sign", type="primary", disabled=not confirm):
            run_action(f"Batch signed: {meaning}.", mes.sign_batch, USER, batch_id, meaning, reason.strip() or None)


def page_traceability():
    st.header("Traceability (material genealogy)")
    forward, backward = st.tabs(["Forward: lot → batches", "Backward: batch → lots"])
    with forward:
        lots = df("SELECT DISTINCT lot_no FROM v_genealogy ORDER BY lot_no")
        if lots.empty:
            st.info("No material has been dispensed yet.")
        else:
            lot_no = st.selectbox("Lot", lots.lot_no)
            st.dataframe(df("""SELECT batch_no, product_name, batch_status, qty_used, uom, dispensed_at
                               FROM v_genealogy WHERE lot_no = %s ORDER BY dispensed_at""", (lot_no,)),
                         hide_index=True, width="stretch")
    with backward:
        batch_id = batch_picker(("DISPENSING", "IN_PROGRESS", "COMPLETED", "RELEASED", "REJECTED"), "trace_batch")
        if batch_id is not None:
            st.dataframe(df("""SELECT g.material_code, g.material_name, g.lot_no, g.lot_status, g.supplier,
                                      g.expiry_date, g.qty_used, g.uom
                               FROM v_genealogy g JOIN batches b USING (batch_no)
                               WHERE b.batch_id = %s ORDER BY g.material_code""", (batch_id,)),
                         hide_index=True, width="stretch")


def page_signals():
    st.header("Process Signals (simulated)")
    st.caption("Values come from a Python simulator using DeltaV-style tag names. There is no connection to a "
               "real DCS, OPC UA server or historian.")
    batch_id = batch_picker(("DISPENSING", "IN_PROGRESS", "COMPLETED", "RELEASED", "REJECTED"), "sig_batch")
    if batch_id is None:
        return
    st.dataframe(df("SELECT tag, description, unit, low_limit, high_limit FROM tag_limits ORDER BY tag"),
                 hide_index=True, width="stretch")
    data = df("SELECT tag, value::float AS value, ts FROM process_signals WHERE batch_id = %s ORDER BY ts",
              (batch_id,))
    if data.empty:
        st.info("No signals recorded for this batch.")
    else:
        for tag, group in data.groupby("tag"):
            lo, hi, unit = conn().execute("SELECT low_limit, high_limit, unit FROM tag_limits WHERE tag = %s",
                                          (tag,)).fetchone()
            outside = int(((group.value < float(lo)) | (group.value > float(hi))).sum())
            st.markdown(f"**{tag}** ({unit}), limits {float(lo):g} to {float(hi):g}"
                        + (f" · :red[{outside} reading(s) outside limits]" if outside else ""))
            st.line_chart(group.set_index("ts")["value"], height=180)

    st.subheader("Generate signals")
    minutes = st.slider("Minutes of data", 10, 120, 30)
    excursion = st.checkbox("Include a dryer inlet temperature excursion (raises a deviation)")
    if st.button("Run simulator"):
        start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        rows = simulator.generate(start, minutes, excursion=simulator.default_excursion() if excursion else None)
        run_action(f"{len(rows)} signal values written.", mes.add_signals, batch_id, rows)


def page_audit():
    st.header("Audit Trail")
    st.write("Append-only. Every insert and update on GMP tables is recorded by a database trigger, with the old "
             "and new values. The database refuses updates and deletes on this table.")
    c = st.columns(3)
    tables = ["(all)"] + df("SELECT DISTINCT table_name FROM audit_trail ORDER BY 1").table_name.tolist()
    table = c[0].selectbox("Table", tables)
    action = c[1].selectbox("Action", ["(all)", "INSERT", "UPDATE"])
    limit = c[2].number_input("Rows", 10, 5000, 200, step=50)
    data = df("""SELECT audit_id, changed_at, changed_by, table_name, record_id, action, reason,
                        old_data::text AS old_data, new_data::text AS new_data
                 FROM audit_trail
                 WHERE (%s = '(all)' OR table_name = %s) AND (%s = '(all)' OR action = %s)
                 ORDER BY audit_id DESC LIMIT %s""", (table, table, action, action, int(limit)))
    st.dataframe(data, hide_index=True, width="stretch")


try:
    {
        "Batch Overview": page_overview, "Create Batch": page_create, "Dispensing": page_dispensing,
        "Step Execution": page_steps, "Review by Exception": page_review, "Traceability": page_traceability,
        "Process Signals": page_signals, "Audit Trail": page_audit,
    }[page]()
finally:
    CONN.close()
