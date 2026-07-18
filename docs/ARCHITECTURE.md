# アーキテクチャ / 技術選定

- 版: v0.8（2026-07-18, Fable 改訂 — **FR-39 確認質問の専用回答フォーム**（利用者指示・`docs/UI_CLARIFICATION_FORM.md`）。§3 SSE の `done` に additive フィールド `kind: "clarification" | null` を追加。ask_user 終端をフロントへライブ通知し、専用回答フォーム＋composer ロック（FR-27 と同型の elicitation 文法）を駆動する。エージェント側ツール契約・履歴サニタイズは不変）
- v0.7（2026-07-18, Fable 改訂 — **FR-36 探索思考のライブステータス**（利用者指示・`docs/AGENT_STATUS_STREAMING.md`）。decide / navigator の LLM 判断をストリーミング化し、生成途中の thought を `status.partial: true` で逐次配信（§3 SSE に additive フィールド追加）。待ち時間主因の実測（decide 3.3〜5.1 秒/回）と guided JSON ストリーミングの成立検証も同文書に記録）
- v0.6（2026-07-18, Fable 改訂 — **FR-35 生成 LLM の本番既定を 31B PP=2 へ切替**（利用者指示）。①backend を `network_mode: host` 化し `VLLM_BASE_URL=http://127.0.0.1:8000/v1` に統一 — PP=2（ホスト直）でも 12B（compose vllm の 127.0.0.1:8000 公開）でも**同一 URL** になり、切り戻しは「どちらのサーバーを立てるか＋`LLM_MODEL`」だけで済む ②compose backend の `depends_on` から vllm を除去（12B は明示起動時のみ）③`serve-31b.sh` をデタッチ起動・start/stop/status/logs 化・`max-num-seqs 8`。切替・切り戻し手順は `docs/PP2_MULTINODE_GUIDE.md` §6-9）
- v0.5（2026-07-18, Fable 改訂 — **FR-34 ハーネス v6 ReAct 化**。①エージェント制御を decide ループ＋ツールへ刷新（`docs/AGENT_REACT.md` v1.0・`docs/AGENT_ARCHITECTURE.md` v2.0）②生成 LLM の **31B 復帰を PP=2（本機+nubia）で検証完了**（PoC・実 LLM E2E 全合格。原理と構築: `docs/PP2_MULTINODE_GUIDE.md`）。**本番既定はまだ 12B 単機**（PP=2 への切替はエンドポイント差し替えのみ・運用判断待ち）③コンテキスト窓 env を `VLLM_MAX_MODEL_LEN` に改名（旧 `LLM_CONTEXT_WINDOW` フォールバックあり））
- v0.4（2026-07-13, Fable 改訂 — ブラッシュアップ対応。①スレッド一覧/名前変更/削除 API を追加（FR-7）②登録 API から属性 `role` を削除（FR-6 改訂・users テーブルは rebuild マイグレーション）③時間コンテキスト注入を新設（FR-8, §7））
- v0.3（2026-07-12, Fable 改訂 — **利用者指示によるモデル構成変更**。①埋め込みを bge-m3(CPU) → **Qwen/Qwen3-Embedding-8B（第2GPUサーバー・vLLM serve）** に変更。②生成 LLM を Gemma4-31B → **より小パラメータの Gemma 4**（同時利用者数とコンテキスト長を優先）に変更。ハーネス v5 と同時）
- v0.2（2026-07-12, Fable 改訂 — Web 検索を ddgs → Tavily に変更。ハーネス v4 と同時）
- v0.1（2026-07-11, Fable 決定）
- 「確定済み仕様」（CLAUDE.md）以外の選定はここに記録する。変更したい場合は Fable が本ファイルを更新してから実装する。

## 1. コンポーネント構成

```
[Vue 3 SPA] --HTTP/SSE--> [FastAPI backend] --OpenAI互換API--> [vLLM 生成]  ← 本番既定: Gemma 4 12B 単機（本機 ibera RTX 3090 Ti）
                               |                                  └ 検証済み代替: Gemma 4 31B PP=2（ibera + nubia RTX 3090・Ray、16k 窓。infra/pp2）
                               |--OpenAI互換 /v1/embeddings--> [vLLM 埋め込み (Qwen3-Embedding-8B)]  ← GPUサーバー2 gouin
                               |--> [Qdrant] (学内ナレッジ ベクトル検索)
                               |--> [Web Search] (Tavily API, 抽象化レイヤ経由)
```

frontend/backend/vllm(生成)/qdrant は本機の docker compose で起動する（vLLM は GPU 割当、`--gpus all`）。
**埋め込み用 vLLM は第2GPUサーバーで別途起動**し、backend からは `EMBEDDING_BASE_URL` で接続する（2026-07-12 利用者指示）。

### ポート割当（2026-07-11 Fable 決定、2026-07-12 v0.3 追記）

| サービス | ポート |
|---|---|
| frontend (Vite dev / nginx) | 5173 |
| backend (FastAPI) | **8080** |
| vLLM（生成、本機） | 8000 |
| vLLM（埋め込み、第2GPUサーバー gouin） | 8001（`EMBEDDING_BASE_URL` = `http://${Second_GPUsever}:8001/v1`） |
| Qdrant | 6333 |

backend のローカル起動・Vite の `/api` プロキシ先はともに 8080 とする（8000 は vLLM が使うため）。
プロキシ先は `VITE_API_PROXY_TARGET` 環境変数で上書き可能にする。

### 本番公開構成（2026-07-14 Fable 決定）

本番はホストの Nginx で公開する（https://ibera.cps.akita-pu.ac.jp）。

- フロント: `npm run build` の dist を /var/www に配置し、ホスト Nginx が直接配信する。frontend コンテナは本番では起動しない。
- バック: ホスト Nginx が `/api/` を `http://127.0.0.1:8080` へリバースプロキシする。`/api/chat` は SSE のため `proxy_buffering off`・`proxy_read_timeout 300s` が必須。
- docker compose の公開ポートはすべて `127.0.0.1:` バインドとする（Docker の port publish はホストのファイアウォールを素通りするため、vLLM・Qdrant・backend への外部直アクセスを遮断する目的）。
- 本番起動（FR-35 以降）: 生成 31B PP=2 を先に立て（`infra/pp2/` — nubia worker → ibera head →
  `serve-31b.sh`）、`docker compose up -d backend`（depends_on で qdrant も起動。**vllm サービスは
  起動しない** — 12B は切り戻し時のみ明示起動）。手順の正: `docs/PP2_MULTINODE_GUIDE.md` §6-9。

## 2. 技術選定と理由

| 項目 | 選定 | 理由 |
|---|---|---|
| フロントエンド | Vue 3 + Vite + Tailwind CSS + Pinia | 演出の参照実装 guidanceLLM2 と同スタックにし、Ver1.0 の「完全再現」をコード流用レベルで保証するため |
| Markdown 描画 | marked | 参照実装と同じ |
| バックエンド | Python 3.11+ / FastAPI | SSE・非同期・LLM エコシステムとの親和性 |
| エージェント制御 | LangGraph **1.2.9**（**定義＝実行**・FR-33 で一本化、`docs/LANGGRAPH_MIGRATION.md`）。**2026-07-18 FR-34 でハーネス v6 = ReAct 化**（`docs/AGENT_REACT.md` v1.0） | **decide ループ**（guided JSON）が retrieve / search / web_search / campus_navigator / ask_user / finish を毎ターン選択。停止はコンテキスト予算（実効窓の 70%/85%）で、周回カウンタは全廃。status/token/map は `get_stream_writer()` の custom イベントでノード内から送出。**LangSmith 系環境変数（`LANGCHAIN_TRACING_V2` / `LANGSMITH_TRACING`）は設定しない**（テレメトリ無効を維持） |
| LLM サービング | vLLM（OpenAI 互換サーバ） | 確定仕様。バックエンドからは OpenAI クライアントで接続 |
| LLM モデル | 本番既定: **`google/gemma-4-31B-it-qat-w4a16-ct` の PP=2**（2026-07-18 FR-35 利用者指示）。緊急切り戻し先: **`google/gemma-4-12B-it-qat-w4a16-ct` 単機**（compose vllm サービスとして定義を保持） | 31B は本機+nubia の 2 筐体パイプライン並列（PP=2・Ray）: 16k 窓・decode 37.9 tok/s・prefix cache 98.8% 短縮・実 LLM E2E 全合格（FR-34、`docs/PP2_MULTINODE_GUIDE.md`）。ハーネス v6 はモデル非依存で、12B への切り戻しは PP 停止→compose vllm 起動→`LLM_MODEL` 差し替えのみ（同一 URL・§6-9 runbook）。thinking 非対応・`chat_template_kwargs` を送らない規約は両モデル共通（AGENT_HARNESS.md §4） |
| 埋め込み | **`Qwen/Qwen3-Embedding-8B`（第2GPUサーバー・vLLM serve・OpenAI 互換 /v1/embeddings）** | **2026-07-12 利用者指示**: bge-m3(CPU) から変更。MTEB 多言語で最高水準・日本語検索に強い。生成用 GPU と取り合わないよう別マシンで提供。クエリ側 instruct プレフィックス等の利用規約はハーネス v5 §V5-1 | 
| 埋め込み（旧） | `BAAI/bge-m3`（CPU） | v0.2 までの構成。`EMBEDDING_BASE_URL` 未設定時の開発用フォールバックとしてコードパスは残す |
| リランカー | `BAAI/bge-reranker-v2-m3`（任意、Phase 3 で効果測定） | 検索精度向上の定番。効果がなければ外す |
| ベクトル DB | Qdrant（docker） | 運用が軽く、メタデータフィルタが強い。compose に載せやすい |
| Web 検索 | **Tavily API**（`TAVILY_API_KEY` を `.env` で供給。httpx 直、SDK 不使用）。`SearchProvider` インターフェースで抽象化 | **2026-07-12 利用者指示で ddgs から移行**。`include_domains` によるドメイン制限と `raw_content`（本文同梱）で検索品質とレイテンシを改善（AGENT_HARNESS.md §V4）。**2026-07-14 FR-18-1**: 枠超過等（401/403/429/432/433）でサーキットブレーカー作動 → Web ステップをスキップしナレッジのみで継続（`docs/RELEASE_PREP.md` §1） |
| PWA 配布 | `frontend/public/manifest.json` ＋ アイコン一式（`public/icons/`、apple-touch-icon）。Nginx 公開・HTTPS 必須 | **2026-07-14 FR-18-4**。Service Worker はスコープ外（`docs/RELEASE_PREP.md` §4） |
| ストリーミング | SSE（`text/event-stream`） | 単方向で十分。WebSocket より単純 |

## 3. API / SSE イベントスキーマ

### エンドポイント一覧

```
POST   /api/auth/register   ニックネーム登録（docs/UI_LOGIN.md。2026-07-13 から role なし）
POST   /api/auth/login      ログイン
GET    /api/auth/me         セッション確認 (Bearer)
POST   /api/chat            チャット送信 → SSE ストリーム (Bearer)
GET    /api/threads         自分のスレッド一覧（updated_at 降順。id/title/created_at/updated_at）(Bearer)
GET    /api/threads/{id}    スレッド履歴取得 (Bearer)
PATCH  /api/threads/{id}    スレッド名変更（body: {"title": "..."} 1〜60文字）(Bearer)
DELETE /api/threads/{id}    スレッド削除（メッセージも CASCADE 削除、204）(Bearer)
GET    /api/health          ヘルスチェック（vLLM/Qdrant 疎通含む）
```

- ユーザー・スレッドの永続化は **SQLite**（`backend/data/`、ボリュームマウント）。
  規模（オープンキャンパス 1 日イベント）に対して RDB サーバは過剰なため。
- `/api/chat` と `/api/threads` は Bearer トークン必須。無効なら 401。

### チャット SSE

`POST /api/chat`（リクエスト body: `{"message": "<質問文>", "thread_id": "<既存スレッドID または null>",
"origin_node": "<キャンパスノードid（任意・FR-27。マップタップによる現在地申告）>"}`。SSE ストリームを返す。
`origin_node` 省略時は従来と完全同一挙動。指定時は backend が「現在地は〇〇です。＋message」を内部合成して
エージェント入力・履歴に用い、user メッセージの `map_json` に `origin_select` メタを保存する — MAP_CARD.md §11-2）

```
event: status
data: {"step": "analyze" | "retrieve" | "search" | "web_search" | "evaluate" | "generate",
       "text": "学内ナレッジを検索しています…",
       "partial": true | false}   // FR-36。true = 進行中思考の伸長断片（フェードなしで書き換え）

event: token
data: {"text": "秋田県立"}

event: map
data: {"mode": "route" | "place" | "ask_origin",
       "origin": {"node": "...", "label": "..."} | null,
       "destination": {"node": "...", "label": "...", "room": "..." | null, "floor": 4 | null} | null,
       "path": {"nodes": [...], "edges": [...]},   // mode=route のみ
       "steps": ["..."],                            // mode=route のみ
       "prompt": "...", "question": "..."}          // mode=ask_origin のみ

event: done
data: {"thread_id": "...", "message_id": "...",
       "sources": [{"title": "...", "url": "...", "type": "knowledge" | "web"}],
       "kind": "clarification" | null}   // FR-39。clarification = ask_user 終端（専用回答フォームを活性化）

event: error
data: {"message": "..."}
```

- `status` は各ステップ開始時に必ず送る（FR-2）。`text` は日本語の短文で、フロントはそのまま表示する。
  FR-36 で decide / navigator の思考中は `partial: true` の伸長系列（同一 step・text が単調伸長）を
  逐次送り、確定時に `partial: false` で全文を送る（詳細: `docs/AGENT_STATUS_STREAMING.md` §2〜4）。
- `token` 受信開始でフロントはローディング演出を終了し、本文の逐次描画に切り替える。
  表示は FR-25 の「なめらか文字送り」でペーシングする（`docs/RELEASE_PREP.md` §14。frontend のみの
  変更で、SSE スキーマ・backend は不変）。
- `done` の `sources` は回答末尾の出典表示に使う（FR-25 以降、表示は文字送り完了後）。
- `done` の `kind: "clarification"` は ask_user 終端の合図（FR-39）。フロントは文字送り完了後に
  専用回答フォームを活性化し composer をロックする（詳細: `docs/UI_CLARIFICATION_FORM.md`。
  ask_origin 終端は従来どおり `map.mode: "ask_origin"` で合図し `kind` は null）。
- `map` は FR-26 のマップカード（2026-07-17 追加、詳細: `docs/MAP_CARD.md`）。token 完了後・`done` 直前に
  最大 1 回。送らないケースのストリームは従来と完全同一（後方互換）。リクエスト body は不変
  （マップタップの現在地は合成メッセージとして通常の `message` で送る — MAP_CARD.md §7-3）。

## 4. リポジトリ構成（計画）

```
oc_2026/
├── CLAUDE.md / AGENTS.md / README.md
├── docs/                  # 仕様書（常に正）
├── frontend/              # Vue 3 SPA
│   ├── public/app-icon.png   # ルートの app-icon.png をコピー
│   ├── public/manifest.json  # PWA マニフェスト（FR-18-4）
│   ├── public/icons/         # PWA アイコン（192/512/maskable、Fable 生成）
│   └── src/...
├── backend/
│   ├── app/               # FastAPI (api, agent, rag, search, llm)
│   └── tests/
├── knowledge/             # RAG ナレッジ（Markdown, docs/KNOWLEDGE.md 準拠）
│   └── ingest/            # 取り込みスクリプト
├── docker-compose.yml     # frontend, backend, vllm, qdrant
└── .env.example
```

## 5. vLLM 起動構成（2026-07-12 v0.3 改訂: 生成=小型 Gemma 4 / 埋め込み=第2GPUサーバー）

### 5.1 生成用 vLLM（本機 RTX 3090 Ti 24GB、ポート 8000）

**2026-07-12 利用者指示**により、31B から**より小パラメータの Gemma 4** に変更する。
背景: 31B は重みロードだけで 19.79GiB を消費し KV が極めて重く（約0.85MB/token）、
**max-model-len 2816 が上限**だった（実測）。RAG コンテキストが窮屈になり検索ヒットを
generate に届けられない事象の一因（AGENT_HARNESS.md §V5-0）。複数人同時利用にも不足。

> **2026-07-18 追記（FR-34）**: 上記 2816 問題は **PP=2（本機+nubia の 2 筐体パイプライン並列）で
> 解消を検証済み**（16k 窓・PoC P1〜P4 と実 LLM E2E 全合格）。31B PP=2 の起動定義・手順は
> `infra/pp2/`（スクリプト・README）と `docs/PP2_MULTINODE_GUIDE.md`（原理・構築・トラブルシュート）。
> 本節の 12B 単機構成は**本番既定 兼 当日の緊急切り戻し先**として維持する。

- モデル: **`google/gemma-4-12B-it-qat-w4a16-ct` で確定**（2026-07-12 利用者承認・Fable が HF 存在確認済み）。
- 受け入れ条件（実測で確認・Fable 検収）:
  - `--max-model-len` **8192 以上**（目標 16384）
  - `--max-num-seqs` **8 以上**（オープンキャンパス当日の同時利用想定）
  - 応答品質: EVAL_QUESTIONS.md の回帰質問（§G 含む）で v4 構成と同等以上
- 起動構成（ルート docker-compose.yml の vllm サービスを更新。初期値、実測で調整）:

```bash
  --model google/gemma-4-12B-it-qat-w4a16-ct \
  --max-model-len 16384 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.92 \
  --limit-mm-per-prompt '{"image": 0}'
```

  12B w4a16 の重みは概ね 7〜8GiB のため 24GB で 16384 コンテキスト × 8 seqs は
  収まる見込み（KV 実測で OOM するなら 12288 → 8192 の順に縮退。8192 未満は不可）。
  31B で必要だった `--enforce-eager` は外して起動を試し、OOM 時のみ復活させる。
- 確定後、`LLM_CONTEXT_WINDOW` / `LLM_ANSWER_MAX_TOKENS` を実測値へ更新する
  （目標: `LLM_CONTEXT_WINDOW=16384`（最低 8192）、`LLM_ANSWER_MAX_TOKENS=1024`）。
- `chat_template_kwargs: {"enable_thinking": false}` は **Gemma に送らない**（Qwen 固有。AGENT_HARNESS.md §4）。
- 旧 31B 構成（`google/gemma-4-31B-it-qat-w4a16-ct`、max-model-len 2816、enforce-eager）は撤去。

### 5.2 埋め込み用 vLLM（第2GPUサーバー「gouin」、ポート 8001）

**2026-07-12 利用者指示**: 生成用 GPU と取り合わないため、別マシン **gouin** の GPU で
`Qwen/Qwen3-Embedding-8B` を vLLM の embedding タスクで提供する（OpenAI 互換 `/v1/embeddings`）。

- 起動ファイル: **`deploy/gouin/docker-compose.yml`**（Fable 作成済み）。gouin 上で
  `docker compose up -d` するだけでよい（起動は利用者が実施）。ポートは 8001。
- gouin の IP は本機ルートの `.env` に **`Second_GPUsever`** キーで記載済み（利用者管理・値はコミットしない）。
  ルート docker-compose.yml の backend は
  `EMBEDDING_BASE_URL: http://${Second_GPUsever}:8001/v1` で参照する。
- 埋め込みモードのフラグは **`--runner pooling`**（2026-07-12 gouin 実機で確定。旧 `--task embed` は現行 vLLM イメージで廃止済み。モデルは位置引数で渡す）。
- backend / ingest は `EMBEDDING_BASE_URL` 経由で接続。
  **未設定時は従来の bge-m3(CPU) ローカル実行にフォールバック**（開発環境用）。
- ベクトル次元は **4096**（bge-m3 の 1024 から変更）。**Qdrant コレクションの再作成と全ナレッジの
  再インジェストが必須**（ハーネス v5 §V5-1）。
- クエリ側 instruct プレフィックス・title 込み埋め込み等の利用規約は AGENT_HARNESS.md §V5-1 を正とする。

## 6. 設定・シークレット

- モデル名・vLLM URL・Qdrant URL 等はすべて環境変数（`.env`）で注入。`.env` はコミットしない。
- 外部 API キー（使う場合のみ）も同様。

## 7. 時間コンテキスト注入（FR-8, 2026-07-13 追加）

- `backend/app/services/time_context.py` が **JST（zoneinfo Asia/Tokyo）** の現在時刻から
  日本語の時間コンテキスト文字列を**決定論的に**生成し、`graph.py` の generate 用システムプロンプト
  （および mock エージェント）へ注入する。LLM には計算済みの値だけを渡す。
- 状態遷移: 開催前（あと N 日）→ 当日開場前（開場まであと M 分）→ 開催中（開催中イベント＋60 分以内に始まるイベント）→ 当日終了後 → 開催後。
- イベントスケジュールは `backend/app/data/oc2026_schedule.json`。**検証済みの時刻のみ収載**
  （出典: knowledge/ の転記または大学公式 PDF。検証できない時刻は載せず、載っていないイベントの
  時刻を LLM が推測しないようプロンプトで禁止する）。
- プロンプト側ルール: 「残り日数・分数・開催中イベントは時間コンテキストの記載値のみを使う。自分で計算・推測しない」。
