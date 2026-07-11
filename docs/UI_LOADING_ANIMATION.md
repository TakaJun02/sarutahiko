# ローディング演出仕様（AI 回答待ち演出）

- 版: v0.1（2026-07-11, Fable 起草）
- 参照実装: https://github.com/takahashiJe/guidanceLLM2 の
  `frontend/src/components/OC_ChatMessage.vue` と `frontend/src/assets/tailwind.css`
- 実機挙動はルートの `chat.mov`（コミット禁止・ローカル参照のみ）で Fable が確認済み。
  以下のコード仕様と動画の見た目は一致している。

## Ver1.0 — 完全再現仕様

### 見た目（chat.mov で確認した挙動）

- AI メッセージ位置に、**32×32px の円形スピナー**と、その右に**ステータステキスト**が横並びで表示される。
- スピナーは 3 層構造:
  1. **グラデーションの円弧**（オレンジ→黄→緑）が、弧の長さを伸縮させながら円周を周回する
  2. その SVG コンテナ全体も等速回転しており、弧の動きに周回感が加わる
  3. 中央に **app-icon.png**（20×20px, 円形, 白いグロー）が置かれ、**4 秒に 1 回「クルン」と 1 回転**する
- 参照実装ではテキストは固定文言（ja: 「お待ちください…」）。
  **本システムではここを SSE `status` イベントの `text` で随時更新する**（これが唯一の意図的差分）。

### 実装コード（参照実装から転記。これをそのまま使う）

テンプレート（Vue / Tailwind。クラス接頭辞 `tw-` は参照実装の設定によるもので、
新規プロジェクトで接頭辞を使わないなら `tw-` を外して等価に移植する）:

```html
<!-- Pending/Spinner -->
<div v-if="isPending" class="tw-flex tw-items-center tw-gap-4">
  <div class="tw-relative tw-w-8 tw-h-8">
    <svg class="tw-absolute tw-top-0 tw-left-0 tw-w-full tw-h-full tw-overflow-visible animate-gemini-spinner-container" viewBox="0 0 24 24">
      <defs>
        <linearGradient :id="gradientId" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#FF8A65" />
          <stop offset="50%" stop-color="#FFEB3B" />
          <stop offset="100%" stop-color="#69F0AE" />
        </linearGradient>
      </defs>
      <circle cx="12" cy="12" r="11" fill="none" stroke-width="2.5" class="tw-stroke-gray-500" opacity="0"></circle>
      <circle cx="12" cy="12" r="11" fill="none" :stroke="`url(#${gradientId})`" stroke-width="2.5"
              class="animate-gemini-spinner-arc" stroke-linecap="round" stroke-dasharray="69.115"></circle>
    </svg>
    <div class="tw-absolute tw-inset-0 tw-flex tw-items-center tw-justify-center">
      <img src="/app-icon.png" alt="App Icon"
           class="tw-w-5 tw-h-5 tw-rounded-full animate-icon-rotate"
           style="transform-origin: 50% 50%; box-shadow: 0 0 10px rgba(255, 255, 255, 0.4);">
    </div>
  </div>
  <p class="tw-text-base tw-text-gray-200">{{ pendingText }}</p>
</div>
```

CSS（キーフレーム定義。数値を一切変えないこと）:

```css
/* コンテナを一定速度で回転させるキーフレーム */
@keyframes gemini_spinner_rotate {
  100% { transform: rotate(360deg); }
}

/* 円弧の長さと開始位置を同時に変化させる、シームレスなキーフレーム */
@keyframes gemini_spinner_arc_dash {
  0%   { stroke-dasharray: 1, 68;  stroke-dashoffset: 0; }
  50%  { stroke-dasharray: 50, 68; stroke-dashoffset: -25; }
  100% { stroke-dasharray: 1, 68;  stroke-dashoffset: -68; }
}

/* アイコンを一定時間ごとにクルンと回転させるためのキーフレーム */
@keyframes icon_kurun_rotate {
  0%, 90% { transform: rotate(0deg); }
  100%    { transform: rotate(360deg); }
}

.animate-gemini-spinner-container { animation: gemini_spinner_rotate 2s linear infinite; }
.animate-gemini-spinner-arc       { animation: gemini_spinner_arc_dash 1.5s ease-in-out infinite; }
.animate-icon-rotate              { animation: icon_kurun_rotate 4s ease-in-out infinite; }
```

### 再現チェックリスト（レビュー時に Fable が確認する項目）

- [ ] 円周は `2π × 11 ≈ 69.115`。`stroke-dasharray="69.115"` が初期属性として付き、アニメで上書きされる
- [ ] グラデーション ID はインスタンスごとに一意（複数メッセージ同時表示で色が壊れないため）
- [ ] コンテナ回転 2s linear / 弧の伸縮 1.5s ease-in-out / アイコン 4s（90% まで静止→残り 10% で 1 回転）
- [ ] 弧の端は `stroke-linecap="round"`
- [ ] アイコンは 20×20px・円形クリップ・`box-shadow: 0 0 10px rgba(255,255,255,0.4)` のグロー
- [ ] ダークテーマ背景上で表示（参照実装はダーク基調のチャット画面）
- [ ] テキストは SSE `status` の `text` で更新される（本システム唯一の差分）
- [ ] `token` イベント受信で演出が消え、本文ストリーミング描画に切り替わる

### 参照実装の後続挙動（参考）

参照実装は回答完了後に本文を「空白区切りの単語ごとに 40ms 間隔」で表示するが、
日本語では機能しないため本システムでは採用しない（FR-3 のトークンストリーミングで置換）。

## Ver5.0 — 詳細仕様「Aurora Ring」（v1.0, 2026-07-11 Fable 起草）

Ver1.0 の DNA（グラデーション円弧＋中央アイコン＋クルン回転）を保ったまま、
ステップ連動・多層化・遷移演出を加えて「5 世代分の進化」にする。
**Ver1.0 のコンポーネントは残し、`LoadingSpinnerV5.vue` として別実装**する（比較・切り戻しのため）。

### 5-1. ステップ連動カラーテーマ

SSE `status` の `step` ごとに円弧のグラデーション 3 色を切り替える。切替は 400ms でクロスフェード
（`stop-color` を CSS カスタムプロパティ + `transition` で変化させる）。

| step | テーマ | 3色 (0% / 50% / 100%) |
|---|---|---|
| analyze | 思考の紫→青 | #B388FF / #82B1FF / #80D8FF |
| retrieve | 検索の青→水色 | #448AFF / #40C4FF / #84FFFF |
| web_search | 外へ広がる緑 | #69F0AE / #B9F6CA / #FFFF8D |
| evaluate | 吟味の琥珀 | #FFD180 / #FFAB40 / #FF8A65 |
| generate | Ver1.0 の暖色（原点回帰） | #FF8A65 / #FFEB3B / #69F0AE |

### 5-2. 多層リング

1. **主弧**: Ver1.0 の dash アニメーション（数値そのまま: 1.5s / dasharray 1,68→50,68→1,68）
2. **残光弧**: 主弧の複製を `filter: blur(2.5px)`・opacity 0.45 で主弧の背面に重ねる（グロー表現）
3. **伴走弧**: r=8.5 の細い弧（stroke-width 1、opacity 0.3、dasharray 12,41.4）を**逆回転**（3s linear）で内側に周回させる
4. コンテナ回転（2s linear）とアイコンのクルン（4s、90% 静止→10% で 1 回転）は Ver1.0 のまま

### 5-3. ステータステキスト演出

- テキスト切替: Vue `<Transition>` で「旧テキストが上へ 6px フェードアウト／新テキストが下から 6px フェードイン」（各 250ms、`mode="out-in"`）
- 表示中: ChatGPT 風シマー。テキストに `background: linear-gradient(90deg, rgba(255,255,255,.45), #fff, rgba(255,255,255,.45))` +
  `background-clip: text` + `background-size: 200%` を適用し、`background-position` を 2.2s で無限スイープ

### 5-4. 完了トランジション（token 受信時）

1. リング全体（弧 3 層）を 300ms で `opacity 0` + `scale(0.85)` にフェードアウト
2. 中央アイコンは 300ms で回答メッセージのアバター位置・サイズ（24px）へ**そのまま遷移**して着地
   （実装は FLIP か、同一要素をレイアウトだけ切り替えて `transition: all 300ms ease-out`。白フラッシュ禁止）
3. 着地完了を待たずに本文ストリーミング描画を開始してよい

### 5-5. アクセシビリティ（必須）

`prefers-reduced-motion: reduce` 時:
- 回転・シマー・伴走弧を停止。主弧は静止した 270° の弧（dasharray 52,68）で表示
- テキスト切替は opacity のみのクロスフェード（150ms）
- 完了時も opacity フェードのみ

### 5-6. 実装条件・受け入れチェックリスト

- CSS/SVG のみで実装（canvas・外部アニメーションライブラリ禁止）。アニメーションは transform/opacity/stroke 系のみ
- [ ] step 変化で 3 色が 400ms でクロスフェードする（5 テーマすべて）
- [ ] 主弧の伸縮タイミングが Ver1.0 と完全一致（数値流用）
- [ ] 残光弧・伴走弧が視認できるが主張しすぎない（スクリーンショット比較でレビュー）
- [ ] テキスト切替アニメとシマーが動く
- [ ] token 受信でリング→アバターの morph が 300ms で完了し、白フラッシュがない
- [ ] reduced-motion で全静止版に切り替わる
- [ ] モバイル実機相当（390px 幅）で 60fps 相当の滑らかさ（DevTools performance で確認）
