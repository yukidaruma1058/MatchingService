-- OAuth クライアント設定以外の DB データを全削除する。
-- 残す key: gmail_oauth_client_id / gmail_oauth_client_secret / gmail_oauth_project_id
--
-- 実行例:
--   docker compose -f .docker/docker-compose.yml exec -T db \
--     psql -U matching -d matching -v ON_ERROR_STOP=1 -f - < scripts/wipe_db_keep_oauth.sql

BEGIN;

DELETE FROM system_settings
WHERE key NOT IN (
  'gmail_oauth_client_id',
  'gmail_oauth_client_secret',
  'gmail_oauth_project_id'
);

TRUNCATE TABLE
  outreach_replies,
  outreach_message_talents,
  outreach_messages,
  matches,
  match_runs,
  commute_cache,
  commute_api_usage,
  contacts,
  companies,
  talents,
  projects,
  emails
RESTART IDENTITY CASCADE;

COMMIT;

SELECT key FROM system_settings ORDER BY key;
SELECT 'emails' AS table_name, count(*) AS rows FROM emails
UNION ALL SELECT 'talents', count(*) FROM talents
UNION ALL SELECT 'projects', count(*) FROM projects
UNION ALL SELECT 'companies', count(*) FROM companies
UNION ALL SELECT 'contacts', count(*) FROM contacts
UNION ALL SELECT 'matches', count(*) FROM matches
UNION ALL SELECT 'outreach_messages', count(*) FROM outreach_messages;
