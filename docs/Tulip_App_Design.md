# Tulip App Design (spec only, not built)

**Status: Planned.** This is a design spec for a Tulip front end on the same PostgreSQL back end.
No Tulip app has been built.
Only describe Tulip as "Built" on a resume after it exists.

## Goal

Give operators a touch-friendly shop-floor UI for dispensing and step execution.
QA review, traceability and the audit trail stay in the Streamlit app.
Because the GMP rules live in the database, the Tulip app needs no rule logic of its own.

## Integration

- **Tulip Connector** (HTTP to a small REST layer, or a direct SQL connector) calling the same operations as `mes.py`.
- Each connector function runs in one transaction that sets `mes.user` to the Tulip logged-in user and, for corrections, `mes.reason`.
- Error handling: show the database's `message_primary` text, for example *"Lot L24-PCM-003 has status QUARANTINE: only RELEASED lots can be dispensed"*.

| Connector function | SQL / operation | Inputs | Output |
|---|---|---|---|
| `get_open_batches` | `SELECT … FROM v_batch_progress WHERE status IN ('CREATED','DISPENSING','IN_PROGRESS')` | none | batch list |
| `get_materials_to_dispense` | as in `mes.materials_to_dispense` | batch_id | material, target, tolerance |
| `get_lot_by_barcode` | `SELECT … FROM material_lots WHERE lot_no = $1` | scanned lot_no | lot, status, expiry |
| `record_dispense` | `INSERT INTO dispensing …` | batch, material, lot, weight, verifier badge | dispense_id or error |
| `get_next_step` | as in `mes.next_step` | batch_id | instruction, limits |
| `record_step` | `INSERT INTO step_executions …` | batch, step, value | exec_id or error |

## Apps and steps

**App 1: Dispensing**
1. *Select batch*: interactive table of open batches.
2. *Scan lot*: barcode scanner input, which shows the lot status and expiry before weighing.
3. *Weigh*: scale device input (Tulip edge device) fills the actual weight, with manual entry as a fallback. A gauge shows target ± tolerance.
4. *Verify*: a second operator scans their badge. The app blocks the same badge as the dispenser, and the database enforces it too.
5. *Confirm*: call `record_dispense`, show success or the database error, then loop to the next material.

**App 2: Step Execution**
1. *Select batch*, then *Show next step* with instruction text, an image or video, and the limits.
2. *Enter value*: number input with a colour indicator (in limits or out of limits). Out-of-limit values are allowed and raise a deviation automatically.
3. *Complete*: call `record_step`. After the last step, show "Batch complete: waiting for QA".

## Tulip tables (optional)

Use a Tulip table for UI state only, such as the current batch per station. Do not put batch records in it, because PostgreSQL stays the single system of record.

## Analytics

Tulip analytics on step durations per station, or use the Power BI views listed in the README.

## Build checklist (when you build it)

- [ ] REST layer or SQL connector with a service account. Set `mes.user` per call and do not use the service account name as the user.
- [ ] Dispensing app with scale and scanner devices
- [ ] Step execution app
- [ ] Screenshots or a short video in the README
- [ ] Only then change the resume from "Planned" to "Built"
