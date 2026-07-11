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

## Ver5.0 — アップデート方針（詳細仕様は Phase 1 完了後に Fable が起草）

Ver1.0 の DNA（グラデーション円弧＋中央アイコン＋クルン回転）は保ちつつ、
「5 世代分の進化」と感じられる品質にする。候補方向性:

1. **ステップ連動**: SSE `status` の `step` に応じて弧の色・速度・表情が変わる
   （例: retrieve=青系で高速、web_search=緑系で外向きパルス、generate=Ver1.0 の暖色）
2. **ステータステキストの演出**: テキスト切替時のクロスフェード／シマー（ChatGPT 風の光沢スイープ）
3. **質感向上**: 弧のグロー（にじみ）、複数レイヤの弧、微細なパーティクル
4. **遷移の滑らかさ**: 演出→本文描画への morph（スピナーがアバターアイコン位置に着地する等）
5. **アクセシビリティ**: `prefers-reduced-motion` 時は回転を止め、フェードのみにする（必須）

実装は CSS/SVG を基本とし、必要なら canvas を許可する。外部アニメーションライブラリ追加は Fable の承認制。
