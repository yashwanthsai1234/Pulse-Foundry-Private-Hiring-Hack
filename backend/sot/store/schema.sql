-- IMPLEMENTATION §5. Persistent tables keep data across runs; gold tables are rebuilt each run (DELETE + INSERT).
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP,
  status TEXT, summary JSON);
CREATE TABLE IF NOT EXISTS files (file_id TEXT PRIMARY KEY, file_name TEXT, path TEXT, size BIGINT,
  received_at TIMESTAMP, run_id TEXT, parser TEXT, sniff_score DOUBLE, bids JSON, status TEXT);
CREATE TABLE IF NOT EXISTS raw_tables (table_id TEXT PRIMARY KEY, file_id TEXT, parser TEXT, page INT,
  sheet TEXT, header JSON, n_rows INT, context JSON, extraction JSON, parquet_path TEXT, cell_bboxes JSON);
CREATE TABLE IF NOT EXISTS mappings (table_id TEXT PRIMARY KEY, template_id TEXT, confidence DOUBLE,
  matches JSON, unmapped JSON, missing_required JSON, source TEXT, contract_id TEXT, drift BOOLEAN, status TEXT);
CREATE TABLE IF NOT EXISTS contracts (contract_id TEXT PRIMARY KEY, template_id TEXT, header_fingerprint TEXT,
  version INT, column_map JSON, source TEXT, approved BOOLEAN, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS source_records (record_id TEXT PRIMARY KEY, table_id TEXT, template_id TEXT,
  entity TEXT, fields JSON, raw JSON, person_key JSON, loc JSON, parse_issues JSON);
CREATE TABLE IF NOT EXISTS shifts_silver (shift_id TEXT PRIMARY KEY, record_id TEXT, facility_id TEXT,
  role TEXT, work_date DATE, token TEXT, start_t TIME, end_t TIME, hours DOUBLE, hours_source TEXT, loc JSON);

-- gold
CREATE TABLE IF NOT EXISTS links (a TEXT, b TEXT, prob DOUBLE, weight DOUBLE, method TEXT, reasons JSON);
CREATE TABLE IF NOT EXISTS persons (person_id TEXT PRIMARY KEY, employee_id TEXT, has_hr BOOLEAN,
  display_name TEXT, role TEXT, home_facility_id TEXT, phone TEXT, hire_date DATE);
CREATE TABLE IF NOT EXISTS person_records (person_id TEXT, record_id TEXT, template_id TEXT, link_prob DOUBLE);
CREATE TABLE IF NOT EXISTS credentials (credential_id TEXT PRIMARY KEY, holder_type TEXT, holder_id TEXT,
  holder_name TEXT, credential_type TEXT, number TEXT, issued_on DATE, expires_on DATE, last_verified DATE);
CREATE TABLE IF NOT EXISTS shifts (shift_id TEXT PRIMARY KEY, person_id TEXT, facility_id TEXT, role TEXT,
  work_date DATE, start_ts TIMESTAMP, end_ts TIMESTAMP, hours DOUBLE, record_id TEXT, loc JSON);
CREATE TABLE IF NOT EXISTS pay_periods (pay_id TEXT PRIMARY KEY, person_id TEXT, facility_id TEXT, role TEXT,
  period_start DATE, period_end DATE, hours_paid DOUBLE, record_id TEXT);
CREATE TABLE IF NOT EXISTS claims (claim_id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, attribute TEXT,
  value JSON, value_type TEXT, template_id TEXT, record_id TEXT, loc JSON, observed_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS golden_values (entity_type TEXT, entity_id TEXT, attribute TEXT, value JSON,
  claim_id TEXT, rule TEXT, conflict BOOLEAN, conflicting_claim_ids JSON);

-- persistent across runs
CREATE TABLE IF NOT EXISTS issues (fingerprint TEXT PRIMARY KEY, check_id TEXT, severity TEXT, title TEXT,
  message TEXT, entity_ids JSON, facility_id TEXT, period_start DATE, period_end DATE, evidence JSON,
  action TEXT, status TEXT DEFAULT 'open', owner TEXT, note TEXT, first_seen_run TEXT, last_seen_run TEXT,
  active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS agent_tasks (task_id TEXT PRIMARY KEY, kind TEXT, run_id TEXT, ref TEXT, status TEXT,
  payload JSON, output JSON, validator_notes JSON, created_at TIMESTAMP, finished_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS agent_cache (cache_key TEXT PRIMARY KEY, kind TEXT, output JSON, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS events (run_id TEXT, seq INT, ts TIMESTAMP, type TEXT, file_name TEXT,
  message TEXT, data JSON);
