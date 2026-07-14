# RELEASE_PREP — FR-18 リリース準備一式（利用者指示 5 点）＋ FR-19 改訂

- 版: v0.3（2026-07-15, Fable 改訂 — FR-22: About モーダルに APU-Navi アクセス用 QR コードを追加。
  研究室 HP と誤解されないよう確定文言の案内文を付す。§11 追加）
- v0.2（2026-07-14, Fable 改訂 — FR-19: ヘッダーロックアップ再設計・右上アイコンの画像化・
  About モーダル導入。§8 追加。§2/§3 は FR-19 により一部改訂）
- v0.1（2026-07-14, Fable 起草）
- 対象 FR: **FR-18**（`docs/SPEC.md` v0.10）・**FR-19**（同 v0.11、§8）・**FR-20**（同 v0.12、§9）・
  **FR-21**（同 v0.13、§10）・**FR-22**（同 v0.14、§11）
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

## 2. FR-18-2 ヘッダー「APU-Navi Powered by Gemma4」（※意匠は FR-19 §8-1 で改訂）

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

## 3. FR-18-3 隠しリンク（CPS 研究室サイト）（※FR-19 §8-2/§8-3 で「目立つアイコン＋About モーダル」へ改訂）

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

- 本ドキュメントと `docs/SPEC.md`（v0.10 以降）が正。不明点は実装を止めず `docs/QUESTIONS.md` に起票。
- Codex サンドボックスでは `.git` が読み取り専用のため、**ブランチ操作・コミットはしない**
  （working tree に変更を残すこと。コミットは Fable が行う）。
- アイコン PNG は支給済み（§4.2）。再生成・上書きしない。
- コード識別子・コメントは英語。

## 8. FR-19 ヘッダーロックアップ再設計と About モーダル（2026-07-14 追加・利用者指示 3 点）

FR-18 の検収後、利用者フィードバックで §2/§3 を改訂する。背景（利用者提供・モーダル文言の根拠）:
**本システムはサイバーフィジカルシステム研究室（CPS Lab）で開発されたもので、
高橋潤大さんがオープンキャンパス 2026 の出展として開発した。だから研究室サイトへのリンクを載せる。**

デザインリードは引き続き Codex / GPT-5.6Sol。Campus Signal の語彙内で、
オーロラ 3 箇所限定・コーラル単一アクセントの原則は維持する。

### 8-1 ヘッダーロックアップの再設計（「カッコよく」の引き上げ）

FR-18-2 の実装（フラットな 10px テキスト併記）は「地味」との評価。**サフィックスが
単なる説明文ではなく "技術シグネチャ" に見える**よう再設計する。

- 必須要件:
  - 階層は不変: 「APU-Navi」が主、「Powered by Gemma4」が従。従の視覚重量が主を超えない。
  - 「Gemma4」がロックアップ内の視覚アクセントであること。許可される処理（**いずれか 1 つを
    選び、両ブレークポイントで一貫適用**）:
    1. コーラル域内のグラデーションテキスト（`--brand` 〜 `--brand-soft` 程度の狭域。オーロラ 3 色域は不可）
    2. 微グロー（コーラルの `text-shadow`、ぼかし半径 ≤ 8px・主張しすぎない輝度）
    3. 髪線チップ（`border-edge` 系 1px の pill に「POWERED BY GEMMA4」を収める。チップ内で Gemma4 をコーラル強調）
  - 区切り要素（任意・1 つまで）: 中黒 `·` / 縦髪線 / コーラルドット。
  - モーション: 既定は静的。付ける場合は **hover 時のみ or マウント時 1 回（≤1.2s）**。
    常時ループ禁止（FR-16 の待機アンビエントと競合させない）。`prefers-reduced-motion` で無効化。
  - モバイル 360px で 1 行維持（FR-18-2 と同じ）。truncate はタイトル側のみ。
  - フォントは既存 font-display（Space Grotesk）系のまま。新フォント追加禁止。
- 対象は引き続き ChatView の 2 ヘッダーのみ（sidebar / login / title 不変）。

### 8-2 右上アイコンの画像化（「もう少し目立つ」）（※FR-21 §10-3 で白黒クレジットグリフへ再改訂）

FR-18-3 の抽象グリフ（white/25 ストローク）を廃し、**`/app-icon.png`（CPS Lab ロゴ・フルカラー）
の画像ボタン**に置き換える。ダークヘッダー上でフルカラーが自然に目を引く。

- `<img src="/app-icon.png" alt="">` を包む `<button type="button">`（**アンカー廃止**。直リンクしない）。
- 画像サイズ **h-7 w-7 前後**（28px。両ブレークポイント同等）、`rounded-ui-sm`、
  髪線リング（`ring-1 ring-edge-strong` 等）＋ `shadow-soft` 程度の浮き。
- ホバー: 明度/スケールの軽い持ち上げ（scale ≤ 1.06）、active で押し込み。基底は不透明度 90% 前後
  → hover 100% など、Sol 裁量で「押せる気配」を出す（ボタン然とした枠・塗りは引き続き不要）。
- 位置は FR-18-3 と同じ（モバイル: ヘッダー右端 `ml-auto` / デスクトップ: HONJO / OC 2026 の右隣）。
- a11y: `aria-haspopup="dialog"`・`aria-label="このアプリについて"`。ヒット領域 ≥ 40px。

### 8-3 About モーダル（案内を挟む）

アイコン押下で**ページ遷移せず、アプリ内モーダル**を開く。研究室サイトへはモーダル内の
リンクから新規タブで飛ぶ（**iframe 埋め込みは不採用**: 外部サイトの X-Frame-Options /
frame-ancestors で表示が壊れるリスクがあるため）。

- 実装: ChatView 既存のダイアログ機構を拡張（`dialog.kind = 'about'` を追加）。
  オーバーレイ `bg-black/70 backdrop-blur-[2px]`・`dialog-panel`（`max-w-sm rounded-ui-lg
  border-edge-strong bg-ink-raised p-5 shadow-glass`）・Esc / 背景クリックで閉じる・
  フォーカス復帰、はすべて既存挙動に載せる。
- パネル構成（上から）:
  1. ロゴ: `/app-icon.png` を `h-12 w-12 rounded-ui shadow-soft` 程度で表示
  2. 見出し(h3): **APU-Navi について**
  3. 本文（文言は確定。改行位置・字間は Sol 裁量）:
     > APU-Navi は、オープンキャンパス 2026 の出展として、サイバーフィジカルシステム研究室
     > （CPS Lab）の高橋 潤大が開発した本荘キャンパス案内 AI エージェントです。
     >
     > 回答はローカル GPU 上の Gemma4 と Agentic RAG で生成しています。
  4. リンク（新規タブ・`rel="noopener noreferrer"`）:
     **サイバーフィジカルシステム研究室のサイトへ** → `https://www.cps.akita-pu.ac.jp/`
     意匠はコーラルのテキストリンク or 髪線ボタン（Sol 裁量）。外部遷移と分かる `↗` 等の記号を添える。
  5. 右下に「閉じる」ボタン（既存ダイアログのキャンセルボタンと同意匠）。
- マイクロコピー（任意）: パネル下部に `CPS LAB / AKITA PREFECTURAL UNIVERSITY` 等の
  uppercase 微小ラベル（white/35）を敷いてよい。
- `aria-label`（dialog）は「このアプリについて」。

### 8-4 検収チェックリスト（FR-19 分）

- [ ] ロックアップ: 360px / 1280px 両方で新意匠が適用され 1 行維持。Gemma4 のアクセントが
      フラットテキストでない（グラデ/グロー/チップのいずれか）。オーロラ・常時ループなし。
- [ ] 右上: app-icon 画像ボタンに置換。旧ストロークグリフと `<a>` 直リンクが消えている。
- [ ] モーダル: アイコン押下で開く。文言が §8-3 と一致。リンクが新規タブで研究室サイトを開く。
      Esc・背景クリック・閉じるボタンで閉じ、フォーカスがアイコンへ戻る。
- [ ] スレッド rename/delete ダイアログに回帰がない。
- [ ] `npm run test` / `npm run build` green。

## 9. FR-20 Gemma4 ブランディング微調整（2026-07-14 追加・利用者指示）（※FR-21 §10 で一部改訂: 透過アイコン化・右配置・色改訂）

背景: 利用者が Gemma 公式ロゴアイコン `frontend/public/icon-gemma4.jpeg`（640×640・白背景 JPEG・
青グラデの四芒星）を支給。「Powered by Gemma4」の近くにこのアイコンを置き、「Gemma4」の文字色を
Gemma 公式カラー（青〜水色）にして整える。デザインリードは引き続き Codex / GPT-5.6Sol。

### 9-1 ロックアップへの Gemma アイコン追加

- 対象は ChatView の 2 ヘッダー（モバイル h1 / デスクトップ h1）の suffix グループのみ。
  表示順は **`Powered by` → アイコン → `Gemma4`**。両ブレークポイントで一貫。
- 白背景 JPEG は透過化せず、**`rounded-full` の白チップ（ファビコン風バッジ）**として見せる。
  - サイズ 14〜18px の正方形（両 BP 同一）・`shrink-0`。任意で `ring-1 ring-edge-strong` の髪線。
  - 装飾画像として `alt=""`。ボタン化・リンク化しない。
  - suffix グループは `items-baseline` のため、アイコンは `self-center` 等でワードマークと
    光学中央合わせ（微調整は Sol 裁量）。
- 360px で 1 行維持（FR-19 §8-1 と同じ）。きつい場合は区切り縦髪線の省略可（両 BP 一貫）。
- **実装記録（R2・2026-07-14）**: チップ追加（+20px）により 360px でタイトルが 5px 溢れ
  「APU-N…」に truncate されたため、本条項を発動し区切り縦髪線を両 BP で削除（7px 回収）。
  Fable が Playwright 実測（title scrollWidth 67px = clientWidth 67px）で解消を検収済み。

### 9-2 「Gemma4」を Gemma 公式ブルーのグラデへ

- FR-19 §8-1 の「コーラル域内」制約は、**この要素に限り利用者指示で解除**する
  （Campus Signal「コーラル単一アクセント」原則の明示的例外。青を他要素へ波及させない）。
- `frontend/tailwind.config.js` にトークン追加（値はアイコン四芒星ストローク両端の実測）:
  `colors.gemma = { start: '#3487fd', end: '#a3c1ff' }`
- 適用（両 BP の Gemma4 span。現行 `from-brand-signal to-brand-soft` を置換）:
  `bg-gradient-to-r from-gemma-start to-gemma-end bg-clip-text text-transparent`
- 10px での可読性が弱いと判断した場合のみ、start の明度 +10% まで持ち上げ可（色相維持。
  逸脱したら実値をこの節へ追記）。

### 9-3 変更しないもの（厳守）

- **右上ボタン（`/app-icon.png`・2 箇所）は不変**。Gemma アイコンを右上ボタンに使わない（利用者明示指示）。
- About モーダル: working tree にある**利用者直編集の本文文言を保持**（巻き戻し禁止）。
- sidebar / login / 空状態: 変更なし。新規モーションの追加も禁止（静的のまま）。

### 9-4 検収チェックリスト（FR-20 分）

- [ ] 360px / 1280px 両方で「Powered by ＋ アイコン ＋ Gemma4」が 1 行・光学整列・チップが潰れていない。
- [ ] Gemma4 が青系グラデ（コーラルでない）。青が他要素へ波及していない。
- [ ] 右上ボタンが app-icon.png のまま。About モーダルの利用者編集文言が保持されている。
- [ ] `npm run test` / `npm run build` green。

## 10. FR-21 Gemma ブランディング改訂 R2（2026-07-14 追加・利用者指示 3 点、§8-2/§9 を一部改訂）

背景: 利用者が公式ロックアップの参照画像 `referenceUI/referenceUI_Gemma.png`（黒地・透過グリフ＋
青グラデワードマーク。ローカル保持のみ・コミット禁止）を支給。白チップをやめ**透過をいかして
ダークヘッダーへ直接載せる**方針に改訂。あわせて右上ボタンは「目立つ画像」から
**「白黒・控えめ・クレジット風」**へ反転する（FR-19 §8-2 の狙いを利用者指示で更新）。

### 10-1 ロックアップ: 透過スターアイコン（§9-1 改訂）

- アセットは Fable 支給の **`/icon-gemma4.png`（96×96・透過・四芒星のみ）** を使う
  （生成記録: 元 JPEG を fuzz 8% 白抜き → アルファ開演算 Disk:3 で格子線・円を除去 → trim・96px 化。
  16px 表示での視認性を確認済み）。旧 `/icon-gemma4.jpeg` は参照しない（ファイル削除もしない）。
- **表示順を変更: `Powered by` → `Gemma4` → アイコン**（アイコンはワードマークの右）。
- `rounded-full` / `bg-white` / `ring` の白チップ装飾は**全廃**し、透過のまま置く。
- サイズは h-4 w-4（16px）目安（14〜18px で Sol 裁量・両 BP 同一）・`shrink-0 self-center`・`alt=""`。
- 両 BP 一貫・360px 1 行維持（区切り縦髪線なしは FR-20 R2 のまま）。

### 10-2 ワードマーク色の改訂（§9-2 改訂）

- 参照画像（黒地公式ロックアップ）のレターコア実測に合わせ、tailwind トークンを更新:
  `colors.gemma = { start: '#497fef', end: '#619af1' }`（G 側 → 4 側。旧 #3487fd / #a3c1ff を置換）。
- 適用クラスは現行のまま（`bg-gradient-to-r from-gemma-start to-gemma-end bg-clip-text text-transparent`）。

### 10-3 右上ボタン: 白黒クレジットグリフ（§8-2 改訂）

- `/app-icon.png` の `<img>` を廃し、**インライン SVG のモノクログリフ**へ置換（画像ファイル不使用・
  カラー/グラデ不可）。ボタンとしての構造・a11y（`aria-haspopup="dialog"`・
  `aria-label="このアプリについて"`・40px ヒット領域）・About モーダル挙動・フォーカス復帰は現状維持。
- 意匠要件: 「クレジット / 奥付」の佇まい。細線 stroke（1.25〜1.5px 相当）・`currentColor`・
  基底 `text-white/30` 前後 → hover `text-white/70` 程度（`hover:bg-fill-hover` 併用可）・
  active 押し込み。ring / shadow / 常時の枠塗りは付けない。スケールは hover ≤1.04 まで。
- グリフ実寸 16〜18px。モチーフは Sol 裁量で 1 案・両 BP 同一（例: 極細サークル＋「i」/
  CPS の Y ノード抽象（FR-18-3 系譜）/ 奥付風 © の抽象）。
- 配置は現行どおり（モバイル: ヘッダー右端 `ml-auto` / デスクトップ: HONJO / OC 2026 の右隣）。

### 10-4 検収チェックリスト（FR-21 分）

- [ ] 360px / 1280px: 「POWERED BY GEMMA4 ＋ 透過スター」の順で 1 行・白フチ/白箱が出ていない。
- [ ] GEMMA4 のグラデが参照画像の色域（#497FEF → #619AF1）。青の他要素への波及なし。
- [ ] 右上が白黒インライン SVG グリフ（app-icon 画像が消えている）。About モーダル開閉・
      フォーカス復帰に回帰なし。
- [ ] 利用者編集の About 文言（【CPS Lab】…の 1 段落のみ）がそのまま。
- [ ] `npm run test` / `npm run build` green。

## 11. FR-22 About モーダルに APU-Navi アクセス用 QR コードを追加（2026-07-15 追加・利用者指示）

背景: 本番公開 URL は `https://ibera.cps.akita-pu.ac.jp`（`docs/ARCHITECTURE.md`「本番公開構成」参照）。
利用者支給の QR 画像 `frontend/public/qrcode_ibera.cps.akita-pu.ac.jp.png`（白地・中央に恐竜モチーフ・
上記 URL をエンコード）を About モーダル内で提示し、来場者が自分のスマートフォンで APU-Navi を
開けるようにする。

**懸念（利用者指摘）**: モーダル内には研究室サイトへのリンクが既にあり、ドメインも
`cps.akita-pu.ac.jp` 配下のため、QR を「研究室ホームページの QR」と誤解されうる。
誤解を防ぐ案内文（§11-2 確定文言）を必ず添える。

### 11-1 配置

- 挿入位置: About モーダル（`dialog.kind === 'about'`）内、**本文段落の直後・研究室サイトリンクの直前**。
- 上下を髪線 divider（`border-edge` 相当）または十分な余白で区切り、
  「本文 / QR セクション / 研究室リンク」が別ブロックと読めるようにする（手段は Sol 裁量）。
- 既存要素は変更しない: 利用者直編集の本文段落（【CPS Lab】…の 1 段落）・研究室サイトリンク・
  閉じるボタン・ダイアログ機構（Esc / 背景クリック / フォーカス復帰）。

### 11-2 文言（確定。改行位置・字間は Sol 裁量）

QR セクション内の並び順もこの通りとする:

1. 小見出し: **お手元のスマートフォンでも使えます**
2. 説明文: この QR コードを読み取ると、APU-Navi（このアプリ本体）が開きます。
   ぜひお手元のスマートフォンでお試しください。
3. QR 画像（§11-3）
4. URL 表記（QR 直下・小さめ・等幅寄りで可）: `ibera.cps.akita-pu.ac.jp`
5. 注記（説明文より一段小さく・white/45 前後）:
   ※ サイバーフィジカルシステム研究室のホームページの QR コードではありません。
   研究室サイトは、すぐ下のリンクからご覧いただけます。

注記は研究室サイトリンクの直上に置かれる想定（§11-1 の挿入位置により「すぐ下のリンク」が成立する）。
リンクの並び順を変える場合は注記の文言も整合させること（Fable へ要確認）。

### 11-3 QR の意匠・スキャナビリティ制約

- 画像: `/qrcode_ibera.cps.akita-pu.ac.jp.png` を `<img>` で表示。
  `alt="APU-Navi アクセス用 QR コード"`（意味のある画像。`alt=""` の装飾扱いは禁止）。
- 表示サイズ **140〜180px 四方**・中央寄せ。
- 白地は加工せずそのまま（ダークパネル上に白タイルとして浮かせる）。角丸は `rounded-ui-sm` 程度まで・
  髪線 ring 可。ただし **QR の静穏域（白余白）を欠く加工、不透明度・フィルタ・ブレンド・色反転は禁止**
  （スマホカメラの読み取り率を落とすため）。
- モーダルが縦に伸びるため、ダイアログパネルに `max-h-[calc(100dvh-2rem)] overflow-y-auto` 相当の
  ガードを付与（rename / delete ダイアログに回帰を出さないこと）。
- **開いた直後はパネル先頭（アイコン・見出し）が見えること（R2・2026-07-15 検収指摘）**:
  既存の初期フォーカス（閉じるボタン）はパネル下端にあるため、フォーカス起因の scrollIntoView で
  パネルが下端までスクロールした状態で開いてしまう（360×667 実測 scrollTop=135）。
  初期フォーカス先は変えず `focus({ preventScroll: true })` 等で自動スクロールのみ抑止する
  （rename / delete にも適用可・回帰なきこと）。

### 11-4 検収チェックリスト（FR-22 分）

- [ ] About モーダルで QR セクションが本文と研究室リンクの間に表示され、文言・並び順が §11-2 と一致。
- [ ] QR が白地のまま 140px 以上で表示され、フィルタ・反転・静穏域欠けがない。
- [ ] 実機スマホで読み取り `https://ibera.cps.akita-pu.ac.jp` が開く（実機分は利用者 / Fable）。
- [ ] 利用者直編集の本文段落・研究室リンク・閉じる・Esc / 背景クリック / フォーカス復帰が不変。
- [ ] 小型画面（高さ 667px 目安）でモーダルがはみ出さず、必要ならパネル内スクロールできる。
- [ ] 360×667 で開いた直後にパネル先頭（アイコン・「APU-Navi について」見出し）が見えている
      （下端スクロール状態で開かない）。
- [ ] rename / delete ダイアログに回帰なし。`npm run test` / `npm run build` green。

## 12. FR-23 ビューポート固定シェル化とセーフエリア対応（2026-07-15 追加・利用者指示 2 点）

利用者報告（iPhone 14 実機）:

1. ログイン画面もチャット画面も**画面ごと動いてしまい使いにくい**。固定してほしい。
2. スマホ利用時に**画面上部がカメラ（ノッチ）と被る**。iPhone 14 は内カメラが画面上に凸のため、
   上部コンテンツが隠れる。

### 12-0 原因分析（Fable 調査済み・実装前に再確認不要）

- `html / body / #app` は `min-height: 100%` のみで、document スクロールを禁止していない。
- LoginView はルートが `min-h-dvh` の document スクロール構造。コンテンツ（hero `min-h-[31rem]`
  ＋シート約 320px）が iPhone 縦の可視高を超え、ページ全体がスクロールする。
  iOS ではラバーバンド・Safari ツールバー伸縮も加わり「画面ごと動く」。
- ChatView はルート `h-dvh overflow-hidden`＋`<main>` 内部スクロールで構造は正しいが、
  (a) 内部スクローラに `overscroll-behavior` がなく端到達時に document へバウンスが連鎖、
  (b) iOS はキーボード表示時に window 自体をパンするため画面ごとずれる、
  (c) リネームダイアログの input が `text-sm`（14px）のため iOS が自動ズームし画面ごと拡大される。
- セーフエリア: `viewport-fit=cover`＋manifest `display: standalone`＋
  `apple-mobile-web-app-status-bar-style: black-translucent` により、ホーム画面追加時は
  コンテンツがステータスバー／ノッチ裏まで広がるが、**`env(safe-area-inset-top)` が全 UI で未適用**
  （bottom は適用済み）。ChatView ヘッダー・LoginView ブランド・サイドバー上部がノッチに被る。

### 12-1 ドキュメント固定（アプリシェル化）

- `frontend/src/style.css`: `html, body { height: 100%; overflow: hidden; overscroll-behavior: none; }`
  `#app { height: 100%; }` に変更（現行の `min-height: 100%` 3 連指定を置換）。
  スクロールは各ビューの内部コンテナのみで行う。
- 共通クラス `.app-viewport { height: var(--app-height, 100%); }` を style.css に定義し、
  **両ビューのルート要素**に適用する（`--app-height` は §12-2 の composable が供給。
  JS 不動作・非対応環境では 100% にフォールバックし、従来の全画面表示と等価になること）。
- ChatView ルート: `h-dvh` → `.app-viewport`（`overflow-hidden` は維持）。
- LoginView ルート: `min-h-dvh` → `.app-viewport`＋`overflow-y-auto`（`overflow-x-hidden` は維持）。
  コンテンツが収まる画面ではスクロールが発生せず固定表示になること。
  - hero の `min-h-[31rem]` は **`sm:min-h-[31rem]` に変更**（640px 未満では固定 min-h を外し
    flex に任せる）。シート（`<footer class="login-sheet">`）には `shrink-0` を付与し、
    フォームが flex 圧縮で潰れないようにする。
    ねらい: iPhone 14 縦（390×844, Safari）で初期表示時にニックネーム入力欄まで見える。
    収まらない極小画面ではビュー内スクロールにフォールバックする（document は動かさない）。
- 内部スクローラすべてに `overscroll-contain`（Tailwind ユーティリティ）を付与:
  ChatView `<main>`・LoginView ルート・ThreadSidebar のスレッドリスト・ダイアログパネル
  （`overflow-y-auto` を持つ要素が対象）。

### 12-2 iOS キーボード対応（visualViewport 同期）

- 新規 composable `frontend/src/composables/useAppViewport.js` を作成し、`App.vue` でマウントする。
  仕様:
  - `window.visualViewport` があれば、その `height` を px 値で
    `document.documentElement.style.setProperty('--app-height', ...)` に反映する。
    初回即時＋`visualViewport` の `resize` イベントで更新。
  - **`visualViewport.scale > 1`（ピンチズーム中）は更新しない**（ズームで高さが縮む誤動作防止）。
  - iOS はキーボード表示時に window をパンするため、`visualViewport` の `resize` および
    window の `scroll` イベントで `window.scrollY > 0` なら `window.scrollTo(0, 0)` で打ち消す。
    （document 固定（§12-1）＋シェル高さの visualViewport 同期により、composer は
    キーボード直上に位置するため、パンを打ち消しても入力欄は隠れない。）
  - `visualViewport` 非対応環境では何もしない（`--app-height` 未設定 → 100% フォールバック）。
  - アンマウント時にリスナーを全解除する。
- `frontend/index.html` の viewport meta に `interactive-widget=resizes-content` を追加
  （Android Chrome 108+ はこれでレイアウトビューポート自体が縮む。iOS は無視するため
  composable と併存して矛盾しない）。

### 12-3 セーフエリア上部対応（`env(safe-area-inset-top)`）

既存の bottom 系（composer・サイドバー下部・ダイアログ下部・ログインシート）は変更しない。
top を以下に適用する（すべて Tailwind 任意値の `env()` 直書きで既存記法に合わせる）:

- ChatView の sticky ヘッダー: `<header>` 自体に `pt-[env(safe-area-inset-top)]` を付与
  （背景・blur・下ボーダーはヘッダー全体が伸びるため、ノッチ裏まで自然につながる）。
- ThreadSidebar 上部ブロック: `pt-4` → `pt-[calc(1rem_+_env(safe-area-inset-top))]`
  （デスクトップレール・モバイルドロワーの両インスタンスに効く。inset 0 の環境では不変）。
- LoginView hero 内コンテナ: `pt-6` → `pt-[calc(1.5rem_+_env(safe-area-inset-top))]`、
  `sm:pt-8` → `sm:pt-[calc(2rem_+_env(safe-area-inset-top))]`。
- ダイアログ overlay（`fixed inset-0` の flex コンテナ）: `pt-[calc(1rem_+_env(safe-area-inset-top))]`
  を追加し、パネルの `max-h-[calc(100dvh-2rem)]` は **`max-h-full` に変更**
  （overlay の padding が safe-area を含むため、パネルは常に可視領域内に収まる）。
- **R2（2026-07-15 Fable 検収指摘）**: ダイアログ overlay は `fixed inset-0` → **`absolute inset-0`
  に変更**する。fixed は layout viewport 基準のため、キーボード表示で `.app-viewport` が縮んでも
  overlay は縮まず、items-end のパネル（rename 入力欄）がキーボード裏に隠れる。しかも §12-2 の
  window パン打ち消しにより iOS のオートスクロール救済も働かない（R1 実測: `--app-height` 500px
  シミュレーションで入力欄 bottom 743 > 可視域 500）。ChatView ルート `.chat-shell` は
  `position: relative`・inset 0 全画面のため、absolute 化しても通常時の見た目・z 順
  （z-50 > ドロワー z-40、同一 stacking context 内）は不変で、キーボード表示中のみ
  縮んだシェルに追従してパネルがキーボード直上に来る。
  なおドロワー（`fixed inset-0 z-40`）は入力欄を持たず、開閉時にフォーカスが外れて
  キーボードは閉じるため fixed のままでよい。
- 横向き（left / right inset)は **P2・今回スコープ外**（会場運用は縦持ち前提。ただし対応する場合は
  ヘッダー・composer dock の横 padding に加算する方式とする）。
- 注記（P2・今回対象外）: standalone のステータスバー文字は black-translucent により白固定のため、
  明色のログイン画面上部では時計等が見えにくい。実害が確認されたら別 FR で扱う。

### 12-4 iOS 自動ズーム防止

- リネームダイアログの input `text-sm` → `text-base` に変更（iOS は font-size 16px 未満の
  入力欄フォーカスで画面ごと自動ズームするため）。周辺の余白調整は Sol 裁量、
  ただし**すべての input / textarea の computed font-size は 16px 以上を維持**すること
  （composer textarea・ログイン入力欄は現状 text-base で適合済み。回帰させない）。

### 12-5 テスト

- `useAppViewport` のユニットテストを追加（jsdom に `visualViewport` モックを差して検証）:
  (a) マウントで `--app-height` が visualViewport.height に設定される
  (b) `resize` 発火で追従する
  (c) `scale > 1` では更新されない
  (d) アンマウントでリスナーが解除される
  (e) `visualViewport` 未定義なら `--app-height` を設定しない
- 既存テスト（29 件）に回帰を出さない。

### 12-6 検収チェックリスト（FR-23 分）

- [ ] PC・スマホとも、ログイン / チャットの両画面で document がスクロールしない
      （`document.scrollingElement` の scrollHeight == clientHeight、window.scrollY 常時 0）。
- [ ] 内部スクローラ（メッセージ一覧・スレッド一覧・ダイアログ・ログイン）の端到達で
      ページ全体がバウンスしない（実機分は利用者）。
- [ ] iPhone 14 縦: ログイン初期表示でニックネーム入力欄が見える（実機分は利用者）。
- [ ] チャットの textarea フォーカス→キーボード表示中も composer が可視（キーボード直上）・
      ヘッダーが画面内に残る。キーボードを閉じるとレイアウトが完全復帰し、ずれが残らない（実機）。
- [ ] ホーム画面追加（standalone）でヘッダー内容・ログインブランド・サイドバー上部が
      ノッチ / ステータスバーに被らない（実機）。
- [ ] リネームダイアログの input フォーカスで iOS が自動ズームしない（実機）。
- [ ] デスクトップ（safe-area 0・visualViewport = ウィンドウ高）で見た目の回帰なし
      （ヘッダー高さ・ログインの構図・ダイアログ挙動が従来どおり）。
- [ ] `npm run test` / `npm run build` green。新規 composable テストを含む。

## 13. FR-24 キーボード表示時のレイアウト最適化と「最新へ戻る」ボタン（2026-07-15 追加・利用者指示 3 点）

利用者指示（スマホ実機・チャット画面）:

1. キーボード（入力フォーム）を開いたとき、**フォームがやや上がりすぎる**。
2. **会話開始前（空状態）**でキーボードを開いたら**例文チップは非表示**にし、ロゴとあいさつメッセージが
   **フォームと画面上端の間にちょうどよく収まるよう自動リサイズ**する挙動にする。
3. **会話履歴がある状態**でキーボードを開いたとき: 履歴の最下部にいる場合は**履歴を上に押し上げて
   最下部固定を維持**、途中にいる場合は**表示位置を保ったまま**開く。あわせて履歴の途中にいるときは
   ChatGPT / Gemini のように**「いちばん下へすぐ戻れる」ボタンを composer 直上に半透明ガラス調**で置く。

（利用者文面の「過去動画」は前後の文脈「会話履歴を上に押し上げる」から「過去の会話（履歴）」と解釈 — Fable 裁定）

### 13-0 原因分析（Fable 調査済み・実装前に再確認不要）

- 「フォームが上がりすぎ」: composer の下余白は `pb-[calc(0.75rem_+_env(safe-area-inset-bottom))]`。
  キーボード表示中はシェル下端（= visualViewport 下端）がキーボード上端に一致するが、
  `env(safe-area-inset-bottom)`（ホームインジケータ、standalone で約 34px）は**キーボード表示中も
  変わらない**ため、composer がキーボード上端から約 46px（0.75rem + 34px）浮く。
- 空状態: 空状態コンテンツ（ロゴ 56px＋見出し `clamp(2rem,5vw,3.6rem)`＋例文チップ群）は
  キーボード表示時の可視高（iPhone 14 縦: visualViewport 約 500px − ヘッダー約 115px −
  composer 約 105px ≒ 280px）に収まらず内部スクロールが発生し、「ちょうどよく」表示されない。
- 履歴あり: シェル縮小時、ブラウザは scrollTop を保持するため**最下部にいた場合は下端が隠れる**
  （最下部固定は自前で再スクロールしないと実現できない）。途中閲覧時の位置保持は既定挙動で満たされる。
- 自動追従の副作用: 現状はストリーミング更新のたびに**無条件で**最下部へ scrollIntoView しており、
  履歴を遡って読んでいる最中でも下へ引き戻される。「最新へ戻る」ボタンを意味あるものにするには
  **最下部にいるときだけ自動追従**するよう条件化が必要（13-4 規則 2。ChatGPT / Gemini と同じ規範）。

### 13-1 キーボード検知と viewport 共有状態（`useAppViewport.js` 拡張）

- 共有リアクティブ状態をモジュールスコープに新設し、`useViewportState()` としてエクスポートする:
  `appHeight`（number | null。`--app-height` に書いた px 値）と `keyboardOpen`（boolean）。
  ChatView はこれを watch してスクロール制御（13-4 規則 1）に使う。
- キーボード検知（`syncAppHeight` 内。`scale > 1` 中は従来どおり一切更新しない）:
  - 基準高 `maxViewportHeight` を保持する。`visualViewport.width` が変わったら（回転・分割等）
    現在高でリセットし、それ以外は `max(現在値, visualViewport.height)` で更新する。
  - `keyboardOpen = (pointer: coarse) && (maxViewportHeight - visualViewport.height >= 150)`。
    定数 `KEYBOARD_MIN_DELTA_PX = 150`（ソフトキーボードは 260px 以上、Safari ツールバー伸縮・
    Android URL バーの高さ変動は 110px 以下のため誤検知しない）。
    `window.matchMedia('(pointer: coarse)')` でデスクトップのウィンドウ縦リサイズを除外する。
  - 判定を `document.documentElement` の `data-keyboard="open"` 属性へ反映（閉時は属性を削除）。
    CSS 側は `html[data-keyboard='open']` で分岐する（13-2 / 13-3）。
  - この方式は `window.innerHeight` に依存しないため、iOS（キーボードが visualViewport のみ
    縮める）と Android（`interactive-widget=resizes-content` で layout viewport ごと縮む —
    どちらでも visualViewport.height は縮む）の両方で同一コードで機能する。
- アンマウント時はリスナー解除に加え、`data-keyboard` 属性を削除し共有状態を初期値へ戻す。

### 13-2 composer 底部余白の是正（指示 1）

- `frontend/src/style.css` に追加:
  `html[data-keyboard='open'] .composer-dock { padding-bottom: 0.75rem; }`
  （キーボードがホームインジケータ領域を覆うため、表示中は safe-area 加算を外して
  キーボード直上に密着させる）。
- キーボード閉時は現状の `calc(0.75rem + env(safe-area-inset-bottom))` のまま変更しない。
- footer 高さの変化は既存の ResizeObserver（`updateFooterClearance`）が拾うため追加対応不要。

### 13-3 空状態のキーボード時コンパクト化（指示 2）

`html[data-keyboard='open']` 配下でのみ適用する（style.css。既存の `.chat-empty__*` フックを使う）:

- `.chat-empty__actions`（例文チップ群）: `display: none`。
  キーボードを閉じた際に entrance アニメーション（`empty_item_enter`）が再生されるのは許容
  （初期表示と同じ振り付けのため違和感がない。目障りと判断したら Sol 裁量で opacity ベースの
  抑制に変えてよい）。
- `.chat-empty__identity img`（ロゴ）: 3.5rem 四方 → **2.5rem 四方**。
- `.chat-empty__heading`: font-size **`clamp(1.5rem, 5vw, 1.875rem)`**・margin-top **1rem**（通常 1.5rem）。
- 上記の寸法変化には `transition`（`var(--motion-base)` ease-out、対象: width / height /
  font-size / margin）を付けて開閉を滑らかにする。`prefers-reduced-motion: reduce` では transition なし。
- **受け入れ基準**: iPhone 14 縦相当（visualViewport ≒ 390×500）で、ロゴ＋あいさつ（最長バリアント・
  長めのニックネーム）が**内部スクロールなしで全可視**、かつ既存の flex `justify-center` により
  **ヘッダー下端と composer 上端の間で上下センタリング**されること。
  上記数値は Sol が ±20% の範囲で微調整してよい（基準を満たすこと）。

### 13-4 履歴のスクロール保持・最下部ピン留め・自動追従の条件化（指示 3 前半）

ChatView に「最下部にいるか」の追跡を導入し、スクロール挙動を次の規則に統一する:

- **状態**: `isAtBottom`（ref、初期値 true）。`<main>`（ref 付与）の `@scroll.passive` で
  `scrollHeight - scrollTop - clientHeight <= 72`（定数 `AT_BOTTOM_THRESHOLD_PX = 72`）を評価して更新。
  ただし直近の smooth スクロール開始から **600ms**（定数 `SMOOTH_SCROLL_SUPPRESS_MS`）は計測を
  スキップする（プログラム起因の smooth アニメーション途中経過を「ユーザーが上へ離脱した」と
  誤認しないため。instant（'auto'）スクロールは同期完了するため抑制不要）。
- **`scrollToBottom(fallbackBehavior = 'smooth')`**: behavior は
  `pendingScrollBehavior || fallbackBehavior`（pending の消費・null 戻しは現行どおり）。
  実行後に `isAtBottom = true` を設定し、smooth のときのみ上記の計測抑制ウィンドウを張る。
- **規則 1（キーボード開閉・シェル高変化）**: `useViewportState().appHeight` を watch し、
  メッセージ 1 件以上かつ `isAtBottom` なら `scrollToBottom('auto')`（instant で最下部を維持 =
  履歴が押し上がる）。`isAtBottom` でなければ何もしない（ブラウザ既定の scrollTop 保持に任せる =
  表示位置そのまま）。キーボード閉時も同watchで整合する（閉で最下部なら自動的に最下部のまま）。
- **規則 2（ストリーミング自動追従の条件化）**: 既存のメッセージ内容シグネチャ watch は
  `pendingScrollBehavior || isAtBottom` のときだけ `scrollToBottom('auto')` を呼ぶ
  （従来の無条件 smooth 追従を廃止。上に遡って読んでいる間は引き戻さない。
  チャンク間隔が短いため追従は instant でよい — ChatGPT 同等の体感）。
- **規則 3（明示アクションは常に最下部へ）**: `send()` / `retryLastMessage()` は実行時に
  `pendingScrollBehavior = 'smooth'` を設定する（履歴途中から送信しても smooth で最下部へ。
  従来の送信時の見た目を保つ）。スレッド復元は従来どおり `'auto'`。
- メッセージが 0 件になったとき（newChat 等）は `isAtBottom = true` に戻す
  （既存の greeting 再抽選 watch に追記でよい）。

### 13-5 「最新へ戻る」ボタン（指示 3 後半）

- 表示条件: `chat.messages.length > 0 && !isAtBottom`（空状態・最下部では出ない）。
  `<Transition>`（opacity ＋ 4px 上昇 ＋ scale 0.96→1、`var(--motion-base)`。
  reduced-motion では transition なし）で出入りする。
- 配置: composer フォーム内の `.mx-auto.w-full.max-w-3xl` ラッパーを `relative` 化し、その中に
  `absolute -top-14 left-1/2 -translate-x-1/2` で配置（composer シェル上端から約 12px 上・水平中央。
  composer-dock の上部グラデーション帯に浮かぶ。sticky フォーム基準なのでスクロールに影響されない）。
- 見た目（半透明ガラス。既存トークンで構成）: 円形 `h-11 w-11`（44px タッチターゲット）、
  `rounded-full border border-edge-strong bg-ink-raised/70 shadow-glass backdrop-blur-md`、
  中に下向き矢印 SVG（現行アイコンと同じ stroke 系。`text-white/80`、hover で `text-white`・
  背景不透明度アップ）。hover / active は送信ボタンの作法（`active:scale-[0.94]` 等）に合わせる。
  細部の質感は Sol 裁量（「半透明のガラス」の印象を満たすこと）。
- 挙動: click で `scrollToBottom('smooth')`（`isAtBottom` が true になり自身は即フェードアウト）。
  **`@mousedown.prevent` を付けて composer の textarea からフォーカスを奪わない**
  （タップしてもキーボードが閉じない — ChatGPT / Gemini 同等）。
- a11y: `aria-label="最新のメッセージへ移動"`。
- z 順: フォーム（z-10）内のため履歴の上・ヘッダー（z-20）ダイアログ（z-50）の下で問題なし。

### 13-6 テスト

- `useAppViewport.spec.js` に追加（visualViewport モック＋ `matchMedia` モック）:
  (a) 高さが基準から 150px 以上縮むと `data-keyboard="open"` が付き `keyboardOpen` ref が true になる
  (b) 高さ復帰で属性が外れ ref が false に戻る
  (c) `pointer: coarse` でない環境では縮んでも open にならない
  (d) width 変化（回転相当）で基準がリセットされ、リセット直後の縮小高では open にならない
  (e) `scale > 1` ではキーボード判定も更新されない
  (f) アンマウントで `data-keyboard` が除去され共有状態が初期化される
- `ChatView.spec.js`（既存のソース文字列方式）に追加:
  (a) 「最新へ戻る」ボタンが `aria-label`・`@mousedown.prevent`・ガラス系クラス群を持つ
  (b) メッセージシグネチャ watch が `isAtBottom` でゲートされている（無条件追従の再発防止）
  (c) `send()` が `pendingScrollBehavior = 'smooth'` を設定する
- 既存テスト（25 件）に回帰を出さない。`npm run test` / `npm run build` green。

### 13-7 検収チェックリスト（FR-24 分）

- [ ] キーボード表示中、composer とキーボード上端の隙間が 0.75rem 相当まで詰まる（実機は利用者）。
- [ ] 空状態＋キーボード表示で例文チップが消え、ロゴ＋あいさつが縮小して内部スクロールなしで
      ヘッダーと composer の間に中央表示される。キーボードを閉じると元の寸法・例文表示に戻る。
- [ ] 履歴最下部でキーボードを開くと、最下部固定のまま履歴が押し上がる。
- [ ] 履歴途中でキーボードを開くと、表示位置が変わらない。
- [ ] 履歴途中で「最新へ戻る」ボタンが composer 直上・水平中央にガラス調で表示され、
      タップで最下部へ smooth スクロールして消える。タップしてもキーボードは閉じない（実機）。
- [ ] ストリーミング中に上へスクロールすると自動追従が止まり、ボタンで復帰すると追従が再開する。
- [ ] 最下部・空状態ではボタンが出ない。
- [ ] デスクトップ（fine pointer）: ウィンドウ縦リサイズでキーボード判定が誤発火せず、
      スクロール挙動・composer 余白に回帰がない。
- [ ] `npm run test` / `npm run build` green。
