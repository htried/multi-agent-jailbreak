# new class that inherits from ConstrainedMAOrchestrator
# but, adds capability-based guardrails and contextual CFG generation

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Mapping, Sequence

from autogen_core import AgentId, CancellationToken, DefaultTopicId, rpc, MessageContext
from autogen_core.models import (
    AssistantMessage, 
    ChatCompletionClient, 
    LLMMessage,
    UserMessage, 
)
from autogen_core.utils import extract_json_from_str

from autogen_agentchat.base import Response, TerminationCondition
from autogen_agentchat.messages import (
    BaseAgentEvent,
    BaseChatMessage,
    MessageFactory,
    SelectSpeakerEvent,
    TextMessage,
    StopMessage,
)
from autogen_agentchat.state import MagenticOneOrchestratorState
from autogen_agentchat.teams._group_chat._events import (
    GroupChatAgentResponse,
    GroupChatMessage,
    GroupChatRequestPublish,
    GroupChatReset,
    GroupChatStart,
    GroupChatTermination,
    SerializableException,
)
from autogen_agentchat.teams._group_chat._magentic_one._magentic_one_orchestrator import MagenticOneOrchestrator
from autogen_agentchat.teams._group_chat._base_group_chat_manager import BaseGroupChatManager
from autogen_agentchat.teams._group_chat._magentic_one._prompts import LedgerEntry

from lark import Lark
from lark.exceptions import UnexpectedEOF, UnexpectedToken
from typing import Set

from multiagents.constrained_utils.prompts import (
    ORCHESTRATOR_PROGRESS_LEDGER_PROMPT, 
    ORCHESTRATOR_CAPABILITIES_PROMPT,
    ORCHESTRATOR_NATURAL_LANGUAGE_RULES_PROMPT,
    ORCHESTRATOR_CONTEXTUAL_CFG_PROMPT,
    ORCHESTRATOR_GUARDRAIL_VALIDATION_PROMPT
)


class ContextualMAOrchestrator(MagenticOneOrchestrator):
    """The ContextualMAOrchestrator manages a group chat with capability-based guardrails and contextual CFG constraints."""

    def __init__(
        self,
        name: str,
        group_topic_type: str,
        output_topic_type: str,
        participant_topic_types: List[str],
        participant_names: List[str],
        participant_descriptions: List[str],
        max_turns: int | None,
        message_factory: MessageFactory,
        model_client: ChatCompletionClient,
        max_stalls: int,
        final_answer_prompt: str,
        output_message_queue: asyncio.Queue[BaseAgentEvent | BaseChatMessage | GroupChatTermination],
        termination_condition: TerminationCondition | None,
        emit_team_events: bool,
    ):
        super().__init__(
            name=name,
            group_topic_type=group_topic_type,
            output_topic_type=output_topic_type,
            participant_topic_types=participant_topic_types,
            participant_names=participant_names,
            participant_descriptions=participant_descriptions,
            max_turns=max_turns,
            message_factory=message_factory,
            model_client=model_client,
            max_stalls=max_stalls,
            final_answer_prompt=final_answer_prompt,
            output_message_queue=output_message_queue,
            termination_condition=termination_condition,
            emit_team_events=emit_team_events,
        )
        self._current_speaker_sequence = []  # Track the current speaker sequence
        self._agent_capabilities = {}  # Store extracted capabilities
        self._natural_language_rules = {}  # Store natural language rules per agent
        self._agent_conditions = {}  # Store usage conditions per agent
        self._cfg = ""  # Store the grammar string
        self._parser = None  # Store the Lark parser
        self._guardrail_retry_count = {}  # Track retry attempts per agent
    
    def _clean_json_response(self, response_content: str) -> str:
        """Clean JSON response by removing backticks and 'json' labels."""
        # Remove markdown code block formatting
        cleaned = re.sub(r'^```json\s*', '', response_content.strip())
        cleaned = re.sub(r'^```\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        # Remove any remaining backticks
        cleaned = re.sub(r'`+', '', cleaned)
        return cleaned.strip()

    def _get_capabilities_prompt(self, task: str, plan: str, agent_descriptions: str) -> str:
        return ORCHESTRATOR_CAPABILITIES_PROMPT.format(task=task, plan=plan, agent_descriptions=agent_descriptions)

    def _get_natural_language_rules_prompt(self, task: str, plan: str, capabilities: str) -> str:
        return ORCHESTRATOR_NATURAL_LANGUAGE_RULES_PROMPT.format(task=task, plan=plan, capabilities=capabilities)

    def _get_contextual_cfg_prompt(self, task: str, plan: str, capabilities: str, rules: str) -> str:
        return ORCHESTRATOR_CONTEXTUAL_CFG_PROMPT.format(task=task, plan=plan, capabilities=capabilities, rules=rules)

    def _get_guardrail_validation_prompt(self, agent_name: str, task: str, rules: str, conditions: str, evidence: str, instruction: str) -> str:
        return ORCHESTRATOR_GUARDRAIL_VALIDATION_PROMPT.format(
            agent_name=agent_name, 
            task=task,
            rules=rules,
            conditions=conditions, 
            evidence=evidence, 
            instruction=instruction
        )

    def _get_progress_ledger_prompt(self, task: str, team: str, names: List[str]) -> str:
        return ORCHESTRATOR_PROGRESS_LEDGER_PROMPT.format(task=task, team=team, names=", ".join(names))

    def _get_conversation_string(self) -> str:
        return " ".join(self._current_speaker_sequence)

    def _get_parser(self, grammar_str: str) -> Lark:
        try:
            return Lark(grammar_str, parser='lalr')
        except Exception as e:
            raise ValueError(f"Error parsing grammar: {e}.")

    def _validate_speaker_sequence(self, next_speaker: str) -> bool:
        """Validate if the next speaker follows the CFG constraints."""
        try:
            self._parser.parse(f"{self._get_conversation_string()} {next_speaker}")
            return True
        except UnexpectedEOF:
            return True
        except UnexpectedToken as e:
            # Only treat end-of-input as a valid partial parse
            if e.token.type == '$END':
                return True
            else:
                return False
        except Exception as e:
            return False

    def _get_allowed_speakers(self) -> List[str]:
        """Get the list of speakers allowed to speak next based on CFG constraints."""
        allowed_speakers = []
        for speaker in self._participant_names:
            if self._validate_speaker_sequence(speaker):
                allowed_speakers.append(speaker)
        
        return allowed_speakers

    def _can_complete_conversation(self) -> bool:
        """Check if the current conversation can form a complete parse."""
        try:
            self._parser.parse(self._get_conversation_string())
            return True
        except:
            return False
    
    def _update_team_description(self, allowed_speakers: List[str]) -> None:
        filtered_team_description = ""
        allowed_descriptions = [self._participant_descriptions[self._participant_names.index(speaker)] for speaker in allowed_speakers]
        for topic_type, description in zip(allowed_speakers, allowed_descriptions, strict=True):
            filtered_team_description += re.sub(r"\s+", " ", f"{topic_type}: {description}").strip() + "\n"
        self._team_description = filtered_team_description.strip()

    async def _extract_agent_capabilities(self, cancellation_token: CancellationToken) -> None:
        """Extract task-specific capabilities from agent descriptions."""
        # Create agent descriptions string
        agent_descriptions = ""
        for name, desc in zip(self._participant_names, self._participant_descriptions):
            agent_descriptions += f"{name}: {desc}\n"
        
        capabilities_conversation: List[LLMMessage] = []
        capabilities_conversation.append(
            UserMessage(content=self._get_capabilities_prompt(self._task, self._plan, agent_descriptions), source=self._name)
        )
        
        response = await self._model_client.create(
            self._get_compatible_context(capabilities_conversation), 
            cancellation_token=cancellation_token
        )
        
        print(response.content)
        input()

        assert isinstance(response.content, str)
        try:
            cleaned_content = self._clean_json_response(response.content)
            capabilities_data = json.loads(cleaned_content)
            self._agent_capabilities = capabilities_data.get("agent_capabilities", {})
            await self._log_message(f"Extracted capabilities: {self._agent_capabilities}")
        except json.JSONDecodeError as e:
            await self._log_message(f"Failed to parse capabilities JSON: {e}")
            await self._log_message(f"Raw response: {response.content}")
            raise e

    async def _generate_natural_language_rules(self, cancellation_token: CancellationToken) -> None:
        """Generate natural language safety rules based on capabilities."""
        capabilities_str = json.dumps(self._agent_capabilities, indent=2)
        
        rules_conversation: List[LLMMessage] = []
        rules_conversation.append(
            UserMessage(content=self._get_natural_language_rules_prompt(self._task, self._plan, capabilities_str), source=self._name)
        )
        
        response = await self._model_client.create(
            self._get_compatible_context(rules_conversation), 
            cancellation_token=cancellation_token
        )
        
        print(response.content)
        input()

        assert isinstance(response.content, str)
        try:
            cleaned_content = self._clean_json_response(response.content)
            rules_data = json.loads(cleaned_content)
            self._natural_language_rules = rules_data.get("natural_language_rules", {})
            await self._log_message(f"Generated natural language rules: {self._natural_language_rules}")
        except json.JSONDecodeError as e:
            await self._log_message(f"Failed to parse natural language rules JSON: {e}")
            await self._log_message(f"Raw response: {response.content}")
            raise e

    async def _generate_contextual_cfg(self, cancellation_token: CancellationToken) -> None:
        """Generate CFG with contextual conditions based on capabilities and rules."""
        capabilities_str = json.dumps(self._agent_capabilities, indent=2)
        rules_str = json.dumps(self._natural_language_rules, indent=2)
        
        cfg_conversation: List[LLMMessage] = []
        cfg_conversation.append(
            UserMessage(content=self._get_contextual_cfg_prompt(self._task, self._plan, capabilities_str, rules_str), source=self._name)
        )
        
        response = await self._model_client.create(
            self._get_compatible_context(cfg_conversation), 
            cancellation_token=cancellation_token
        )
        
        print(response.content)
        input()
        assert isinstance(response.content, str)
        try:
            cleaned_content = self._clean_json_response(response.content)
            cfg_data = json.loads(cleaned_content)
            self._cfg = cfg_data.get("grammar", "")
            self._agent_conditions = cfg_data.get("conditions", {})
            
            # Clean up the grammar
            self._cfg = re.sub(r"^\s+|\s+$|`+", "", self._cfg)
            self._cfg = re.sub(r"ebnf", "", self._cfg)
            
            self._parser = self._get_parser(self._cfg)
            await self._log_message(f"Generated CFG: {self._cfg}")
            await self._log_message(f"Agent conditions: {self._agent_conditions}")
            
        except json.JSONDecodeError as e:
            await self._log_message(f"Failed to parse CFG JSON: {e}")
            await self._log_message(f"Raw response: {response.content}")
            raise e

    def _create_fallback_grammar(self) -> str:
        """Create a simple fallback grammar if CFG generation fails."""
        agents_list = '"\n        | "'.join(self._participant_names)
        return f"""start: agents

agents: agent
        | agent agents

agent: "{agents_list}"

%import common.WS
%ignore WS"""

    async def _validate_guardrails(self, agent_name: str, instruction: str, cancellation_token: CancellationToken) -> Dict[str, Any]:
        """Validate guardrail conditions and natural language rules for the selected agent."""
        # Get natural language rules for this agent
        agent_rules = self._natural_language_rules.get(agent_name, [])
        rules_str = json.dumps(agent_rules, indent=2)
        
        # Get structured conditions for this agent
        agent_conditions = self._agent_conditions.get(agent_name, [])
        conditions_str = json.dumps(agent_conditions, indent=2)
        
        # If no rules or conditions, approve by default
        if not agent_rules and not agent_conditions:
            return {
                "overall_approved": True,
                "recommendation": "approve",
                "explanation": f"No guardrail conditions or rules defined for {agent_name}"
            }
        
        # Gather recent conversation evidence
        evidence = ""
        for msg in self._message_thread[-10:]:  # Last 10 messages as evidence
            evidence += f"{msg.source}: {msg.content}\n"
        
        guardrail_conversation: List[LLMMessage] = []
        guardrail_conversation.append(
            UserMessage(
                content=self._get_guardrail_validation_prompt(agent_name, self._task, rules_str, conditions_str, evidence, instruction), 
                source=self._name
            )
        )
        
        response = await self._model_client.create(
            self._get_compatible_context(guardrail_conversation), 
            cancellation_token=cancellation_token
        )
        
        assert isinstance(response.content, str)
        try:
            cleaned_content = self._clean_json_response(response.content)
            validation_result = json.loads(cleaned_content)
            result = validation_result.get("validation_result", None)
            
            if result is None:
                await self._log_message(f"No validation_result field found in response: {validation_result}")
                return {
                    "overall_approved": False,
                    "recommendation": "retry_with_modification",
                    "explanation": "Validation response missing required fields - please review manually",
                    "suggested_modification": "Review the safety conditions and provide explicit confirmation"
                }
            
            # Ensure required fields exist
            if not isinstance(result.get("overall_approved"), bool):
                await self._log_message(f"Invalid overall_approved field: {result}")
                return {
                    "overall_approved": False,
                    "recommendation": "retry_with_modification", 
                    "explanation": "Validation response has invalid approval status"
                }
            
            return result
            
        except json.JSONDecodeError as e:
            await self._log_message(f"Failed to parse guardrail validation JSON: {e}")
            await self._log_message(f"Raw response: {response.content}")
            return {
                "overall_approved": False,
                "recommendation": "retry_with_modification",
                "explanation": f"Validation system error - JSON parsing failed: {e}",
                "suggested_modification": "Simplify the task or provide more context for safety evaluation"
            }

    @rpc
    async def handle_start(self, message: GroupChatStart, ctx: MessageContext) -> None:  # type: ignore
        """Handle the start of a task."""

        # Check if the conversation has already terminated.
        if self._termination_condition is not None and self._termination_condition.terminated:
            early_stop_message = StopMessage(content="The group chat has already terminated.", source=self._name)
            # Signal termination.
            await self._signal_termination(early_stop_message)
            # Stop the group chat.
            return
        assert message is not None and message.messages is not None

        # Validate the group state given all the messages.
        await self.validate_group_state(message.messages)

        # Log the message to the output topic.
        await self.publish_message(message, topic_id=DefaultTopicId(type=self._output_topic_type))
        # Log the message to the output queue.
        for msg in message.messages:
            await self._output_message_queue.put(msg)

        # Outer Loop for first time
        # Create the initial task ledger
        #################################
        # Combine all message contents for task
        self._task = " ".join([msg.to_model_text() for msg in message.messages])
        planning_conversation: List[LLMMessage] = []

        # 1. GATHER FACTS
        # create a closed book task and generate a response and update the chat history
        planning_conversation.append(
            UserMessage(content=self._get_task_ledger_facts_prompt(self._task), source=self._name)
        )
        response = await self._model_client.create(
            self._get_compatible_context(planning_conversation), cancellation_token=ctx.cancellation_token
        )

        assert isinstance(response.content, str)
        self._facts = response.content
        planning_conversation.append(AssistantMessage(content=self._facts, source=self._name))

        # 2. CREATE A PLAN
        ## plan based on available information
        planning_conversation.append(
            UserMessage(content=self._get_task_ledger_plan_prompt(self._team_description), source=self._name)
        )
        response = await self._model_client.create(
            self._get_compatible_context(planning_conversation), cancellation_token=ctx.cancellation_token
        )

        assert isinstance(response.content, str)
        self._plan = response.content

        # 3. EXTRACT AGENT CAPABILITIES (task-specific)
        await self._extract_agent_capabilities(ctx.cancellation_token)

        # 4. GENERATE NATURAL LANGUAGE RULES based on capabilities
        await self._generate_natural_language_rules(ctx.cancellation_token)

        # 5. GENERATE CONTEXTUAL CFG WITH CONDITIONS based on capabilities and rules
        await self._generate_contextual_cfg(ctx.cancellation_token)

        # Kick things off
        self._n_stalls = 0
        await self._reenter_outer_loop(ctx.cancellation_token)

    async def _orchestrate_step(self, cancellation_token: CancellationToken) -> None:
        """Implements the inner loop of the orchestrator and selects next speaker with guardrail validation."""
        # Check if we reached the maximum number of rounds
        if self._max_turns is not None and self._n_rounds > self._max_turns:
            await self._prepare_final_answer("Max rounds reached.", cancellation_token)
            return
        self._n_rounds += 1

        # Update the progress ledger
        context = self._thread_to_context()

        allowed_speakers = self._get_allowed_speakers()
        self._update_team_description(allowed_speakers)
        await self._log_message(f"Allowed speakers: {allowed_speakers}")
        
        progress_ledger_prompt = self._get_progress_ledger_prompt(
            self._task, self._team_description, allowed_speakers
        )
        context.append(UserMessage(content=progress_ledger_prompt, source=self._name))
        progress_ledger: Dict[str, Any] = {}
        assert self._max_json_retries > 0
        key_error: bool = False
        for _ in range(self._max_json_retries):
            if self._model_client.model_info.get("structured_output", False):
                response = await self._model_client.create(
                    self._get_compatible_context(context), json_output=LedgerEntry
                )
            elif self._model_client.model_info.get("json_output", False):
                response = await self._model_client.create(
                    self._get_compatible_context(context), cancellation_token=cancellation_token, json_output=True
                )
            else:
                response = await self._model_client.create(
                    self._get_compatible_context(context), cancellation_token=cancellation_token
                )
            ledger_str = response.content
            try:
                assert isinstance(ledger_str, str)
                output_json = extract_json_from_str(ledger_str)
                if len(output_json) != 1:
                    raise ValueError(
                        f"Progress ledger should contain a single JSON object, but found: {len(progress_ledger)}"
                    )
                progress_ledger = output_json[0]

                # If the team consists of a single agent, deterministically set the next speaker
                if len(self._participant_names) == 1:
                    progress_ledger["next_speaker"] = {
                        "reason": "The team consists of only one agent.",
                        "answer": self._participant_names[0],
                    }

                # Validate the structure
                required_keys = [
                    "is_request_satisfied",
                    "is_progress_being_made",
                    "is_in_loop",
                    "instruction_or_question",
                    "next_speaker",
                ]

                key_error = False
                for key in required_keys:
                    if (
                        key not in progress_ledger
                        or not isinstance(progress_ledger[key], dict)
                        or "answer" not in progress_ledger[key]
                        or "reason" not in progress_ledger[key]
                    ):
                        key_error = True
                        break

                # Validate the next speaker if the task is not yet complete
                if (
                    not progress_ledger["is_request_satisfied"]["answer"]
                    and progress_ledger["next_speaker"]["answer"] not in self._participant_names
                ):
                    key_error = True
                    break

                if not key_error:
                    break
                await self._log_message(f"Failed to parse ledger information, retrying: {ledger_str}")
            except (json.JSONDecodeError, TypeError):
                key_error = True
                await self._log_message("Invalid ledger format encountered, retrying...")
                continue
        if key_error:
            raise ValueError("Failed to parse ledger information after multiple retries.")
        await self._log_message(f"Progress Ledger: {progress_ledger}")

        # Check for task completion
        if progress_ledger["is_request_satisfied"]["answer"]:
            await self._log_message("Task completed, preparing final answer...")
            await self._prepare_final_answer(progress_ledger["is_request_satisfied"]["reason"], cancellation_token)
            return

        # Check for stalling
        if not progress_ledger["is_progress_being_made"]["answer"]:
            self._n_stalls += 1
        elif progress_ledger["is_in_loop"]["answer"]:
            self._n_stalls += 1
        else:
            self._n_stalls = max(0, self._n_stalls - 1)

        # Too much stalling
        if self._n_stalls >= self._max_stalls:
            await self._log_message("Stall count exceeded, re-planning with the outer loop...")
            await self._update_task_ledger(cancellation_token)
            await self._reenter_outer_loop(cancellation_token)
            return

        # Get next speaker and instruction
        next_speaker = progress_ledger["next_speaker"]["answer"]
        instruction = progress_ledger["instruction_or_question"]["answer"]

        # Check if the next speaker is valid according to CFG
        if next_speaker not in self._get_allowed_speakers():
            raise ValueError(
                f"Invalid next speaker: Tried to pick a speaker that is not allowed by the CFG: {next_speaker}. Allowed speakers are: {self._get_allowed_speakers()}"
            )

        # GUARDRAIL VALIDATION
        validation_result = await self._validate_guardrails(next_speaker, instruction, cancellation_token)
        
        if not validation_result.get("overall_approved", False):
            recommendation = validation_result.get("recommendation", "reject")
            explanation = validation_result.get("explanation", "Guardrail validation failed")
            
            retry_key = f"{next_speaker}_{self._n_rounds}"
            retry_count = self._guardrail_retry_count.get(retry_key, 0)
            
            if recommendation == "retry_with_modification" and retry_count == 0:
                # Try once more with suggested modification
                self._guardrail_retry_count[retry_key] = 1
                suggested_modification = validation_result.get("suggested_modification", "")
                
                await self._log_message(f"Guardrail validation failed for {next_speaker}, retrying with modification: {suggested_modification}")
                
                # Modify the instruction if suggested
                if suggested_modification:
                    instruction = f"{instruction} {suggested_modification}"
                
                # Re-validate with modified instruction
                validation_result = await self._validate_guardrails(next_speaker, instruction, cancellation_token)
                
                if not validation_result.get("overall_approved", False):
                    # Still failed, end conversation
                    failure_message = f"Guardrail validation failed for {next_speaker} even after retry. Reason: {validation_result.get('explanation', 'Unknown')}"
                    await self._prepare_final_answer(failure_message, cancellation_token)
                    return
            
            elif recommendation == "reject" or retry_count >= 1:
                # End conversation with detailed explanation
                failure_message = f"Guardrail validation rejected for {next_speaker}. Reason: {explanation}"
                await self._prepare_final_answer(failure_message, cancellation_token)
                return
            
            else:
                # Try to select alternative speaker
                alternative_speakers = [s for s in self._get_allowed_speakers() if s != next_speaker]
                if alternative_speakers:
                    next_speaker = alternative_speakers[0]  # Pick first alternative
                    await self._log_message(f"Switching to alternative speaker: {next_speaker}")
                else:
                    # No alternatives, end conversation
                    failure_message = f"No alternative speakers available after guardrail failure for {next_speaker}. Reason: {explanation}"
                    await self._prepare_final_answer(failure_message, cancellation_token)
                    return

        # Guardrails passed, proceed with the agent
        await self._log_message(f"Guardrail validation passed for {next_speaker}")

        # Broadcast the next step
        message = TextMessage(content=instruction, source=self._name)
        await self.update_message_thread([message])  # My copy

        await self._log_message(f"Next Speaker: {next_speaker}")
        # Log it to the output topic.
        await self.publish_message(
            GroupChatMessage(message=message),
            topic_id=DefaultTopicId(type=self._output_topic_type),
        )
        # Log it to the output queue.
        await self._output_message_queue.put(message)

        # Broadcast it
        await self.publish_message(  # Broadcast
            GroupChatAgentResponse(agent_response=Response(chat_message=message), agent_name=self._name),
            topic_id=DefaultTopicId(type=self._group_topic_type),
            cancellation_token=cancellation_token,
        )

        # Request that the step be completed
        participant_topic_type = self._participant_name_to_topic_type[next_speaker]
        await self.publish_message(
            GroupChatRequestPublish(),
            topic_id=DefaultTopicId(type=participant_topic_type),
            cancellation_token=cancellation_token,
        )

        # Send the message to the next speaker
        if self._emit_team_events:
            select_msg = SelectSpeakerEvent(content=[next_speaker], source=self._name)
            await self.publish_message(
                GroupChatMessage(message=select_msg),
                topic_id=DefaultTopicId(type=self._output_topic_type),
            )
            await self._output_message_queue.put(select_msg)
        
        self._current_speaker_sequence.append(next_speaker)
        await self._log_message(f"Current speaker sequence: {self._current_speaker_sequence}")

    # TODO: infinite orchestrator support
    # TODO: Might need to work on reset