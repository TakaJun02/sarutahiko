# campus-guide-agent (oc_2026)

秋田県立大学 本荘キャンパスの学内情報を answering する AI エージェントシステム。
主な利用シーンは**オープンキャンパス 2026 来場者**（高校生・保護者）からの質問対応。

## 役割分担（厳守）

| 役割 | 担当 |
|---|---|
| 仕様の決定・アーキテクチャ判断 | **Fable**（Claude Code） |
| 実装・サーベイ・ナレッジ収集 | **Codex** |
| コードレビュー | **Fable**（Claude Code） |

- Fable は原則コードを書かない。仕様を `docs/` に落とし、Codex に実装を委譲し、成果物をレビューする。
- Codex は仕様の不明点を勝手に決めない。不明点は実装を止めず `docs/QUESTIONS.md` に追記し、Fable の裁定を待つ。
- 仕様変更はすべて `docs/` の該当ファイルを更新してから実装に反映する（ドキュメントが常に正）。

## 確定済みの仕様（変更には利用者の承認が必要）

1. **Agentic RAG ベース**＋必要に応じて **Web Search** を行う。
2. フロントには ChatGPT/Gemini アプリのように、**推論ステップごとに「今何をしているか」を短いテキストで随時通知**する。
3. LLM はこのマシンの GPU（**RTX 3090 Ti 24GB**）を使い、**vLLM 経由のローカル LLM**。
4. UI の「AI からの回答を待つ間の演出」は [guidanceLLM2](https://github.com/takahashiJe/guidanceLLM2) を**完全再現**して Ver1.0 とし、その後 Ver5.0 と呼べるレベルにアップデートする（仕様: `docs/UI_LOADING_ANIMATION.md`）。
5. RAG ナレッジは未整備。**Codex が WebSearch しながら作成**する（計画: `docs/KNOWLEDGE.md`）。

上記以外の技術選定は Fable が柔軟に決定してよい（決定したら `docs/ARCHITECTURE.md` に記録）。

## ドキュメントマップ

- `docs/SPEC.md` — システム仕様書（機能要件・非機能要件・ロードマップ）
- `docs/ARCHITECTURE.md` — 技術構成・SSE イベントスキーマ・リポジトリ構成
- `docs/UI_LOADING_ANIMATION.md` — ローディング演出 Ver1.0 完全再現仕様（コード付き）＋ Ver5.0 方針
- `docs/UI_LOGIN.md` — ログイン機能・ログイン画面 UI 仕様（ChatGPT/Gemini 風）
- `docs/KNOWLEDGE.md` — RAG ナレッジ構築計画（収集源・フォーマット・検証ルール）
- `docs/QUESTIONS.md` — Codex → Fable への質問・裁定ログ
- `AGENTS.md` — Codex 向け実装ガイド（このファイルと整合を保つこと）

## リポジトリの約束事

- ブランチ: `main`（リリース）← `develop`（統合）← `feature/*`（作業）。PR は `develop` 向け。
- `chat.mov`（約 800MB の参考画面録画）と `app-icon.png` はルートに置いてあるが、**chat.mov は絶対にコミットしない**（.gitignore 済み）。
- `referenceUI/`（FR-14 意匠の正となる Gemini アプリ実スクショ）も**ローカル保持のみ・コミットしない**（.gitignore 済み。実測値は `docs/UI_POLISH_V2.md` §10-2 に転記済み）。
- `app-icon.png` はローディング演出の中央アイコンとして frontend の public/ にコピーして使う。
- ドキュメント・コミットメッセージは日本語でよい。コード内の識別子・コメントは英語。
- 参照実装 guidanceLLM2 はリポジトリに含めない。必要なら都度 clone する（演出の該当コードは `docs/UI_LOADING_ANIMATION.md` に全文転記済み）。

## 環境メモ

- GPU: NVIDIA GeForce RTX 3090 Ti (24GB VRAM) ×1
- OS: Linux / shell: bash
- ffmpeg はシステム未導入（動画確認が必要なら Python venv + imageio-ffmpeg を使う）
