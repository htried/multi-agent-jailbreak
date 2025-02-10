import asyncio
from metagpt.logs import logger
from metagpt.roles.di.data_interpreter import DataInterpreter
from metagpt.utils.recovery_util import save_history

async def main(query: str = ""):
    di = DataInterpreter(react_mode='react')
    rsp = await di.run(query)
    logger.info(rsp)
    save_history(role=di)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    args = parser.parse_args()

    asyncio.run(main(args.query))
