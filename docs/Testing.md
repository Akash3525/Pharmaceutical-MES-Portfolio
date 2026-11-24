# Testing

There are 31 automated tests:
- **25 GMP rule tests** check the rules directly against PostgreSQL.
- **2 OPC UA tests** run the server end to end.
- **4 app tests** drive the Streamlit app headlessly with Streamlit's AppTest.

They run on every push through GitHub Actions (`.github/workflows/tests.yml`) against a fresh PostgreSQL 17 container.

The requirements, the traceability matrix and the protocol results are in [Validation.md](Validation.md).

## Run them

```bash
pytest -v
```

The tests build a separate database, `mes_portfolio_test`, from scratch and load the sample data into it, so they never touch your demo data.

## What is tested

| Area | Tests |
|---|---|
| Sample data | 12 batches in the expected states; exactly 3 with deliberate deviations |
| Dispensing | Quarantined lot refused · expired lot refused · wrong material refused · more than the stock on hand refused · second-person verification required, and the verifier can't be the dispenser · a dispensed weight can't be edited · out-of-tolerance weight raises a deviation |
| Execution | Steps refused before full dispensing and out of order · the last step completes the batch · out-of-limit value raises a deviation; an in-limit value doesn't |
| Process signals | An excursion raises exactly one deviation per tag |
| Audit trail | UPDATE, DELETE and TRUNCATE on the audit trail are refused · GMP records can't be deleted · inserts are logged with user and time · a change without a reason is refused · a change with a reason is logged with old and new values |
| Deviations | Only QA can close, and a resolution is required · a closed deviation can't be reopened |
| QA signature | Only QA can sign; operators and supervisors can't · a QA user who verified a dispense can't sign that batch · rejecting needs a reason · signatures can't be modified · an open deviation blocks release until QA closes it, after which the record is locked |
| Traceability | Genealogy traces a lot forward to batches and a batch back to its lots |
| Defence in depth | A raw SQL insert, bypassing the Python code, still hits the database rules |
| OPC UA | The server publishes all four tags within their limits, and the excursion switch pushes the dryer temperature above its alarm limit · with `--log-batch`, the excursion is logged to the batch and raises a deviation |
| App | The user picker offers operator, supervisor and QA users · all 8 pages render · the Dispensing page records a dispense and shows the database's refusal when there is no verifier · the Traceability page shows both directions |

## Example: a deliberately triggered deviation

`test_open_deviation_blocks_release_until_closed` runs a complete batch, then corrects the loss-on-drying value to 3.2 % with a reason. The limit is 2.5 %.

1. The database raises a STEP deviation automatically.
2. QA tries to release the batch → **refused: open deviations**.
3. A supervisor tries to close the deviation → **refused: only QA**.
4. QA closes it with a resolution, then releases the batch → **RELEASED**.
5. An operator tries to edit a step after release → **refused: record locked**.

## Latest local run

```
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
collected 31 items

Testing/test_app_ui.py::test_user_picker_offers_operator_supervisor_and_qa PASSED
Testing/test_app_ui.py::test_every_page_renders PASSED
Testing/test_app_ui.py::test_dispensing_page_records_a_released_lot_and_shows_database_refusals PASSED
Testing/test_app_ui.py::test_traceability_page_shows_both_directions PASSED
Testing/test_gmp_rules.py::test_seed_has_12_batches_and_3_with_deviations PASSED
Testing/test_gmp_rules.py::test_cannot_dispense_from_quarantined_lot PASSED
Testing/test_gmp_rules.py::test_cannot_dispense_from_expired_lot PASSED
Testing/test_gmp_rules.py::test_dispensing_requires_second_person_verification PASSED
Testing/test_gmp_rules.py::test_cannot_dispense_wrong_material PASSED
Testing/test_gmp_rules.py::test_cannot_dispense_more_than_stock_on_hand PASSED
Testing/test_gmp_rules.py::test_dispensed_weight_cannot_be_edited PASSED
Testing/test_gmp_rules.py::test_out_of_tolerance_dispense_raises_deviation PASSED
Testing/test_gmp_rules.py::test_steps_need_full_dispensing_and_run_in_order PASSED
Testing/test_gmp_rules.py::test_last_step_completes_the_batch PASSED
Testing/test_gmp_rules.py::test_out_of_limit_step_raises_deviation_and_in_limit_does_not PASSED
Testing/test_gmp_rules.py::test_signal_excursion_raises_one_deviation_per_tag PASSED
Testing/test_gmp_rules.py::test_audit_trail_is_append_only PASSED
Testing/test_gmp_rules.py::test_gmp_records_cannot_be_deleted PASSED
Testing/test_gmp_rules.py::test_change_without_reason_is_rejected PASSED
Testing/test_gmp_rules.py::test_change_with_reason_is_audited_with_old_and_new_value PASSED
Testing/test_gmp_rules.py::test_inserts_are_audited_with_user_and_time PASSED
Testing/test_gmp_rules.py::test_closing_a_deviation_needs_a_resolution_and_closed_is_final PASSED
Testing/test_gmp_rules.py::test_only_qa_can_sign PASSED
Testing/test_gmp_rules.py::test_rejecting_a_batch_needs_a_reason PASSED
Testing/test_gmp_rules.py::test_signatures_cannot_be_modified PASSED
Testing/test_gmp_rules.py::test_qa_cannot_sign_a_batch_they_executed PASSED
Testing/test_gmp_rules.py::test_open_deviation_blocks_release_until_closed PASSED
Testing/test_gmp_rules.py::test_genealogy_traces_lot_to_batches_and_back PASSED
Testing/test_gmp_rules.py::test_rule_violations_are_database_errors_not_app_checks PASSED
Testing/test_opcua_server.py::test_tags_are_published_and_excursion_breaches_limit PASSED
Testing/test_opcua_server.py::test_logged_excursion_raises_a_deviation_on_the_batch PASSED

============================= 31 passed in 15.31s =============================
```
