# DEFINE

## Session Timestamp: 2026-08-04T04:05:00Z

### Decomposed TODO List (Derived directly from `PLAN.md`)

- [x] **[T001] Setup Development Scaffolding & Docker Environment**: Create directory layout (`src/agents`, `src/tools`, `src/prompts`, `tests`), `pyproject.toml`, `Makefile`, `.env`, `Dockerfile`, and `docker-compose.yml` `[setup]` `[docker]`
- [x] **[T002] Implement Configuration Module**: Load environment variables, Vertex GenAI / Google GenAI SDK auth in `src/config.py` `[setup]` `[docker]`
- [x] **[T003] Establish Shared Session State**: Implement Pydantic `PipelineState` managing scripts, storyboards, frame metrics, and mode selection in `src/state.py` `[state]`
- [x] **[T004] Build Video Processing Parser**: OpenCV terminal frame capture routine in `src/tools/video_parser.py` `[tools]` `[parallel]`
- [x] **[T005] Implement Gemini Omni Flash Wrapper Tool**: Client wrapper supporting `interactions.create` with reference images and I2V payloads in `src/tools/omni_client.py` `[tools]` `[parallel]`
- [x] **[T010] Build File Concatenator Utility**: FFMPEG stream-copy stitcher wrapper in `src/tools/stitcher.py` `[tools]` `[parallel]`
- [x] **[T006] Program Agent System Prompts**: Instruction files for Screenwriter, Storyboarder, Prompt Optimizer, Health Checker, and Quality Rater in `src/prompts/pre_prod_system.txt` and `src/prompts/prod_loop_system.txt` `[prompts]` `[parallel]`
- [x] **[T007] Orchestrate Multi-Agent Routing Graph**: ADK execution sequence in `src/agents/stitcher_graph.py` and CLI entry point `src/main.py` `[agents]`
- [x] **[T008] Write Unit & Integration Evals**: Pytest suite in `tests/test_pipeline.py` executed inside Docker container `[testing]` `[docker]`
- [x] **[T009] Configure GCR AgentHub Publication**: Standardized deployment package in `agent.yaml` and `Dockerfile` `[deploy]` `[docker]`
