# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T03:06:30Z
*   **Target Task:** Fix `streaming_agent_run_with_events` argument handling in `reasoning_engine_adapter.py` and deploy
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Code Fix & Local Validation [backend] [adapter]
- [ ] `[T001]` **[backend]** Update `app/app_utils/reasoning_engine_adapter.py` to dynamically inspect method signature and correctly format arguments for `streaming_agent_run_with_events` and standard query methods.
- [ ] `[T002]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`) and verify zero regressions.

### Phase 2: Deployment & CI/CD [deploy] [infra]
- [ ] `[T003]` **[git]** Commit changes on `main` and push to GitHub to trigger Cloud Build for Cloud Run.
- [ ] `[T004]` **[deploy]** Update Vertex AI Agent Runtime reasoning engine in `asia-east1` via `agents-cli deploy`.

### Phase 3: Live Verification [verify]
- [ ] `[T005]` **[verify]** Test live `:streamQuery` with `streaming_agent_run_with_events` against Agent Runtime in `asia-east1` to ensure events stream successfully without error.
