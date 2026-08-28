# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-28T02:23:40Z
*   **Target Task:** Model Upgrade to `gemini-omni-1.1-flash-preview`
*   **Status:** IN_PROGRESS

---

## 📝 Detailed TODO Breakdown

### Phase 1: Configuration & Code Updates [config] [agent]
- [ ] `[T001]` **[config]** Update `VIDEO_GEN_MODEL` in [`app/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/config.py) and [`src/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/config.py) to `"gemini-omni-1.1-flash-preview"`.
- [ ] `[T002]` **[agent]** Update model references in [`agent.yaml`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/agent.yaml), [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py), [`app/tools/omni_client.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/tools/omni_client.py), and [`src/tools/omni_client.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/tools/omni_client.py).
- [ ] `[T003]` **[docs]** Update documentation in [`GEMINI.md`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/GEMINI.md), [`README.md`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/README.md), and [`interaction_explained.md`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/interaction_explained.md).

### Phase 2: Test Updates & Verification [test]
- [ ] `[T004]` **[test]** Update test assertions in [`tests/unit/test_config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/unit/test_config.py), [`tests/test_config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/test_config.py), and [`tests/test_omni_client.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/test_omni_client.py).
- [ ] `[T005]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).

### Phase 3: Deployment & Git [deploy] [git]
- [ ] `[T006]` **[deploy]** Deploy agent container to Vertex AI Agent Runtime in `asia-east1`.
- [ ] `[T007]` **[git]** Commit all changes and push to `main` on GitHub.
