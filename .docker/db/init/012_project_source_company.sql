-- 案件の配信会社名（重複取込判定キー用）

ALTER TABLE projects ADD COLUMN IF NOT EXISTS source_company_name VARCHAR(255);

UPDATE projects AS p
SET source_company_name = c.name
FROM companies AS c
WHERE p.source_company_name IS NULL
  AND p.distributor_company_id = c.id;
