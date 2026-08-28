# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-28T07:55:05Z
*   **Target Task:** Fix Reference Image Conditioning in I2V Mode
*   **Status:** IN_PROGRESS

---

## 📝 Detailed TODO Breakdown

### Phase 1: Code Updates [backend] [pipeline]
- [ ] `[T001]` **[backend]** Update [`app/fast_api_app.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/fast_api_app.py) to pass `reference_images_b64=reference_assets_b64` in `i2v_chaining` mode.
- [ ] `[T002]` **[backend]** Update [`app/agents/pipeline.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agents/pipeline.py) to pass `reference_images_b64=state.reference_assets_b64` in `i2v_chaining` mode.

### Phase 2: Testing & Verification [test]
- [ ] `[T003]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`) to verify 100% pass rate.

### Phase 3: Cloud Run Build & Deploy [cloudrun] [deploy]
- [ ] `[T004]` **[cloudrun]** Build and push container `asia-east1-docker.pkg.dev/vital-octagon-19612/vidgen/vidgen-omni:latest` via Cloud Build.
- [ ] `[T005]` **[cloudrun]** Deploy Cloud Run service `vidgen-frontend` in `asia-east1`.
- [ ] `[T006]` **[deploy]** Deploy agent container to Vertex AI Agent Runtime in `vital-octagon-19612` (`asia-east1`).
- [ ] `[T007]` **[git]** Commit all changes and push to GitHub `main`.
