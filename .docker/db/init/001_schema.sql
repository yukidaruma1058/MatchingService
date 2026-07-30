CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS system_settings (
  key VARCHAR(64) PRIMARY KEY,
  value JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS emails (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  gmail_message_id VARCHAR(128) NOT NULL UNIQUE,
  thread_id VARCHAR(128),
  label VARCHAR(64) NOT NULL,
  from_address VARCHAR(255) NOT NULL,
  subject TEXT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL,
  body_text TEXT,
  body_html TEXT,
  email_type VARCHAR(16) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  source_company_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emails_status ON emails (status);
CREATE INDEX IF NOT EXISTS idx_emails_received_at ON emails (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_created_at ON emails (created_at);

INSERT INTO system_settings (key, value)
VALUES ('ingest_data_retention_days', '0'::jsonb)
ON CONFLICT (key) DO NOTHING;
