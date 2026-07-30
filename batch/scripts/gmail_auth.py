#!/usr/bin/env python3
"""Gmail OAuth 初回認可スクリプト。

ブラウザで Google 認可を行い、token.json を生成する。
credentials.json は secrets/ に配置しておくこと。

Usage:
  python batch/scripts/gmail_auth.py
  python batch/scripts/gmail_auth.py --credentials secrets/credentials.json --token secrets/token.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Gmail OAuth token.json")
    parser.add_argument(
        "--credentials",
        default="secrets/credentials.json",
        help="Path to OAuth client credentials JSON",
    )
    parser.add_argument(
        "--token",
        default="secrets/token.json",
        help="Path to write authorized user token JSON",
    )
    args = parser.parse_args()

    credentials_path = Path(args.credentials)
    token_path = Path(args.token)

    if not credentials_path.exists():
        raise SystemExit(f"credentials file not found: {credentials_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Wrote token to {token_path}")


if __name__ == "__main__":
    main()
