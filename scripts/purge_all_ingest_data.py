"""取込メールと、そこから生成された人材・案件・採点・提案データをすべて削除する。

使い方（Docker 環境）:
  docker compose -f .docker/docker-compose.yml exec api \\
    python /scripts/purge_all_ingest_data.py --yes

  ※ compose で scripts をマウントしていない場合:
  docker compose -f .docker/docker-compose.yml exec api \\
    sh -c 'PYTHONPATH=/batch python -c "from app.purge_ingest import purge_all_ingest_data; print(purge_all_ingest_data())"'

ローカル（batch 依存）:
  cd batch && PYTHONPATH=. python ../scripts/purge_all_ingest_data.py --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[1] / "batch"
if not (_BATCH_ROOT / "app").is_dir():
    _BATCH_ROOT = Path("/batch")
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.purge_ingest import purge_all_ingest_data


def main() -> int:
    parser = argparse.ArgumentParser(description="取込メールデータをすべて削除する")
    parser.add_argument("--yes", action="store_true", help="確認なしで実行")
    parser.add_argument("--skip-drive", action="store_true", help="Drive 上のスキルシートは削除しない")
    args = parser.parse_args()

    if not args.yes:
        print("取込メール・人材・案件・採点・提案データをすべて削除します。")
        print("企業・担当者・スキルマスタは残します。")
        answer = input("続行しますか？ [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("中止しました。")
            return 1

    try:
        result = purge_all_ingest_data(skip_drive=args.skip_drive)
    except Exception as exc:  # noqa: BLE001
        print(f"削除に失敗しました: {exc}", file=sys.stderr)
        return 1

    print("削除完了:")
    print(
        f"  emails: {result['before_emails']} -> {result['remaining_emails']} "
        f"(deleted {result['deleted_emails']})"
    )
    print(
        f"  talents: {result['before_talents']} -> {result['remaining_talents']} "
        f"(deleted {result['deleted_talents']})"
    )
    print(
        f"  projects: {result['before_projects']} -> {result['remaining_projects']} "
        f"(deleted {result['deleted_projects']})"
    )
    print(f"  matches deleted: {result['deleted_matches']}")
    print(f"  match_runs deleted: {result['deleted_match_runs']}")
    print(f"  outreach_messages deleted: {result['deleted_outreach_messages']}")
    print(f"  outreach_replies deleted: {result['deleted_outreach_replies']}")
    print(f"  talent_skill_sheets deleted: {result['deleted_talent_skill_sheets']}")
    if result["drive_files_attempted"]:
        print(f"  drive skill sheets attempted: {result['drive_files_attempted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
