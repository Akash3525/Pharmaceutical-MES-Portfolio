-- Pharmaceutical MES / electronic batch record: PostgreSQL schema.
--
-- The GMP rules live in the database, not in the user interface, so they apply
-- whichever front end (Streamlit, Tulip, a script) writes the data.
--
-- Session context. The application sets these at the start of each transaction:
--   SELECT set_config('mes.user',   '<username>', true);
--   SELECT set_config('mes.reason', '<reason for change>', true);
--
-- Learning project. Not a validated GxP system.

DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;

---------------------------------------------------------------- master data
CREATE TABLE app_users (
    user_id    serial PRIMARY KEY,
    username   text UNIQUE NOT NULL,
    full_name  text NOT NULL,
    role       text NOT NULL CHECK (role IN ('OPERATOR', 'SUPERVISOR', 'QA', 'ADMIN')),
    active     boolean NOT NULL DEFAULT true
);

CREATE TABLE materials (
    material_id  serial PRIMARY KEY,
    code         text UNIQUE NOT NULL,
    name         text NOT NULL,
    uom          text NOT NULL DEFAULT 'kg'
);

CREATE TABLE material_lots (
    lot_id         serial PRIMARY KEY,
    lot_no         text UNIQUE NOT NULL,
    material_id    int NOT NULL REFERENCES materials,
    supplier       text NOT NULL,
    status         text NOT NULL CHECK (status IN ('QUARANTINE', 'RELEASED', 'REJECTED')),
    expiry_date    date NOT NULL,
    qty_received   numeric(12,3) NOT NULL CHECK (qty_received > 0),
    qty_available  numeric(12,3) NOT NULL CHECK (qty_available >= 0),
    received_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE products (
    product_id  serial PRIMARY KEY,
    code        text UNIQUE NOT NULL,
    name        text NOT NULL
);

CREATE TABLE recipes (
    recipe_id   serial PRIMARY KEY,
    product_id  int NOT NULL REFERENCES products,
    version     int NOT NULL,
    name        text NOT NULL,
    batch_size  numeric(12,3) NOT NULL,
    batch_uom   text NOT NULL DEFAULT 'kg',
    status      text NOT NULL DEFAULT 'APPROVED' CHECK (status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    UNIQUE (product_id, version)
);

CREATE TABLE recipe_materials (
    recipe_id      int NOT NULL REFERENCES recipes,
    material_id    int NOT NULL REFERENCES materials,
    qty_per_batch  numeric(12,3) NOT NULL CHECK (qty_per_batch > 0),
    tolerance_pct  numeric(5,2) NOT NULL DEFAULT 2.0,
    PRIMARY KEY (recipe_id, material_id)
);

CREATE TABLE recipe_steps (
    recipe_id       int NOT NULL REFERENCES recipes,
    step_no         int NOT NULL,
    instruction     text NOT NULL,
    parameter_name  text NOT NULL,
    unit            text NOT NULL,
    lower_limit     numeric NOT NULL,
    upper_limit     numeric NOT NULL,
    PRIMARY KEY (recipe_id, step_no),
    CHECK (lower_limit <= upper_limit)
);

-- Alarm limits for simulated DCS tags (DeltaV-style names).
CREATE TABLE tag_limits (
    tag          text PRIMARY KEY,
    description  text NOT NULL,
    unit         text NOT NULL,
    low_limit    numeric NOT NULL,
    high_limit   numeric NOT NULL
);

---------------------------------------------------------------- execution
CREATE TABLE batches (
    batch_id      serial PRIMARY KEY,
    batch_no      text UNIQUE NOT NULL,
    recipe_id     int NOT NULL REFERENCES recipes,
    status        text NOT NULL DEFAULT 'CREATED'
                  CHECK (status IN ('CREATED', 'DISPENSING', 'IN_PROGRESS', 'COMPLETED', 'RELEASED', 'REJECTED')),
    created_by    int NOT NULL REFERENCES app_users,
    created_at    timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    completed_at  timestamptz,
    disposition_at timestamptz
);

CREATE TABLE dispensing (
    dispense_id   serial PRIMARY KEY,
    batch_id      int NOT NULL REFERENCES batches,
    material_id   int NOT NULL REFERENCES materials,
    lot_id        int NOT NULL REFERENCES material_lots,
    target_qty    numeric(12,3),
    actual_qty    numeric(12,3) NOT NULL CHECK (actual_qty > 0),
    dispensed_by  int NOT NULL REFERENCES app_users,
    verified_by   int REFERENCES app_users,
    dispensed_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (batch_id, material_id)
);

CREATE TABLE step_executions (
    exec_id         serial PRIMARY KEY,
    batch_id        int NOT NULL REFERENCES batches,
    step_no         int NOT NULL,
    recorded_value  numeric NOT NULL,
    executed_by     int NOT NULL REFERENCES app_users,
    executed_at     timestamptz NOT NULL DEFAULT now(),
    comment         text,
    UNIQUE (batch_id, step_no)
);

CREATE TABLE process_signals (
    signal_id  bigserial PRIMARY KEY,
    batch_id   int NOT NULL REFERENCES batches,
    tag        text NOT NULL REFERENCES tag_limits,
    value      numeric NOT NULL,
    quality    text NOT NULL DEFAULT 'GOOD',
    ts         timestamptz NOT NULL
);

CREATE TABLE deviations (
    deviation_id  serial PRIMARY KEY,
    batch_id      int NOT NULL REFERENCES batches,
    source        text NOT NULL CHECK (source IN ('DISPENSING', 'STEP', 'PROCESS_SIGNAL', 'MANUAL')),
    severity      text NOT NULL CHECK (severity IN ('MINOR', 'MAJOR', 'CRITICAL')),
    description   text NOT NULL,
    status        text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    raised_by     text NOT NULL,
    raised_at     timestamptz NOT NULL DEFAULT now(),
    closed_by     int REFERENCES app_users,
    closed_at     timestamptz,
    resolution    text
);

CREATE TABLE batch_signatures (
    signature_id  serial PRIMARY KEY,
    batch_id      int NOT NULL REFERENCES batches,
    signed_by     int NOT NULL REFERENCES app_users,
    meaning       text NOT NULL CHECK (meaning IN ('RELEASE', 'REJECT')),
    reason        text,
    signed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_trail (
    audit_id    bigserial PRIMARY KEY,
    table_name  text NOT NULL,
    record_id   text NOT NULL,
    action      text NOT NULL,
    old_data    jsonb,
    new_data    jsonb,
    changed_by  text NOT NULL,
    reason      text,
    changed_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX ON dispensing (lot_id);
CREATE INDEX ON process_signals (batch_id, tag, ts);
CREATE INDEX ON deviations (batch_id);
CREATE INDEX ON audit_trail (table_name, record_id);

---------------------------------------------------------------- helpers
CREATE FUNCTION mes_session_user() RETURNS text LANGUAGE sql STABLE AS $$
    SELECT coalesce(nullif(current_setting('mes.user', true), ''), session_user::text)
$$;

CREATE FUNCTION mes_role_of(p_user_id int) RETURNS text LANGUAGE sql STABLE AS $$
    SELECT role FROM app_users WHERE user_id = p_user_id AND active
$$;

---------------------------------------------------------------- audit trail
-- Every insert and update on a GMP table is copied to audit_trail.
-- A direct UPDATE needs a reason (mes.reason). Updates made by another
-- trigger (pg_trigger_depth() > 1) are system actions and are labelled so.
CREATE FUNCTION trg_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_reason text := nullif(btrim(current_setting('mes.reason', true)), '');
    v_pk     text := TG_ARGV[0];
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF to_jsonb(NEW) = to_jsonb(OLD) THEN
            RETURN NEW;
        END IF;
        IF pg_trigger_depth() > 1 THEN
            v_reason := 'System: automatic status update';
        ELSIF v_reason IS NULL THEN
            RAISE EXCEPTION 'A reason for change is required to modify % record %',
                TG_TABLE_NAME, to_jsonb(NEW) ->> v_pk
                USING ERRCODE = 'P0001', HINT = 'Set mes.reason in this transaction.';
        END IF;
    ELSE
        v_reason := NULL;
    END IF;

    INSERT INTO audit_trail (table_name, record_id, action, old_data, new_data, changed_by, reason)
    VALUES (TG_TABLE_NAME, to_jsonb(NEW) ->> v_pk, TG_OP,
            CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END, to_jsonb(NEW),
            mes_session_user(), v_reason);
    RETURN NEW;
END $$;

CREATE FUNCTION trg_forbid_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'GMP records in % cannot be deleted', TG_TABLE_NAME USING ERRCODE = 'P0001';
END $$;

CREATE FUNCTION trg_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'The audit trail is append-only: % is not allowed', TG_OP USING ERRCODE = 'P0001';
END $$;

CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_trail
    FOR EACH ROW EXECUTE FUNCTION trg_audit_append_only();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_trail
    FOR EACH STATEMENT EXECUTE FUNCTION trg_audit_append_only();

DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT * FROM (VALUES
        ('material_lots', 'lot_id'), ('batches', 'batch_id'), ('dispensing', 'dispense_id'),
        ('step_executions', 'exec_id'), ('deviations', 'deviation_id'),
        ('batch_signatures', 'signature_id')) AS v(tbl, pk)
    LOOP
        EXECUTE format('CREATE TRIGGER zz_audit AFTER INSERT OR UPDATE ON %I
                        FOR EACH ROW EXECUTE FUNCTION trg_audit(%L)', t.tbl, t.pk);
        EXECUTE format('CREATE TRIGGER no_delete BEFORE DELETE ON %I
                        FOR EACH ROW EXECUTE FUNCTION trg_forbid_delete()', t.tbl);
    END LOOP;
END $$;

---------------------------------------------------------------- dispensing
-- Only a released, unexpired lot of the right material, with a second person
-- verifying, and enough stock. Out-of-tolerance weights raise a deviation.
CREATE FUNCTION trg_dispense_before() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_lot    material_lots%ROWTYPE;
    v_batch  batches%ROWTYPE;
    v_req    recipe_materials%ROWTYPE;
BEGIN
    SELECT * INTO v_batch FROM batches WHERE batch_id = NEW.batch_id;
    IF v_batch.status NOT IN ('CREATED', 'DISPENSING') THEN
        RAISE EXCEPTION 'Batch % is %: dispensing is closed', v_batch.batch_no, v_batch.status;
    END IF;

    SELECT * INTO v_req FROM recipe_materials
    WHERE recipe_id = v_batch.recipe_id AND material_id = NEW.material_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Material % is not in the recipe for batch %', NEW.material_id, v_batch.batch_no;
    END IF;

    SELECT * INTO v_lot FROM material_lots WHERE lot_id = NEW.lot_id FOR UPDATE;
    IF v_lot.material_id <> NEW.material_id THEN
        RAISE EXCEPTION 'Lot % is not the requested material', v_lot.lot_no;
    END IF;
    IF v_lot.status <> 'RELEASED' THEN
        RAISE EXCEPTION 'Lot % has status %: only RELEASED lots can be dispensed', v_lot.lot_no, v_lot.status;
    END IF;
    IF v_lot.expiry_date < greatest(current_date, NEW.dispensed_at::date) THEN
        RAISE EXCEPTION 'Lot % expired on %', v_lot.lot_no, v_lot.expiry_date;
    END IF;
    IF v_lot.qty_available < NEW.actual_qty THEN
        RAISE EXCEPTION 'Lot % has only % % available', v_lot.lot_no, v_lot.qty_available,
            (SELECT uom FROM materials WHERE material_id = NEW.material_id);
    END IF;

    IF NEW.verified_by IS NULL THEN
        RAISE EXCEPTION 'Dispensing requires second-person verification';
    END IF;
    IF NEW.verified_by = NEW.dispensed_by THEN
        RAISE EXCEPTION 'The verifier must be a different person from the dispenser';
    END IF;

    NEW.target_qty := v_req.qty_per_batch;
    RETURN NEW;
END $$;

CREATE FUNCTION trg_dispense_after() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_tol  numeric;
    v_dev  numeric;
BEGIN
    UPDATE material_lots SET qty_available = qty_available - NEW.actual_qty WHERE lot_id = NEW.lot_id;
    UPDATE batches SET status = 'DISPENSING' WHERE batch_id = NEW.batch_id AND status = 'CREATED';

    SELECT rm.tolerance_pct INTO v_tol
    FROM recipe_materials rm JOIN batches b ON b.recipe_id = rm.recipe_id
    WHERE b.batch_id = NEW.batch_id AND rm.material_id = NEW.material_id;
    v_dev := 100 * (NEW.actual_qty - NEW.target_qty) / NEW.target_qty;
    IF abs(v_dev) > v_tol THEN
        INSERT INTO deviations (batch_id, source, severity, description, raised_by, raised_at)
        VALUES (NEW.batch_id, 'DISPENSING', 'MAJOR',
                format('Dispensed %s %s of %s against target %s (%s%%, tolerance ±%s%%)',
                       NEW.actual_qty, (SELECT uom FROM materials WHERE material_id = NEW.material_id),
                       (SELECT code FROM materials WHERE material_id = NEW.material_id),
                       NEW.target_qty, round(v_dev, 2), v_tol),
                'SYSTEM', NEW.dispensed_at);
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER a_dispense_before BEFORE INSERT ON dispensing
    FOR EACH ROW EXECUTE FUNCTION trg_dispense_before();
CREATE TRIGGER b_dispense_after AFTER INSERT ON dispensing
    FOR EACH ROW EXECUTE FUNCTION trg_dispense_after();

CREATE FUNCTION trg_dispense_locked() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.lot_id <> OLD.lot_id OR NEW.actual_qty <> OLD.actual_qty OR NEW.material_id <> OLD.material_id THEN
        RAISE EXCEPTION 'Dispensed quantities and lots cannot be edited; raise a deviation instead';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER a_dispense_locked BEFORE UPDATE ON dispensing
    FOR EACH ROW EXECUTE FUNCTION trg_dispense_locked();

---------------------------------------------------------------- step execution
-- Steps run in order, only after all materials are dispensed. Values outside
-- the recipe limits raise a deviation. The last step completes the batch.
CREATE FUNCTION trg_step_before() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_batch    batches%ROWTYPE;
    v_missing  int;
BEGIN
    SELECT * INTO v_batch FROM batches WHERE batch_id = NEW.batch_id;

    IF TG_OP = 'UPDATE' THEN
        IF v_batch.status IN ('RELEASED', 'REJECTED') THEN
            RAISE EXCEPTION 'Batch % is %: its record is locked', v_batch.batch_no, v_batch.status;
        END IF;
        IF NEW.step_no <> OLD.step_no OR NEW.batch_id <> OLD.batch_id THEN
            RAISE EXCEPTION 'Step number and batch cannot be changed';
        END IF;
        RETURN NEW;
    END IF;

    IF v_batch.status NOT IN ('DISPENSING', 'IN_PROGRESS') THEN
        RAISE EXCEPTION 'Batch % is %: steps cannot be executed', v_batch.batch_no, v_batch.status;
    END IF;
    SELECT count(*) INTO v_missing
    FROM recipe_materials rm
    WHERE rm.recipe_id = v_batch.recipe_id
      AND NOT EXISTS (SELECT 1 FROM dispensing d WHERE d.batch_id = NEW.batch_id AND d.material_id = rm.material_id);
    IF v_missing > 0 THEN
        RAISE EXCEPTION 'Batch %: % material(s) not yet dispensed', v_batch.batch_no, v_missing;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM recipe_steps WHERE recipe_id = v_batch.recipe_id AND step_no = NEW.step_no) THEN
        RAISE EXCEPTION 'Step % does not exist in the recipe', NEW.step_no;
    END IF;
    IF NEW.step_no > 1 AND NOT EXISTS (
        SELECT 1 FROM step_executions WHERE batch_id = NEW.batch_id AND step_no = NEW.step_no - 1) THEN
        RAISE EXCEPTION 'Step % must be completed before step %', NEW.step_no - 1, NEW.step_no;
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION trg_step_after() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_step   recipe_steps%ROWTYPE;
    v_total  int;
    v_done   int;
BEGIN
    SELECT rs.* INTO v_step
    FROM recipe_steps rs JOIN batches b ON b.recipe_id = rs.recipe_id
    WHERE b.batch_id = NEW.batch_id AND rs.step_no = NEW.step_no;

    IF NEW.recorded_value NOT BETWEEN v_step.lower_limit AND v_step.upper_limit
       AND (TG_OP = 'INSERT' OR NEW.recorded_value IS DISTINCT FROM OLD.recorded_value) THEN
        INSERT INTO deviations (batch_id, source, severity, description, raised_by, raised_at)
        VALUES (NEW.batch_id, 'STEP', 'MAJOR',
                format('Step %s %s = %s %s, outside limits %s to %s',
                       NEW.step_no, v_step.parameter_name, NEW.recorded_value, v_step.unit,
                       v_step.lower_limit, v_step.upper_limit),
                'SYSTEM', NEW.executed_at);
    END IF;

    IF TG_OP = 'INSERT' THEN
        UPDATE batches SET status = 'IN_PROGRESS', started_at = NEW.executed_at
        WHERE batch_id = NEW.batch_id AND status = 'DISPENSING';

        SELECT count(*) INTO v_total FROM recipe_steps rs JOIN batches b ON b.recipe_id = rs.recipe_id
        WHERE b.batch_id = NEW.batch_id;
        SELECT count(*) INTO v_done FROM step_executions WHERE batch_id = NEW.batch_id;
        IF v_done = v_total THEN
            UPDATE batches SET status = 'COMPLETED', completed_at = NEW.executed_at
            WHERE batch_id = NEW.batch_id;
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER a_step_before BEFORE INSERT OR UPDATE ON step_executions
    FOR EACH ROW EXECUTE FUNCTION trg_step_before();
CREATE TRIGGER b_step_after AFTER INSERT OR UPDATE ON step_executions
    FOR EACH ROW EXECUTE FUNCTION trg_step_after();

---------------------------------------------------------------- process signals
-- A value outside the tag's alarm limits raises one deviation per batch and tag
-- (further excursions on the same tag are covered by the open deviation).
CREATE FUNCTION trg_signal_after() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_lim tag_limits%ROWTYPE;
BEGIN
    SELECT * INTO v_lim FROM tag_limits WHERE tag = NEW.tag;
    IF NEW.value NOT BETWEEN v_lim.low_limit AND v_lim.high_limit
       AND NOT EXISTS (SELECT 1 FROM deviations
                       WHERE batch_id = NEW.batch_id AND source = 'PROCESS_SIGNAL'
                         AND status = 'OPEN' AND description LIKE NEW.tag || ' %') THEN
        INSERT INTO deviations (batch_id, source, severity, description, raised_by, raised_at)
        VALUES (NEW.batch_id, 'PROCESS_SIGNAL', 'MINOR',
                format('%s (%s) = %s %s at %s, alarm limits %s to %s', NEW.tag, v_lim.description,
                       round(NEW.value, 2), v_lim.unit, to_char(NEW.ts, 'YYYY-MM-DD HH24:MI'),
                       v_lim.low_limit, v_lim.high_limit),
                'SYSTEM', NEW.ts);
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER a_signal_after AFTER INSERT ON process_signals
    FOR EACH ROW EXECUTE FUNCTION trg_signal_after();

---------------------------------------------------------------- deviations
CREATE FUNCTION trg_deviation_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'CLOSED' THEN
        RAISE EXCEPTION 'Deviation % is closed and cannot be changed', OLD.deviation_id;
    END IF;
    IF NEW.batch_id <> OLD.batch_id OR NEW.source <> OLD.source OR NEW.description <> OLD.description THEN
        RAISE EXCEPTION 'Only status, severity and resolution of a deviation can be changed';
    END IF;
    IF NEW.status = 'CLOSED' THEN
        IF coalesce(mes_role_of(NEW.closed_by), '') <> 'QA' THEN
            RAISE EXCEPTION 'Only an active QA user can close a deviation';
        END IF;
        IF nullif(btrim(NEW.resolution), '') IS NULL THEN
            RAISE EXCEPTION 'A resolution is required to close a deviation';
        END IF;
        NEW.closed_at := coalesce(NEW.closed_at, now());
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER a_deviation_update BEFORE UPDATE ON deviations
    FOR EACH ROW EXECUTE FUNCTION trg_deviation_update();

---------------------------------------------------------------- QA disposition
-- Only QA signs. Nobody signs a batch they dispensed, verified or executed.
-- The batch must be complete, and open deviations block release.
CREATE FUNCTION trg_signature_before() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_batch batches%ROWTYPE;
BEGIN
    SELECT * INTO v_batch FROM batches WHERE batch_id = NEW.batch_id FOR UPDATE;

    IF coalesce(mes_role_of(NEW.signed_by), '') <> 'QA' THEN
        RAISE EXCEPTION 'Only an active QA user can sign a batch disposition';
    END IF;
    IF EXISTS (SELECT 1 FROM dispensing WHERE batch_id = NEW.batch_id
                 AND NEW.signed_by IN (dispensed_by, verified_by))
       OR EXISTS (SELECT 1 FROM step_executions WHERE batch_id = NEW.batch_id
                 AND executed_by = NEW.signed_by) THEN
        RAISE EXCEPTION 'User cannot sign batch %: they took part in executing it', v_batch.batch_no;
    END IF;
    IF v_batch.status <> 'COMPLETED' THEN
        RAISE EXCEPTION 'Batch % is %: only COMPLETED batches can be signed', v_batch.batch_no, v_batch.status;
    END IF;
    IF NEW.meaning = 'RELEASE' AND EXISTS (
        SELECT 1 FROM deviations WHERE batch_id = NEW.batch_id AND status = 'OPEN') THEN
        RAISE EXCEPTION 'Batch % has open deviations and cannot be released', v_batch.batch_no;
    END IF;
    IF NEW.meaning = 'REJECT' AND nullif(btrim(NEW.reason), '') IS NULL THEN
        RAISE EXCEPTION 'A reason is required to reject a batch';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION trg_signature_after() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE batches
    SET status = CASE NEW.meaning WHEN 'RELEASE' THEN 'RELEASED' ELSE 'REJECTED' END,
        disposition_at = NEW.signed_at
    WHERE batch_id = NEW.batch_id;
    RETURN NEW;
END $$;

CREATE TRIGGER a_signature_before BEFORE INSERT ON batch_signatures
    FOR EACH ROW EXECUTE FUNCTION trg_signature_before();
CREATE TRIGGER b_signature_after AFTER INSERT ON batch_signatures
    FOR EACH ROW EXECUTE FUNCTION trg_signature_after();

CREATE FUNCTION trg_signature_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Electronic signatures cannot be modified';
END $$;

CREATE TRIGGER a_signature_immutable BEFORE UPDATE ON batch_signatures
    FOR EACH ROW EXECUTE FUNCTION trg_signature_immutable();

---------------------------------------------------------------- views
CREATE VIEW v_batch_progress AS
SELECT b.batch_id, b.batch_no, p.code AS product_code, p.name AS product_name,
       r.version AS recipe_version, b.status,
       (SELECT count(*) FROM recipe_materials WHERE recipe_id = b.recipe_id)            AS materials_required,
       (SELECT count(*) FROM dispensing WHERE batch_id = b.batch_id)                    AS materials_dispensed,
       (SELECT count(*) FROM recipe_steps WHERE recipe_id = b.recipe_id)                AS steps_total,
       (SELECT count(*) FROM step_executions WHERE batch_id = b.batch_id)               AS steps_done,
       (SELECT count(*) FROM deviations WHERE batch_id = b.batch_id AND status = 'OPEN') AS open_deviations,
       (SELECT count(*) FROM deviations WHERE batch_id = b.batch_id)                    AS total_deviations,
       round(100.0 * ((SELECT count(*) FROM dispensing WHERE batch_id = b.batch_id)
                    + (SELECT count(*) FROM step_executions WHERE batch_id = b.batch_id))
             / ((SELECT count(*) FROM recipe_materials WHERE recipe_id = b.recipe_id)
              + (SELECT count(*) FROM recipe_steps WHERE recipe_id = b.recipe_id)), 0)  AS pct_complete,
       b.created_at, b.started_at, b.completed_at, b.disposition_at
FROM batches b
JOIN recipes r USING (recipe_id)
JOIN products p USING (product_id);

-- Everything a QA reviewer must look at; a batch with no rows here can be
-- reviewed by exception.
CREATE VIEW v_review_by_exception AS
SELECT b.batch_id, b.batch_no, b.status AS batch_status,
       'DEVIATION ' || d.status AS exception_type, d.severity,
       format('DEV-%s [%s] %s%s', lpad(d.deviation_id::text, 5, '0'), d.source, d.description,
              coalesce(' | Resolution: ' || d.resolution, '')) AS detail,
       d.raised_at AS occurred_at
FROM deviations d JOIN batches b USING (batch_id)
UNION ALL
SELECT b.batch_id, b.batch_no, b.status, 'RECORD CHANGED', 'INFO',
       format('%s %s changed by %s: %s', a.table_name, a.record_id, a.changed_by, a.reason),
       a.changed_at
FROM audit_trail a
JOIN batches b ON b.batch_id = (a.new_data ->> 'batch_id')::int
WHERE a.action = 'UPDATE'
  AND a.table_name IN ('dispensing', 'step_executions')
UNION ALL
SELECT b.batch_id, b.batch_no, b.status, 'PROCESS ALARM', 'INFO',
       format('%s: %s reading(s) outside %s to %s %s, worst %s', s.tag, count(*),
              l.low_limit, l.high_limit, l.unit,
              round(CASE WHEN max(s.value) > l.high_limit THEN max(s.value) ELSE min(s.value) END, 2)),
       min(s.ts)
FROM process_signals s
JOIN tag_limits l USING (tag)
JOIN batches b USING (batch_id)
WHERE s.value NOT BETWEEN l.low_limit AND l.high_limit
GROUP BY b.batch_id, b.batch_no, b.status, s.tag, l.low_limit, l.high_limit, l.unit;

-- Material genealogy: forward (lot -> batches) and backward (batch -> lots).
CREATE VIEW v_genealogy AS
SELECT l.lot_no, m.code AS material_code, m.name AS material_name, l.supplier,
       l.status AS lot_status, l.expiry_date,
       b.batch_no, p.code AS product_code, p.name AS product_name, b.status AS batch_status,
       d.actual_qty AS qty_used, m.uom, d.dispensed_at
FROM dispensing d
JOIN material_lots l USING (lot_id)
JOIN materials m ON m.material_id = d.material_id
JOIN batches b USING (batch_id)
JOIN recipes r USING (recipe_id)
JOIN products p USING (product_id);
