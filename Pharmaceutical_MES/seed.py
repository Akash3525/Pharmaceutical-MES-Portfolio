"""Create the database and load fictional master data plus 12 batches.

Usage:  python Pharmaceutical_MES/seed.py

Batches 1-5 are released, 6-7 are complete and waiting for QA, 8-10 are
complete with a deliberate deviation each (out-of-tolerance dispense,
out-of-limit step value, process temperature excursion), 11 is in progress
and 12 has just been created. Every record goes through the same database
rules as the app, so the seed itself exercises the GMP triggers.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

import db
import mes
import simulator

USERS = [
    ("op.patel", "Ravi Patel", "OPERATOR"),
    ("op.garcia", "Maria Garcia", "OPERATOR"),
    ("sup.chen", "Li Chen", "SUPERVISOR"),
    ("qa.okafor", "Grace Okafor", "QA"),
    ("qa.berg", "Lars Berg", "QA"),
    ("admin", "System Administrator", "ADMIN"),
]

MATERIALS = [
    ("API-PCM", "Paracetamol API"),
    ("API-IBU", "Ibuprofen API"),
    ("EXC-MCC", "Microcrystalline cellulose PH-101"),
    ("EXC-STA", "Maize starch"),
    ("EXC-PVP", "Povidone K30"),
    ("EXC-CCS", "Croscarmellose sodium"),
    ("EXC-MGS", "Magnesium stearate"),
]

# lot_no, material, supplier, status, days to expiry, qty
LOTS = [
    ("L24-PCM-001", "API-PCM", "Fictional Pharma Chem Ltd", "RELEASED", 420, 300),
    ("L24-PCM-002", "API-PCM", "Fictional Pharma Chem Ltd", "RELEASED", 610, 800),
    ("L24-PCM-003", "API-PCM", "Fictional Pharma Chem Ltd", "QUARANTINE", 700, 300),
    ("L24-IBU-001", "API-IBU", "Example Actives GmbH", "RELEASED", 380, 250),
    ("L24-IBU-002", "API-IBU", "Example Actives GmbH", "REJECTED", 500, 150),
    ("L24-MCC-001", "EXC-MCC", "Sample Excipients Inc", "RELEASED", 540, 1000),
    ("L24-MCC-002", "EXC-MCC", "Sample Excipients Inc", "RELEASED", 30, 50),
    ("L23-MCC-009", "EXC-MCC", "Sample Excipients Inc", "RELEASED", -12, 80),  # expired
    ("L24-STA-001", "EXC-STA", "Demo Starch Co", "RELEASED", 365, 400),
    ("L24-PVP-001", "EXC-PVP", "Sample Excipients Inc", "RELEASED", 450, 120),
    ("L24-CCS-001", "EXC-CCS", "Sample Excipients Inc", "RELEASED", 400, 40),
    ("L24-MGS-001", "EXC-MGS", "Demo Lubricants SA", "RELEASED", 300, 50),
]

PRODUCTS = [("PCM-500", "Paracetamol 500 mg tablets"), ("IBU-200", "Ibuprofen 200 mg tablets")]

# product: (batch size kg, [(material, kg, tolerance %)], [(instruction, parameter, unit, low, high)])
RECIPES = {
    "PCM-500": (100, [("API-PCM", 50.0, 1.0), ("EXC-MCC", 35.0, 2.0), ("EXC-STA", 10.0, 2.0),
                      ("EXC-PVP", 4.0, 2.0), ("EXC-MGS", 1.0, 5.0)],
                [("Dry mix API and excipients in high-shear granulator", "Mixing time", "min", 5, 10),
                 ("Wet granulate with povidone binder solution", "Impeller speed", "rpm", 150, 250),
                 ("Dry granules in fluid bed dryer", "Loss on drying", "%", 1.0, 2.5),
                 ("Blend dried granules with magnesium stearate", "Blend time", "min", 3, 5),
                 ("Compress tablets", "Mean tablet weight", "mg", 582, 618)]),
    "IBU-200": (80, [("API-IBU", 32.0, 1.0), ("EXC-MCC", 36.0, 2.0), ("EXC-STA", 8.0, 2.0),
                     ("EXC-CCS", 3.2, 2.0), ("EXC-MGS", 0.8, 5.0)],
                [("Dry mix API and excipients in high-shear granulator", "Mixing time", "min", 5, 10),
                 ("Wet granulate with purified water", "Impeller speed", "rpm", 150, 250),
                 ("Dry granules in fluid bed dryer", "Loss on drying", "%", 1.0, 2.0),
                 ("Blend dried granules with magnesium stearate", "Blend time", "min", 3, 5),
                 ("Compress tablets", "Mean tablet weight", "mg", 388, 412)]),
}

# batch number in sequence -> product, final state, deliberate problem
BATCH_PLAN = [
    ("PCM-500", "RELEASED", None), ("IBU-200", "RELEASED", None), ("PCM-500", "RELEASED", None),
    ("PCM-500", "RELEASED", None), ("IBU-200", "RELEASED", None),
    ("PCM-500", "COMPLETED", None), ("IBU-200", "COMPLETED", None),
    ("PCM-500", "COMPLETED", "dispense_tolerance"),
    ("PCM-500", "COMPLETED", "step_out_of_limit"),
    ("IBU-200", "COMPLETED", "signal_excursion"),
    ("PCM-500", "IN_PROGRESS", None),
    ("IBU-200", "CREATED", None),
]


def seed_master_data(conn) -> None:
    with db.session(conn, "admin"):
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO app_users (username, full_name, role) VALUES (%s, %s, %s)", USERS)
            cur.executemany("INSERT INTO materials (code, name) VALUES (%s, %s)", MATERIALS)
            cur.executemany("INSERT INTO products (code, name) VALUES (%s, %s)", PRODUCTS)
            cur.executemany("INSERT INTO tag_limits VALUES (%s, %s, %s, %s, %s)", simulator.tag_limit_rows())
            today = date.today()
            cur.executemany(
                "INSERT INTO material_lots (lot_no, material_id, supplier, status, expiry_date, qty_received, "
                "qty_available, received_at) SELECT %s, material_id, %s, %s, %s, %s, %s, now() - interval '60 days' "
                "FROM materials WHERE code = %s",
                [(lot, sup, st, today + timedelta(days=d), q, q, mat) for lot, mat, sup, st, d, q in LOTS])
            for code, (size, mats, steps) in RECIPES.items():
                recipe_id = cur.execute(
                    "INSERT INTO recipes (product_id, version, name, batch_size) "
                    "SELECT product_id, 1, name || ' - master recipe', %s FROM products WHERE code = %s "
                    "RETURNING recipe_id", (size, code)).fetchone()[0]
                cur.executemany(
                    "INSERT INTO recipe_materials SELECT %s, material_id, %s, %s FROM materials WHERE code = %s",
                    [(recipe_id, qty, tol, mat) for mat, qty, tol in mats])
                cur.executemany(
                    "INSERT INTO recipe_steps VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [(recipe_id, n, *s) for n, s in enumerate(steps, start=1)])


def _recipe_id(conn, product_code: str) -> int:
    return conn.execute("SELECT recipe_id FROM recipes JOIN products USING (product_id) WHERE code = %s",
                        (product_code,)).fetchone()[0]


def seed_batches(conn, seed: int = 7) -> None:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(days=24)
    operators = ["op.patel", "op.garcia"]

    for i, (product, state, problem) in enumerate(BATCH_PLAN):
        t = start + timedelta(days=1.8 * i, hours=rng.randint(0, 3))
        batch_id = mes.create_batch(conn, "sup.chen", _recipe_id(conn, product), created_at=t)
        if state == "CREATED":
            continue

        dispenser, verifier = operators[i % 2], operators[(i + 1) % 2]
        t += timedelta(hours=1)
        for material_id, code, _, _, target, _ in mes.materials_to_dispense(conn, batch_id):
            target = float(target)
            qty = round(target * rng.uniform(0.997, 1.003), 3)
            if problem == "dispense_tolerance" and code == "EXC-MGS":
                qty = round(target * 1.08, 3)  # 8 % over, tolerance is 5 %
            lot_id = mes.suggest_lot(conn, material_id, qty)
            mes.dispense(conn, dispenser, verifier, batch_id, material_id, lot_id, qty, at=t)
            t += timedelta(minutes=rng.randint(6, 15))

        # Process signals from the granulation and drying phase.
        excursion = simulator.default_excursion(rng) if problem == "signal_excursion" else None
        mes.add_signals(conn, batch_id, simulator.generate(t + timedelta(minutes=30), minutes=60,
                                                           seed=rng.randint(0, 10**6), excursion=excursion))

        executor = operators[(i + 1) % 2]
        n_steps = 2 if state == "IN_PROGRESS" else None
        steps = conn.execute("SELECT step_no, lower_limit, upper_limit FROM batches JOIN recipe_steps "
                             "USING (recipe_id) WHERE batch_id = %s ORDER BY step_no", (batch_id,)).fetchall()
        for step_no, lo, hi in steps[:n_steps]:
            t += timedelta(minutes=rng.randint(35, 70))
            lo, hi = float(lo), float(hi)
            value = round(rng.uniform(lo + 0.25 * (hi - lo), hi - 0.25 * (hi - lo)), 1)
            if problem == "step_out_of_limit" and step_no == 3:
                value = round(hi + 0.6, 1)  # loss on drying too high
            mes.record_step(conn, executor, batch_id, step_no, value, at=t)

        if problem == "step_out_of_limit":
            # A transcription error corrected afterwards, with a reason: shows up in review by exception.
            row = conn.execute("SELECT recorded_value FROM step_executions WHERE batch_id = %s AND step_no = 5",
                               (batch_id,)).fetchone()
            mes.correct_step(conn, executor, batch_id, 5, float(row[0]) + 1.0,
                             "Transcription error: value re-read from balance printout")

        if state == "RELEASED":
            mes.sign_batch(conn, "qa.okafor", batch_id, "RELEASE", at=t + timedelta(hours=20))


def seed_all(conn) -> None:
    db.apply_schema(conn)
    seed_master_data(conn)
    seed_batches(conn)


def main() -> None:
    name = db.conn_params()["dbname"]
    db.ensure_database(name)
    with db.connect() as conn:
        seed_all(conn)
        rows = conn.execute("SELECT status, count(*) FROM batches GROUP BY status ORDER BY status").fetchall()
        devs = conn.execute("SELECT count(*), count(DISTINCT batch_id) FROM deviations").fetchone()
        audit = conn.execute("SELECT count(*) FROM audit_trail").fetchone()[0]
    print(f"Database '{name}' seeded.")
    print("Batches: " + ", ".join(f"{s} {n}" for s, n in rows))
    print(f"Deviations: {devs[0]} on {devs[1]} batches; audit trail entries: {audit}")


if __name__ == "__main__":
    main()
