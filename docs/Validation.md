# Validation documents

> **Portfolio demonstration, not a validated GxP system.** This document shows how the requirements, tests and results of this project would be recorded in a validation package. It is not a completed validation package. The project runs on fictional data with a simulated user picker, and no formal validation (IQ/OQ/PQ), SOPs or change control exist for it.

The document set has five parts:

1. [Functional requirements specification](#1-functional-requirements-specification)
2. [Requirements traceability matrix](#2-requirements-traceability-matrix)
3. [Functional test protocol and results](#3-functional-test-protocol-and-results)
4. [Validation summary](#4-validation-summary)
5. [21 CFR Part 11 and EU Annex 11 concept mapping](#5-21-cfr-part-11-and-eu-annex-11-concept-mapping)

The approach is risk-based, in the spirit of GAMP 5 and computer software assurance. High-risk requirements are tested automatically on every push. The few requirements that are about the user interface are also covered by automated app tests.

**System under test**
- PostgreSQL 17 database with PL/pgSQL triggers ([schema.sql](../Pharmaceutical_MES/schema.sql))
- an 8-page Streamlit app
- a Python OPC UA server and viewer
- CSV exports to Power BI

**Execution environment:** Windows 11, PostgreSQL 17, Python 3.12.10, run on 2026-11-24. The same automated suite also runs in GitHub Actions on Ubuntu against a fresh `postgres:17` container.

## 1. Functional requirements specification

Each requirement is rated by its effect on product quality and data integrity. FR-27 to FR-30 are rules the database already enforced that were missing from the first draft of this list.

| ID | Requirement | Area | Risk |
|---|---|---|---|
| FR-01 | Dispensing accepts only lots with status RELEASED | Dispensing | High |
| FR-02 | Dispensing rejects expired lots | Dispensing | High |
| FR-03 | Dispensing rejects a lot of the wrong material for the recipe | Dispensing | High |
| FR-04 | Dispensing rejects a quantity larger than the stock on hand | Dispensing | Medium |
| FR-05 | Every dispense requires verification by a second person | Dispensing | High |
| FR-06 | The verifier cannot be the person who dispensed | Dispensing | High |
| FR-07 | Dispensed weights cannot be edited after entry | Dispensing | High |
| FR-08 | An out-of-tolerance dispensed weight raises a deviation automatically | Deviations | High |
| FR-09 | An out-of-limit step value raises a deviation automatically | Deviations | High |
| FR-10 | A process alarm raises a deviation automatically | Deviations | High |
| FR-11 | Only QA can close a deviation, and a resolution is required | Deviations | High |
| FR-12 | Steps can start only after full dispensing | Execution | High |
| FR-13 | Steps must run in recipe order | Execution | High |
| FR-14 | Completing the last step completes the batch | Execution | Medium |
| FR-15 | Batch records lock after disposition | Execution | High |
| FR-16 | Every insert and update is logged with old and new values, user and time | Audit trail | High |
| FR-17 | Every update requires a reason | Audit trail | High |
| FR-18 | The audit trail cannot be updated, deleted or truncated | Audit trail | High |
| FR-19 | Only QA can sign for batch release | E-signatures | High |
| FR-20 | Nobody can sign a batch they dispensed, verified or executed | E-signatures | High |
| FR-21 | Open deviations block release | E-signatures | High |
| FR-22 | Rejecting a batch requires a reason | E-signatures | Medium |
| FR-23 | The genealogy view traces a lot forward to batches and a batch back to its lots | Traceability | Medium |
| FR-24 | The OPC UA server publishes four simulated process tags | Process data | Low |
| FR-25 | A process excursion logged to the batch record raises a deviation | Process data | Medium |
| FR-26 | The app offers operator, supervisor and QA roles through a simulated user picker | Access | Medium |
| FR-27 | GMP records (lots, batches, dispenses, steps, deviations, signatures) cannot be deleted | Record protection | High |
| FR-28 | The rules hold for any client, including raw SQL that bypasses the app | Record protection | High |
| FR-29 | Electronic signatures cannot be modified once recorded | E-signatures | High |
| FR-30 | A closed deviation cannot be changed or reopened | Deviations | High |

## 2. Requirements traceability matrix

All 31 automated tests are in [Testing/](../Testing/):
- `test_gmp_rules.py`: 25 database rule tests
- `test_opcua_server.py`: 2 OPC UA tests
- `test_app_ui.py`: 4 app tests, which drive the Streamlit app headlessly with Streamlit's AppTest

| Req. | Protocol test | Automated test | Result |
|---|---|---|---|
| FR-01 | TC-01, TC-02 | `test_dispensing_page_records_a_released_lot_and_shows_database_refusals` · `test_cannot_dispense_from_quarantined_lot` | Pass |
| FR-02 | TC-03 | `test_cannot_dispense_from_expired_lot` | Pass |
| FR-03 | TC-04 | `test_cannot_dispense_wrong_material` | Pass |
| FR-04 | TC-05 | `test_cannot_dispense_more_than_stock_on_hand` | Pass |
| FR-05 | TC-06 | `test_dispensing_requires_second_person_verification` | Pass |
| FR-06 | TC-06 | `test_dispensing_requires_second_person_verification` | Pass |
| FR-07 | TC-07 | `test_dispensed_weight_cannot_be_edited` | Pass |
| FR-08 | TC-08 | `test_out_of_tolerance_dispense_raises_deviation` | Pass |
| FR-09 | TC-09 | `test_out_of_limit_step_raises_deviation_and_in_limit_does_not` | Pass |
| FR-10 | TC-10 | `test_signal_excursion_raises_one_deviation_per_tag` | Pass |
| FR-11 | TC-11 | `test_closing_a_deviation_needs_a_resolution_and_closed_is_final` · `test_open_deviation_blocks_release_until_closed` | Pass |
| FR-12 | TC-12 | `test_steps_need_full_dispensing_and_run_in_order` | Pass |
| FR-13 | TC-12 | `test_steps_need_full_dispensing_and_run_in_order` | Pass |
| FR-14 | TC-13 | `test_last_step_completes_the_batch` | Pass |
| FR-15 | TC-13 | `test_open_deviation_blocks_release_until_closed` (edit after release refused) | Pass |
| FR-16 | TC-14 | `test_inserts_are_audited_with_user_and_time` · `test_change_with_reason_is_audited_with_old_and_new_value` | Pass |
| FR-17 | TC-15 | `test_change_without_reason_is_rejected` | Pass |
| FR-18 | TC-15 | `test_audit_trail_is_append_only` | Pass |
| FR-19 | TC-16 | `test_only_qa_can_sign` | Pass |
| FR-20 | TC-16 | `test_qa_cannot_sign_a_batch_they_executed` | Pass |
| FR-21 | TC-17 | `test_open_deviation_blocks_release_until_closed` | Pass |
| FR-22 | TC-17 | `test_rejecting_a_batch_needs_a_reason` | Pass |
| FR-23 | TC-18 | `test_genealogy_traces_lot_to_batches_and_back` · `test_traceability_page_shows_both_directions` | Pass |
| FR-24 | TC-19 | `test_tags_are_published_and_excursion_breaches_limit` | Pass |
| FR-25 | TC-10 | `test_logged_excursion_raises_a_deviation_on_the_batch` | Pass |
| FR-26 | TC-20 | `test_user_picker_offers_operator_supervisor_and_qa` · `test_every_page_renders` | Pass |
| FR-27 | TC-21 | `test_gmp_records_cannot_be_deleted` | Pass |
| FR-28 | TC-21 | `test_rule_violations_are_database_errors_not_app_checks` | Pass |
| FR-29 | TC-22 | `test_signatures_cannot_be_modified` | Pass |
| FR-30 | TC-11 | `test_closing_a_deviation_needs_a_resolution_and_closed_is_final` | Pass |

`test_seed_has_12_batches_and_3_with_deviations` checks that the test data is set up correctly. It isn't linked to a requirement.

## 3. Functional test protocol and results

Each case was run against the seeded test database (`mes_portfolio_test`, 12 fictional batches), and each result records how it was executed:
- **Auto:** the case's automated test passed.
- **Manual:** the case was also run by hand, and the output is shown under the table.

Steps that need a second user switch users in the simulated user picker, or pass a different username in the test.

| ID | Objective | Steps | Expected result | Actual result | Pass/Fail |
|---|---|---|---|---|---|
| TC-01 | Released lot can be dispensed | In the Dispensing page, as operator Ravi Patel, dispense a RELEASED, unexpired lot of the right material, verified by Maria Garcia | Dispense is recorded | App shows "Dispense recorded."; one dispensing row exists for the batch (Auto) | Pass |
| TC-02 | Unreleased lot is rejected | Dispense from quarantined lot L24-PCM-003 | Database rejects it | Refused: "...only RELEASED lots can be dispensed" (Auto) | Pass |
| TC-03 | Expired lot is rejected | Dispense from expired lot L23-MCC-009 | Database rejects it | Refused: "Lot L23-MCC-009 expired on ..." (Auto) | Pass |
| TC-04 | Wrong material is rejected | Dispense ibuprofen API into a paracetamol batch; dispense starch using a magnesium stearate lot | Database rejects both | Refused: "...is not in the recipe..." and "...is not the requested material" (Auto) | Pass |
| TC-05 | Insufficient stock is rejected | Dispense 5,000 kg from lot L24-MCC-002 | Database rejects it | Refused: "Lot L24-MCC-002 has only ... available" (Auto) | Pass |
| TC-06 | Second-person verification | Dispense with no verifier, then with the dispenser as verifier, then with a different operator | First two refused; third accepted | Refused: "requires second-person verification" (also shown in the app) and "must be a different person"; accepted with op.garcia (Auto) | Pass |
| TC-07 | Dispensed weight cannot be edited | Update a recorded dispensed weight, with a reason | Update is blocked | Refused: "Dispensed quantities and lots cannot be edited; raise a deviation instead" (Auto) | Pass |
| TC-08 | Out-of-tolerance weight raises deviation | Dispense 1.10 kg magnesium stearate (target 1.0 kg, ±5 %) | A deviation is created automatically | One open DISPENSING deviation (Auto) | Pass |
| TC-09 | Out-of-limit step value raises deviation | Record impeller speed 280 rpm (limits 150-250); record an in-limit value | Deviation for the out-of-limit value only | One STEP deviation; none for the in-limit value (Auto) | Pass |
| TC-10 | Process alarm raises deviation | Start the OPC UA server with `--log-batch`, turn the excursion switch on | A deviation is created and linked to the batch | One PROCESS_SIGNAL deviation on the batch (Auto + Manual, output 1) | Pass |
| TC-11 | Only QA closes deviations; closed is final | Close a deviation as operator; as QA with a blank resolution; as QA with a resolution; then try to reopen it | First two refused; third succeeds; reopen refused | Refused: "Only an active QA user...", "A resolution is required..."; closed by qa.okafor; reopen refused: "...is closed and cannot be changed" (Auto) | Pass |
| TC-12 | Step order and dispensing gate | Record step 1 before any dispensing, with 1 of 5 materials, then step 2 before step 1 | All refused | Refused: "steps cannot be executed", "4 material(s) not yet dispensed", "Step 1 must be completed before step 2" (Auto) | Pass |
| TC-13 | Batch completion and record lock | Dispense all, record step 1, record remaining steps; after release, edit a step | Status moves DISPENSING → IN_PROGRESS → COMPLETED; edit after release refused | Statuses as expected, `completed_at` set; edit refused: "...its record is locked" (Auto) | Pass |
| TC-14 | Audit trail captures changes | Create a batch; correct a step value with a reason; read the audit trail | Entries show user, time, and old and new values | INSERT by sup.chen with timestamp; UPDATE by op.garcia, reason recorded, 7.5 → 8 (Auto) | Pass |
| TC-15 | Reason required and trail immutable | Correct a step without a reason; UPDATE, DELETE and TRUNCATE the audit trail | All refused | Refused: "A reason for change is required..."; all three refused: "The audit trail is append-only" (Auto) | Pass |
| TC-16 | E-signature restrictions | Sign as operator; as supervisor; as QA who verified a dispense; as independent QA | Only the independent QA signature is accepted | First three refused; qa.okafor accepted (Auto) | Pass |
| TC-17 | Release gating | Release a batch with an open deviation; reject without a reason; reject with a reason | Release blocked; rejection without reason refused; with reason accepted | Refused: "...has open deviations...", "A reason is required to reject a batch"; status REJECTED with reason (Auto) | Pass |
| TC-18 | Genealogy | Traceability page: forward for a lot, backward for a batch; also query the view | Lot shows batches that used it; batch shows its lots | Both tabs show rows; a new batch traces back to 5 lots and its API lot traces forward to several batches (Auto) | Pass |
| TC-19 | OPC UA tags | Start the server and viewer; switch the excursion on | Four tags show live values; dryer temperature flagged ALARM | Four tags within limits; FBD-201/TIC-201 rose to about 73 °C and was flagged ALARM (Auto + Manual, output 1) | Pass |
| TC-20 | Simulated user picker and pages | Open the app; list the user picker options; open every page | Operator, supervisor and QA users are offered; all 8 pages load | Picker labelled "Signed in as (simulated)" lists OPERATOR, SUPERVISOR and QA users; all 8 pages render without errors (Auto) | Pass |
| TC-21 | Record protection | DELETE a step execution; insert a dispense with raw SQL and no verifier | Both refused by the database | Refused: "GMP records in step_executions cannot be deleted"; raw insert refused: "requires second-person verification" (Auto) | Pass |
| TC-22 | Signatures are final | Change the meaning of a recorded signature | Refused | Refused: "Electronic signatures cannot be modified" (Auto) | Pass |

### Output 1: TC-10 and TC-19 run by hand

The server was started against the test database with `--port 4850 --log-batch PCM-500-0030 --log-every 1`. The viewer was then run with the excursion switch off, then on:

```
time          GRAN-101/TIC-101/PV.CV    GRAN-101/SIC-102/PV.CV     FBD-201/TIC-201/PV.CV      FBD-201/MT-202/PV.CV
------------------------------------------------------------------------------------------------------------------
15:44:28           31.24 degC               197.51 rpm                 62.49 degC                25.06 %RH
Excursion switched on
15:44:29           32.15 degC               192.45 rpm                 62.58 degC                23.57 %RH
15:44:30           31.79 degC               193.22 rpm                 72.64 degC  ALARM         23.83 %RH
15:44:31           32.13 degC               191.76 rpm                 73.35 degC  ALARM         23.96 %RH
```

The batch then had one open deviation, raised by the database trigger:

```
PROCESS_SIGNAL | OPEN | FBD-201/TIC-201/PV.CV (Fluid bed dryer inlet air temperature) = 72.80 degC, alarm limits 55 to 70
```

The deviation is raised once per tag, so the further readings above the limit were covered by the open deviation. 72 signal rows were logged.

### Automated run

```
$ pytest -v
...
============================= 31 passed in 15.31s =============================
```

The full list of test names is in [Testing.md](Testing.md).

## 4. Validation summary

**Result:**
- All 30 requirements are covered, and all 22 protocol cases passed.
- All 31 automated tests pass, both locally and in GitHub Actions.
- TC-10 and TC-19 were also run by hand.
- No test failures remain open.

**Issues found during development (all fixed before this run).** These came from building and using the app. They were not found by this protocol:
- The app froze because Streamlit runs shared one database connection.
- The batch picker showed an out-of-date status after a batch changed state.
- Newly created batches were missing from the Process Signals page.
- A caption wrongly said there was no OPC UA server.

**Gaps found while writing this protocol, and how they were closed:**
- 9 database tests were added, for FR-03, FR-04, FR-07, FR-11, FR-14, FR-16 (insert), FR-22, FR-29 and FR-30.
- 1 OPC UA end-to-end test was added, for FR-25.
- 4 app tests were added, for TC-01, TC-18 and TC-20.

**Limitations of the simulation:**
- The user picker simulates login. There are no passwords, identity management or session controls.
- Process data comes from a Python simulator, not a real DCS.
- The data is fictional. The system has not been through IQ/OQ/PQ, supplier assessment, SOPs or change control.
- Records are not archived or backed up the way a production system's would be.
- The OPC UA server runs without security (anonymous, no encryption) and listens only on this computer.

**Conclusion:** the project meets its stated functional requirements, as shown by the results above. It is suitable as a portfolio demonstration. **It is not validated for GxP use.**

## 5. 21 CFR Part 11 and EU Annex 11 concept mapping

This table shows which regulatory ideas the project mirrors and what a real system would still need. It is a learning aid, not a compliance claim.

| Concept | Reference | In this project | Gap in a real system |
|---|---|---|---|
| Audit trail | Part 11 §11.10(e); Annex 11 clause 9 | Append-only log with old and new values, user, time and reason (FR-16 to FR-18) | Secure time source, retention and periodic review procedures |
| Electronic signatures | Part 11 §11.50, §11.70, §11.200; Annex 11 clause 14 | QA-only signing, tied to the batch record and unchangeable once recorded (FR-19, FR-20, FR-29) | Two-component authentication and signature manifestation controls |
| Access control | Part 11 §11.10(d), §11.10(g); Annex 11 clause 12 | Role checks for operator, supervisor and QA in the database (FR-11, FR-19, FR-26) | Real identity management, password policy and account reviews |
| Record protection | Part 11 §11.10(c); Annex 11 clause 7 | Records lock after disposition and cannot be edited or deleted, whatever client writes to the database (FR-07, FR-15, FR-27, FR-28) | Backup, archiving and restore testing |
| System validation | Part 11 §11.10(a); Annex 11 clause 4 | This document set and the automated tests | Full validation plan, IQ/OQ/PQ, change control and periodic evaluation |
| Batch release | Annex 11 clause 15 | Release blocked by open deviations and by unauthorised signers (FR-20, FR-21) | Qualified person or QA release procedure |
