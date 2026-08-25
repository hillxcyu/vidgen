# Coding Agent Guide for vidgen-omni (ADK 2.0)

## Prerequisites
Install the CLI (one-time):
```bash
uv tool install google-agents-cli
```

---

## Development Phases

### Phase 1: Understand Requirements
Before writing any code, understand the project's requirements, constraints, and success criteria.

### Phase 2: Build and Implement
Implement agent logic in `app/`. Use `agents-cli playground` for interactive testing. Iterate based on user feedback.

### Phase 3: The Evaluation Loop (Main Iteration Phase)
Start with 1-2 eval cases, run `agents-cli eval run`, iterate by making changes and rerunning it until satisfied.

### Phase 4: Pre-Deployment Tests
Run `uv run pytest tests/unit tests/integration`. Fix issues until all tests pass.

### Phase 5: Deploy to Dev
Requires explicit human approval. Run `agents-cli deploy` only after user confirms.

---

## Development Commands

| Command | Purpose |
|---------|---------|
| `agents-cli info` | Inspect project configuration |
| `agents-cli playground` | Interactive local testing |
| `uv run pytest tests/` | Run unit and integration tests |
| `agents-cli eval run` | Run the agent over the eval dataset and grade the traces |
| `agents-cli run "prompt"` | Smoke test the agent directly |

---

## Operational Guidelines for Coding Agents

- **Code preservation**: Only modify code directly targeted by the user's request. Preserve all surrounding code, config values, comments, and formatting.
- **Model selection**: Screenwriter, Storyboarder, Prompt Optimizer, Health Checker, and Quality Rater use `gemini-3.7-flash`. Video generation uses `gemini-omni-flash-preview`.
- **Location**: Set `GOOGLE_CLOUD_LOCATION="global"` for Vertex AI GenAI SDK.
- **Run Python with `uv`**: `uv run python ...`
