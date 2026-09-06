CREATE TABLE IF NOT EXISTS raw_events (
  id VARCHAR(36) PRIMARY KEY,
  provider VARCHAR(64) NOT NULL,
  source_record_id VARCHAR(255),
  import_batch_id VARCHAR(36) NOT NULL,
  observed_start TIMESTAMPTZ,
  observed_end TIMESTAMPTZ,
  received_at TIMESTAMPTZ NOT NULL,
  payload_json JSONB NOT NULL,
  payload_hash VARCHAR(64) NOT NULL,
  permissions_scope VARCHAR(255),
  schema_version VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS normalized_metrics (
  id VARCHAR(36) PRIMARY KEY,
  provider VARCHAR(64) NOT NULL,
  source VARCHAR(128) NOT NULL,
  metric_name VARCHAR(128) NOT NULL,
  value_numeric DOUBLE PRECISION,
  value_text TEXT,
  unit VARCHAR(32),
  observed_start TIMESTAMPTZ NOT NULL,
  observed_end TIMESTAMPTZ,
  aggregation_window VARCHAR(64),
  confidence DOUBLE PRECISION NOT NULL,
  raw_event_id VARCHAR(36) NOT NULL REFERENCES raw_events(id),
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_features (
  date DATE NOT NULL,
  timezone VARCHAR(64) NOT NULL,
  weight DOUBLE PRECISION,
  calories DOUBLE PRECISION,
  protein DOUBLE PRECISION,
  carbs DOUBLE PRECISION,
  fat DOUBLE PRECISION,
  systolic_bp DOUBLE PRECISION,
  diastolic_bp DOUBLE PRECISION,
  resting_hr DOUBLE PRECISION,
  hrv DOUBLE PRECISION,
  sleep_duration DOUBLE PRECISION,
  sleep_efficiency DOUBLE PRECISION,
  steps DOUBLE PRECISION,
  active_energy DOUBLE PRECISION,
  training_load DOUBLE PRECISION,
  workout_count DOUBLE PRECISION,
  tirzepatide_dose_mg DOUBLE PRECISION,
  tirzepatide_days_since_dose DOUBLE PRECISION,
  notes TEXT,
  source_flags JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (date, timezone)
);

CREATE TABLE IF NOT EXISTS coaching_goals (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  is_active INTEGER NOT NULL,
  start_date DATE NOT NULL,
  target_date DATE NOT NULL,
  start_weight_kg DOUBLE PRECISION NOT NULL,
  target_weight_kg DOUBLE PRECISION NOT NULL,
  daily_calorie_target DOUBLE PRECISION,
  daily_protein_target_g DOUBLE PRECISION,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS connector_states (
  connector VARCHAR(64) PRIMARY KEY,
  status VARCHAR(32) NOT NULL,
  detail TEXT NOT NULL,
  last_sync_at TIMESTAMPTZ,
  last_error TEXT,
  next_action TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
  provider VARCHAR(64) PRIMARY KEY,
  access_token TEXT,
  refresh_token TEXT,
  token_type VARCHAR(32),
  scope TEXT,
  expires_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS medication_doses (
  id VARCHAR(36) PRIMARY KEY,
  medication_name VARCHAR(128) NOT NULL,
  dose_mg DOUBLE PRECISION NOT NULL,
  taken_at TIMESTAMPTZ NOT NULL,
  side_effects TEXT,
  appetite VARCHAR(64),
  gi_symptoms TEXT,
  hydration_notes TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dose_change_contexts (
  id VARCHAR(36) PRIMARY KEY,
  medication_name VARCHAR(128) NOT NULL,
  prior_dose_mg DOUBLE PRECISION,
  planned_dose_mg DOUBLE PRECISION,
  planned_start_date DATE,
  clinician_name VARCHAR(128),
  source_type VARCHAR(64),
  source_reference TEXT,
  preparation_notes TEXT,
  monitoring_notes TEXT,
  follow_up_questions TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS strength_sessions (
  id VARCHAR(36) PRIMARY KEY,
  raw_event_id VARCHAR(36) NOT NULL UNIQUE REFERENCES raw_events(id),
  source VARCHAR(64) NOT NULL,
  source_record_id VARCHAR(255) NOT NULL,
  source_kind VARCHAR(32) NOT NULL,
  capture_status VARCHAR(32) NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  duration_seconds DOUBLE PRECISION,
  timezone VARCHAR(64) NOT NULL,
  timing_confidence VARCHAR(32) NOT NULL,
  program_name VARCHAR(128),
  program_session_name VARCHAR(128),
  program_week INTEGER,
  program_block INTEGER,
  program_notes TEXT,
  session_rpe DOUBLE PRECISION,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_strength_session_source_record UNIQUE (source, source_record_id)
);

CREATE TABLE IF NOT EXISTS strength_exercises (
  id VARCHAR(36) PRIMARY KEY,
  session_id VARCHAR(36) NOT NULL REFERENCES strength_sessions(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  series_name VARCHAR(128),
  name VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL,
  planned_sets VARCHAR(64),
  planned_reps VARCHAR(64),
  planned_tempo VARCHAR(32),
  planned_rest_seconds DOUBLE PRECISION,
  target_intensity VARCHAR(128),
  planned_notes TEXT,
  notes TEXT,
  CONSTRAINT uq_strength_exercise_position UNIQUE (session_id, position)
);

CREATE TABLE IF NOT EXISTS strength_sets (
  id VARCHAR(36) PRIMARY KEY,
  exercise_id VARCHAR(36) NOT NULL REFERENCES strength_exercises(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  status VARCHAR(32) NOT NULL,
  reps INTEGER,
  rep_multiplier DOUBLE PRECISION NOT NULL,
  load_value DOUBLE PRECISION,
  load_unit VARCHAR(16),
  load_kg DOUBLE PRECISION,
  load_multiplier DOUBLE PRECISION NOT NULL,
  duration_seconds DOUBLE PRECISION,
  distance_meters DOUBLE PRECISION,
  rpe DOUBLE PRECISION,
  is_warmup BOOLEAN NOT NULL,
  notes TEXT,
  CONSTRAINT uq_strength_set_position UNIQUE (exercise_id, position)
);
