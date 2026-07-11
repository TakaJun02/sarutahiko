# campus-guide-agent

秋田県立大学 本荘キャンパスの学内情報を答える AI エージェント（オープンキャンパス 2026 来場者向け）。

- Agentic RAG + Web Search、ローカル LLM（vLLM）、推論ステップの実況表示
- 仕様: [`docs/SPEC.md`](docs/SPEC.md) ／ 構成: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- 開発体制: 仕様・レビュー = Claude (Fable)、実装・サーベイ = Codex — 詳細は [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md)

## Phase 1 ローカル起動

### Backend

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

SQLite は既定で `backend/data/campus-guide.sqlite3` に作成されます。設定例は `.env.example` を参照してください。

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite dev server は `/api` を既定で `http://127.0.0.1:8080` にプロキシします。
必要に応じて `VITE_API_PROXY_TARGET` でプロキシ先を上書きできます。

### Verification

```bash
cd frontend && npm run build
cd ..
pytest
```
