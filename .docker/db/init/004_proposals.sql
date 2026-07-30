-- 004: 提案・返信フロー（outreach）

CREATE TABLE IF NOT EXISTS outreach_messages (
  id UUID PRIMARY KEY,
  kind VARCHAR(32) NOT NULL,
  match_id UUID REFERENCES matches(id) ON DELETE SET NULL,
  talent_id UUID REFERENCES talents(id) ON DELETE SET NULL,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'draft',
  gmail_message_id VARCHAR(128),
  thread_id VARCHAR(128),
  in_reply_to_email_id UUID REFERENCES emails(id) ON DELETE SET NULL,
  subject TEXT,
  body_text TEXT,
  sent_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_messages_kind_status ON outreach_messages (kind, status);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_match_id ON outreach_messages (match_id);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_project_id ON outreach_messages (project_id);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_thread_id ON outreach_messages (thread_id);

CREATE TABLE IF NOT EXISTS outreach_message_talents (
  outreach_message_id UUID NOT NULL REFERENCES outreach_messages(id) ON DELETE CASCADE,
  talent_id UUID NOT NULL REFERENCES talents(id) ON DELETE CASCADE,
  match_id UUID REFERENCES matches(id) ON DELETE SET NULL,
  PRIMARY KEY (outreach_message_id, talent_id)
);

CREATE TABLE IF NOT EXISTS outreach_replies (
  id UUID PRIMARY KEY,
  outreach_message_id UUID NOT NULL REFERENCES outreach_messages(id) ON DELETE CASCADE,
  gmail_message_id VARCHAR(128) NOT NULL UNIQUE,
  thread_id VARCHAR(128),
  received_at TIMESTAMPTZ NOT NULL,
  body_text TEXT,
  judgment VARCHAR(16) NOT NULL DEFAULT 'unknown',
  judgment_source VARCHAR(16) NOT NULL DEFAULT 'auto',
  labeled_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_replies_outreach_message_id ON outreach_replies (outreach_message_id);
