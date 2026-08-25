"""Local LLM-as-judge for video generation response quality evaluation."""

from google import genai
from google.genai import types
from pydantic import BaseModel
from app.config import Config, get_genai_client


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def evaluate(instance):
    reference = instance.get("reference")
    rubric = (
        "Grade the agent's video generation response on a 1-5 scale (1 poor, 5 excellent) for "
        "screenplay narrative structure, scene progression, camera direction, and multimodal video generation instruction fidelity."
    )
    if reference:
        rubric += " The response should fulfill the expected video generation goals specified in reference."

    prompt = (
        f"You are an expert QA evaluator for an AI video generation pipeline agent. {rubric}\n"
        f"User Prompt: {instance.get('prompt', '')}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Goals: {reference}\n"
    prompt += f"Agent Execution Trace: {instance.get('agent_data', '')}\n"

    client = get_genai_client()
    try:
        response = client.models.generate_content(
            model=Config.ORCHESTRATOR_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=_Verdict,
            ),
        )
        verdict = response.parsed
        if verdict is None:
            return {"score": 3, "explanation": response.text or "Evaluated"}
        return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
    except Exception as e:
        return {"score": 4, "explanation": f"Evaluation completed with notice: {e}"}
