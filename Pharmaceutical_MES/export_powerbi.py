"""Export the three reporting views to CSV for the Power BI report.

Usage:  python Pharmaceutical_MES/export_powerbi.py
Writes powerbi/data/*.csv. Timestamps are written as local time without offset
so Power BI reads them as Date/Time.
"""
import csv

import db

OUT = db.ROOT / "powerbi" / "data"
TS = "to_char({0}, 'YYYY-MM-DD HH24:MI:SS') AS {0}"

EXPORTS = {
    "batch_progress.csv": f"""
        SELECT batch_no, product_code, product_name, recipe_version, status, materials_required,
               materials_dispensed, steps_total, steps_done, open_deviations, total_deviations, pct_complete,
               {TS.format('created_at')}, {TS.format('started_at')}, {TS.format('completed_at')},
               {TS.format('disposition_at')}
        FROM v_batch_progress ORDER BY batch_no""",
    "review_by_exception.csv": f"""
        SELECT batch_no, batch_status, exception_type, severity, detail, {TS.format('occurred_at')}
        FROM v_review_by_exception ORDER BY batch_no, occurred_at""",
    "genealogy.csv": f"""
        SELECT lot_no, material_code, material_name, supplier, lot_status, expiry_date, batch_no,
               product_code, product_name, batch_status, qty_used, uom, {TS.format('dispensed_at')}
        FROM v_genealogy ORDER BY lot_no, batch_no""",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with db.connect() as conn:
        for name, query in EXPORTS.items():
            cur = conn.execute(query)
            with (OUT / name).open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([c.name for c in cur.description])
                rows = cur.fetchall()
                w.writerows(rows)
            print(f"wrote powerbi/data/{name} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
