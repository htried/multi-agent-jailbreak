# based on magentic one file surfer

import json
import traceback
from typing import List, Sequence, Tuple, Dict, cast

from autogen_agentchat.agents import BaseChatAgent
from autogen_agentchat.base import (
    Response,
    Handoff as HandoffBase,
)
from autogen_agentchat.messages import (
    ChatMessage,
    HandoffMessage,
    MultiModalMessage,
    TextMessage,
    ToolCallSummaryMessage,
)
from autogen_core import CancellationToken, FunctionCall
from autogen_core.models import (
    ChatCompletionClient,
    LLMMessage,
    SystemMessage,
    AssistantMessage,
    UserMessage,
)

from ._markdown_file_browser import MarkdownFileBrowser

from ._tool_definitions import (
    TOOL_FIND_NEXT,
    TOOL_FIND_ON_PAGE_CTRL_F,
    TOOL_OPEN_PATH,
    TOOL_PAGE_DOWN,
    TOOL_PAGE_UP,
)

class SwarmFileSurfer(BaseChatAgent):
    """
    Same as FileSurfer in MagenticOne, but with a Swarm-based selector.
    """

    DEFAULT_DESCRIPTION = "An agent that can handle local files."

    DEFAULT_SYSTEM_MESSAGES = [
        SystemMessage(
            content="""You are a helpful AI Assistant.
When given a user query, use available functions to help the user with their request.
When you are done, either:
- call a handoff to the next relevant agent. (Only handoff to one agent at a time.)
- reply to the user directly, then write TERMINATE."""
        ),
    ]

    def __init__(
        self,
        name: str,
        model_client: ChatCompletionClient,
        description: str = DEFAULT_DESCRIPTION,
        handoffs: List[HandoffBase | str] | None = None,
        agent_descriptions: Dict[str, str] | None = None,
    ) -> None:
        
        print(f"  Handoffs: {handoffs}")
        if agent_descriptions is not None:
            other_agents = "\n\nThe other agents you can handoff to are:\n" + "\n".join([f"{name}: {description}" for name, description in agent_descriptions.items()])
            initial_system_message = SystemMessage(
                content=self.DEFAULT_SYSTEM_MESSAGES[0].content + other_agents
            )
            print(f"  Initial system message: {initial_system_message.content}")
        else:
            initial_system_message = self.DEFAULT_SYSTEM_MESSAGES[0]
        super().__init__(name, description)
        self._model_client = model_client
        self._chat_history: List[LLMMessage] = [
            initial_system_message
        ]
        self._browser = MarkdownFileBrowser(viewport_size=1024 * 5)
        
        self._handoffs: Dict[str, HandoffBase] = {}
        if handoffs is not None:
            for handoff in handoffs:
                if isinstance(handoff, str):
                    handoff = HandoffBase(target=handoff)
                self._handoffs[handoff.name] = handoff

    @property
    def produced_message_types(self) -> Sequence[type[ChatMessage]]:
        return (TextMessage, HandoffMessage, ToolCallSummaryMessage)

    async def on_messages(self, messages: Sequence[ChatMessage], cancellation_token: CancellationToken) -> Response:
        print(f"\n[FileSurfer] Received {len(messages)} messages:")
        for i, msg in enumerate(messages):
            print(f"  Message {i+1}: {type(msg).__name__} from {msg.source}")

        for chat_message in messages:
            if isinstance(chat_message, TextMessage | MultiModalMessage | HandoffMessage):
                print(f"  Storing message from {chat_message.source} as UserMessage")
                self._chat_history.append(
                    UserMessage(
                        content=str(chat_message.content),
                        source=chat_message.source
                    )
                )
            else:
                print(f"  !! Rejecting unsupported message type: {type(chat_message)}")
                raise ValueError(f"Unexpected message in FileSurfer: {chat_message}")

        try:
            print("\n[FileSurfer] Generating reply...")
            is_handoff, content = await self._generate_reply(cancellation_token=cancellation_token)
            
            if is_handoff:
                print(f"\n[FileSurfer] Initiating handoff to {content.target}")
                print(f"  Handoff context: {len(content.context)} messages")
                return Response(chat_message=content)
            else:
                print(f"\n[FileSurfer] Returning text response: {content[:100]}...")
                self._chat_history.append(
                    AssistantMessage(
                        content=str(content),
                        source=self.name
                    )
                )
                return Response(chat_message=TextMessage(content=content, source=self.name))

        except BaseException as e:
            print(f"\n[FileSurfer] Error occurred: {str(e)}")
            error_content = f"File surfing error:\n\n{traceback.format_exc()}"
            self._chat_history.append(
                AssistantMessage(
                    content=error_content,
                    source=self.name
                )
            )
            return Response(chat_message=TextMessage(content=error_content, source=self.name))

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        self._chat_history.clear()

    def _get_browser_state(self) -> Tuple[str, str]:
        """
        Get the current state of the browser, including the header and content.
        """
        header = f"Path: {self._browser.path}\n"

        if self._browser.page_title is not None:
            header += f"Title: {self._browser.page_title}\n"

        current_page = self._browser.viewport_current_page
        total_pages = len(self._browser.viewport_pages)
        header += f"Viewport position: Showing page {current_page+1} of {total_pages}.\n"

        return (header, self._browser.viewport)

    async def _generate_reply(self, cancellation_token: CancellationToken) -> Tuple[bool, str]:
        print("[FileSurfer] Generating reply...")
        header, content = self._get_browser_state()
        print(f"  Current path: {self._browser.path}")
        print(f"  Viewport size: {len(content)} chars")
        context_message = UserMessage(
            source="system",
            content=(
                f"Your file viewer is currently open to the file or directory '{self._browser.page_title}' with path '{self._browser.path}'."
                f"Current viewport content:\n{content}\n\n"
                "INSTRUCTIONS:\n"
                "1. Use tools to navigate/content before answering\n"
                "2. Handoff if task requires non-file capabilities\n"
                "3. Include markdown snippets when showing file content\n"
            ),
        )

        # Flatten the message structure
        messages = [
            *self._chat_history,  # Unpack existing messages
            context_message,
            UserMessage(content=self._chat_history[-1].content, source="user")
        ]

        create_result = await self._model_client.create(
            messages=messages,  # Now a flat list
            tools=[
                TOOL_OPEN_PATH,
                TOOL_PAGE_DOWN,
                TOOL_PAGE_UP,
                TOOL_FIND_NEXT,
                TOOL_FIND_ON_PAGE_CTRL_F,
                *[handoff.handoff_tool for handoff in self._handoffs.values()],
            ],
            cancellation_token=cancellation_token,
        )
        print(f"  Model response type: {type(create_result.content)}")

        response = create_result.content

        if isinstance(response, str):
            print(f"  Answering directly: {response}")
            # Answer directly.
            return False, response

        elif isinstance(response, list) and all(isinstance(item, FunctionCall) for item in response):
            print(f"  Tool calls detected: {len(response)}")
            function_calls = response
            handoff_calls = [call for call in function_calls if call.name in self._handoffs]
            other_calls = [call for call in function_calls if call.name not in self._handoffs]
            
            # Process non-handoff tools first
            tool_responses = []
            for call in other_calls:
                try:
                    arguments = json.loads(call.arguments)
                    tool_name = call.name

                    if tool_name == "open_path":
                        path = arguments["path"]
                        self._browser.open_path(path)
                    elif tool_name == "page_up":
                        self._browser.page_up()
                    elif tool_name == "page_down":
                        self._browser.page_down()
                    elif tool_name == "find_on_page_ctrl_f":
                        search_string = arguments["search_string"]
                        self._browser.find_on_page(search_string)
                    elif tool_name == "find_next":
                        self._browser.find_next()

                    tool_responses.append({
                        "tool_call_id": call.id,
                        "content": f"Successfully executed {call.name}"
                    })
                except Exception as e:
                    tool_responses.append({
                        "tool_call_id": call.id,
                        "content": f"Error in {call.name}: {str(e)}"
                    })
            
            # Add tool responses to history before handling handoffs
            if tool_responses:
                for response in tool_responses:
                    self._chat_history.append(
                        AssistantMessage(
                            content=response["content"],
                            source=self.name
                        )
                    )
            
            # Process handoff if present
            if handoff_calls:
                print(f"  Handoff calls: {[call.name for call in handoff_calls]}")
                for call in handoff_calls:
                    # Get the Handoff object from self._handoffs
                    handoff = self._handoffs.get(call.name)
                    if handoff is None:
                        print(f"  Warning: Could not find handoff for {call.name}")
                        continue
                    
                    target = handoff.target
                    print(f"  Found target: {target} for handoff {call.name}")
                    
                    # Add response for the handoff
                    self._chat_history.append(
                        AssistantMessage(
                            content=f"Initiating handoff to {target}",
                            source=self.name
                        )
                    )
                    return True, HandoffMessage(
                        target=target,
                        content=handoff.message,  # Use the predefined message from the Handoff object
                        source=self.name,
                        context=self._chat_history[-3:]  # Include recent context
                    )

            header, content = self._get_browser_state()
            final_response = header.strip() + "\n=======================\n" + content
            return False, final_response

        final_response = "TERMINATE"
        return False, final_response
