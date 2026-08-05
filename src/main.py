import argparse
import sys
from src.state import PipelineState
from src.agents.stitcher_graph import run_pipeline, create_adk_agents
from src.config import Config, get_genai_client

def start_interactive_chat():
    """Starts an interactive conversational chat session with the Master Orchestrator Agent."""
    print("=" * 70)
    print("🤖 Welcome to the GenMedia-Omni Master Orchestrator Agent Chat!")
    print("Type your video generation prompt, ask questions, or type 'exit' to quit.")
    print("=" * 70)

    config = Config()
    client = get_genai_client()
    agents = create_adk_agents(config)
    orchestrator = agents["orchestrator"]

    while True:
        try:
            user_input = input("\n👤 User > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                print("👋 Exiting agent chat. Goodbye!")
                break

            if user_input.lower().startswith("generate ") or user_input.lower().startswith("create "):
                intent = user_input.replace("generate ", "").replace("create ", "").strip()
                print(f"\n🎬 OrchestratorAgent: Understood! Triggering multi-agent pipeline for '{intent}'...")
                state = PipelineState(original_intent=intent, mode="i2v_chaining", num_shots=3)
                result_state = run_pipeline(state, output_dir="./output", client=client)
                print(f"✅ Pipeline Complete! Stitched Video: {result_state.stitched_video_path}")
            else:
                response = client.models.generate_content(
                    model=orchestrator.model,
                    contents=f"{orchestrator.instruction}\nUser: {user_input}\nOrchestratorAgent:"
                )
                print(f"\n🤖 OrchestratorAgent > {response.text.strip()}")
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Goodbye!")
            break

def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Generative Media Pipeline (GenMedia-Omni)")
    parser.add_argument("--prompt", type=str, default=None, help="Video prompt intent (if omitted, launches interactive chat)")
    parser.add_argument("--shots", "--num-shots", type=int, default=3, help="Number of video shots to generate (default: 3)")
    parser.add_argument("--mode", type=str, choices=["reference", "i2v_chaining"], default="i2v_chaining", help="Stitching mode")
    parser.add_argument("--output", type=str, default="/tmp/vidgen_output", help="Output directory")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch interactive chat mode")

    args = parser.parse_args()

    if args.interactive or args.prompt is None:
        start_interactive_chat()
        return

    print(f"Starting GenMedia-Omni Pipeline...")
    print(f"Prompt: {args.prompt}")
    print(f"Shots: {args.shots}")
    print(f"Mode: {args.mode}")

    state = PipelineState(
        original_intent=args.prompt,
        num_shots=args.shots,
        mode=args.mode
    )

    result_state = run_pipeline(state, output_dir=args.output)
    print(f"Pipeline Execution Complete!")
    print(f"Stitched Video Output: {result_state.stitched_video_path}")

if __name__ == "__main__":
    main()
