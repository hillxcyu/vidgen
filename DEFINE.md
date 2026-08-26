# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T06:01:00Z
*   **Target Task:** Fix Stream Serialization Crash for Artifacts (`TypeError: Object of type Part is not JSON serializable`)
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Serialization Fix & Code Refinement [adapter] [storage]
- [ ] `[T001]` **[adapter]** Update `app/app_utils/reasoning_engine_adapter.py` with custom `safe_json_dumps` to serialize `types.Part`, `_ArtifactVersion`, and nested Pydantic models.
- [ ] `[T002]` **[storage]** Refine `app/tools/gcs_storage.py` `ensure_gcs_bucket` to prevent redundant IAM policy checks on existing buckets.

### Phase 2: Testing & CI/CD [test] [deploy]
- [ ] `[T003]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T004]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T005]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [ ] `[T006]` **[verify]** Verify live reasoning engine stream query serializes events and artifacts properly.
