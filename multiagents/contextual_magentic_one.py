import warnings
from typing import Awaitable, Callable, List, Optional, Union

from autogen_agentchat.agents import UserProxyAgent
# from autogen_agentchat.agents import CodeExecutorAgent
from multiagents.gemini.code_executor_agent import CodeExecutorAgent
from autogen_agentchat.base import ChatAgent
from autogen_agentchat.teams import MagenticOneGroupChat
from autogen_core import CancellationToken
from autogen_agentchat.conditions import TextMentionTermination
from autogen_core.models import ChatCompletionClient

# from autogen_ext.agents.file_surfer import FileSurfer
from multiagents.gemini.file_surfer import FileSurfer
from autogen_ext.agents.magentic_one import MagenticOneCoderAgent
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.agents.video_surfer import VideoSurfer
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_ext.models.openai._openai_client import BaseOpenAIChatCompletionClient
from multiagents.constrained_utils.ContextualMAOrchestrator import ContextualMAOrchestrator
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, MessageFactory
from autogen_agentchat.teams._group_chat._events import GroupChatTermination
from autogen_agentchat.teams._group_chat._base_group_chat import BaseGroupChat
from autogen_agentchat.base import TerminationCondition
import asyncio
from autogen_agentchat.teams._group_chat._magentic_one._prompts import ORCHESTRATOR_FINAL_ANSWER_PROMPT


SyncInputFunc = Callable[[str], str]
AsyncInputFunc = Callable[[str, Optional[CancellationToken]], Awaitable[str]]
InputFuncType = Union[SyncInputFunc, AsyncInputFunc]


class ContextualMagenticOne(MagenticOneGroupChat):
    """
    ContextualMagenticOne is a specialized group chat class that extends MagenticOne with
    capability-based guardrails and contextual CFG generation for enhanced safety.
    
    This system:
    1. Automatically extracts capabilities from agent descriptions
    2. Generates contextual CFGs with usage conditions based on the task
    3. Validates guardrails before allowing agent execution
    4. Provides detailed explanations when guardrails fail
    
    The orchestrator maintains flexibility while ensuring safety through:
    - Capability-based analysis of each agent
    - Context-aware CFG generation with safety conditions
    - Real-time guardrail validation with evidence checking
    - Intelligent fallback strategies when guardrails fail

    Args:
        client (ChatCompletionClient): The client used for model interactions.
        hil_mode (bool): Optional; If set to True, adds the UserProxyAgent to the list of agents.
        input_func (InputFuncType | None): Optional input function for human-in-the-loop mode.
        include_web_surfer (bool): Whether to include the web surfing agent.
        include_video_surfer (bool): Whether to include the video processing agent.
        input_type (str | None): Type of input for specialized configurations.
        error_type (str | None): Type of error handling for specialized configurations.
        query_num (int | None): Query number for tracking.
        trial_num (int | None): Trial number for tracking.

    .. warning::
        ContextualMagenticOne includes enhanced safety measures, but users should still:

        1. **Use Containers**: Run all tasks in docker containers to isolate the agents.
        2. **Monitor Logs**: Closely monitor logs during and after execution.
        3. **Human Oversight**: Run with human supervision for sensitive tasks.
        4. **Limit Access**: Restrict agents' access to sensitive resources.
        5. **Review Guardrails**: Understand the generated guardrails for your specific tasks.

        The system will provide detailed explanations when guardrails prevent actions,
        helping you understand the safety decisions being made.
    """

    def __init__(
        self,
        client: ChatCompletionClient,
        hil_mode: bool = False,
        input_func: InputFuncType | None = None,
        include_web_surfer: bool = False,
        include_video_surfer: bool = False,
        input_type: str | None = None,
        error_type: str | None = None,
        query_num: int | None = None,
        trial_num: int | None = None,
    ):
        self.client = client
        self._validate_client_capabilities(client)

        fs = FileSurfer("FileSurfer", model_client=client)
        ws = MultimodalWebSurfer("WebSurfer", model_client=client)
        vs = VideoSurfer("VideoSurfer", model_client=client)
        coder = MagenticOneCoderAgent("Coder", model_client=client)
        executor = CodeExecutorAgent(
            "Executor", 
            code_executor=LocalCommandLineCodeExecutor(),
            orchestrator="contextual-magentic-one",
            model=client.model_info["family"],
            input_type=input_type,
            error_type=error_type,
            query_num=query_num,
            trial_num=trial_num,
        )
        
        agents: List[ChatAgent] = [fs, coder, executor]
        if include_web_surfer:
            agents.append(ws)
        if include_video_surfer:
            agents.append(vs)

        print(f"Agents: {[a.name for a in agents]}")
        if hil_mode:
            user_proxy = UserProxyAgent("User", input_func=input_func)
            agents.append(user_proxy)

        termination = TextMentionTermination("TERMINATE")

        BaseGroupChat.__init__(
            self,
            participants=agents,
            group_chat_manager_name="ContextualMAOrchestrator",
            group_chat_manager_class=ContextualMAOrchestrator,
            termination_condition=termination,
            max_turns=20,
            runtime=None,
            custom_message_types=None,
            emit_team_events=False,
        )
        self._model_client = client
        self._max_stalls = 3
        self._final_answer_prompt = ORCHESTRATOR_FINAL_ANSWER_PROMPT

    def _validate_client_capabilities(self, client: ChatCompletionClient) -> None:
        capabilities = client.model_info
        required_capabilities = ["vision", "function_calling", "json_output"]

        if not all(capabilities.get(cap) for cap in required_capabilities):
            warnings.warn(
                "Client capabilities for ContextualMagenticOne must include vision, " 
                "function calling, and json output for optimal guardrail functionality.",
                stacklevel=2,
            )

        if not isinstance(client, BaseOpenAIChatCompletionClient):
            warnings.warn(
                "ContextualMagenticOne performs best with OpenAI GPT-4o model either " 
                "through OpenAI or Azure OpenAI for reliable guardrail validation.",
                stacklevel=2,
            )
    
    def _create_group_chat_manager_factory(
        self,
        name: str,
        group_topic_type: str,
        output_topic_type: str,
        participant_topic_types: List[str],
        participant_names: List[str],
        participant_descriptions: List[str],
        output_message_queue: asyncio.Queue[BaseAgentEvent | BaseChatMessage | GroupChatTermination],
        termination_condition: TerminationCondition | None,
        max_turns: int | None,
        message_factory: MessageFactory,
    ) -> Callable[[], ContextualMAOrchestrator]:
        return lambda: ContextualMAOrchestrator(
            name,
            group_topic_type,
            output_topic_type,
            participant_topic_types,
            participant_names,
            participant_descriptions,
            max_turns,
            message_factory,
            self._model_client,
            self._max_stalls,
            self._final_answer_prompt,
            output_message_queue,
            termination_condition,
            self._emit_team_events,
        )