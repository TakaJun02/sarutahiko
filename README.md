<div align="center">

<img src="app-icon.png" width="108" alt="APU-Navi icon" />

# APU-Navi

**秋田県立大学 本荘キャンパスを案内する、フルローカル LLM の AI エージェント**

検索が「当たる」ことを祈らない —
**欲しい情報に「届く」まで、エージェント自身が探し方を変えながら到達する**キャンパスガイド。

[![Vue 3](https://img.shields.io/badge/Vue-3.5-42b883?logo=vuedotjs&logoColor=white)](frontend/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python%203.11-009688?logo=fastapi&logoColor=white)](backend/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.9-1c3c3c)](docs/AGENT_REACT.md)
[![vLLM](https://img.shields.io/badge/vLLM-OpenAI%20compatible-4b32c3)](docs/PP2_MULTINODE_GUIDE.md)
[![Gemma 4](https://img.shields.io/badge/Gemma%204-31B%20w4a16%20·%20PP%3D2-4285f4?logo=google&logoColor=white)](docs/ARCHITECTURE.md)
[![Qdrant](https://img.shields.io/badge/Qdrant-784%2B%20chunks-dc244c)](knowledge/)
[![PWA](https://img.shields.io/badge/PWA-installable-5a0fc8)](frontend/public/manifest.json)

**本番:** https://ibera.cps.akita-pu.ac.jp

</div>

---

## ✨ これは何？

**APU-Navi** は、秋田県立大学 本荘キャンパスの学部・学科、研究室、施設、アクセス、
オープンキャンパス当日のイベントについて自然言語で質問できる AI エージェントです。
オープンキャンパス 2026 来場者（高校生・保護者）からの質問対応を主戦場にしています。

クラウド LLM API は一切使いません。**生成も埋め込みも研究室の GPU 3 台で完結**します —
Gemma 4 31B を 2 筐体パイプライン並列（PP=2）でサービングし、
学内ナレッジ 130 文書・784+ チャンクを Qdrant でベクトル検索、
足りない情報だけ Tavily で Web 検索します。

そしてこのプロダクトの核心は、モデルでもインフラでもなく、**次章の ReAct エージェントの設計**です。

## 🧠 このプロダクトの核 — 「欲しい情報に届く」ための 3 つの設計

RAG プロダクトの回答品質は、生成よりも先に**検索の到達性**と**コンテキストの使い方**で決まります。
APU-Navi は固定の検索パイプラインを持たず、LangGraph 上の **decide ノード（LLM・guided JSON）が
毎ターン「次に何をするか」を選ぶ** ReAct ループとして探索します。
その質を決めたのが、次の 3 つの設計判断です。

### ① 意味検索と文字列検索の両輪を持たせる

- **課題**: ベクトル検索だけでは「D404」「〇〇研究室」「バス 何時」のような
  **固有表現・完全一致系の質問に弱い**。埋め込み空間では部屋番号や教員名は「近く」ならない。
- **打ち手**: 意味ベクトル検索 `retrieve` に加えて、**決定的な字句グレップ `search`**
  （表記ゆれバリアント展開付き・LLM 不使用）を並置し、質問の性質に応じて decide が使い分ける。
- **効果**: 「雰囲気で聞かれた質問」は retrieve が、「名指しの質問」は search が拾う。
  片方が空振りしても decide が観測からもう片方へ切り替えるため、**欲しい情報へ確実に到達できる**。

### ② 断片 → 全文の 2 段取得（最も効いた工夫）

- **課題**: RAG の宿命のジレンマ。検索ヒットをそのまま大量に積むと**無駄な情報でコンテキストが
  圧迫**され、チャンクを絞ると**情報を取りこぼす**。どちらに倒しても回答品質が落ちる。
- **打ち手**: 検索ツールの観測は 1 件 **500 トークン上限の抜粋**に圧縮して返し、
  切り詰めたことと出典ファイル（`truncated` / `file_id`）を明示する。そのうえで
  「この文書は続きが要る」とエージェント自身が判断したものだけ、**`get_docs` で元ドキュメントの
  全文**を取得する。
- **効果**: **「情報の取りこぼし」と「コンテキストの圧迫」の回避を同時に成立**させた。
  どの文書を深掘りするかの判断を固定ルールではなくエージェントに委ねたことが、
  このプロダクトで**最も回答品質に効いた**設計判断。

### ③ 経路案内はサブエージェントに切り出す

- **課題**: メインエージェントにツールを増やすほど、decide の**ツール選択ミス**が増える。
  経路案内（場所解決・経路探索・出発地確認）はそれ自体が一つのドメインで、ツール数が多い。
- **打ち手**: 経路系の判断をメインのメニューに並べず、**`campus_navigator` サブエージェント 1 つに
  集約**。各観測に LLM を挟んで整形する案も検討したが、レスポンス時間が伸びるため不採用 —
  **時間コストゼロの「構造による解決」**を選んだ。サブエージェント側もまず fast path
  （決定的・LLM 0 回）で解決を試み、失敗時だけ内部 decide に落ちる 2 段構え。
- **効果**: メインの選択肢は 7 つに保たれ選択精度が安定。経路質問の大半は LLM 追加呼び出し
  なしで返り、**速度と精度を両立**した。

### 3 つの工夫が組み込まれた ReAct ループ全体

図中の ①②③ が上の設計に対応します。探索の停止は周回数ではなく
**コンテキスト予算**（実トークン計測で 70% soft / 85% hard）で決めます。

```mermaid
flowchart TD
    Q(["ユーザー質問"]) --> DE
    DE["<b>decide</b>（LLM・guided JSON）<br/>{thought, action, action_input}<br/>thought は SSE でライブ実況"]

    DE -->|retrieve| RT["🔎 <b>retrieve</b> ①<br/>意味ベクトル検索<br/>（Qwen3-Embedding + Qdrant）"]
    DE -->|search| SE["🔤 <b>search</b> ①<br/>決定的字句グレップ<br/>（表記ゆれバリアント展開）"]
    DE -->|get_docs| GD["📄 <b>get_docs</b> ②<br/>断片の元ドキュメント<br/>全文取得（file_id 単位）"]
    DE -->|web_search| WS["🌐 <b>web_search</b><br/>Tavily<br/>（サーキットブレーカー付き）"]
    DE -->|campus_navigator| NV["🗺️ <b>campus_navigator</b> ③<br/>経路サブエージェント<br/>fast path（LLM 0回）→ 内部 decide ≤3手"]

    RT -->|"観測（500 tok 上限・truncated / file_id 明示）②"| DE
    SE -->|観測| DE
    GD -->|"観測（本文 ~1.5k tok）"| DE
    WS -->|観測| DE
    NV -->|"route / place（観測）"| DE
    NV -->|"出発地不明 → ask_origin でターン終端"| DONE

    DE -->|ask_user| AU["❓ <b>ask_user</b>（human-in-the-loop）<br/>interrupt で実行を中断し来場者に質問<br/>（専用回答フォーム）"]
    AU -->|"来場者の回答（観測）<br/>※ターンを跨いで同一実行を再開"| DE
    DE -->|finish| GE["✍️ <b>generate</b><br/>evidence から回答をストリーミング生成"]
    GE --> DONE(["done"])
```

| ツール | 実体 | 役割 |
|---|---|---|
| `retrieve` ① | 埋め込み vLLM + Qdrant | 意味ベクトル検索。「雰囲気で聞かれた質問」を拾う |
| `search` ① | Qdrant スキャン（LLM 不使用） | 決定的な文字列検索。部屋番号・固有名詞に強い |
| `get_docs` ② | Qdrant（LLM 不使用） | 検索でヒットした断片の**元ドキュメント全文**を取得 |
| `web_search` | Tavily API | 学内ナレッジにない情報だけ Web で補完 |
| `campus_navigator` ③ | サブエージェント | 学内の場所解決・経路探索（Dijkstra）・マップカード構築 |
| `ask_user` | LangGraph interrupt/resume | 質問が曖昧なとき来場者に聞き返す human-in-the-loop。実行を checkpoint で中断し、回答を**観測として decide へ持ち帰って**同じ探索を継続 |
| `finish` → generate | 生成 vLLM | 集めた evidence から回答を生成 |

### ③ の中身 — campus_navigator サブエージェントの内部アーキテクチャ

`campus_navigator` 自体も 1 体の ReAct エージェントです。ただし**まず決定的な fast path
（LLM 0 回）で解決を試み、失敗したときだけ内部 decide ループに落ちる** 2 段構えで、
経路質問の大半を LLM なしで返します。

```mermaid
flowchart TD
    IN(["依頼 = request + 原質問 + 直近履歴 + 解決済み事実<br/>（ハーネスが機械的に合成 — メイン LLM の言い換えに依存しない）"]) --> FP

    FP["⚡ <b>fast path</b>（決定的・LLM 0回）<br/>find_locations_in_text + resolve_location で<br/>目的地・出発地を即時解決"]
    FP -->|解決成立| OUT
    FP -->|曖昧・解決失敗| ND

    ND["<b>内部 decide</b>（LLM・guided JSON・上限 3 手）"]
    ND -->|resolve_place| RP{{"resolve_location<br/>場所名 → 経路グラフのノード解決"}}
    ND -->|find_route| FR{{"Dijkstra 経路探索＋ステップ文生成<br/>（campus_map.py 純関数）"}}
    ND -->|ask_origin| VA["🛡️ 決定的バリデータ<br/>・目的地が未解決 → 差し戻し<br/>・出発地が履歴で既知 → 差し戻し（find_route を使え）"]
    RP -->|観測| ND
    FR -->|観測| ND
    VA -->|不合格（エラー観測）| ND
    VA -->|合格| NO["need_origin<br/>turn_terminated を構造伝播"]

    ND --> OUT["構造化結果<br/>route / place / not_navigable"]
    OUT --> MAIN(["メイン decide へ観測として返す<br/>map_payload / sources は state にマージ → generate が使う"])
    NO --> AO(["respond_need_origin でターン終端<br/>→ マップタップで現在地申告（composer ロック）"])
```

戻り値は構造化 4 種のみ:

| type | 内容 | メイン側の扱い |
|---|---|---|
| `route` | 経路ステップ文（決定的テンプレ由来）＋マップカード payload ＋出典 | 観測として decide へ。generate が回答に使う |
| `place` | 所在ファクト＋マップカード payload ＋出典 | 同上 |
| `need_origin` | 出発地確認のマップカード（ask_origin） | **ターン終端**。来場者がマップをタップして現在地を申告 |
| `not_navigable` | 対象外・解決不能の理由 | 観測として decide へ（web_search 等で続行） |

設計原則は 2 つ。**LLM に空間推論をさせない** — 場所解決・Dijkstra・ステップ文生成は
すべて `campus_map.py` の純関数で、LLM は「どのツールを呼ぶか」しか決めない。
**第二の話者にしない** — サブエージェントは構造化結果を返す専門家に徹し、来場者向けの
最終文章は常にメインの generate が一本で書く（token→map→done の順序保証と出典組立を
1 箇所に保つため）。ask_origin の発動も LLM の提案を決定的バリデータが裁く構造で、
モデルの従順さに依存しません。

ハーネスの仕様詳細は [`docs/AGENT_REACT.md`](docs/AGENT_REACT.md)、
全体図は [`docs/AGENT_ARCHITECTURE.md`](docs/AGENT_ARCHITECTURE.md)、
ask_user の human-in-the-loop 化は [`docs/AGENT_HITL.md`](docs/AGENT_HITL.md)。

## 🚀 主な機能

- 🧠 **Agentic RAG（ReAct ループ）** — 上記 3 つの設計を組み込んだ decide ループが
  `retrieve` / `search` / `get_docs` / `web_search` / `campus_navigator` / `ask_user` / `finish` を毎ターン自律選択
- 💭 **思考のライブ実況** — 「学内ナレッジを検索しています…」だけでなく、エージェントが**いま生成中の思考そのもの**を SSE でストリーミング表示（guided JSON のストリーミングデコード）
- 🗺️ **経路案内マップカード** — 「受付から学部棟Ⅰまで行きたい」で自作ベクターマップに経路を描画。出発地不明ならマップタップで現在地を申告、全画面ビューア（pinch / ダブルタップ）付き
- ✍️ **なめらか文字送り** — トークン到着をクライアント側でペーシングし、ChatGPT/Gemini 級の読み心地に
- ❓ **確認質問フォーム** — エージェントが逆質問（`ask_user`）したターンは専用回答フォーム＋composer ロックの elicitation UI に切り替え。回答は human-in-the-loop（LangGraph interrupt/resume）で**同一実行に観測として戻り**、集めた evidence を保ったまま探索を継続
- 🌌 **Gemini 実スクショ準拠のアンビエント UI** — ログイン=白×パステルブルーの霧、チャット=黒×深インディゴのグロー。待機中は「雲が流れる」思考中モーション
- 📱 **PWA** — ホーム画面に追加してアプリとして起動。スマホ縦画面の利用が主戦場
- 🧵 **会話スレッド永続化** — ニックネーム登録だけの軽量ログインで、履歴・名前変更・削除に対応（SQLite）
- 🛡️ **フェイルセーフ** — Tavily 枠超過時はサーキットブレーカーが作動し、学内ナレッジのみで回答継続
- 🥚 **隠し機能** — 合言葉を知っている人だけが出会える"なにか"がいます

## 🏗️ システム構成

```mermaid
flowchart LR
    subgraph client["ブラウザ（Vue 3 SPA / PWA）"]
        UI["ChatView / MapCard<br/>SSE 受信・なめらか文字送り"]
    end
    subgraph ibera["ibera（RTX 3090 Ti 24GB）"]
        BE["FastAPI backend<br/>LangGraph ReAct ハーネス"]
        VLLM["vLLM 生成<br/>Gemma 4 31B w4a16<br/>PP=2 前半層（rank0）"]
        QD[("Qdrant<br/>campus_knowledge<br/>784+ チャンク")]
        DB[("SQLite<br/>users / threads / messages")]
    end
    subgraph nubia["nubia（RTX 3090）"]
        PP2["vLLM PP=2 後半層（rank1）<br/>Ray / NCCL"]
    end
    subgraph gouin["gouin（第2GPUサーバー）"]
        EMB["vLLM 埋め込み<br/>Qwen3-Embedding-8B"]
    end
    TAVILY["Tavily Web Search<br/>（サーキットブレーカー付き）"]

    UI -- "POST /api/chat（SSE）" --> BE
    BE -- "guided JSON / streaming" --> VLLM
    VLLM -.-> PP2
    BE -- "/v1/embeddings" --> EMB
    BE -- "ベクトル検索" --> QD
    BE -- "httpx" --> TAVILY
    BE --> DB
```

1 つの質問に対しエージェントは `status`（思考実況）→ `token`（回答本文）→ `map`（経路カード）→
`done`（出典・確認質問フラグ）の SSE イベントを流します。スキーマの正は
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §3。

### 技術スタック

| レイヤ | 選定 |
|---|---|
| フロントエンド | Vue 3 + Vite + Tailwind CSS + Pinia + marked |
| バックエンド | Python 3.11 / FastAPI / SSE |
| エージェント制御 | LangGraph 1.2.9（StateGraph 定義＝実行・ReAct ハーネス v6・interrupt/resume HITL） |
| 生成 LLM | `google/gemma-4-31B-it-qat-w4a16-ct` — vLLM PP=2（ibera + nubia、16k 窓）。切り戻し先: 12B 単機 |
| 埋め込み | `Qwen/Qwen3-Embedding-8B` — 別 GPU サーバーで vLLM serve（OpenAI 互換 `/v1/embeddings`） |
| ベクトル DB | Qdrant |
| Web 検索 | Tavily API（`SearchProvider` で抽象化） |
| 永続化 | SQLite（1 日イベント規模に最適化） |

## ⚡ クイックスタート（Docker Compose）

前提: NVIDIA GPU + Docker（`--gpus` 対応）、埋め込みサーバー（`EMBEDDING_BASE_URL`）への疎通。
単機で動かす場合は compose 同梱の **Gemma 4 12B** を使います（`LLM_MODEL` を 12B に上書き）。

```bash
docker compose up -d qdrant vllm
python -m pip install -r backend/requirements.txt
python knowledge/ingest/ingest.py --recreate          # ナレッジ投入（130 文書 → 784+ チャンク）
LLM_MODEL=google/gemma-4-12B-it-qat-w4a16-ct docker compose up -d backend
docker compose up -d frontend
```

| サービス | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend health | http://localhost:8080/api/health |
| vLLM（生成） | http://localhost:8000/v1 |
| Qdrant | http://localhost:6333 |

> **本番構成（31B PP=2）**: nubia の worker → ibera の head → `serve-31b.sh` の順で
> 2 筐体サービングを立ててから `docker compose up -d backend`（compose の vllm サービスは起動しない）。
> 構築原理と runbook は [`docs/PP2_MULTINODE_GUIDE.md`](docs/PP2_MULTINODE_GUIDE.md) / [`infra/pp2/`](infra/pp2/)。

## 🛠️ ローカル開発

### Backend

```bash
cd backend
python -m pip install -r requirements.txt
AGENT_MODE=mock uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

`AGENT_MODE=mock` なら GPU なしで起動できます。実エージェントを使う場合はリポジトリルートで
vLLM と Qdrant を立ち上げ、ナレッジを投入してから起動します。

```bash
docker compose up -d qdrant vllm
python knowledge/ingest/ingest.py --recreate
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

SQLite は既定で `backend/data/campus-guide.sqlite3` に作成されます。設定は `.env.example` を参照。

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite dev server は `/api` を `http://127.0.0.1:8080` にプロキシします
（`VITE_API_PROXY_TARGET` で上書き可）。

### テスト

```bash
pytest                        # backend（リポジトリルートで）
cd frontend && npm run test   # frontend（Vitest）
cd frontend && npm run build  # ビルド検証
```

## 📁 リポジトリ構成

```
oc_2026/
├── frontend/          # Vue 3 SPA（チャット UI・マップカード・ローディング演出・PWA）
├── backend/           # FastAPI（認証・スレッド・SSE チャット・ReAct エージェント）
│   └── app/agent/     # LangGraph ハーネス・キャンパス経路グラフ・navigator サブエージェント
├── knowledge/         # RAG ナレッジ 130 文書（学部・施設・アクセス・OC2026 イベント…）
│   └── ingest/        # Qdrant インジェストスクリプト
├── infra/pp2/         # Gemma 4 31B の 2 筐体 PP=2 サービング一式（Ray / serve-31b.sh）
├── deploy/            # 本番デプロイ関連
└── docs/              # 全仕様書（ドキュメントが常に正）
```

## 📚 ドキュメント

| ドキュメント | 内容 |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | システム仕様書（FR-1〜FR-42 の全機能要件と改訂履歴） |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 技術選定・API / SSE イベントスキーマ・本番公開構成 |
| [`docs/AGENT_ARCHITECTURE.md`](docs/AGENT_ARCHITECTURE.md) | エージェント全体のワークフロー図（mermaid） |
| [`docs/AGENT_REACT.md`](docs/AGENT_REACT.md) | ReAct ハーネス v6 の仕様（decide ループ・ツール契約） |
| [`docs/AGENT_HITL.md`](docs/AGENT_HITL.md) | ask_user の human-in-the-loop 化（interrupt/resume） |
| [`docs/PP2_MULTINODE_GUIDE.md`](docs/PP2_MULTINODE_GUIDE.md) | 31B 2 筐体パイプライン並列の原理・構築・切り戻し runbook |
| [`docs/MAP_CARD.md`](docs/MAP_CARD.md) | 経路案内マップカード（route / place / ask_origin） |
| [`docs/UI_LOADING_ANIMATION.md`](docs/UI_LOADING_ANIMATION.md) | ローディング演出 Ver1.0 → Ver5.0 |
| [`docs/KNOWLEDGE.md`](docs/KNOWLEDGE.md) | RAG ナレッジ構築計画（収集源・検証ルール） |

## 🤖 開発体制 — AI ペアによるドキュメント駆動開発

このリポジトリは **2 つの AI エージェントの分業**で開発されています。

| 役割 | 担当 |
|---|---|
| 仕様の決定・アーキテクチャ判断・コードレビュー | **Fable**（Claude Code） |
| 実装・サーベイ・ナレッジ収集 | **Codex** |

Fable が仕様を `docs/` に落とし、Codex が実装し、Fable が検収する。
仕様の不明点は [`docs/QUESTIONS.md`](docs/QUESTIONS.md) で裁定を仰ぎ、
**ドキュメントを常に正**として運用します。詳細は [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md)。

ブランチ運用: `main`（リリース）← `develop`（統合）← `feature/*`（作業）。PR は `develop` 向け。

---

<div align="center">

秋田県立大学 サイバーフィジカルシステム研究室（CPS Lab）
開発: 高橋 潤大 ／ Powered by **Gemma 4** — すべての推論は学内 GPU で

</div>
