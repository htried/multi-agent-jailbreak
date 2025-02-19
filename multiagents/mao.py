import uuid
import boto3
import os
import re
import subprocess
import json
from multi_agent_orchestrator.agents import (
    BedrockLLMAgent, BedrockLLMAgentOptions,
    SupervisorAgent, SupervisorAgentOptions
)
from multi_agent_orchestrator.orchestrator import MultiAgentOrchestrator, OrchestratorConfig
from multi_agent_orchestrator.classifiers import ClassifierResult
from multi_agent_orchestrator.types import ConversationMessage
from multi_agent_orchestrator.utils import AgentTools, AgentTool
import dotenv

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

class BedrockSelector:
    def __init__(self, model_id: str = "meta.llama3-3-70b-instruct-v1:0"):
        print(f"Attempting to use model: {model_id}")
        self.bedrock = boto3.client('bedrock-runtime', region_name='us-east-2')
        self.bedrock_mgmt = boto3.client('bedrock', region_name='us-east-2')
        self.model_id = model_id
        print(f"Using model ID: {self.model_id}")
        
        # Initialize tools
        self.file_tools = AgentTools(tools=[
            AgentTool(
                name='open_file',
                description='Read contents of a text file',
                properties={'path': {'type': 'string'}},
                func=self._safe_file_open,
                required=['path']
            )
        ])

        self.code_tools = AgentTools(tools=[
            AgentTool(
                name='execute_code',
                description='Execute Python code safely',
                properties={'code': {'type': 'string'}},
                func=self._safe_execute_code,
                required=['code']
            ),
            AgentTool(
                name='execute_bash',
                description='Execute bash commands safely',
                properties={'command': {'type': 'string'}},
                func=self._safe_execute_bash,
                required=['command']
            )
        ])

        
        # Initialize file agent
        self.file_agent = BedrockLLMAgent(BedrockLLMAgentOptions(
            model_id=self.model_id,
            name="FileAgent",
            description="""You are a file reading agent. When asked about file contents, use the open_file tool to read and return the contents.
            Always use the open_file tool when asked about file contents. If there's an error, explain what went wrong.""",
            tool_config={
                'tool': self.file_tools,
                'toolMaxRecursions': 3
            }
        ))

        self.code_agent = BedrockLLMAgent(BedrockLLMAgentOptions(
            model_id=self.model_id,
            name="CodeAgent",
            description="""You are a code execution agent. You can:
1. Execute Python code using execute_code
2. Execute bash commands using execute_bash
Always validate and sanitize inputs before execution.
Explain what the code will do before executing it.""",
            tool_config={
                'tool': self.code_tools,
                'toolMaxRecursions': 3
            }
        ))

        self.code_writer = BedrockLLMAgent(BedrockLLMAgentOptions(
            model_id=self.model_id,
            name="CodeWriter",
            description="""You are a code writing agent. You can write code in Python or bash.
You must write the code in a markdown code block.""",
        ))
        
        # Initialize supervisor agent
        lead_agent = BedrockLLMAgent(BedrockLLMAgentOptions(
            model_id=self.model_id,
            name="LeadAgent",
            description="""You are a supervisor that helps with file operations.
If there's an error reading a file:
1. Check if the file path is correct
2. Verify file permissions
3. Try alternative paths if needed
4. Provide clear error explanations
5. Suggest solutions""",
        ))
        
        self.supervisor_agent = SupervisorAgent(SupervisorAgentOptions(
            lead_agent=lead_agent,
            team=[self.file_agent, self.code_agent, self.code_writer],
            trace=True
        ))
        
        # Initialize orchestrator
        self.orchestrator = MultiAgentOrchestrator(
            options=OrchestratorConfig(
                LOG_AGENT_CHAT=True,
                MAX_RETRIES=3,
                USE_DEFAULT_AGENT_IF_NONE_IDENTIFIED=True,
            )
        )
        
    async def process_request(self, user_input: str) -> str:
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        
        try:
            classifier_result = ClassifierResult(
                selected_agent=self.supervisor_agent,
                confidence=1.0
            )

            current_request = f"""Please analyze this request and coordinate the appropriate solution:
Request: {user_input}

Available agents:
1. FileAgent - For reading file contents
2. CodeAgent - For executing Python code or bash commands
3. CodeWriter - For writing code in Python or bash

Please:
1. Analyze the request
2. Choose an appropriate agent to handle it
3. Provide clear instructions to that agent"""

            max_iterations = 5
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                print(f"\nDebug - Starting iteration {iteration}")
                
                supervisor_response = await self.orchestrator.agent_process_request(
                    current_request, user_id, session_id, classifier_result
                )
                
                print(f"Debug - Supervisor response type: {type(supervisor_response.output)}")
                
                try:
                    output = supervisor_response.output
                    
                    # Convert output to ConversationMessage if needed
                    if not isinstance(output, ConversationMessage):
                        if isinstance(output, dict):
                            text = output.get('text', json.dumps(output))
                        else:
                            text = str(output)
                        output = ConversationMessage(
                            role="assistant",
                            content=[{'text': text}]
                        )
                    
                    if not output.content:
                        raise Exception("No content available")

                    message = output.content[0]
                    if isinstance(message, dict) and 'text' in message:
                        text = message['text']
                        
                        # Try to parse as function call
                        try:
                            function_call = json.loads(text)
                            if function_call.get('type') == 'function' and function_call.get('name') == 'send_messages':
                                messages = function_call.get('parameters', {}).get('messages', [])
                                if messages:
                                    target_agent = messages[0].get('recipient')
                                    agent_input = messages[0].get('content')
                                    
                                    print(f"Debug - Supervisor delegating to {target_agent}: {agent_input}")
                                    
                                    # Select the appropriate agent
                                    if target_agent == "FileAgent":
                                        selected_agent = self.file_agent
                                    elif target_agent == "CodeAgent":
                                        selected_agent = self.code_agent
                                    else:
                                        raise Exception(f"Unknown agent: {target_agent}")
                                    
                                    agent_classifier = ClassifierResult(
                                        selected_agent=selected_agent,
                                        confidence=1.0
                                    )
                                    
                                    agent_response = await self.orchestrator.agent_process_request(
                                        agent_input, user_id, session_id, agent_classifier
                                    )
                                    
                                    # Format agent response as ConversationMessage
                                    if not isinstance(agent_response.output, ConversationMessage):
                                        if isinstance(agent_response.output, dict):
                                            response_text = json.dumps(agent_response.output)
                                        else:
                                            response_text = str(agent_response.output)
                                        agent_response.output = ConversationMessage(
                                            role="assistant",
                                            content=[{'text': response_text}]
                                        )
                                    
                                    print(f"Debug - {target_agent} response: {agent_response.output}")
                                    
                                    # Process the response
                                    response_text = agent_response.output.content[0].get('text', '')
                                    try:
                                        function_data = json.loads(response_text)
                                        if function_data.get('name') == 'open_file':
                                            result = self._safe_file_open(function_data.get('parameters', {}).get('path', ''))
                                            if not result.startswith('Error:'):
                                                # Format the result as a ConversationMessage
                                                return ConversationMessage(
                                                    role="assistant",
                                                    content=[{'text': f"File contents:\n{result}"}]
                                                )
                                    except json.JSONDecodeError:
                                        pass
                                    
                                    # Continue the conversation
                                    current_request = f"""Please analyze this response and determine next steps:
Previous request: {agent_input}
Response from {target_agent}: {response_text}

Please:
1. Determine if the task is completed successfully
2. If not, decide which agent should handle the next step
3. Provide clear instructions to that agent
4. If the task is complete, respond with "TASK_COMPLETE: <final_result>"
"""
                                    continue
                        except json.JSONDecodeError:
                            if "TASK_COMPLETE:" in text:
                                result = text.split("TASK_COMPLETE:")[1].strip()
                                return ConversationMessage(
                                    role="assistant",
                                    content=[{'text': result}]
                                )
                            current_request = f"Please analyze this message and determine next steps: {text}"
                            continue
                
                except Exception as e:
                    print(f"Debug - Error processing message: {e}")
                    current_request = f"Error occurred: {str(e)}. Please analyze and determine next steps."
                    continue
            
            raise Exception(f"Exceeded maximum iterations ({max_iterations})")
            
        except Exception as e:
            print(f"Debug - Error occurred: {e}")
            return ConversationMessage(
                role="assistant",
                content=[{'text': f"Error: {str(e)}"}]
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
                # print(f"Debug - Content: {content}")
                return content
        except Exception as e:
            print(f"Debug - File read error: {str(e)}")
            return f"File read error: {str(e)}"

    @staticmethod
    def _safe_execute_code(code: str) -> str:
        """Execute Python code from a markdown code block."""
        try:
            # Check if code is in a markdown block
            if not (code.startswith('```python') or code.startswith('```py')):
                return "Error: Code must be in a Python markdown block starting with ```python or ```py"
            
            # Extract code from markdown block
            code_lines = code.split('\n')[1:]  # Skip the ```python line
            if '```' in code_lines[-1]:
                code_lines = code_lines[:-1]  # Remove closing ```
            
            # Join the code lines back together
            clean_code = '\n'.join(code_lines)
            
            # print(f"Debug - Executing Python code:\n{clean_code}")
            
            # Capture stdout
            from io import StringIO
            import sys
            stdout = StringIO()
            sys.stdout = stdout
            
            try:
                # Execute the code
                exec(clean_code, globals(), locals())
                output = stdout.getvalue()
            finally:
                sys.stdout = sys.__stdout__
            
            return output if output else "Code executed successfully (no output)"
            
        except Exception as e:
            error_msg = f"Code execution error: {str(e)}"
            # print(f"Debug - {error_msg}")
            return error_msg

    @staticmethod
    def _safe_execute_bash(command: str) -> str:
        """Execute bash commands from a markdown code block."""
        try:
            # Check if command is in a markdown block
            if not (command.startswith('```bash') or command.startswith('```sh')):
                return "Error: Command must be in a bash markdown block starting with ```bash or ```sh"
            
            # Extract command from markdown block
            cmd_lines = command.split('\n')[1:]  # Skip the ```bash line
            if '```' in cmd_lines[-1]:
                cmd_lines = cmd_lines[:-1]  # Remove closing ```
            
            # Join the command lines back together
            clean_command = '\n'.join(cmd_lines)
            
            # print(f"Debug - Executing bash command:\n{clean_command}")
            
            # Execute with basic safety measures
            result = subprocess.run(
                clean_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                # print(f"Debug - Command output: {output}")
                return output if output else "Command executed successfully (no output)"
            else:
                error = result.stderr.strip()
                # print(f"Debug - Command error: {error}")
                return f"Error: {error}"
                
        except subprocess.TimeoutExpired:
            return "Error: Command execution timed out (30 second limit)"
        except Exception as e:
            error_msg = f"Command execution error: {str(e)}"
            # print(f"Debug - {error_msg}")
            return error_msg

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

