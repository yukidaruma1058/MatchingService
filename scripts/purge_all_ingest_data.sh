#!/usr/bin/env bash
# 取込メール・人材・案件・採点・提案データを DB からすべて削除する。
# 企業・担当者・スキルマスタは残す。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="docker compose -f ${ROOT}/.docker/docker-compose.yml"

echo "取込データを削除します..."
"${COMPOSE}" exec -T api sh -c 'PYTHONPATH=/batch python - <<'"'"'PY'"'"'
from app.purge_ingest import purge_all_ingest_data

result = purge_all_ingest_data(skip_drive=False)
print("削除完了:")
print(f"  emails: {result['before_emails']} -> {result['remaining_emails']} (deleted {result['deleted_emails']})")
print(f"  talents: {result['before_talents']} -> {result['remaining_talents']} (deleted {result['deleted_talents']})")
print(f"  projects: {result['before_projects']} -> {result['remaining_projects']} (deleted {result['deleted_projects']})")
print(f"  matches deleted: {result['deleted_matches']}")
print(f"  match_runs deleted: {result['deleted_match_runs']}")
print(f"  outreach_messages deleted: {result['deleted_outreach_messages']}")
print(f"  outreach_replies deleted: {result['deleted_outreach_replies']}")
print(f"  talent_skill_sheets deleted: {result['deleted_talent_skill_sheets']}")
if result["drive_files_attempted"]:
    print(f"  drive skill sheets attempted: {result['drive_files_attempted']}")
PY'
