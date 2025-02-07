import argparse
import asyncio
import os
from dotenv import load_dotenv
from autogen_ext.models.openai import OpenAIChatCompletionClient
from multiagents.magentic_one import MagenticOne
from multiagents.round_robin import RoundRobin
from multiagents.selector import Selector
from multiagents.swarm.swarm import SwarmTeam
from autogen_agentchat import EVENT_LOGGER_NAME
from autogen_agentchat.ui import Console
import logging
from logging.handlers import RotatingFileHandler

load_dotenv()

async def main(hil_mode: bool, query: str, model: str, mas_type: str, include_web_surfer: bool, include_video_surfer: bool) -> None:
    try:
        if 'gpt-' in model or 'o1' in model or 'o3' in model:
            client = OpenAIChatCompletionClient(
                api_key=os.environ["OPENAI_API_KEY"],
                model=model
            )
        elif 'gemini' in model or 'gemma' in model:
            client = OpenAIChatCompletionClient(
                model=model,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=os.environ["GEMINI_API_KEY"],
                model_info={
                    "vision": True,
                    "function_calling": True,
                    "json_output": True,
                    "family": "unknown",
                },
            )
        else:
            raise ValueError(f"Unsupported model: {model}")
        
        try:
            if mas_type == "magentic_one":
                agent = MagenticOne(client=client, hil_mode=hil_mode)
            elif mas_type == "round_robin":
                agent = RoundRobin(client=client, max_turns=20, include_web_surfer=include_web_surfer, include_video_surfer=include_video_surfer)
            elif mas_type == "selector":
                agent = Selector(client=client, max_turns=20, include_web_surfer=include_web_surfer, include_video_surfer=include_video_surfer)
            elif mas_type == "swarm":
                agent = SwarmTeam(client=client, max_turns=20)
            await Console(agent.run_stream(task=query))
        except Exception as e:
            print(f"Error during agent execution: {str(e)}")
            raise
            
    except Exception as e:
        print(f"Fatal error in main: {str(e)}")
        raise

# Set up logging configuration
def setup_logging(log_level=logging.INFO):
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    file_handler = RotatingFileHandler(
        'logs/app.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    logger.addHandler(file_handler)
    
    # Also set up the EVENT_LOGGER specifically
    event_logger = logging.getLogger(EVENT_LOGGER_NAME)
    event_logger.setLevel(log_level)
    
    return logger

if __name__ == "__main__":
    # Set up logging before parsing arguments
    logger = setup_logging()
    
    parser = argparse.ArgumentParser(description="Run MagenticOne.")
    parser.add_argument("--hil_mode", action="store_true", default=False, help="Run in human-in-the-loop mode")
    parser.add_argument("--query", type=str, help="Query to run (can be text or path to .txt file)")
    parser.add_argument("--mas_type", type=str, help="Type of MAS to use (round_robin, swarm, selector, or magentic_one)")
    parser.add_argument("--model", type=str, required=True, help="Model to use for query")
    parser.add_argument("--include_web_surfer", action="store_true", default=False, help="Include WebSurfer in the MAS")
    parser.add_argument("--include_video_surfer", action="store_true", default=False, help="Include VideoSurfer in the MAS")
    args = parser.parse_args()

    # Validate query arguments
    if not args.query:
        parser.error("Must specify --query")

    if not args.mas_type:
        parser.error("Must specify --mas_type")

    if not args.model:
        parser.error("Must specify --model")

    # Process query based on type
    query = None
    if args.query == "":
        query = "What capabilities do you have? Please describe what you can help me with."
    elif args.query:
        if os.path.exists(args.query):
            with open(args.query, "r") as file:
                query = file.read()
        else:
            query = args.query

    asyncio.run(main(args.hil_mode, query, args.model, args.mas_type, args.include_web_surfer, args.include_video_surfer))