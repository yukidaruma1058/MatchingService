-- 未使用設定キーの削除（auto_match_enabled / gmail_label_talent_reply）
DELETE FROM system_settings
WHERE key IN ('auto_match_enabled', 'gmail_label_talent_reply');
