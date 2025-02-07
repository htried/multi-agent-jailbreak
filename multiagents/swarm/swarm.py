from autogen_agentchat.teams import Swarm
from autogen_agentchat.conditions import TextMentionTermination
from autogen_core.models import ChatCompletionClient
from .swarm_file_surfer import SwarmFileSurfer
from .swarm_code_writer import SwarmCodeWriter
from .swarm_code_executor import SwarmCodeExecutor
import warnings
# from autogen_ext.agents.web_surfer import MultimodalWebSurfer
# from autogen_ext.agents.video_surfer import VideoSurfer
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_ext.models.openai._openai_client import BaseOpenAIChatCompletionClient

team_descriptions = {
    "FileSurfer": SwarmFileSurfer.DEFAULT_DESCRIPTION,
    "CodeWriter": SwarmCodeWriter.MAGENTIC_ONE_CODER_DESCRIPTION,
    "CodeExecutor": SwarmCodeExecutor.DEFAULT_DESCRIPTION,
}

def get_other_agents(name: str) -> dict[str, str]:
    return {n: d for n, d in team_descriptions.items() if n != name}

class SwarmTeam(Swarm):
    def __init__(
        self,
        client: ChatCompletionClient,
        max_turns: int | None = 20,
        # include_web_surfer: bool = True,
        # include_video_surfer: bool = True,
    ):
        self.client = client
        self._validate_client_capabilities(client)

        agents = []
        # if include_web_surfer:
        #     ws = MultimodalWebSurfer("WebSurfer", model_client=client, debug_dir="debug", to_save_screenshots=True, downloads_folder="downloads")
        #     agents.append(ws)
        
        name = "FileSurfer"
        other_agents = get_other_agents(name)
        handoffs = [name for name in other_agents]
        fs = SwarmFileSurfer(name, model_client=client, handoffs=handoffs, agent_descriptions=other_agents)
        agents.append(fs)

        # if include_video_surfer:
        #     vs = VideoSurfer("VideoSurfer", model_client=client)
        #     agents.append(vs)
        
        name = "CodeWriter"
        other_agents = get_other_agents(name)
        handoffs = [name for name in other_agents]
        coder = SwarmCodeWriter(name, model_client=client, handoffs=handoffs, agent_descriptions=other_agents)
        agents.append(coder)

        name = "CodeExecutor"
        other_agents = get_other_agents(name)
        handoffs = [name for name in other_agents]
        executor = SwarmCodeExecutor(name, code_executor=LocalCommandLineCodeExecutor(), model_client=client, handoffs=handoffs, agent_descriptions=other_agents)
        agents.append(executor)
        print(f"Agents: {[a.name for a in agents]}")

        termination = TextMentionTermination("TERMINATE")

        super().__init__(agents, termination_condition=termination, max_turns=max_turns)

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