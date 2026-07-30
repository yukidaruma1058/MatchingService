-- 009: 1通の返信を複数提案（案件ごと）へ紐づけ可能にする
-- gmail_message_id 単独 UNIQUE → (outreach_message_id, gmail_message_id) UNIQUE

ALTER TABLE outreach_replies DROP CONSTRAINT IF EXISTS outreach_replies_gmail_message_id_key;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'uq_outreach_replies_message_gmail'
  ) THEN
    ALTER TABLE outreach_replies
      ADD CONSTRAINT uq_outreach_replies_message_gmail
      UNIQUE (outreach_message_id, gmail_message_id);
  END IF;
END $$;
