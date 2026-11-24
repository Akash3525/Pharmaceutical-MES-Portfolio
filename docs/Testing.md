# Testing

18 automated tests: 17 check the GMP rules directly against PostgreSQL, and 1 is an end-to-end test of the OPC UA server. They run on every push through GitHub Actions (`.github/workflows/tests.yml`) against a fresh PostgreSQL 17 container.

## Run them

```bash
pytest -v
```

The tests build a separate database, `mes_portfolio_test`, from scratch and load the sample data into it, so they never touch your demo data.

## What is tested

| Area | Tests |
|---|---|
| Sample data | 12 batches in the expected states; exactly 3 with deliberate deviations |
| Dispensing | Quarantined lot refused · expired lot refused · second-person verification required, and the verifier cannot be the dispenser · out-of-tolerance weight raises a deviation |
| Execution | Steps refused before full dispensing and out of order · out-of-limit value raises a deviation; an in-limit value does not |
| Process signals | An excursion raises exactly one deviation per tag |
| Audit trail | UPDATE, DELETE and TRUNCATE on the audit trail are refused · GMP records cannot be deleted · a change without a reason is refused · a change with a reason is logged with old and new values |
| QA signature | Only QA can sign · a QA user who verified a dispense cannot sign that batch · an open deviation blocks release until QA closes it, after which the record is locked |
| Traceability | Genealogy traces a lot forward to batches and a batch back to its lots |
| Defence in depth | A raw SQL insert, bypassing the Python code, still hits the database rules |
| OPC UA | The server publishes all four tags within their limits, and the excursion switch pushes the dryer temperature above its alarm limit |

## Example: a deliberately triggered deviation

`test_open_deviation_blocks_release_until_closed` runs a complete batch, then corrects the loss-on-drying value to 3.2 % (limit 2.5 %) with a reason:

1. The database raises a STEP deviation automatically.
2. QA tries to release the batch → **refused: open deviations**.
3. A supervisor tries to close the deviation → **refused: only QA**.
4. QA closes it with a resolution, then releases the batch → **RELEASED**.
5. An operator tries to edit a step after release → **refused: record locked**.

## Latest local run

```
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
collected 18 items

Testing/test_gmp_rules.py::test_seed_has_12_batches_and_3_with_deviations PASSED
Testing/test_gmp_rules.py::test_cannot_dispense_from_quarantined_lot PASSED
Testing/test_gmp_rules.py::test_cannot_dispense_from_expired_lot PASSED
Testing/test_gmp_rules.py::test_dispensing_requires_second_person_verification PASSED
Testing/test_gmp_rules.py::test_out_of_tolerance_dispense_raises_deviation PASSED
Testing/test_gmp_rules.py::test_steps_need_full_dispensing_and_run_in_order PASSED
Testing/test_gmp_rules.py::test_out_of_limit_step_raises_deviation_and_in_limit_does_not PASSED
Testing/test_gmp_rules.py::test_signal_excursion_raises_one_deviation_per_tag PASSED
Testing/test_gmp_rules.py::test_audit_trail_is_append_only PASSED
Testing/test_gmp_rules.py::test_gmp_records_cannot_be_deleted PASSED
Testing/test_gmp_rules.py::test_change_without_reason_is_rejected PASSED
Testing/test_gmp_rules.py::test_change_with_reason_is_audited_with_old_and_new_value PASSED
Testing/test_gmp_rules.py::test_only_qa_can_sign PASSED
Testing/test_gmp_rules.py::test_qa_cannot_sign_a_batch_they_executed PASSED
Testing/test_gmp_rules.py::test_open_deviation_blocks_release_until_closed PASSED
Testing/test_gmp_rules.py::test_genealogy_traces_lot_to_batches_and_back PASSED
Testing/test_gmp_rules.py::test_rule_violations_are_database_errors_not_app_checks PASSED
Testing/test_opcua_server.py::test_tags_are_published_and_excursion_breaches_limit PASSED

============================= 18 passed in 7.04s ==============================
```
