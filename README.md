# Pharmaceutical MES Portfolio

Simulated pharmaceutical MES and electronic batch record system (Python, Streamlit, PostgreSQL) with audit trail, deviation handling and QA review. Learning project, not a validated GxP system.

> All products, lots, suppliers and people are fictional. Process signals come from a Python simulator, not a real DCS or OPC UA connection.

## Highlights

**GMP rules live in the database.** PostgreSQL triggers enforce them, so they apply whichever front end writes the data, whether that is Streamlit, a script, a test or a future Tulip app.

| Area | Rule enforced by PostgreSQL |
|---|---|
| **Dispensing** | Lot must be RELEASED, unexpired, the right material and have enough stock. A second person must verify, and the verifier cannot be the dispenser. Dispensed quantities cannot be edited. |
| **Deviations** | An out-of-tolerance weight, an out-of-limit step value or a process alarm raises a deviation automatically. Only QA can close one, and a resolution is required. |
| **Execution** | Steps run only after full dispensing, and in recipe order. The last step completes the batch. Records lock after QA disposition. |
| **Audit trail** | Every insert and update is logged with old and new values, user and time. Updates require a reason. The trail cannot be updated, deleted or truncated, and GMP records cannot be deleted. |
| **Signatures** | Only QA can sign. Nobody can sign a batch they dispensed, verified or executed. Open deviations block release, and rejecting a batch requires a reason. |
| **Traceability** | Material genealogy view traces a lot forward to batches, or a batch back to its lots. |

## The app (8 pages)

| Page | What it does |
|---|---|
| Batch Overview | Status, progress and open deviations for every batch |
| Create Batch | Pick an approved master recipe and see its BOM and steps |
| Dispensing | Weigh against target and tolerance, with first-expiry-first-out lot suggestion and second-person verification |
| Step Execution | Guided steps with limits, plus corrections that require a reason |
| Review by Exception | QA sees only deviations, changed records and alarms, then closes deviations and signs |
| Traceability | Forward and backward genealogy |
| Process Signals | Simulated DeltaV-style tag trends, with a button to generate data and an optional excursion |
| Audit Trail | Filterable, append-only log with old and new JSON |

The **"Signed in as"** picker simulates login so you can switch between operator, supervisor and QA. It is not real authentication.

## Sample data

`seed.py` loads 12 fictional batches of two products (paracetamol 500 mg and ibuprofen 200 mg tablets):

- 5 released by QA
- 2 complete and waiting for QA, with no exceptions
- **3 complete with a deliberate deviation for a reviewer to find:**
  - magnesium stearate dispensed 8 % over target (tolerance 5 %)
  - loss on drying 3.1 % against a limit of 2.5 %, plus a later corrected tablet-weight entry with its reason
  - dryer inlet air temperature excursion to about 73 °C (alarm limit 70 °C)
- 1 in progress, 1 just created

The lots include a quarantined, a rejected and an expired lot, so you can watch the database refuse them.

## Project structure

```
Pharmaceutical_MES/
  schema.sql     tables, GMP triggers, views
  app.py         Streamlit UI (8 pages)
  mes.py         thin write helpers shared by app, seed and tests
  seed.py        creates the database and loads the sample data
  simulator.py   DeltaV-style process signal simulator
  db.py          connection settings (MES_DB_* variables)
Testing/
  test_gmp_rules.py   17 tests, one or more per rule
docs/
  Architecture.md     rule map, batch lifecycle, design decisions
  Tulip_App_Design.md design spec (not built)
  PowerBI_Guide.md    dashboard plan and DAX (not built)
```

## Run it

Requires Python 3.10+ and PostgreSQL 14+.

```bash
python -m venv .venv
.venv\Scripts\activate             # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env             # then set MES_DB_PASSWORD

python Pharmaceutical_MES/seed.py  # creates the mes_portfolio database if needed and loads sample data
pytest -v                          # uses a separate mes_portfolio_test database
streamlit run Pharmaceutical_MES/app.py
```

Generate more process data for a batch from the command line:

```bash
python Pharmaceutical_MES/simulator.py PCM-500-0007 --minutes 30 --excursion
```

**Windows note:** if the `psycopg-binary` DLL is blocked (for example by Smart App Control), set `PSYCOPG_IMPL=python` in `.env`. `db.py` then uses `libpq.dll` from the local PostgreSQL install.

## Not built yet

- **Power BI dashboard**: connect to `v_batch_progress`, `v_review_by_exception` and `v_genealogy`. See the [Power BI Guide](docs/PowerBI_Guide.md).
- **Tulip app**: design spec only, see [Tulip App Design](docs/Tulip_App_Design.md). The status is *Planned*.
- **OPC UA server** for the simulator: not built. Signals are written directly to the database.

## Skills demonstrated

PostgreSQL (PL/pgSQL triggers, constraints, JSONB audit, views) · Python · Streamlit · pytest · GMP and data-integrity concepts (ALCOA+, 21 CFR Part 11-style audit trail and e-signatures, second-person verification, review by exception, genealogy) · MES and ISA-88 batch concepts (master recipe, dispensing, step execution, disposition)
