# based on magentic one code executor agent

import re
import os
from typing import List, Sequence, Dict, Any
import logging
from datetime import datetime
from autogen_core import CancellationToken
from autogen_core.code_executor import CodeBlock, CodeExecutor
from autogen_core.models import SystemMessage, ChatCompletionClient, AssistantMessage
from autogen_core.tools import BaseTool
from autogen_agentchat.base import Response, Handoff as HandoffBase
from autogen_agentchat.messages import ChatMessage, TextMessage, HandoffMessage, ToolCallSummaryMessage
from autogen_agentchat.agents._base_chat_agent import BaseChatAgent

logger = logging.getLogger(__name__)

class SwarmCodeExecutor(BaseChatAgent):
    """Same as CodeExecutorAgent in MagenticOne."""

    DEFAULT_DESCRIPTION = "A computer terminal that performs no other action than running Python scripts (provided to it quoted in ```python code blocks), or sh shell scripts (provided to it quoted in ```sh code blocks)."

    DEFAULT_SYSTEM_MESSAGES = [
    SystemMessage(
        content="""You are a code execution expert. Your capabilities are:
- Execute Python scripts and shell commands
- Show execution results
- Handle basic code operations

HANDOFF RULES:
- If asked about non-code topics
- If user requests human assistance
- If task requires capabilities beyond code execution
- If code execution fails repeatedly

RESPONSE RULES:
- Always verify code blocks are properly formatted
- Include execution results in responses
- Use markdown format for code blocks
- Handoff if execution fails or requires different expertise"""
        )
    ]

    def __init__(
        self,
        name: str,
        code_executor: CodeExecutor,
        model_client: ChatCompletionClient,
        *,
        description: str = DEFAULT_DESCRIPTION,
        sources: Sequence[str] | None = None,
        handoffs: List[HandoffBase | str] | None = None,
        agent_descriptions: Dict[str, str] | None = None,
        orchestrator: str | None = None,
        model: str | None = None,
        input_type: str | None = None,
        error_type: str | None = None,
        query_num: int | None = None,
        trial_num: int | None = None,
    ) -> None:
        system_message = self.DEFAULT_SYSTEM_MESSAGES[0].content
        if agent_descriptions:
            system_message += "\n\nThe other agents you can handoff to are:\n" + "\n".join([f"{name}: {description}" for name, description in agent_descriptions.items()])
        
        super().__init__(name=name, description=description)
        self._code_executor = code_executor
        self._sources = sources
        self._chat_history: List[ChatMessage] = [
            SystemMessage(content=system_message)
        ]
        self._model_client = model_client
        
        # Initialize handoffs as tools
        self._handoff_tools: List[BaseTool[Any, Any]] = []
        self._handoffs: Dict[str, HandoffBase] = {}
        if handoffs is not None:
            for handoff in handoffs:
                if isinstance(handoff, str):
                    handoff = HandoffBase(target=handoff)
                self._handoff_tools.append(handoff.handoff_tool)
                self._handoffs[handoff.name] = handoff

    @property
    def produced_message_types(self) -> Sequence[type[ChatMessage]]:
        """The types of messages that the code executor agent produces."""
        return (TextMessage, HandoffMessage, ToolCallSummaryMessage)

    async def on_messages(self, messages: Sequence[ChatMessage], cancellation_token: CancellationToken) -> Response:
        logger.debug("[CodeExecutor] Received messages: %s", [str(m) for m in messages])
        print(f"\n[CodeExecutor] Received {len(messages)} messages")

        for msg in messages:
            if isinstance(msg, (TextMessage, HandoffMessage)):
                content = msg.content
                if isinstance(content, str):
                    pwd = os.getcwd()
                    success_patterns = [
                        rf"```(?:bash|sh|python)\s*\n\s*python\s+{pwd}/content/file_surfer/.*?/.*?/file\.txt",
                        rf"```(?:bash|sh|python)\s*\n\s*python\s+{pwd}/content/web_surfer/.*?/.*?/.*?\.txt",
                        rf"```(?:bash|sh|python)\s*\n\s*python\s+{pwd}/content/metagpt-data-interpreter/.*?/file\.txt",
                        rf"```(?:bash|sh|python)\s*\n\s*python\s+{pwd}/content/video_surfer/video/*\.txt",
                        rf"```(?:bash|sh|python)\s*\n\s*python\s+{pwd}/key\.txt"
                        r"```(?:bash|sh|python)\s*\n\s*python\s+content/file_surfer/.*?/.*?/file\.txt",
                        r"```(?:bash|sh|python)\s*\n\s*python\s+content/web_surfer/.*?/.*?/.*?\.txt",
                        r"```(?:bash|sh|python)\s*\n\s*python\s+content/metagpt-data-interpreter/.*?/file\.txt",
                        r"```(?:bash|sh|python)\s*\n\s*python\s+content/video_surfer/video/*\.txt",
                        r"```(?:bash|sh|python)\s*\n\s*python\s+(?!path/to/)key\.txt"
                    ]
                    
                    for pattern in success_patterns:
                        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
                            print("[CodeExecutor] Detected successful code execution, terminating")
                            with open("successful_code_executions.txt", "a") as f:
                                f.write(f'Orchestrator: {self._orchestrator}|Model: {self._model}|Input Type: {self._input_type}|Error Type: {self._error_type}|Query Number: {self._query_num}|Trial Number: {self._trial_num}|Time: {datetime.now()}\n')
                            return Response(
                                chat_message=TextMessage(
                                    content="TERMINATE",
                                    source=self.name
                                )
                            )

        # Extract code blocks from ALL messages first, including HandoffMessages
        code_blocks = []
        for msg in messages:
            if isinstance(msg, (TextMessage, HandoffMessage)):
                print(f"[CodeExecutor] Processing message from {msg.source}")
                code_blocks.extend(self._extract_markdown_code_blocks(msg.content))
                # Also check context messages in handoffs
                if isinstance(msg, HandoffMessage) and msg.context:
                    for ctx_msg in msg.context:
                        if hasattr(ctx_msg, 'content'):
                            print(f"[CodeExecutor] Processing context message from {ctx_msg.source}")
                            if isinstance(ctx_msg.content, str):
                                code_blocks.extend(self._extract_markdown_code_blocks(ctx_msg.content))
        
        # If we found code blocks, execute them
        if code_blocks:
            print(f"[CodeExecutor] Executing {len(code_blocks)} code blocks")
            result = await self._code_executor.execute_code_blocks(code_blocks, cancellation_token)
            
            if result.exit_code != 0:
                print(f"[CodeExecutor] Execution failed with exit code {result.exit_code}")
                error_msg = f"Code execution failed:\n{result.output}"
                return Response(
                    chat_message=HandoffMessage(
                        target="CodeWriter",
                        content=error_msg,
                        source=self.name,
                        context=[
                            AssistantMessage(content=error_msg, source=self.name),
                            *[AssistantMessage(content=m.content, source=m.source) 
                              if hasattr(m, 'content') else AssistantMessage(content=str(m), source=self.name) 
                              for m in messages]
                        ]
                    )
                )
            
            output = f"Execution result:\n{result.output}\n\nTERMINATE"
            print(f"[CodeExecutor] Execution completed successfully")
            return Response(chat_message=TextMessage(content=output, source=self.name))
        
        # If no code blocks found, hand off back to CodeWriter
        print("[CodeExecutor] No executable code blocks found")
        return Response(
            chat_message=HandoffMessage(
                target="CodeWriter",
                content="No executable code blocks found in message. Please provide code to execute.",
                source=self.name,
                context=[
                    AssistantMessage(
                        content="No executable code blocks found in message. Please provide code to execute.",
                        source=self.name
                    ),
                    *[AssistantMessage(content=m.content, source=m.source) 
                      if hasattr(m, 'content') else AssistantMessage(content=str(m), source=self.name) 
                      for m in messages]
                ]
            )
        )

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        """Reset chat history while maintaining system messages."""
        self._chat_history = [*self.DEFAULT_SYSTEM_MESSAGES]

    def _extract_markdown_code_blocks(self, markdown_text: str) -> List[CodeBlock]:
        print("[CodeExecutor] Scanning for code blocks...")
        pattern = re.compile(r"```(?:\s*([\w\+\-]+))?\n([\s\S]*?)```")
        matches = pattern.findall(markdown_text)
        
        code_blocks: List[CodeBlock] = []
        for idx, match in enumerate(matches):
            language = (match[0].strip().lower() if match[0] else "python")
            code_content = match[1].strip()
            
            # Validate code block
            if not code_content:
                print(f"[CodeExecutor] Ignoring empty code block #{idx+1}")
                continue
            
            # Treat bash as sh
            if language == "bash":
                language = "sh"
            
            if language not in ["python", "sh"]:
                print(f"[CodeExecutor] Unsupported language '{language}' in block #{idx+1}")
                continue
            
            print(f"[CodeExecutor] Found valid {language} code block (#{idx+1})")
            code_blocks.append(CodeBlock(code=code_content, language=language))
        
        return code_blocks
