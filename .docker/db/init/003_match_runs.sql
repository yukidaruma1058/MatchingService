-- BAT-003: ルールスコア採点（match_runs / matches）と通勤キャッシュ

CREATE TABLE IF NOT EXISTS match_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger VARCHAR(16) NOT NULL,
  ai_judgement_top_n SMALLINT,
  ai_assist_enabled BOOLEAN NOT NULL DEFAULT false,
  status VARCHAR(16) NOT NULL DEFAULT 'running',
  stats JSONB,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_match_runs_started_at ON match_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS matches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  match_run_id UUID NOT NULL REFERENCES match_runs (id) ON DELETE CASCADE,
  talent_id UUID NOT NULL REFERENCES talents (id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  score SMALLINT NOT NULL,
  score_band VARCHAR(8),
  score_breakdown JSONB,
  ai_score SMALLINT,
  reason TEXT,
  recommendation_points TEXT,
  ai_judged_at TIMESTAMPTZ,
  is_candidate BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (match_run_id, talent_id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_project_score ON matches (project_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_matches_talent_project ON matches (talent_id, project_id);
CREATE INDEX IF NOT EXISTS idx_matches_run ON matches (match_run_id);

CREATE TABLE IF NOT EXISTS commute_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  origin_key VARCHAR(255) NOT NULL,
  destination_key VARCHAR(255) NOT NULL,
  duration_minutes INTEGER,
  provider VARCHAR(32) NOT NULL DEFAULT 'google_routes',
  raw_status VARCHAR(64),
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (origin_key, destination_key, provider)
);

CREATE INDEX IF NOT EXISTS idx_commute_cache_fetched ON commute_cache (fetched_at DESC);

CREATE TABLE IF NOT EXISTS commute_api_usage (
  year_month CHAR(7) PRIMARY KEY,
  request_count INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
