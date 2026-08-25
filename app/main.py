import argparse
import sys
import uvicorn
from app.state import PipelineState
from app.agents.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Generative Media Pipeline (vidgen-omni)")
    parser.add_argument("--prompt", type=str, default="A red panda skiing in Hakuba, Japan", help="Video description prompt")
    parser.add_argument("--shots", type=int, default=3, help="Number of shots (1-10)")
    parser.add_argument("--mode", type=str, default="i2v_chaining", choices=["i2v_chaining", "reference"], help="Generation mode")
    parser.add_argument("--server", action="store_true", help="Launch FastAPI Web Studio server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    args = parser.parse_args()

    if args.server:
        print(f"Starting vidgen-omni Web Studio on http://{args.host}:{args.port}")
        uvicorn.run("app.fast_api_app:app", host=args.host, port=args.port, reload=False)
        return

    print(f"Executing vidgen-omni CLI Pipeline...")
    print(f"Prompt: {args.prompt}")
    print(f"Shots: {args.shots}, Mode: {args.mode}")

    state = PipelineState(
        original_intent=args.prompt,
        num_shots=args.shots,
        mode=args.mode
    )
    final_state = run_pipeline(state, output_dir="./output")
    print(f"\nPipeline Execution Complete!")
    print(f"Stitched Video: {final_state.stitched_video_path}")
    print(f"Quality Rating: {final_state.quality_rating}")


if __name__ == "__main__":
    main()
