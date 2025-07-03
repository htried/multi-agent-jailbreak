# new class that inherits from MagenticOneOrchestrator
# but, the speaker selection is constrained by a CFG passed in as an argument

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

from multiagents.constrained_utils.prompts import ORCHESTRATOR_PROGRESS_LEDGER_PROMPT, ORCHESTRATOR_CFG_PROMPT


class ConstrainedMAOrchestrator(MagenticOneOrchestrator):
    """The ConstrainedMAOrchestrator manages a group chat with CFG-constrained speaker selection."""

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
        # cfg_constraints: Dict[str, List[str]] | None = None,  # New parameter for CFG constraints
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
    
    def _get_cfg_prompt(self, task: str, plan: str) -> str:
        return ORCHESTRATOR_CFG_PROMPT.format(task=task, plan=plan)

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

        # 3. GENERATE A CFG
        planning_conversation.append(
            UserMessage(content=self._get_cfg_prompt(self._task, self._plan), source=self._name)
        )
        response = await self._model_client.create(
            self._get_compatible_context(planning_conversation), cancellation_token=ctx.cancellation_token
        )

        print(response.content)
        input()
        assert isinstance(response.content, str)
        self._cfg = re.sub(r"^\s+|\s+$|`+", "", response.content)
        # remove 'ebnf' from the entire string
        self._cfg = re.sub(r"ebnf", "", self._cfg)
        self._parser = self._get_parser(self._cfg)

        # Kick things off
        self._n_stalls = 0
        await self._reenter_outer_loop(ctx.cancellation_token)


    async def _orchestrate_step(self, cancellation_token: CancellationToken) -> None:
        """Implements the inner loop of the orchestrator and selects next speaker."""
        # Check if we reached the maximum number of rounds
        if self._max_turns is not None and self._n_rounds > self._max_turns:
            await self._prepare_final_answer("Max rounds reached.", cancellation_token)
            return
        self._n_rounds += 1

        # Update the progress ledger
        context = self._thread_to_context()

        allowed_speakers = self._get_allowed_speakers()
        self._update_team_description(allowed_speakers)
        print(f"Allowed speakers: {allowed_speakers}")
        print(self._team_description)
        input()
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

        # Broadcast the next step
        message = TextMessage(content=progress_ledger["instruction_or_question"]["answer"], source=self._name)
        await self.update_message_thread([message])  # My copy

        await self._log_message(f"Next Speaker: {progress_ledger['next_speaker']['answer']}")
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
        next_speaker = progress_ledger["next_speaker"]["answer"]
        # Check if the next speaker is valid
        # if next_speaker not in self._participant_name_to_topic_type:
        #     raise ValueError(
        #         f"Invalid next speaker: {next_speaker} from the ledger, participants are: {self._participant_names}"
        #     )
        if next_speaker not in self._get_allowed_speakers():
            raise ValueError(
                f"Invalid next speaker: Tried to pick a speaker that is not allowed by the CFG: {next_speaker}. Allowed speakers are: {self._get_allowed_speakers()}"
            )
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
        print(f"Current speaker sequence: {self._current_speaker_sequence}")

    # TODO: infinite orchestrator support
    # TOOD: Might need to work on reset
