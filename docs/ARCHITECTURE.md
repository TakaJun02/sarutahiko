# アーキテクチャ / 技術選定

- 版: v0.2（2026-07-12, Fable 改訂 — Web 検索を ddgs → Tavily に変更。ハーネス v4 と同時）
- v0.1（2026-07-11, Fable 決定）
- 「確定済み仕様」（CLAUDE.md）以外の選定はここに記録する。変更したい場合は Fable が本ファイルを更新してから実装する。

## 1. コンポーネント構成

```
[Vue 3 SPA] --HTTP/SSE--> [FastAPI backend] --OpenAI互換API--> [vLLM (Qwen3)]
                               |--> [Qdrant] (学内ナレッジ ベクトル検索)
                               |--> [Web Search] (Tavily API, 抽象化レイヤ経由)
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
| LLM モデル | `google/gemma-4-31B-it-qat-w4a16-ct`（**2026-07-11 利用者指定**） | 利用者指示によりQwen3-14B-AWQから変更。Apache-2.0・w4a16 量子化 31B。Gemma は thinking モード非対応のため Qwen 固有の `chat_template_kwargs` は送らない（AGENT_HARNESS.md §4） |
| 埋め込み | `BAAI/bge-m3` | 日本語を含む多言語で高性能。ローカル実行可 |
| リランカー | `BAAI/bge-reranker-v2-m3`（任意、Phase 3 で効果測定） | 検索精度向上の定番。効果がなければ外す |
| ベクトル DB | Qdrant（docker） | 運用が軽く、メタデータフィルタが強い。compose に載せやすい |
| Web 検索 | **Tavily API**（`TAVILY_API_KEY` を `.env` で供給。httpx 直、SDK 不使用）。`SearchProvider` インターフェースで抽象化 | **2026-07-12 利用者指示で ddgs から移行**。`include_domains` によるドメイン制限と `raw_content`（本文同梱）で検索品質とレイテンシを改善（AGENT_HARNESS.md §V4） |
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
data: {"step": "analyze" | "retrieve" | "search" | "web_search" | "evaluate" | "generate",
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

## 5. vLLM 起動構成（2026-07-11 改訂: Gemma 4 31B へ変更）

利用者指定により `google/gemma-4-31B-it-qat-w4a16-ct` を使用する（旧 Qwen3-14B-AWQ 構成は撤去）:

```bash
docker run --gpus all \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -p 8000:8000 vllm/vllm-openai:latest \
  --model google/gemma-4-31B-it-qat-w4a16-ct \
  --max-model-len 2816 \
  --max-num-seqs 4 \
  --gpu-memory-utilization 0.95 \
  --enforce-eager \
  --limit-mm-per-prompt '{"image": 0}'
```

- **2026-07-12 Fable 実測で確定**。重みロードだけで 19.79GiB を消費し、Gemma4 は KV が極めて重い
  （約0.85MB/token）ため、24GB では **max-model-len 2816 が上限**（8192/6144/4096/3584/3200/2880 で
  KV不足または実行時OOMを確認済み）。FP8 KV は SM86（3090 Ti）非対応。
- これに伴いハーネス側で**コンテキスト予算管理が必須**（環境変数 `LLM_CONTEXT_WINDOW=2816`、
  回答は `LLM_ANSWER_MAX_TOKENS=640`。チャンク・Webページ・履歴を予算内に切り詰める）。
- `--reasoning-parser qwen3` は**削除**（Gemma に不要）。
- `chat_template_kwargs: {"enable_thinking": false}` は **Gemma に送らない**（Qwen 固有。AGENT_HARNESS.md §4）。
- トレードオフ（利用者への注記）: Qwen3-14B-AWQ 構成では 16k コンテキストを確保できたが、
  指定モデルへの変更で 2816 に縮小。RAG の同時投入コンテキスト量が大きく制限される。
- モデル重みと `BAAI/bge-m3` はホストの HF キャッシュにダウンロード済み。compose では同じボリュームを使う（再ダウンロード禁止）。
- 埋め込み（bge-m3）は従来どおり **CPU で実行**。

## 6. 設定・シークレット

- モデル名・vLLM URL・Qdrant URL 等はすべて環境変数（`.env`）で注入。`.env` はコミットしない。
- 外部 API キー（使う場合のみ）も同様。
