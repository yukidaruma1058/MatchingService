-- 外国籍・商流制約カラム（既存 DB 向け）

ALTER TABLE talents ADD COLUMN IF NOT EXISTS is_foreign_national BOOLEAN;
ALTER TABLE talents ADD COLUMN IF NOT EXISTS commerce_flow VARCHAR(64);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS foreign_nationality_ng BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS commerce_flow_limit VARCHAR(64);
