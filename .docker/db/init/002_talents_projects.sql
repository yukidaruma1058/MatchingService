-- BAT-002: AI 要約後の人材・案件テーブル（companies 未実装のため company FK は持たない）

CREATE TABLE IF NOT EXISTS talents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email_id UUID NOT NULL UNIQUE REFERENCES emails (id) ON DELETE CASCADE,
  introducer_company_id UUID,
  display_name VARCHAR(128) NOT NULL,
  affiliation VARCHAR(255),
  age SMALLINT,
  gender VARCHAR(16),
  experience_years SMALLINT,
  desired_rate INTEGER,
  available_from VARCHAR(64),
  work_style VARCHAR(255),
  nearest_station VARCHAR(64),
  skills JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_company_name VARCHAR(255),
  is_foreign_national BOOLEAN,
  commerce_flow VARCHAR(64),
  summary TEXT,
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_talents_status ON talents (status);
CREATE INDEX IF NOT EXISTS idx_talents_created_at ON talents (created_at DESC);

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email_id UUID NOT NULL UNIQUE REFERENCES emails (id) ON DELETE CASCADE,
  distributor_company_id UUID,
  project_code VARCHAR(32),
  title VARCHAR(255) NOT NULL,
  required_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
  rate_min INTEGER,
  rate_max INTEGER,
  location VARCHAR(128),
  work_style VARCHAR(255),
  working_hours VARCHAR(128),
  start_date VARCHAR(64),
  foreign_nationality_ng BOOLEAN,
  commerce_flow_limit VARCHAR(64),
  settlement_range VARCHAR(64),
  interview_count SMALLINT,
  headcount SMALLINT,
  summary TEXT,
  status VARCHAR(16) NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects (created_at DESC);
