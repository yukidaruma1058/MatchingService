-- 案件紹介下書き用: 取込メールのコア原文キャッシュ
ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_core_text TEXT;
