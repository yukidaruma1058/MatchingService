-- 提案メール用 CC アドレス

ALTER TABLE emails
  ADD COLUMN IF NOT EXISTS cc_addresses JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE talents
  ADD COLUMN IF NOT EXISTS proposal_cc_emails JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS proposal_cc_emails JSONB NOT NULL DEFAULT '[]'::jsonb;
