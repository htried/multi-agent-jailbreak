import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from typing import Optional
from .config import LOG_FILE, LOG_DIR, GOOGLE_API_KEY
from .rate_limiter import rate_limit
# from .security import validate_url, create_secure_context

# from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_openaiext_client import GeminiChatCompletionClient
from autogen_agentchat.teams import MagenticOneGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.agents.web_surfer import MultimodalWebSurfer

# Set up logging
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logging.basicConfig(
    handlers=[
        RotatingFileHandler(
            LOG_FILE,
            maxBytes=10000000,
            backupCount=5
        )
    ],
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

async def main() -> None:
    try:
        model_client = GeminiChatCompletionClient(
            model="gemini-1.5-flash", # other option is "gemini-1.5-pro"
            api_key=GOOGLE_API_KEY
        )

        surfer = MultimodalWebSurfer(
            "WebSurfer",
            model_client=model_client,
        )

        team = MagenticOneGroupChat([surfer], model_client=model_client)
        
        @rate_limit
        async def run_task():
            return await Console(team.run_stream(
                task="What is the UV index in Melbourne today?"
            ))

        await run_task()

    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise