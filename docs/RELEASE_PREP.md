# RELEASE_PREP — FR-18 リリース準備一式（利用者指示 5 点）

- 版: v0.1（2026-07-14, Fable 起草）
- 対象 FR: **FR-18**（`docs/SPEC.md` v0.10）
- 実装: Codex（デザイン判断を含む項は GPT-5.6Sol リード、Campus Signal 語彙の範囲内）
- 検収: Fable（本ドキュメント §6 チェックリスト）

2026-07-14 利用者指示の 5 点を 1 バッチで扱う（FR-13 と同形式）。

| # | 内容 | 領域 |
|---|---|---|
| 18-1 | Web 検索（Tavily）フェイルセーフ — 無料枠超過でもシステム継続 | backend |
| 18-2 | ヘッダーを「APU-Navi Powered by Gemma4」へ | frontend |
| 18-3 | ヘッダー右上の隠しリンク（CPS 研究室サイト） | frontend |
| 18-4 | PWA 対応（manifest.json ＋アイコン。Nginx 公開の準備） | frontend / docs |
| 18-5 | 会話履歴コンテキストを 4 ターンへ拡大 | backend |

---

## 1. FR-18-1 Web 検索フェイルセーフ（Tavily 無料枠超過耐性）

### 1.1 現状と課題

`TavilySearchProvider.search()`（`backend/app/search/tavily.py`）は HTTP エラー・タイムアウト・
不正レスポンスをすべて握って `[]` を返すため、**枠超過でシステムが落ちることは現状もない**。
課題は挙動の質:

- 枠超過（HTTP 432 等）後も、リクエストごとに最大 3 ラウンド × 複数クエリの HTTP 往復を
  無駄に繰り返す（フェイルファストしない）。
- ユーザーには「Webで最新情報を探検しています…」が表示されるのに、実際は何も取れていない。

### 1.2 仕様

**(a) プロバイダにサーキットブレーカーを実装**（`tavily.py`）:

- 「利用不可シグナル」と判定する HTTP ステータス: **401 / 403 / 429 / 432 / 433**
  （Tavily はプラン枠超過に 432 系を使う。401/403 はキー失効、429 はレート制限）。
- 上記を受けたら `unavailable_until = now + 600 秒`（クールダウン 10 分、モジュール定数化）。
  クールダウン中の `search()` は **HTTP を発行せず即 `[]`** を返す。
- クールダウン経過後の次回 `search()` は通常どおり HTTP を試行する（自動再プローブ。
  成功したら通常運転に自然復帰）。
- タイムアウト・5xx・接続断・パース失敗は**従来どおり `[]` を返すだけ**でブレーカーは発動しない
  （一過性エラーで 10 分沈黙しない）。
- `api_key` が空の場合も「利用不可」扱い（現行の即 `[]` は維持しつつ、下記 `available` が
  False を返すこと）。
- 公開プロパティ **`available: bool`** を追加（クールダウン中または key 空で False）。
- ログ: ブレーカー発動時に `logger.warning`（ステータスコードとクールダウン秒を含める）。

**(b) エージェント側で Web ステップ自体をスキップ**（`backend/app/agent/graph.py`）:

- `_should_run_web_search()` の冒頭で
  `getattr(self.search_provider, "available", True)` が False なら即 `False` を返す。
  → ルーティングが `web_search` を選ばず `generate` へ直行し、
  「Webで探検しています…」という**空振りステータスも出ない**。
- `getattr` のデフォルト True により、`available` を持たないテスト用スタブ・モックは無改修で動く。
- SSE イベントスキーマ（step 値・イベント種別）は**変更しない**。

**(c) 回答品質の担保は既存仕様のまま**: Web が使えない場合はナレッジのみで生成し、
根拠が無ければ FR-1 の「分からない＋問い合わせ先案内」に従う（変更なし）。

### 1.3 テスト要件（backend/tests）

1. provider: 432 応答を 1 回受けたら、以降のクールダウン内 `search()` が HTTP を発行しない
   （client_factory の呼び出し回数で検証）＋ `available` が False。
2. provider: クールダウン経過後（`unavailable_until` を過去に差し替え）は HTTP を再試行する。
3. provider: タイムアウト・500 ではブレーカーが発動しない（`available` True のまま）。
4. provider: `api_key` 空で `available` False。
5. graph: `available=False` のプロバイダを注入すると `web_search` ノードが実行されず
   （status イベントに web_search が現れない）、`done` まで完走する。
6. 既存テスト全件パス。

---

## 2. FR-18-2 ヘッダー「APU-Navi Powered by Gemma4」

### 2.1 対象

`frontend/src/views/ChatView.vue` のヘッダー 2 箇所のみ:

- モバイル用 `<h1>`（現 531 行付近、`lg:hidden`）
- デスクトップ用 `<h1>`（現 533 行付近、`hidden lg:flex` 内）

**ThreadSidebar.vue・LoginView.vue のブランド表記、`index.html` の `<title>` は変更しない。**

### 2.2 意匠（基準値。Sol は Campus Signal の範囲で微調整可）

- 「APU-Navi」本体の書体・サイズ・トラッキングは現状維持。
- 直後にサフィックス **`Powered by Gemma4`** をベースライン付近で添える:
  - `Powered by` — `text-[10px] font-medium uppercase tracking-[0.18em] text-white/35`
    （既存の「Honjo / OC 2026」チップと同語彙）
  - `Gemma4` — 同サイズ・`font-semibold`・**Signal Coral 系**（`text-brand-soft` 等）。
    **オーロラグラデーションは使わない**（FR-12 の「Aurora は 3 箇所限定」原則を維持）。
  - タイトルとサフィックスの間は `gap-1.5〜2` 相当。サフィックスは `shrink-0 whitespace-nowrap`、
    truncate はタイトル側にのみ効かせる。
- モバイル 360px 幅でも 1 行に収まること（h1 と同じ行。折返し・見切れ不可）。
- 表記は利用者指定どおり **`Powered by Gemma4`**（スペース・大小文字はこの見た目で。
  uppercase 化により表示は `POWERED BY GEMMA4` になってよいが、`Gemma4` の強調が判別できること）。

---

## 3. FR-18-3 隠しリンク（CPS 研究室サイト）

### 3.1 仕様

- `ChatView.vue` ヘッダーの**最右端**（モバイル・デスクトップ両方）に
  `<a href="https://www.cps.akita-pu.ac.jp/" target="_blank" rel="noopener noreferrer">` を置く。
  - モバイル行: `ml-auto` で右端へ。デスクトップ行: 「HONJO / OC 2026」ラベルの右隣。
- **ボタンの体裁は出さない**（枠線・背景・影なし）。中身はインライン SVG グリフ 1 個:
  - サイズ `h-4 w-4` 程度、`stroke="currentColor"` または `fill="currentColor"`。
  - 色 `text-white/25`、`hover:text-white/70`、遷移は既存の `duration-fast ease-standard`。
  - グリフ形状は Sol 裁量（回路ノード・歯車・スパーク等、app-icon（CPS lab ロゴ）への
    目配せがあると良い。Campus Signal と調和すること）。
- ヒット領域はグリフより広く `h-9 w-9` 以上を `grid place-items-center` で確保
  （視覚は控えめのまま操作性は確保）。
- `aria-label="CPS 研究室サイト"` を付ける（視覚的には隠し、支援技術には正直に）。
- ルーター遷移ではなく通常のアンカー（新規タブ）。チャット状態を失わないこと。

---

## 4. FR-18-4 PWA 対応（manifest.json）

最終公開は Nginx（静的 `frontend/dist/` 配信 + `/api` リバースプロキシ）。
フロントを「ホーム画面に追加 → スタンドアロン起動」できるようにする。
**Service Worker / オフラインキャッシュは本 FR のスコープ外**（Chromium は SW なしで
インストール可能。将来 FR で検討）。

### 4.1 `frontend/public/manifest.json`（新規）

```json
{
  "name": "APU-Navi | 本荘キャンパス案内",
  "short_name": "APU-Navi",
  "description": "APU-Navi — 秋田県立大学 本荘キャンパス オープンキャンパス2026 来場者向け案内",
  "lang": "ja",
  "dir": "ltr",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#0d0f0e",
  "theme_color": "#0d0f0e",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

### 4.2 アイコン素材（**Fable 支給済み・生成不要**）

`app-icon.png`（1260²）から生成済みでリポジトリに配置済み。Codex は参照するだけでよい:

- `frontend/public/icons/icon-192.png` / `icon-512.png` — 透過のまま縮小（purpose any）
- `frontend/public/icons/icon-maskable-512.png` — 白地・中央 80% セーフゾーン（purpose maskable）
- `frontend/public/apple-touch-icon.png` — 180²・白地フラット化（iOS は透過を黒くするため）

### 4.3 `frontend/index.html` への追記

`<head>` に以下を追加（既存の `theme-color` #0d0f0e・icon リンクは維持）:

```html
<link rel="manifest" href="/manifest.json" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-title" content="APU-Navi" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
```

### 4.4 Nginx 公開時の参考設定（ドキュメントのみ。実ファイル追加は公開作業時）

- **PWA インストールには HTTPS が必須**（secure context。`http://<LAN IP>` 配信では
  「ホーム画面に追加」してもスタンドアロンにならない。公開時は証明書を用意すること）。
- SPA フォールバック: `location / { try_files $uri /index.html; }`
- `/api` は SSE を殺さない: `proxy_buffering off;`（backend も `X-Accel-Buffering: no` を返済）。
- manifest の MIME: nginx 既定では `.json → application/json` で全ブラウザ動作する。
  形式上の正式型にしたい場合のみ
  `location = /manifest.json { types {} default_type application/manifest+json; }`。

```nginx
server {
    listen 443 ssl;
    server_name <公開ホスト名>;
    # ssl_certificate / ssl_certificate_key は公開時に設定

    root /var/www/apu-navi/dist;
    index index.html;

    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;   # SSE
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

### 4.5 検証

- `npm run build` 後、`dist/manifest.json`・`dist/icons/*`・`dist/apple-touch-icon.png` が存在。
- Chrome DevTools → Application → Manifest でエラー 0・インストール可能表示
  （localhost は secure context 扱いなので dev サーバで確認可）。

---

## 5. FR-18-5 会話履歴コンテキストの 4 ターン化

### 5.1 定義

「1 ターン」= ユーザー発話＋アシスタント応答の 1 往復。
エージェントに渡す履歴を**直近 4 ターン = 8 メッセージ**にする（現状: 取得 6 件 →
graph 内でさらに 4 メッセージ = 実質 2 ターンに切り詰め）。

### 5.2 変更点

- `backend/app/api/chat.py`: `get_recent_messages(..., limit=6)` → `limit=8`。
- `backend/app/agent/graph.py`: `MAX_HISTORY_MESSAGES = 4` → `8`。
- **変更しないもの**: `MAX_HISTORY_CHARS`（500/メッセージ）、
  `GENERATION_HISTORY_CHAR_STAGES`（500/250/120 の段階縮退）、
  `_verify_generation_prompt` / context-length リトライ機構。
  → 8 メッセージ化によるプロンプト増（最悪 +約2,000 文字）はこの既存ガードで吸収する。

### 5.3 テスト要件

- 10 メッセージ保存済みスレッドで、エージェントへ渡る履歴が「直近 8 件・時系列昇順」であること。
- graph の履歴スライス（`[-MAX_HISTORY_MESSAGES:]`）が 8 で効くこと。
- 既存テストの期待値（limit=6 / 4 メッセージ前提のもの）を更新し、全件パス。

---

## 6. 検収チェックリスト（Fable）

- [ ] 18-1: `TAVILY_API_KEY` を無効値にして実起動 → 質問応答が最後まで完走し、
      2 問目以降で web_search ステータスが出ない（ブレーカー作動）。ログに warning。
- [ ] 18-1: 正常キーでは従来どおり Web 検索が動く（回帰なし）。
- [ ] 18-2: モバイル幅 360px / デスクトップ 1280px で「APU-Navi POWERED BY GEMMA4」が
      1 行・意匠どおり（コーラルの Gemma4 強調・オーロラ不使用）。
- [ ] 18-3: ヘッダー右上の控えめグリフ → 新規タブで https://www.cps.akita-pu.ac.jp/ が開く。
      ボタンらしい枠・背景が無い。aria-label あり。
- [ ] 18-4: `npm run build` で dist に manifest/icons が出る。DevTools Manifest エラー 0。
- [ ] 18-5: limit=8 / MAX_HISTORY_MESSAGES=8。4 往復前の内容を踏まえた応答が返る（実機 1 例）。
- [ ] backend `pytest` / frontend `npm run test` / `npm run build` 全て green。
- [ ] SSE スキーマ・ログイン・サイドバー等、対象外領域に差分が無い。

## 7. 実装上の注意（Codex 向け）

- 本ドキュメントと `docs/SPEC.md` v0.10 が正。不明点は実装を止めず `docs/QUESTIONS.md` に起票。
- Codex サンドボックスでは `.git` が読み取り専用のため、**ブランチ操作・コミットはしない**
  （working tree に変更を残すこと。コミットは Fable が行う）。
- アイコン PNG は支給済み（§4.2）。再生成・上書きしない。
- コード識別子・コメントは英語。
