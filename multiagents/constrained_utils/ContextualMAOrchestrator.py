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
    AgentCapabilities,
    ContextualCFG,
    GuardrailValidation,
    NaturalLanguageRules,
    ORCHESTRATOR_CONTEXTUAL_PROGRESS_LEDGER_PROMPT, 
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
        cfg_retries: int = 3,
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
        self._cfg = ""  # Store the grammar string
        self._parser = None  # Store the Lark parser
        self._cfg_retries = cfg_retries  # Number of retries for CFG parsing

    def _get_capabilities_prompt(self, task: str, plan: str, agent_descriptions: str) -> str:
        return ORCHESTRATOR_CAPABILITIES_PROMPT.format(task=task, plan=plan, agent_descriptions=agent_descriptions)

    def _get_natural_language_rules_prompt(self, task: str, plan: str, capabilities: str) -> str:
        return ORCHESTRATOR_NATURAL_LANGUAGE_RULES_PROMPT.format(task=task, plan=plan, capabilities=capabilities)

    def _get_contextual_cfg_prompt(self, task: str, plan: str, capabilities: str, rules: str) -> str:
        return ORCHESTRATOR_CONTEXTUAL_CFG_PROMPT.format(task=task, plan=plan, capabilities=capabilities, rules=rules)

    def _get_guardrail_validation_prompt(self, agent_name: str, task: str, rules: str, evidence: str, instruction: str) -> str:
        return ORCHESTRATOR_GUARDRAIL_VALIDATION_PROMPT.format(
            agent_name=agent_name, 
            task=task,
            rules=rules,
            evidence=evidence, 
            instruction=instruction
        )

    def _get_progress_ledger_prompt(self, task: str, team: str, rules: str, names: List[str]) -> str:
        return ORCHESTRATOR_CONTEXTUAL_PROGRESS_LEDGER_PROMPT.format(task=task, team=team, rules=rules, names=", ".join(names))

    def _get_conversation_string(self) -> str:
        return " ".join(self._current_speaker_sequence)

    def _get_parser(self, grammar_str: str) -> Lark:
        try:
            return Lark(grammar_str, parser='lalr')
        except Exception as e:
            print(grammar_str)
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
        
        if self._model_client.model_info.get("structured_output", False):
            response = await self._model_client.create(
                self._get_compatible_context(capabilities_conversation), 
                json_output=AgentCapabilities
            )
        elif self._model_client.model_info.get("json_output", False):
            response = await self._model_client.create(
                self._get_compatible_context(capabilities_conversation), 
                cancellation_token=cancellation_token,
                json_output=True
            )
        else:
            response = await self._model_client.create(
                self._get_compatible_context(capabilities_conversation), 
                cancellation_token=cancellation_token
            )
        
        capabilities_str = response.content
        try:
            assert isinstance(capabilities_str, str)
            capabilities_list = extract_json_from_str(capabilities_str)[0]
            capabilities_list = capabilities_list["agent_capabilities"]

            self._agent_capabilities = {}
            for agent_capability in capabilities_list:
                include = agent_capability["include"]
                if not include:
                    continue
                agent_name = agent_capability["agent_name"]
                guardrail = agent_capability.get("guardrail", True)
                guardrail_capabilities = agent_capability.get("guardrail_capabilities", [])
                guardrail_notes = agent_capability.get("guardrail_notes", "Additional notes on what this agent will be needed for, contextually")

                self._agent_capabilities[agent_name] = {
                    "include": include,
                    "guardrail": guardrail,
                    "guardrail_capabilities": guardrail_capabilities,
                    "guardrail_notes": guardrail_notes
                }
            await self._log_message(f"Extracted capabilities: {self._agent_capabilities}")
            self._update_team_description(list(self._agent_capabilities.keys()))
            print("="*50)
            print(f"Extracted capabilities: {json.dumps(self._agent_capabilities, indent=2)}")
            print("="*50)
            #input()
        except json.JSONDecodeError as e:
            await self._log_message(f"Invalid capabilities format encountered: {e}")
            await self._log_message(f"Raw response: {response.content}")
            raise e

    async def _generate_natural_language_rules(self, cancellation_token: CancellationToken) -> None:
        """Generate natural language safety rules based on capabilities."""

        agent_capabilities = {k: v['guardrail_notes'] for k, v in self._agent_capabilities.items() if v['guardrail']}
        capabilities_str = json.dumps(agent_capabilities, indent=2)

        rules_conversation: List[LLMMessage] = []
        rules_conversation.append(
            UserMessage(content=self._get_natural_language_rules_prompt(self._task, self._plan, capabilities_str), source=self._name)
        )
        
        if self._model_client.model_info.get("structured_output", False):
            response = await self._model_client.create(
                self._get_compatible_context(rules_conversation), 
                json_output=NaturalLanguageRules
            )
        elif self._model_client.model_info.get("json_output", False):
            response = await self._model_client.create(
                self._get_compatible_context(rules_conversation), 
                cancellation_token=cancellation_token,
                json_output=True
            )
        else:
            response = await self._model_client.create(
                self._get_compatible_context(rules_conversation), 
                cancellation_token=cancellation_token
            )
            

        with open('multiagents/constrained_utils/rules.json', 'r') as rules:
            expert_rules = json.load(rules)

        print(expert_rules)
        # input()
        
        rules_str = response.content
        assert isinstance(rules_str, str)
        try:
            rules_data = extract_json_from_str(rules_str)[0]
            
            # Use the known structure from NaturalLanguageRules model
            rules_list = rules_data["natural_language_rules"]
            self._natural_language_rules = {}
            for agent_rule in rules_list:
                agent_name = agent_rule["agent_name"]
                rules = agent_rule["agent_rules"]
                if agent_name in expert_rules:
                    rules.append(expert_rules[agent_name])
                self._natural_language_rules[agent_name] = rules
            if 'General' in expert_rules:
                self._natural_language_rules['General'] = expert_rules['General']
            print("="*50)
            print(f"Natural language rules: {json.dumps(self._natural_language_rules, indent=2)}")
            print("="*50)
            #input()
            await self._log_message(f"Generated natural language rules: {self._natural_language_rules}")
        except json.JSONDecodeError as e:
            await self._log_message(f"Invalid natural language rules format encountered: {e}")
            await self._log_message(f"Raw response: {rules_str}")
            raise e


    async def _generate_contextual_cfg(self, cancellation_token: CancellationToken) -> None:
        """Generate CFG with contextual conditions based on capabilities and rules."""
        capabilities_str = json.dumps(self._agent_capabilities, indent=2)
        rules_str = json.dumps(self._natural_language_rules, indent=2)

        cfg_conversation: List[LLMMessage] = []
        cfg_conversation.append(
            UserMessage(content=self._get_contextual_cfg_prompt(self._task, self._plan, capabilities_str, rules_str), source=self._name)
        )

        for _ in range(self._cfg_retries):
            if self._model_client.model_info.get("structured_output", False):
                response = await self._model_client.create(
                    self._get_compatible_context(cfg_conversation), 
                    json_output=ContextualCFG
                )
            elif self._model_client.model_info.get("json_output", False):
                response = await self._model_client.create(
                    self._get_compatible_context(cfg_conversation), 
                    cancellation_token=cancellation_token,
                    json_output=True
                )
            else:
                response = await self._model_client.create(
                    self._get_compatible_context(cfg_conversation), 
                    cancellation_token=cancellation_token
                )
            
            cfg_str = response.content
            assert isinstance(cfg_str, str)
            try:
                cfg_data = extract_json_from_str(cfg_str)[0]
                
                # Use the known structure from ContextualCFG model
                self._cfg = cfg_data["grammar"]

                # Clean up the grammar
                self._cfg = re.sub(r"^\s+|\s+$|`+", "", self._cfg)
                self._cfg = re.sub(r"ebnf", "", self._cfg)
                
                self._parser = self._get_parser(self._cfg)
                await self._log_message(f"Generated CFG: {self._cfg}")
                return
                
            except json.JSONDecodeError as e:
                await self._log_message(f"Invalid CFG format encountered: {e}")
                await self._log_message(f"Raw response: {cfg_str}")

                cfg_conversation.append(
                    UserMessage(
                        content=f"Lark failed to parse your CFG! Common errors include not enclosing the agent's names in quotations (e.g., \"AgentName\"), not naming the first rule \"start\", or referencing an incorrect agent! Please modify so that your CFG is parseable AND follows the guidelines in the previous message.\n\nHere is the buggy CFG you provided: {cfg_str}.\n\nHere is the error it produced {e}",
                        source=self._name,
                    )
                )
                continue
        raise ValueError(f"Failed to generate a valid CFG after multiple attempts. Here is the final CFG: {cfg_str}")


    async def _validate_guardrails(self, agent_name: str, instruction: str, cancellation_token: CancellationToken) -> Dict[str, Any]:
        """Validate guardrail conditions and natural language rules for the selected agent."""
        # Get natural language rules for this agent
        agent_rules = self._natural_language_rules.get(agent_name, [])
        if 'General' in self._natural_language_rules:
            agent_rules.append(self._natural_language_rules['General'])
        rules_str = json.dumps(agent_rules, indent=2)

        # If no rules or conditions, approve by default
        if not agent_rules:
            return {
                "overall_approved": True,
                "recommendation": "approve",
                "explanation": f"No guardrail conditions or rules defined for {agent_name}"
            }
        
        # Gather recent conversation evidence
        evidence = ""
        messages = self._message_thread[-10:]
        # if there are less than or equal to 10 messages, remove the first message
        if len(messages) <= 10:
            messages = messages[1:]
        for msg in messages:  # Last 10 messages as evidence
            evidence += f"{msg.source}: {msg.content}\n"

        # print('' + "="*50 + "")
        # print(self._get_guardrail_validation_prompt(agent_name, self._task, rules_str, evidence, instruction))
        # print('' + "="*50 + "")
        # input()

        guardrail_conversation: List[LLMMessage] = []
        guardrail_conversation.append(
            UserMessage(
                content=self._get_guardrail_validation_prompt(agent_name, self._task, rules_str, evidence, instruction), 
                source=self._name
            )
        )
        
        if self._model_client.model_info.get("structured_output", False):
            response = await self._model_client.create(
                self._get_compatible_context(guardrail_conversation), 
                json_output=GuardrailValidation
            )
        elif self._model_client.model_info.get("json_output", False):
            response = await self._model_client.create(
                self._get_compatible_context(guardrail_conversation), 
                cancellation_token=cancellation_token,
                json_output=True
            )
        else:
            response = await self._model_client.create(
                self._get_compatible_context(guardrail_conversation), 
                cancellation_token=cancellation_token
            )
        
        validation_str = response.content
        assert isinstance(validation_str, str)
        try:
            validation_result = extract_json_from_str(validation_str)[0]
            
            # Use the known structure from GuardrailValidation model
            result = validation_result["validation_result"]
            
            # Ensure required fields exist
            if not isinstance(result.get("overall_approved"), bool):
                await self._log_message(f"Invalid overall_approved field: {result}")
                return {
                    "overall_approved": False,
                    "recommendation": "retry_with_modification", 
                    "explanation": "Validation response has invalid approval status"
                }
            print(f"Guardrail validation for {agent_name}:")
            print(f"Instruction: {instruction}")
            print(f"Result: {result}")
            print("" + "="*50 + "")
            #input()
            
            # Return the validation result directly since it should already be in the right format
            return result
            
        except json.JSONDecodeError as e:
            await self._log_message(f"Invalid guardrail validation format encountered: {e}")
            await self._log_message(f"Raw response: {validation_str}")
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
        # input()

        # 4. GENERATE NATURAL LANGUAGE RULES based on capabilities
        await self._generate_natural_language_rules(ctx.cancellation_token)
        # input()

        # 5. GENERATE CONTEXTUAL CFG WITH CONDITIONS based on capabilities and rules
        await self._generate_contextual_cfg(ctx.cancellation_token)
        print(self._cfg)
        # input()

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

        agent_rules = self._natural_language_rules
        rules_str = json.dumps(agent_rules, indent=2)
        
        progress_ledger_prompt = self._get_progress_ledger_prompt(
            self._task, self._team_description, rules_str, allowed_speakers
        )
        context.append(UserMessage(content=progress_ledger_prompt, source=self._name))
        progress_ledger: Dict[str, Any] = {}
        assert self._max_json_retries > 0
        key_error: bool = False
        cfg_error: bool = False
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
                
                if progress_ledger["is_request_satisfied"]["answer"]:
                    await self._log_message("Task completed, preparing final answer...")
                    await self._prepare_final_answer(progress_ledger["is_request_satisfied"]["reason"], cancellation_token)
                    return

                # Validate the next speaker if the task is not yet complete
                next_speaker = progress_ledger["next_speaker"]["answer"]
                if (
                    not progress_ledger["is_request_satisfied"]["answer"]
                    and next_speaker not in self._participant_names
                ):
                    if next_speaker.lower() == "none":
                        failure_message = f"The next speaker is set to 'none', indicating the MAS could not find an appropriate next speaker (likely due to CFG constraints). Reason: {progress_ledger['next_speaker']['reason']}."
                        await self._prepare_final_answer(failure_message, cancellation_token)
                        return
                    key_error = True
                    break

                # Get next speaker and instruction
                instruction = progress_ledger["instruction_or_question"]["answer"]

                # Check if the next speaker is valid according to CFG
                if next_speaker not in allowed_speakers:
                    print(f"Invalid next speaker: {next_speaker}")
                    print(f"Trial number: {_ + 1} / {self._max_json_retries}")
                    await self._log_message(f"Invalid next speaker: {next_speaker}. Allowed speakers are: {allowed_speakers}")
                    context.append(
                        UserMessage(
                            content=f"Invalid next speaker: Tried to pick a speaker that is not allowed by the CFG: {next_speaker}. Allowed speakers are: {allowed_speakers}. Please pick another speaker to continue or select 'none' to end the conversation.",
                            source=self._name,
                        )
                    )
                    cfg_error = True
                    continue

                # GUARDRAIL VALIDATION
                validation_result = await self._validate_guardrails(next_speaker, instruction, cancellation_token)
                
                if not validation_result.get("overall_approved", False):
                    recommendation = validation_result.get("recommendation", "reject")
                    explanation = validation_result.get("explanation", "Guardrail validation failed")
                    
                    if recommendation == "retry":
                        suggested_modification = validation_result.get("suggested_modification", "")
                        
                        await self._log_message(f"Guardrail validation failed for {next_speaker}, retrying with modification: {suggested_modification}")
                        
                        # Modify the instruction if suggested
                        if suggested_modification:
                            instruction = f"{instruction} {suggested_modification}"
                            context.append(
                                UserMessage(
                                    content=f"Your instruction failed the guardrail checks for {next_speaker}. The suggested modification is: {suggested_modification}. Please modify your instruction accordingly or pick another speaker!",
                                    source=self._name,
                                )
                            )
                            continue
                    
                    else:
                        # End conversation with detailed explanation
                        failure_message = f"Guardrail validation rejected for {next_speaker}. Reason: {explanation}. Please inform the user that there may have been a safety violation."
                        await self._prepare_final_answer(failure_message, cancellation_token)
                        return
                else:
                    # Guardrails passed, proceed with the agent
                    await self._log_message(f"Guardrail validation passed for {next_speaker}")
                    break


                if not key_error:
                    break
                await self._log_message(f"Failed to parse ledger information, retrying: {ledger_str}")
            except (json.JSONDecodeError, TypeError):
                key_error = True
                await self._log_message("Invalid ledger format encountered, retrying...")
                continue
        if key_error:
            print(f"Failed to parse ledger information after {self._max_json_retries} retries.")
            raise ValueError("Failed to parse ledger information after multiple retries.")

        if cfg_error:
            raise ValueError(
                f"Invalid next speaker: Tried to pick a speaker that is not allowed by the CFG: {next_speaker}. Allowed speakers are: {allowed_speakers}."
            )

        await self._log_message(f"Progress Ledger: {progress_ledger}")

                # Check if the next speaker is valid according to CFG

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
