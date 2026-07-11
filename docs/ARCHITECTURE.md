# アーキテクチャ / 技術選定

- 版: v0.1（2026-07-11, Fable 決定）
- 「確定済み仕様」（CLAUDE.md）以外の選定はここに記録する。変更したい場合は Fable が本ファイルを更新してから実装する。

## 1. コンポーネント構成

```
[Vue 3 SPA] --HTTP/SSE--> [FastAPI backend] --OpenAI互換API--> [vLLM (Qwen3)]
                               |--> [Qdrant] (学内ナレッジ ベクトル検索)
                               |--> [Web Search] (ddgs, 抽象化レイヤ経由)
```

すべて docker compose で起動する（vLLM は GPU 割当、`--gpus all`）。

### ポート割当（2026-07-11 Fable 決定）

| サービス | ポート |
|---|---|
| frontend (Vite dev / nginx) | 5173 |
| backend (FastAPI) | **8080** |
| vLLM | 8000 |
| Qdrant | 6333 |

backend のローカル起動・Vite の `/api` プロキシ先はともに 8080 とする（8000 は vLLM が使うため）。
プロキシ先は `VITE_API_PROXY_TARGET` 環境変数で上書き可能にする。

## 2. 技術選定と理由

| 項目 | 選定 | 理由 |
|---|---|---|
| フロントエンド | Vue 3 + Vite + Tailwind CSS + Pinia | 演出の参照実装 guidanceLLM2 と同スタックにし、Ver1.0 の「完全再現」をコード流用レベルで保証するため |
| Markdown 描画 | marked | 参照実装と同じ |
| バックエンド | Python 3.11+ / FastAPI | SSE・非同期・LLM エコシステムとの親和性 |
| エージェント制御 | LangGraph | Agentic RAG のループ（検索→評価→再検索）とステップ通知フックを素直に書ける |
| LLM サービング | vLLM（OpenAI 互換サーバ） | 確定仕様。バックエンドからは OpenAI クライアントで接続 |
| LLM モデル | Qwen3 系（第一候補: `Qwen/Qwen3-14B-AWQ`、代替: `Qwen/Qwen3-8B`） | 参照システムも Qwen3。24GB VRAM に量子化 14B + KV キャッシュが収まる。日本語性能良好。最終決定は Phase 2 でスループット実測後 |
| 埋め込み | `BAAI/bge-m3` | 日本語を含む多言語で高性能。ローカル実行可 |
| リランカー | `BAAI/bge-reranker-v2-m3`（任意、Phase 3 で効果測定） | 検索精度向上の定番。効果がなければ外す |
| ベクトル DB | Qdrant（docker） | 運用が軽く、メタデータフィルタが強い。compose に載せやすい |
| Web 検索 | `ddgs`（DuckDuckGo, API キー不要）を既定。`SearchProvider` インターフェースで抽象化 | キーレスで開発が止まらない。後から Tavily 等に差し替え可能 |
| ストリーミング | SSE（`text/event-stream`） | 単方向で十分。WebSocket より単純 |

## 3. API / SSE イベントスキーマ

### エンドポイント一覧

```
POST /api/auth/register   ニックネーム登録（docs/UI_LOGIN.md）
POST /api/auth/login      ログイン
GET  /api/auth/me         セッション確認 (Bearer)
POST /api/chat            チャット送信 → SSE ストリーム (Bearer)
GET  /api/threads/{id}    スレッド履歴取得 (Bearer)
GET  /api/health          ヘルスチェック（vLLM/Qdrant 疎通含む）
```

- ユーザー・スレッドの永続化は **SQLite**（`backend/data/`、ボリュームマウント）。
  規模（オープンキャンパス 1 日イベント）に対して RDB サーバは過剰なため。
- `/api/chat` と `/api/threads` は Bearer トークン必須。無効なら 401。

### チャット SSE

`POST /api/chat`（リクエスト body: `{"message": "<質問文>", "thread_id": "<既存スレッドID または null>"}`。SSE ストリームを返す）

```
event: status
data: {"step": "analyze" | "retrieve" | "web_search" | "evaluate" | "generate",
       "text": "学内ナレッジを検索しています…"}

event: token
data: {"text": "秋田県立"}

event: done
data: {"thread_id": "...", "message_id": "...",
       "sources": [{"title": "...", "url": "...", "type": "knowledge" | "web"}]}

event: error
data: {"message": "..."}
```

- `status` は各ステップ開始時に必ず送る（FR-2）。`text` は日本語の短文で、フロントはそのまま表示する。
- `token` 受信開始でフロントはローディング演出を終了し、本文の逐次描画に切り替える。
- `done` の `sources` は回答末尾の出典表示に使う。

## 4. リポジトリ構成（計画）

```
oc_2026/
├── CLAUDE.md / AGENTS.md / README.md
├── docs/                  # 仕様書（常に正）
├── frontend/              # Vue 3 SPA
│   ├── public/app-icon.png   # ルートの app-icon.png をコピー
│   └── src/...
├── backend/
│   ├── app/               # FastAPI (api, agent, rag, search, llm)
│   └── tests/
├── knowledge/             # RAG ナレッジ（Markdown, docs/KNOWLEDGE.md 準拠）
│   └── ingest/            # 取り込みスクリプト
├── docker-compose.yml     # frontend, backend, vllm, qdrant
└── .env.example
```

## 5. vLLM 起動構成（2026-07-11 Fable 実機検証済み）

以下の構成で RTX 3090 Ti 24GB 上の動作を確認した（日本語応答 OK、VRAM 22.0/24.5GB）:

```bash
docker run --gpus all \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -p 8000:8000 vllm/vllm-openai:latest \
  --model Qwen/Qwen3-14B-AWQ \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.90 \
  --reasoning-parser qwen3
```

- モデル重み（9.4GB）と `BAAI/bge-m3`（4.3GB）はホストの HF キャッシュにダウンロード済み。
  docker compose では同じボリュームマウントを使うこと（再ダウンロード禁止）。
- Qwen3 の thinking モードは既定 ON。**通常の回答生成では `chat_template_kwargs: {"enable_thinking": false}` を指定**して
  レイテンシを抑える（エージェントの計画ステップでは ON にしてよい。効果は Phase 3 で測定）。
- 埋め込み（bge-m3）は **CPU で実行**する（GPU は vLLM が 0.90 を確保済み。クエリ 1 件の埋め込みは CPU で十分速い。
  一括インジェストはオフライン処理なので問題ない）。遅すぎる場合のみ `--gpu-memory-utilization` を 0.85 に下げて GPU 共有を検討。

## 6. 設定・シークレット

- モデル名・vLLM URL・Qdrant URL 等はすべて環境変数（`.env`）で注入。`.env` はコミットしない。
- 外部 API キー（使う場合のみ）も同様。
