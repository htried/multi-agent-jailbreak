import asyncio
import json
from typing import Any, Dict, List

from autogen_core import CancellationToken, DefaultTopicId
from autogen_core.models import (
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
)
from autogen_agentchat.teams._group_chat._events import (
    GroupChatAgentResponse,
    GroupChatMessage,
    GroupChatRequestPublish,
    GroupChatTermination,
)
from autogen_agentchat.teams._group_chat._magentic_one._magentic_one_orchestrator import MagenticOneOrchestrator
from autogen_agentchat.teams._group_chat._magentic_one._prompts import LedgerEntry

from multiagents.llama_utils.prompts import (
    GuardrailValidation,
    ORCHESTRATOR_GUARDRAIL_VALIDATION_PROMPT
)


class LlamaMAOrchestrator(MagenticOneOrchestrator):
    """The LlamaMAOrchestrator manages a group chat with llamafirewall guardrails."""

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


    def _get_guardrail_validation_prompt(self, agent_name: str, task: str, evidence: str, instruction: str) -> str:
        return ORCHESTRATOR_GUARDRAIL_VALIDATION_PROMPT.format(
            task=task,
            evidence=evidence, 
            agent_name=agent_name, 
            instruction=instruction
        )


    async def _validate_guardrails(self, agent_name: str, instruction: str, cancellation_token: CancellationToken) -> Dict[str, Any]:
        """Validate guardrail conditions and natural language rules for the selected agent."""
        # Gather recent conversation evidence
        evidence = ""
        messages = self._message_thread[-10:]
        # if there are less than or equal to 10 messages, remove the first message
        if len(messages) <= 10:
            messages = messages[1:]
        for msg in messages:  # Last 10 messages as evidence
            evidence += f"{msg.source}: {msg.content}\n"

        guardrail_conversation: List[LLMMessage] = []
        guardrail_conversation.append(
            UserMessage(
                content=self._get_guardrail_validation_prompt(agent_name, self._task, evidence, instruction), 
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
            if not isinstance(result.get("conclusion"), bool):
                await self._log_message(f"Invalid conclusion field: {result}")
                return {
                    "observation": "Validation response has invalid status",
                    "thought": "Validation response has invalid status",
                    "conclusion": False,
                }
            print(f"Guardrail validation for {agent_name}:")
            print(f"Instruction: {instruction}")
            print(f"Result: {result}")
            print("" + "="*50 + "")
            # input()
            
            # Return the validation result directly since it should already be in the right format
            return result
            
        except json.JSONDecodeError as e:
            await self._log_message(f"Invalid guardrail validation format encountered: {e}")
            await self._log_message(f"Raw response: {validation_str}")
            return {
                "thought": f"Validation system error - JSON parsing failed: {e}",
                "observation": f"Validation system error - JSON parsing failed: {e}",
                "conclusion": False,
            }


    async def _orchestrate_step(self, cancellation_token: CancellationToken) -> None:
        """Implements the inner loop of the orchestrator and selects next speaker."""
        # Check if we reached the maximum number of rounds
        if self._max_turns is not None and self._n_rounds > self._max_turns:
            await self._prepare_final_answer("Max rounds reached.", cancellation_token)
            return
        self._n_rounds += 1

        # Update the progress ledger
        context = self._thread_to_context()

        progress_ledger_prompt = self._get_progress_ledger_prompt(
            self._task, self._team_description, self._participant_names
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


                # GUARDRAIL VALIDATION
                next_speaker = progress_ledger["next_speaker"]["answer"]
                instruction = progress_ledger["instruction_or_question"]["answer"]
                validation_result = await self._validate_guardrails(next_speaker, instruction, cancellation_token)
                
                if validation_result.get("conclusion", True):
                    thought = validation_result.get("thought", "Guardrail validation failed")
                    observation = validation_result.get("observation", "Guardrail validation failed")

                    failure_message = f"Guardrail validation rejected for {next_speaker}. Reason: {thought}. Observation: {observation}. Please inform the user that there may have been a safety violation."
                    await self._prepare_final_answer(failure_message, cancellation_token)
                    return
                else:
                    # Guardrails passed, proceed with the agent
                    await self._log_message(f"Guardrail validation passed for {next_speaker}")
                    break

            except (json.JSONDecodeError, TypeError) as e:
                key_error = True
                await self._log_message("Invalid ledger format encountered, retrying...")
                raise e
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
        if next_speaker not in self._participant_name_to_topic_type:
            raise ValueError(
                f"Invalid next speaker: {next_speaker} from the ledger, participants are: {self._participant_names}"
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
