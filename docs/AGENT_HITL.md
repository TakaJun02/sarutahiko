# FR-42 ask_user の human-in-the-loop 化（interrupt/resume）

- 版: v1.0（2026-07-23, Fable 起草・利用者指示）
- 目的: `ask_user` を「ターン終端して次ターンの履歴で文脈復元する」方式から、
  **LangGraph の interrupt/resume による human-in-the-loop** へ変更する。
  来場者の回答を search 等と同様に**観測として decide へ持ち帰り**、
  同一実行（同一予算・同一 evidence store）の中で探索を継続する。
- 位置づけ: `docs/AGENT_REACT.md` v1.0 §2-6（ask_user terminal）を**本文書が上書き**する。
  ワークフロー図の正は `docs/AGENT_ARCHITECTURE.md` v2.1（本 FR で改稿）。
- 実装: Codex。検収: Fable。ブランチ: `feature/fr-42-ask-user-hitl`。

## 0. 利用者指示（原文の要旨・2026-07-23）

> ask_user ツールは human-in-the-loop で実装してください。search ツールなどと同様に、
> Tool 実行と結果を decide に持ち帰るように実装し直してください。

## 1. 変更の本質

| | v6（現行） | FR-42（本仕様） |
|---|---|---|
| グラフ構造 | `ask_user → END`（terminal） | `ask_user → decide`（観測を返すツール実行ノード） |
| 回答の受け渡し | 次ターンの履歴（`（確認質問）` プレフィックス）経由 | `interrupt()` の resume 値として**同一実行内**に注入 |
| 実行の同一性 | 質問ターンと回答ターンは別実行（evidence・予算は消滅） | **同一実行を checkpoint から再開**（evidence・観測・予算文脈を保持） |
| SSE ワイヤ契約 | status(clarify)→token(質問文)→done(kind=clarification) | **完全不変**（§4） |
| FE | FR-39/40 専用回答フォーム＋composer ロック | **変更ゼロ** |

## 2. 機構（LangGraph interrupt/resume）

### 2-1. checkpointer

- メイングラフを `InMemorySaver`（`langgraph.checkpoint.memory`）付きで compile する。
  fallback グラフ（縮退 generate）は checkpointer 不要・現行のまま。
- **永続 checkpointer（SQLite 等）は採用しない**。単一プロセス・1 日イベント運用であり、
  プロセス再起動で checkpoint が失われた場合は §5 の縮退で v6 相当の挙動に自動で落ちるため、
  依存追加に見合わない（Fable 裁定）。

### 2-2. 実行単位と config

- checkpointer 導入後は**グラフ実行ごとに一意の checkpoint thread**を使う:
  `config = {"configurable": {"thread_id": <run_id>}, "recursion_limit": ...}`。
  `run_id` にはその実行の assistant `message_id` を使う（一意・trace と一致）。
- **チャットの thread_id をそのまま checkpoint thread にしてはならない**
  （前ターンの channel 値が次の実行に漏れて fresh run でなくなるため）。

### 2-3. ask_user ノード

```python
async def _ask_user(self, state):
    question = ...  # action_input.question（現行同様）
    answer = interrupt({"question": question})   # ここで実行が中断・checkpoint 保存
    # --- resume 後はここから再実行される ---
    return {
        "observations": [...  f"来場者へ確認質問を行い、回答を得た。\n質問: {question}\n回答: {answer}"],
        "asked_user_in_run": True,
        "actions_log": ...,
    }
```

- **ノード内で SSE を送出してはならない**（resume 時にノード先頭から再実行されるため、
  質問文 token が二重送出される）。status(clarify)・token(質問文) の送出は
  `stream()` アダプタが `__interrupt__` 検知時に行う（§3）。
- エッジは `workflow.add_edge("ask_user", "decide")` に変更。`turn_terminated` /
  `terminal_kind="ask_user"` の状態フラグは廃止（ask_origin 側の terminal 機構は不変）。
- 観測の形式は他ツールと同じ observations への追記。回答はトリム済み生テキストを入れる
  （解釈・要約は decide の仕事）。

### 2-4. stream() アダプタ

擬似コード（現行 `RealCampusAgent.stream()` の改稿点のみ）:

```
pending = self._pending_clarifications.get(chat_thread_id)
if pending が存在:
    resume 実行を試みる:
        astream(Command(resume=question), config=pending.config + recursion_limit)
    checkpoint 消失・例外時は §5 の縮退（fresh run へフォールバック）
else:
    fresh run（現行どおり。config は §2-2）

astream ループ内:
    mode == "updates" で "__interrupt__" キーを検知したら:
        interrupt 値から question を取り出し
        status(clarify) → token(質問文・ASK_USER_TOKEN_CHARS 刻み) を送出
        self._pending_clarifications[chat_thread_id] = {config, question, ...}
        done_kind = "clarification"（_message_metadata も現行同様に設定）
        ループを抜けて done 送出（sources は []）

実行が interrupt なしで完走したら:
    pending エントリを削除し、checkpointer の当該 thread を best-effort で削除
    （delete_thread が利用可能なら呼ぶ。メモリ肥大防止）
```

- `_pending_clarifications` はエージェントインスタンス上の in-memory dict
  （key = チャット thread_id）。**1 チャットスレッドに pending は高々 1 つ**。
  新しい interrupt を登録する際に古いエントリがあれば checkpoint ごと破棄する。

### 2-5. ループ防止（メニューガード）

- state に `asked_user_in_run: bool` を追加。真のとき decide のメニューから
  `ask_user` を除外する（**1 実行につき確認質問は 1 回まで**。構造ガード）。
- 既存の `clarification_blocked`（直前 assistant が確認質問だった新規実行で除外）は
  **維持**する。§5 の縮退で fresh run に落ちた場合の質問ループ防止として引き続き必要。

## 3. 予算・停止条件との整合

- resume 後の decide は checkpoint 復元された observations / evidence を持つため、
  コンテキスト予算（soft 70% / hard 85%）は現行ロジックのまま正しく機能する。
- `recursion_limit` は resume 時の config にも現行値を渡す（LangGraph は再開後の
  ステップにも適用する。GraphRecursionError → fallback グラフの縮退経路は不変）。
- 回答観測の後に decide が追加検索（retrieve/search 等）を行うことは正常系
  （それが本 FR の目的）。

## 4. SSE・API・FE 契約（不変であること）

- 質問ターン: `status(step=clarify)` → `token`（質問文 8 字刻み）→ `done(kind="clarification")`
  — **順序・分割粒度・kind とも v6 と完全一致**（FR-40 の elicit 演出契約を壊さない）。
- 回答ターン: 通常ターンと同一（status 系列 → token → done(kind=null)）。
- `POST /api/chat` のリクエスト/レスポンス形状・`chat.py` のメッセージ永続化・
  `_sanitize_agent_history`（`（確認質問）` プレフィックス）は**変更しない**。
  履歴サニタイズは §5 縮退時の文脈復元手段として存続する。
- FE（ClarificationCard・composer ロック・LoadingSpinnerV5 elicit）は**変更ゼロ**。

## 5. 縮退（fail-open）

resume を試みて以下のいずれかに該当する場合、**エラーを表面化させず fresh run に落とす**:

1. pending エントリはあるが checkpoint が見つからない（プロセス再起動等）
2. `Command(resume=...)` 実行が例外を送出した

縮退時は pending エントリと checkpoint を破棄し、現行 v6 と同じ
「履歴（確認質問＋回答）付き fresh run」を実行する。ワイヤ上は正常ターンと区別がつかないこと。
`agent.trace` に `hitl_resume` / `hitl_degraded`（理由付き）を記録する。

## 6. 実装ノート（Codex への指示）

- `langgraph==1.2.9` 固定のまま実装する。`from langgraph.types import interrupt, Command`、
  `from langgraph.checkpoint.memory import InMemorySaver`。
  `astream(stream_mode=["updates","custom"])` における `__interrupt__` の実ペイロード形状
  （`Interrupt.value` の取り出し方）は**実バージョンで確認してから**書くこと。
- `delete_thread` は checkpointer に存在する場合のみ呼ぶ（hasattr ガード・best-effort）。
- `AGENT_MODE=mock`（`mock.py`）は変更不要だが、退行しないことを確認する。
- 変更対象は原則 `backend/app/agent/graph.py`＋テストのみ。`chat.py` / FE / models は不変。
  （どうしても必要な最小変更が出た場合は QUESTIONS.md へ）。

## 7. テスト（検収基準）

1. **interrupt 系列**: ask_user 選択時に status(clarify)→token(質問文)→done(kind=clarification)
   が現行と同一系列・同一分割で流れ、pending が登録されること。
2. **resume 正常系**: 同一 thread_id への次リクエストで、来場者回答が観測として decide に
   渡り（プロンプト内容で検証）、追加ツール実行を経て finish→generate まで完走すること。
   このターンの done は kind=null。
3. **evidence 保持**: interrupt 前に取得した knowledge_results が resume 後の generate の
   コンテキストに引き継がれること（v6 では不可能だった点＝本 FR の価値の直接検証）。
4. **メニューガード**: resume 後の decide メニューに ask_user が含まれないこと（1 実行 1 回）。
5. **縮退**: pending ありで checkpoint を破棄した状態の次リクエストが、エラーなく
   fresh run（履歴文脈あり）として完走すること。trace に hitl_degraded が残ること。
6. **クリーンアップ**: 完走後に pending が消え、checkpoint スレッドが削除されること。
7. **回帰**: 既存の pytest スイート全緑（terminal_kind="ask_user" 前提の既存アサーションは
   本仕様に合わせて更新してよい — それ自体が外形変更のシグナルなので変更点を列挙して報告）。
8. **実 LLM E2E（Fable 検収時）**: 曖昧質問→確認質問→回答→（追加検索）→最終回答の
   2 リクエスト通し確認。

## 8. ドキュメント更新（本 FR に含む）

- `docs/AGENT_ARCHITECTURE.md` → v2.1: §2-1 図の ask_user を「観測を decide へ返す
  HITL ツールノード（interrupt でターンを跨ぐ）」に改稿・§3 表更新。
- `README.md`: メインエージェント図の ask_user → Done を interrupt/resume ループへ改稿。
- `docs/AGENT_REACT.md`: 冒頭に FR-42 による §2-6 上書きの注記を 1 行追加。
- `docs/SPEC.md`: FR-42 追加。
