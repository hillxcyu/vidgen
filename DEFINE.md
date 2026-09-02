# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-09-02T01:43:20Z
*   **Target Task:** Incorporate Gemini Agentic Video Understanding (`media_processing="agentic"`)
*   **Status:** COMPLETED

---

## 📝 Detailed TODO Breakdown

### Phase 1: Dependencies & Configuration [backend]
- [x] `[T001]` **[backend]** Update `pyproject.toml` to require `google-genai>=2.21.0`.
- [x] `[T002]` **[backend]** Install/upgrade `google-genai` in the virtualenv (`uv pip install "google-genai>=2.21.0"`).
- [x] `[T003]` **[backend]** Add `MEDIA_PROCESSING: str = os.getenv("MEDIA_PROCESSING", "agentic")` in [`app/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/config.py) and [`src/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/config.py).

### Phase 2: Agentic Video Part Helper [backend] [tools]
- [x] `[T004]` **[backend]** Implement `create_agentic_video_part()` in [`app/tools/video_parser.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/tools/video_parser.py) and [`src/tools/video_parser.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/tools/video_parser.py) to format `types.Part(file_data=..., media_processing="agentic")` for `gs://` URIs and `types.Part(inline_data=..., media_processing="agentic")` for raw byte buffers.

### Phase 3: Quality Rater Integration [backend] [pipeline]
- [x] `[T005]` **[backend]** Update `evaluate_video_clip_quality` and `QualityRaterAgent` prompt in [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py) to use `create_agentic_video_part` with `media_processing="agentic"` and temporal audit directives.
- [x] `[T006]` **[backend]** Update `evaluate_clip_quality` in [`app/agents/pipeline.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agents/pipeline.py) and [`src/agents/stitcher_graph.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/agents/stitcher_graph.py) to use `create_agentic_video_part`.

### Phase 4: Unit & Integration Testing [test]
- [x] `[T007]` **[test]** Create unit test suite [`tests/unit/test_agentic_video.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/unit/test_agentic_video.py) testing `create_agentic_video_part` with `gs://` URI, HTTPS URL, and inline bytes.
- [x] `[T008]` **[test]** Run full test suite: `uv run pytest tests/unit tests/integration` (37/37 passed, 100%).

### Phase 5: Cloud Build & Deployment [cloudrun] [deploy]
- [x] `[T009]` **[cloudrun]** Build updated Docker container `asia-east1-docker.pkg.dev/vital-octagon-19612/vidgen/vidgen-omni:latest` via Cloud Build (`status: SUCCESS`).
- [x] `[T010]` **[cloudrun]** Redeploy Cloud Run frontend `vidgen-frontend` in `asia-east1` (Revision `vidgen-frontend-00003-d9n`).
- [x] `[T011]` **[deploy]** Redeploy Vertex AI Agent Runtime reasoning engine in `vital-octagon-19612` (`asia-east1`) (`4207320826103463936`).
- [x] `[T012]` **[git]** Commit and push all changes to GitHub `main`.
