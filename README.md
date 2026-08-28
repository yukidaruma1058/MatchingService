# MatchingService

SES 人材紹介・案件配信メールを Gmail から取り込み、OpenAI で要約して PostgreSQL に保存し、検索 UI とマッチングを提供するシステムの基盤です。

## 構成

| サービス | 技術 | 役割 |
|---------|------|------|
| `api` | FastAPI | 検索・マッチング API |
| `web` | Next.js | 管理・検索画面 |
| `db` | PostgreSQL 16 | データ保存 |
| `batch` | Python | Gmail 取込・採点・提案（ワンショット手動実行） |

Docker 関連ファイルはすべて [`.docker/`](.docker/) 配下にあります。

## 前提

- Docker / Docker Compose
- リポジトリルートに `.env`（`.env.example` をコピー）

```bash
cp .env.example .env
```

Gmail OAuth 用の `credentials.json` / `token.json` は `secrets/` に配置してください（コミットしないこと）。

### Gmail 連携の手順（設定画面から完結）

1. [Google Cloud Console](https://console.cloud.google.com/) で **権限のあるプロジェクト** を用意する（個人利用なら新規プロジェクト作成が簡単。会社プロジェクトの場合は編集者以上の権限が必要）
2. Gmail API と Google Drive API を有効化し、OAuth 同意画面を設定する（**対象** でユーザーの種類・公開ステータス・**テストユーザー** を確認。テスト中は連携する Gmail をテストユーザーに追加必須）と OAuth クライアント（**Web アプリケーション**）を作成する。スコープは `gmail.modify` に加え、スキルシート連携用に `https://www.googleapis.com/auth/drive` が必要です（既存連携がある場合は再連携）
3. 設定画面に表示されるリダイレクト URI をコピーし、Google Cloud に登録する（ローカル開発時は `http://localhost:8000/api/gmail/oauth/callback` が自動表示。本番では `API_PUBLIC_BASE_URL` を `.env` に設定）
4. http://localhost:3000/settings を開き、「Gmail 初回連携」横の **?** で手順を確認し、Client ID / Secret を入力して **Gmailと連携する** を押す。スキルシート保存先として、共有ドライブ上の親フォルダ ID を「スキルシート共有ドライブ フォルダ ID」に設定する（配下に `スキルシート/{所属会社}` が自動作成されます）
5. Google の認可画面で許可すると `token.json` が自動作成され、連携完了

「API とサービス」で **追加のアクセス権が必要です**（`resourcemanager.projects.get` 等）と出る場合は、選択中のプロジェクトに権限がありません。詳細は設定画面の **?** を参照してください。

`.env` や `secrets/credentials.json` を手動で用意する方法も引き続き利用できます。

```bash
# 代替: .env に設定（API 起動時に credentials.json を自動生成）
GMAIL_CLIENT_ID=xxxx.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=your-client-secret
```

## 起動

リポジトリルートで実行します。

```bash
# 常駐サービス（DB / API / Web）
docker compose -f .docker/docker-compose.yml up -d --build db api web

# バッチ手動実行（引数なし = pipeline。ingest / cleanup / match 等も可）
# ログ: log/batch.log
docker compose -f .docker/docker-compose.yml --profile batch run --rm batch pipeline
```

開発時の API ホットリロードは [`.docker/docker-compose.override.yml`](.docker/docker-compose.override.yml) を併用します（Web は本番ビルドのまま）。

```bash
docker compose \
  -f .docker/docker-compose.yml \
  -f .docker/docker-compose.override.yml \
  up -d --build db api web
```

## エンドポイント

- Web: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## ディレクトリ

```
.
├── .docker/           # Dockerfile / Compose
├── api/               # FastAPI
├── batch/             # Gmail 取り込みバッチ
├── web/               # Next.js
├── secrets/           # Gmail 認証ファイル（git 管理外）
├── .env.example
└── README.md
```

## 今後の実装予定

- 案件一覧のスコア帯分布・応募人数などリッチ表示
- 設定の取込時刻 UI の拡充

実装済みの主要機能: Gmail 取込・要約、スキルシート共有ドライブ保存、ルール採点、人材/案件詳細からの提案・AI採点、スキルマスタ、設定・Gmail/Drive OAuth
