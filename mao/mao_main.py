import argparse
import asyncio
import os
from multiagents.mao import BedrockSelector

async def main(query: str):
    # Initialize multi-agent system
    system = BedrockSelector()
    
    # Process request through agent pipeline
    try:
        response = await system.process_request(query)
        print("\nFinal Result:")
        print(response)
    except Exception as e:
        print(f"Error processing request: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Agent Orchestrator CLI")
    parser.add_argument("--query", type=str, required=True, 
                       help="Task description to execute")
    args = parser.parse_args()

    asyncio.run(main(args.query))