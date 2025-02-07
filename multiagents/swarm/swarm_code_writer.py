# based on magentic one coder agent

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import Handoff as HandoffBase
from autogen_core.models import (
    ChatCompletionClient,
)
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class SwarmCodeWriter(AssistantAgent):

    MAGENTIC_ONE_CODER_DESCRIPTION = "A helpful and general-purpose AI assistant that has strong language skills, Python skills, and Linux command line skills."

    MAGENTIC_ONE_CODER_SYSTEM_MESSAGE = """You are a helpful AI assistant.
Solve tasks using your coding and language skills.
In the following cases, suggest python code (in a python coding block) or shell script (in a sh coding block) for the user to execute.
    1. When you need to collect info, use the code to output the info you need, for example, browse or search the web, download/read a file, print the content of a webpage or a file, get the current date/time, check the operating system. After sufficient info is printed and the task is ready to be solved based on your language skill, you can solve the task by yourself.
    2. When you need to perform some task with code, use the code to perform the task and output the result. Finish the task smartly.
Solve the task step by step if you need to. If a plan is not provided, explain your plan first. Be clear which step uses code, and which step uses your language skill.
When using code, you must indicate the script type in the code block. The user cannot provide any other feedback or perform any other action beyond executing the code you suggest. The user can't modify your code. So do not suggest incomplete code which requires users to modify. Don't use a code block if it's not intended to be executed by the user.
Don't include multiple code blocks in one response. Do not ask users to copy and paste the result. Instead, use the 'print' function for the output when relevant. Check the execution result returned by the user.
If the result indicates there is an error, fix the error and output the code again. Suggest the full code instead of partial code or code changes. If the error can't be fixed or if the task is not solved even after the code is executed successfully, analyze the problem, revisit your assumption, collect additional info you need, and think of a different approach to try.
When you find an answer, verify the answer carefully. Include verifiable evidence in your response if possible.

When you are done, either:
- call a handoff to the next relevant agent. (Only handoff to one agent at a time.)
- reply to the user directly, then write TERMINATE."""

    def __init__(
        self,
        name: str,
        model_client: ChatCompletionClient,
        handoffs: List[HandoffBase | str] | None = None,
        agent_descriptions: Dict[str, str] | None = None,
    ):
        system_message = self.MAGENTIC_ONE_CODER_SYSTEM_MESSAGE
        if agent_descriptions:
            system_message += "\n\n" + "\n".join([f"{name}: {description}" for name, description in agent_descriptions.items()])
        
        super().__init__(
            name,
            model_client,
            description=self.MAGENTIC_ONE_CODER_DESCRIPTION,
            system_message=system_message,
            handoffs=handoffs,
        )
