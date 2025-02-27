import asyncio
from metagpt.logs import logger
from metagpt.roles.di.data_interpreter import DataInterpreter
from metagpt.utils.recovery_util import save_history
from metagpt.config2 import Config

async def main(query: str = "", model: str = "gpt-4"):
    if model == "gpt-4":
        model_config = Config.from_home("openai.yaml")
    elif model == "o1":
        model_config = Config.from_home("openai.yaml")
        model_config.llm.model = "o1-preview"
    elif model == "gemini-1.5-flash":
        model_config = Config.from_home("gemini.yaml")
        model_config.llm.model = "gemini-1.5-flash"
    elif model == "gemini-1.5-pro":
        model_config = Config.from_home("gemini.yaml")
        model_config.llm.model = "gemini-1.5-pro"
    else:
        raise ValueError(f"Model {model} not supported")
        
    di = DataInterpreter(react_mode='react', config=model_config)
    rsp = await di.run(query)
    logger.info(rsp)
    save_history(role=di)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    args = parser.parse_args()

    asyncio.run(main(args.query))
