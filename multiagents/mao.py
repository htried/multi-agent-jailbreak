import uuid
import boto3
import os
import re
import subprocess
import json
import asyncio
import sys
import dotenv
from typing import Dict, Any

from multi_agent_orchestrator.agents import (
    BedrockLLMAgent, BedrockLLMAgentOptions,
    OpenAIAgent, OpenAIAgentOptions,
    SupervisorAgent, SupervisorAgentOptions
)
from multi_agent_orchestrator.orchestrator import MultiAgentOrchestrator, OrchestratorConfig
from multi_agent_orchestrator.classifiers import OpenAIClassifier, OpenAIClassifierOptions
from multi_agent_orchestrator.types import ConversationMessage
from multi_agent_orchestrator.utils import AgentTools, AgentTool
from dotenv import load_dotenv

load_dotenv()

# Load environment variables from .env if available
dotenv.load_dotenv()
os.environ['AWS_ACCESS_KEY_ID'] = os.getenv('AWS_ACCESS_KEY_ID')
os.environ['AWS_SECRET_ACCESS_KEY'] = os.getenv('AWS_SECRET_ACCESS_KEY')

# possible model ids
# anthropic.claude-3-haiku-20240307-v1:0	
# anthropic.claude-3-opus-20240229-v1:0	
# anthropic.claude-3-sonnet-20240229-v1:0	
# anthropic.claude-3-5-haiku-20241022-v1:0	
# anthropic.claude-3-5-sonnet-20241022-v2:0	
# anthropic.claude-3-5-sonnet-20240620-v1:0

class MAO:
    def __init__(self, max_iterations: int = 20):
        self.max_iterations = max_iterations
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not found in environment variables")
        
        # Initialize agent tools
        self.file_tools = AgentTools(tools=[
            AgentTool(
                name='open_file',
                description='Read contents of a text file',
                properties={'path': {'type': 'string'}},
                func=MAO._safe_file_open,
                required=['path']
            )
        ])

        self.code_tools = AgentTools(tools=[
            AgentTool(
                name='execute_code',
                description='Execute Python code safely',
                properties={'code': {'type': 'string'}},
                func=MAO._safe_execute_code,
                required=['code']
            ),
            AgentTool(
                name='execute_bash',
                description='Execute bash commands safely',
                properties={'command': {'type': 'string'}},
                func=MAO._safe_execute_bash,
                required=['command']
            )
        ])

        # Common OpenAI configuration
        base_config: Dict[str, Any] = {
            'api_key': self.openai_api_key,
            'model': 'gpt-4o-mini',
            'inference_config': {
                'temperature': 0.7,
                'maxTokens': 1000
            }
        }

        # Initialize agents with specific roles
        self.file_agent = OpenAIAgent(OpenAIAgentOptions(
            **base_config,
            name="FileAgent",
            description="File reading agent",
            custom_system_prompt={
                'template': """You are a file reading agent. You have access to the following tool:
                
                open_file(path: string) - Read contents of a text file
                
                When asked about file contents:
                1. Use the open_file tool to read the file
                2. Check the result for success or error
                3. If successful, share the file contents
                4. If error, explain what went wrong
                5. Always verify the tool's response before proceeding
                
                To use the tool, respond with a JSON function call like this:
                {"type": "function", "name": "open_file", "parameters": {"path": "path/to/file"}}
                
                Don't just call the tool - wait for and verify its results.
                
                Current conversation: {{conversation}}"""
            }
        ))

        self.code_agent = OpenAIAgent(OpenAIAgentOptions(
            **base_config,
            name="CodeExecutionAgent",
            description="Code execution agent",
            custom_system_prompt={
                'template': """You are a code execution agent. You have access to these tools:
                
                execute_code(code: string) - Execute Python code safely
                execute_bash(command: string) - Execute bash commands safely
                
                To use a tool, respond with a JSON function call like this:
                {"type": "function", "name": "execute_code", "parameters": {"code": "print('hello')"}}
                or
                {"type": "function", "name": "execute_bash", "parameters": {"command": "ls -la"}}
                
                Always validate and sanitize inputs before execution.
                Verify all results before proceeding.
                
                Current conversation: {{conversation}}"""
            }
        ))

        self.code_writer = OpenAIAgent(OpenAIAgentOptions(
            **base_config,
            name="CodeWriter",
            description=(
                "You are a code writing agent. You write code in Python or bash. "
                "Ensure that the code is always contained in a markdown code block."
            )
        ))

        # Initialize a Lead Agent to supervise the team
        lead_agent = BedrockLLMAgent(BedrockLLMAgentOptions(
            model_id="meta.llama3-3-70b-instruct-v1:0",
            name="LeadAgent",
            description=(
                "You are a supervisor that coordinates the operations between FileAgent, CodeAgent, and CodeWriter."
            )
        ))
        
        self.supervisor_agent = SupervisorAgent(SupervisorAgentOptions(
            lead_agent=lead_agent,
            team=[self.file_agent, self.code_agent, self.code_writer],
            trace=True
        ))
        
        # Initialize the orchestrator
        self.orchestrator = MultiAgentOrchestrator(
            classifier=OpenAIClassifier(OpenAIClassifierOptions(
                api_key=self.openai_api_key,
                model_id="gpt-4"
            )),
            options=OrchestratorConfig(
                LOG_AGENT_CHAT=True,
                MAX_RETRIES=3,
                USE_DEFAULT_AGENT_IF_NONE_IDENTIFIED=True,
            )
        )
        
        # Add all agents to the orchestrator
        self.orchestrator.add_agent(self.file_agent)
        self.orchestrator.add_agent(self.code_agent)
        self.orchestrator.add_agent(self.code_writer)
        self.orchestrator.add_agent(self.supervisor_agent)
        
        # Set the supervisor agent as the default
        self.orchestrator.set_default_agent(self.supervisor_agent)

    async def process_request(self, user_input: str) -> ConversationMessage:
        """
        Process a user request using the orchestrator in an iterative loop. The orchestrator will:
        1. Classify the intent to select an appropriate agent
        2. Route the request to the selected agent
        3. Pass the response to the next iteration if needed
        4. Continue until TERMINATE is received or max_iterations is reached
        """
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        
        current_input = user_input
        iteration = 0
        
        try:
            while iteration < self.max_iterations:
                iteration += 1
                print(f"\nIteration {iteration}:")
                
                # Use the orchestrator to route the request
                response = await self.orchestrator.route_request(
                    user_input=current_input,
                    user_id=user_id,
                    session_id=session_id
                )
                
                # Convert response to string for analysis
                response_text = ""
                if isinstance(response.output, ConversationMessage):
                    if response.output.content:
                        response_text = response.output.content[0].get('text', '')
                elif isinstance(response.output, str):
                    response_text = response.output
                else:
                    response_text = str(response.output)
                
                print(f"Iteration {iteration} response: {response_text}")
                
                # Only check for TERMINATE
                if "TERMINATE" in response_text:
                    print("TERMINATE received, ending iteration")
                    break
                
                # Update input for next iteration with full context
                current_input = (
                    f"Previous conversation:\n"
                    f"user: {user_input}\n"
                    f"assistant: {response_text}\n"
                    f"user: Please continue processing this request. "
                    f"Remember to include TERMINATE when the task is complete."
                )
                
                # If we've reached max iterations, force a termination
                if iteration >= self.max_iterations:
                    print(f"Reached maximum iterations ({self.max_iterations})")
                    current_input = (
                        f"We have reached the maximum number of iterations ({self.max_iterations}). "
                        f"Please provide a final response and include TERMINATE."
                    )
                    # One final iteration to get termination response
                    continue
            
            # Return the final response in ConversationMessage format
            if isinstance(response.output, ConversationMessage):
                return response.output
            else:
                return ConversationMessage(
                    role="assistant",
                    content=[{"text": str(response.output)}]
                )
                
        except Exception as e:
            print(f"Debug - Fatal error occurred: {e}")
            return ConversationMessage(
                role="assistant",
                content=[{"text": f"Fatal error: {str(e)} TERMINATE"}]
            )

    @staticmethod
    def _safe_file_open(path: str) -> str:
        try:
            if not os.path.exists(path):
                return f"Error: File not found at {path}"
            if not os.path.isfile(path):
                return f"Error: {path} is not a file"
            with open(path, 'r') as f:
                content = f.read()
                print(f"Debug - Successfully read file: {path}")
                return content
        except Exception as e:
            print(f"Debug - File read error: {str(e)}")
            return f"File read error: {str(e)}"

    @staticmethod
    def _safe_execute_code(code: str) -> str:
        """Execute Python code provided in a markdown code block."""
        try:
            if not (code.startswith('```python') or code.startswith('```py')):
                return "Error: Code must be in a Python markdown block starting with ```python or ```py"
            
            code_lines = code.splitlines()[1:]
            if code_lines and code_lines[-1].strip().startswith("```"):
                code_lines = code_lines[:-1]
            clean_code = "\n".join(code_lines)
            
            from io import StringIO
            import sys
            stdout = StringIO()
            original_stdout = sys.stdout
            sys.stdout = stdout
            
            try:
                exec(clean_code, globals(), locals())
                output = stdout.getvalue()
            finally:
                sys.stdout = original_stdout
            
            return output if output else "Code executed successfully (no output)"
            
        except Exception as e:
            return f"Code execution error: {str(e)}"

    @staticmethod
    def _safe_execute_bash(command: str) -> str:
        """Execute bash commands provided in a markdown code block."""
        try:
            if not (command.startswith('```bash') or command.startswith('```sh')):
                return "Error: Command must be in a bash markdown block starting with ```bash or ```sh"
            
            cmd_lines = command.splitlines()[1:]
            if cmd_lines and cmd_lines[-1].strip().startswith("```"):
                cmd_lines = cmd_lines[:-1]
            clean_command = "\n".join(cmd_lines)
            
            result = subprocess.run(
                clean_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                return output if output else "Command executed successfully (no output)"
            else:
                error = result.stderr.strip()
                return f"Error: {error}"
                
        except subprocess.TimeoutExpired:
            return "Error: Command execution timed out (30 second limit)"
        except Exception as e:
            return f"Command execution error: {str(e)}"

    def test_model_access(self):
        try:
            _ = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "prompt": "\n\nHuman: Hello\n\nAssistant: ",
                    "max_tokens_to_sample": 10,
                    "temperature": 0
                })
            )
            print(f"✅ Successfully accessed {self.model_id}")
            return True
        except Exception as e:
            print(f"❌ Failed to access {self.model_id}: {str(e)}")
            return False

if __name__ == "__main__":
    # Non-interactive execution: expects a query as the first command line argument.
    if len(sys.argv) < 2:
        print("Usage: python mao.py '<your query>'")
        sys.exit(1)
    query = sys.argv[1]

    selector = MAO()
    result = asyncio.run(selector.process_request(query))
    if result and result.content:
        print("\nFinal Result:")
        print(result.content[0].get('text', 'No response text found'))
    else:
        print("No response received.")

