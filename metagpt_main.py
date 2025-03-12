import asyncio
import argparse
from metagpt.logs import logger
from metagpt.roles.di.data_interpreter import DataInterpreter
from metagpt.utils.recovery_util import save_history
from metagpt.config2 import Config

async def main(query: str = "", model: str = "gpt-4o"):
    print(f"Using model: {model}")  # Debug print
        
    if model.startswith("gemini"):
        # Use Gemini config for any Gemini model
        model_config = Config.from_home("gemini.yaml")
        model_config.llm.model = model
        print(f"Selected Gemini config with model {model_config.llm.model}")
    elif model.startswith("gpt"):
        # Use OpenAI config for any GPT model
        model_config = Config.from_home("openai.yaml")
        model_config.llm.model = model
        print(f"Selected OpenAI config with model {model_config.llm.model}")
    else:
        raise ValueError(f"Model {model} not supported")
    
    di = DataInterpreter(react_mode='react', config=model_config)
    rsp = await di.run(query)
    logger.info(rsp)
    save_history(role=di)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    parser.add_argument("--model", type=str, required=True)
    args = parser.parse_args()

    print(f"Starting with model: {args.model}")  # Debug print
    asyncio.run(main(args.query, args.model))
