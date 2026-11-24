# Architecture

## Design principle: rules in the database

All GMP rules are PostgreSQL triggers and constraints, not Python `if` statements in the user interface.
The Streamlit app, the seed script, the tests and a future Tulip app all write to the same tables, so none of them can skip a rule.
A test proves this by writing straight to the table with SQL, with no Python service layer, and checking that the database still rejects the record.

```
 ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐
 │ Streamlit UI │  │   seed.py    │  │ pytest suite │  │ Tulip (design │
 │   (app.py)   │  │              │  │              │  │  spec only)   │
 └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬────────┘
        └─────────────────┴─────────┬───────┴─────────────────┘
                                    │  mes.py (thin write helpers)
                                    ▼  SET mes.user / mes.reason per transaction
 ┌───────────────────────────────────────────────────────────────────────┐
 │ PostgreSQL                                                            │
 │  tables ── triggers (dispensing, steps, signals, signatures, audit) ──│
 │  views: v_batch_progress · v_review_by_exception · v_genealogy        │
 └───────────────────────────────────────────────────────────────────────┘
        ▲                                                     │
        │ simulator.py (DeltaV-style tag values)              ▼
                                                      Power BI (not built)
```

## Session context

Each write runs in one transaction that first sets two settings:

```sql
SELECT set_config('mes.user',   'op.patel', true);   -- who is acting
SELECT set_config('mes.reason', '...',      true);   -- why, for updates
```

`true` makes them local to the transaction, so they cannot leak into the next one.
The audit trigger reads both.
An update without a reason is rejected, unless another trigger made it.
For example, a signature moves the batch to RELEASED.
Those updates are recorded as `System: automatic status update` (detected with `pg_trigger_depth() > 1`).

## Rule map

| Rule | Where |
|---|---|
| Lot must be RELEASED, unexpired, the right material and have enough stock | `trg_dispense_before` |
| Second-person verification, verifier ≠ dispenser | `trg_dispense_before` |
| Out-of-tolerance weight → deviation; lot stock decremented | `trg_dispense_after` |
| Dispensed lots and quantities cannot be edited | `trg_dispense_locked` |
| Steps only after full dispensing, in order | `trg_step_before` |
| Out-of-limit value → deviation; last step completes the batch | `trg_step_after` |
| Steps locked after disposition | `trg_step_before` (UPDATE) |
| Signal outside alarm limits → one deviation per batch and tag | `trg_signal_after` |
| Only QA closes deviations, and a resolution is required; closed deviations are frozen | `trg_deviation_update` |
| Only QA signs; no one who dispensed, verified or executed; batch complete; no open deviations to release; reason to reject | `trg_signature_before` |
| Signature sets the batch to RELEASED or REJECTED; signatures are immutable | `trg_signature_after`, `trg_signature_immutable` |
| Every insert and update on GMP tables is audited with old and new JSON | `trg_audit` |
| Reason required for user updates | `trg_audit` |
| Audit trail cannot be updated, deleted or truncated | `audit_append_only`, `audit_no_truncate` |
| GMP records cannot be deleted | `trg_forbid_delete` |

## Batch lifecycle

```
CREATED ─(first dispense)→ DISPENSING ─(first step)→ IN_PROGRESS ─(last step)→ COMPLETED
                                                                                 │
                                          QA signature (RELEASE / REJECT) ───────┤
                                                                                 ▼
                                                                    RELEASED / REJECTED (locked)
```

The triggers move a batch from one status to the next. No code updates `batches.status` directly.

## Views

- **`v_batch_progress`**: dispensed materials and executed steps against the recipe, open deviations and percent complete. Feeds the overview page and Power BI.
- **`v_review_by_exception`**: deviations, records changed after entry (with reason), and process alarms. QA reviews these instead of every entry.
- **`v_genealogy`**: one row per lot used in each batch. Filter by lot to trace forward, or by batch to trace backward.

## Simulated signals

`simulator.py` generates values for four DeltaV-style tags, such as `FBD-201/TIC-201/PV.CV`, as a mean-reverting random walk around a setpoint.
`opcua_server.py` publishes these tags over OPC UA, as a DCS would, and can log them into `process_signals` for a chosen batch. `opcua_viewer.py` is a minimal OPC UA client.
No real DCS or historian is involved.
In a real system, a SCADA or MES client (for example Ignition) or a historian interface such as PI or DeltaV Continuous Historian would read the tags and write the same `process_signals` rows.

## What a real system would add

- Real authentication with password or SSO re-entry at signature time (21 CFR Part 11 §11.200), instead of the simulated user picker.
- Recipe versioning and approval workflow, and equipment status and cleaning logs.
- Computer system validation: URS, risk assessment, IQ/OQ/PQ and a traceability matrix.
- Time synchronisation and database-level protection of the audit trail from superusers.
