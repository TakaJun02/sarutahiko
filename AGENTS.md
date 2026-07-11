# AGENTS.md — Codex 向け実装ガイド

あなた（Codex）はこのプロジェクトの**実装・サーベイ・ナレッジ収集担当**。
仕様の決定とレビューは Fable（Claude Code）が行う。

## プロジェクト概要

campus-guide-agent — 秋田県立大学 本荘キャンパスの学内情報を答える AI エージェント。
主対象はオープンキャンパス 2026 来場者（高校生・保護者）。
Agentic RAG + Web Search、ローカル LLM（vLLM / RTX 3090 Ti 24GB）、推論ステップの実況を SSE 配信。

## 必読ドキュメント（実装前に読む。ドキュメントが常に正）

1. `docs/SPEC.md` — 機能要件・非機能要件・ロードマップ
2. `docs/ARCHITECTURE.md` — 技術選定・SSE イベントスキーマ・リポジトリ構成
3. `docs/UI_LOADING_ANIMATION.md` — ローディング演出 Ver1.0 の完全再現仕様（コード全文付き）
4. `docs/UI_LOGIN.md` — ログイン機能・ログイン画面 UI 仕様
5. `docs/KNOWLEDGE.md` — ナレッジ収集のルール（WebSearch 時に厳守）

## 行動ルール

- **仕様の不明点を勝手に決めない。** `docs/QUESTIONS.md` に起票し、妥当な暫定案で実装を続ける
  （ブロックされる場合のみ停止）。docs/ と矛盾する実装をしない。
- 技術選定の変更（ライブラリ追加を含む）は Fable の承認が必要。まず QUESTIONS.md へ。
- ブランチは `feature/*` を切り、PR は `develop` 向け。1 PR = 1 トピック。
- コードの識別子・コメントは英語。ドキュメント・PR 説明は日本語でよい。
- テストを書く（backend: pytest / frontend: 最低限 Vitest でロジック部分）。
- `chat.mov` は絶対にコミットしない。`.env` もコミットしない。
- ローディング演出 Ver1.0 は `docs/UI_LOADING_ANIMATION.md` のコードを**数値を一切変えずに**移植する。
  レビューは同ドキュメントのチェックリストで行われる。
- ナレッジ収集では一次情報源（大学公式サイト）優先・出典 URL 必須・推測補完禁止
  （詳細は `docs/KNOWLEDGE.md` §3）。

## 環境

- GPU: RTX 3090 Ti (24GB) ×1 / Linux / docker compose 使用
- vLLM は OpenAI 互換サーバとして起動し、backend からは OpenAI クライアントで接続
- モデル・URL 等は環境変数注入（`.env.example` を保守する）
