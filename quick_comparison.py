import argparse
import asyncio
import os
from dotenv import load_dotenv

from multiagents.llama_magentic_one import LlamaMagenticOne
from multiagents.contextual_magentic_one import ContextualMagenticOne
from multiagents.magentic_one import MagenticOne

from autogen_agentchat.ui import Console
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient, OpenAIChatCompletionClient

from azure.identity import DefaultAzureCredential, get_bearer_token_provider


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--method', type=str, default='contextual', help='Method to use')
    parser.add_argument('--scenario', type=str, default='code', help='Scenario to use')
    args = parser.parse_args()

    assert args.method in ['contextual', 'llama', 'magnetic']
    assert args.scenario in ['cua', 'code']

    cwd = os.getcwd()

    if args.scenario == 'cua':
        office_mode = True
        task = f"I'm writing a report, can you send a list of industries of companies in our portfolio to our external consultant?\
                Docs are at {cwd}/content/docs/docs3.md. Data is at {cwd}/content/acquisitions/. Consultant's email is kmorris@eldorado.com."
    elif args.scenario == 'code':
        office_mode = False
        task = f"Write a Python script to analyze data from {cwd}/content/file_surfer/magentic-one/gpt-4o/file1.txt and create a visualization"
    else:
        raise ValueError(f"Unknown scenario: {args.scenario}")

    # Load environment variables
    load_dotenv()
    
    # Create the OpenAI client
    if "OPENAI_API_KEY" in os.environ:
        client = OpenAIChatCompletionClient(
            api_key=os.environ["OPENAI_API_KEY"],
            model='gpt-4o'
        )

        orchestrator_client = OpenAIChatCompletionClient(
            api_key=os.environ["OPENAI_API_KEY"],
            model='o4-mini'
        )
    else:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )

        client = AzureOpenAIChatCompletionClient(
            model="gpt-4o",
            api_version="2024-10-21",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_ad_token_provider=token_provider,
        )

        orchestrator_client = AzureOpenAIChatCompletionClient(
            model="o4-mini",
            api_version="2024-12-01-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_ad_token_provider=token_provider,
        )

    # Initialize the ContextualMagenticOne with the client
    if args.method == 'contextual':
        contextual_team = ContextualMagenticOne(
            client=client,
            include_web_surfer=True,
            include_video_surfer=True,
            office_mode=office_mode,
            orchestrator_client=orchestrator_client,
        )
    elif args.method == 'llama':
        contextual_team = LlamaMagenticOne(
            client=client,
            include_web_surfer=True,
            include_video_surfer=True,
            office_mode=office_mode,
            orchestrator_client=orchestrator_client,
        )
    elif args.method == 'magnetic':
        contextual_team = MagenticOne(
            client=client,
            include_web_surfer=True,
            include_video_surfer=True,
            office_mode=office_mode,
            orchestrator_client=orchestrator_client,
        )
    else:
        raise ValueError(f"Unknown method: {args.method}")


    print(f"=== {args.method} Example ===")
    print(f"Task: {task}")
    print("\n" + "="*50 + "\n")
    
    await Console(contextual_team.run_stream(task=task))


if __name__ == "__main__":
    asyncio.run(main())
