import warnings

# from autogen_agentchat.agents import CodeExecutorAgent
from multiagents.gemini.code_executor_agent import CodeExecutorAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_core.models import ChatCompletionClient
# from autogen_ext.agents.file_surfer import FileSurfer
from multiagents.gemini.file_surfer import FileSurfer
from autogen_ext.agents.magentic_one import MagenticOneCoderAgent
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.agents.video_surfer import VideoSurfer
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_ext.models.openai._openai_client import BaseOpenAIChatCompletionClient


class Selector(SelectorGroupChat):
    def __init__(
        self,
        client: ChatCompletionClient,
        max_turns: int | None = 20,
        include_web_surfer: bool = True,
        include_video_surfer: bool = True,
    ):
        self.client = client
        self._validate_client_capabilities(client)

        agents = []
        if include_web_surfer:
            ws = MultimodalWebSurfer("WebSurfer", model_client=client, debug_dir="debug", to_save_screenshots=True, downloads_folder="downloads")
            agents.append(ws)
        
        fs = FileSurfer("FileSurfer", model_client=client)
        agents.append(fs)

        if include_video_surfer:
            vs = VideoSurfer("VideoSurfer", model_client=client)
            agents.append(vs)
        
        coder = MagenticOneCoderAgent("Coder", model_client=client)
        agents.append(coder)

        executor = CodeExecutorAgent("Executor", code_executor=LocalCommandLineCodeExecutor())
        agents.append(executor)
        print(f"Agents: {[a.name for a in agents]}")

        termination = TextMentionTermination("TERMINATE")

        super().__init__(
            agents,
            model_client=client,
            max_turns=max_turns,
            termination_condition=termination,
        )

    def _validate_client_capabilities(self, client: ChatCompletionClient) -> None:
        capabilities = client.model_info
        required_capabilities = ["vision", "function_calling", "json_output"]

        if not all(capabilities.get(cap) for cap in required_capabilities):
            warnings.warn(
                "Client capabilities must include vision, " "function calling, and json output.",
                stacklevel=2,
            )

        if not isinstance(client, BaseOpenAIChatCompletionClient):
            warnings.warn(
                "Performs best with OpenAI GPT-4o model either " "through OpenAI or Azure OpenAI.",
                stacklevel=2,
            )