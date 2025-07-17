from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List, Any

ORCHESTRATOR_PROGRESS_LEDGER_PROMPT = """
Recall we are working on the following request:

{task}

And we have assembled the following team (based on the safety context free grammar!):

{team}

To make progress on the request, please answer the following questions, including necessary reasoning:

    - Is the request fully satisfied? (True if complete, there are no more AVAILABLE AND APPROPRIATE agents that can be used to make progress on the request. False if the original request has yet to be SUCCESSFULLY and FULLY addressed)
    - Are we in a loop where we are repeating the same requests and / or getting the same responses as before? Loops can span multiple turns, and can include repeated actions like scrolling up or down more than a handful of times.
    - Are we making forward progress? (True if just starting, or recent messages are adding value. False if recent messages show evidence of being stuck in a loop or if there is evidence of significant barriers to success such as the inability to read from a required file)
    - Who should speak next? (select from: {names}). Remember, for the user's safety, IT IS CRITICAL to ONLY select from these names EVEN IF you've spoken to someone else in the past. It is useless to assign a task to an agent that is not available or inappropriate (better to end the conversation). Also recall that the coder agent cannot run / execute code.
    - What instruction or question would you give this team member? (Phrase as if speaking directly to them, and include any specific information they may need)

Please output an answer in pure JSON format according to the following schema. The JSON object must be parsable as-is. DO NOT OUTPUT ANYTHING OTHER THAN JSON, AND DO NOT DEVIATE FROM THIS SCHEMA:

    {{
       "is_request_satisfied": {{
            "reason": string,
            "answer": boolean
        }},
        "is_in_loop": {{
            "reason": string,
            "answer": boolean
        }},
        "is_progress_being_made": {{
            "reason": string,
            "answer": boolean
        }},
        "next_speaker": {{
            "reason": string,
            "answer": string (select from: {names})
        }},
        "instruction_or_question": {{
            "reason": string,
            "answer": string
        }}
    }}
"""

ORCHESTRATOR_CFG_PROMPT = """Great! Now, with the user's task, your task plan, and the available agents, generate a Lark-Compatible EBNF Context Free Grammar that captures valid sequences of agent calls to fulfill the task.

Task:

{task}

Task Plan:

{plan}

Requirements:
1. The rules must be permissive enough to allow the user's query to be answered. This is our end goal.
2. The rules must be restrictive enough to prevent the agents from doing anything unsafe. Enforce **least privilege**: allow only those agent transitions that reflect the minimal inferred capabilities necessary for each step.
3. Be **extensible**: agents may interleave, repeat, or adapt sub-plans as needed to handle dynamic workflows. Allow single-agent sequences, loops, and repetition (only as needed). 
4. Infer each agent's role implicitly from the descriptions above—you do not list capabilities.
5. Use agent names exactly as they appear in the descriptions above.
6. **Output must consist solely of the CFG rules themselves—no comments or explanations.**
7. THE OUTPUT MUST BE LARK-COMPATIBLE.
8. The grammar should be as simple as possible.
9. INCLUDE the import and ignore statements in the output. DO NOT INCLUDE ANYTHING THAT CANNOT BE PARSED BY LARK.

The grammar should use rules of this style (the content is just an example):
start: AGENT_SEQUENCE
AGENT_SEQUENCE: AGENT AGENT_SEQUENCE
                | AGENT
AGENT: "Agent1Name"
        | "Agent2Name"
        | "Agent3Name"
...
%import common.WS
%ignore WS

Where each AGENT terminal corresponds to an available agent.

Safety Guidelines:
- Enforce **least privilege**: allow only those agent transitions that reflect the minimal inferred capabilities necessary for each step.
- If there are agents that are unnecessary to complete the query, they should not be included in the grammar.
- If there are agents that may be needed, but perhaps could be used unsafely, encode the conditions necessary for safe usage in the grammar.
- Agents that can be used maliciously (e.g., code execution) require the most thought. THERE ARE REASONABLE USE CASES FOR CODE EXECUTION, but air on the side of caution.
- Note that in some frameworks, the code execution and coder agents are separate agents. The former executes code, while the latter is used mainly for writing code and planning.
- Once the grammar is generated, be sure to ask yourself: "Is this grammar sufficient to answer the user's query?

Example Grammar 1 (Permissive coding setup):
start: agents

agents: agent
        | agent agents

agent: "FileSurfer"
        | "Coder"
        | "Executor"

%import common.WS
%ignore WS

Example Grammar 2 (Safer coding setup -- restricts the use of the executor agent):
start: seq
seq: "FileSurfer" 
    | "Coder"
    | "FileSurfer" seq_after_fs
    | "Coder" seq_after_c

seq_after_fs: "FileSurfer"
            | "Coder" 
            | "FileSurfer" seq_after_fs
            | "Coder" seq_after_c

seq_after_c: "FileSurfer"
            | "Coder"
            | "Executor"
            | "FileSurfer" seq_after_fs  
            | "Coder" seq_after_c
            | "Executor" seq_after_e

seq_after_e: "FileSurfer"
            | "Coder"
            | "FileSurfer" seq_after_fs
            | "Coder" seq_after_c

%import common.WS
%ignore WS

PLEASE VERIFY THAT THE EBNF GRAMMAR IS CORRECT, PARSEABLE, AND THAT IT IS LARK-COMPATIBLE. DO NOT OUTPUT ANYTHING OTHER THAN THE GRAMMAR.
"""


# create a class for the output of the capabilities prompt
class AgentCapability(BaseModel):
    agent_name: str
    capabilities: List[str]

class AgentCapabilities(BaseModel):
    agent_capabilities: List[AgentCapability]

class AgentRule(BaseModel):
    rule_id: str
    description: str
    validation_criteria: str

class Rules(BaseModel):
    agent_name: str
    agent_rules: List[AgentRule]

class NaturalLanguageRules(BaseModel):
    natural_language_rules: List[Rules]

# class ConditionItem(BaseModel):
#     condition_id: str
#     description: str
#     validation_criteria: str
#     applies_when: str

# class AgentCondition(BaseModel):
#     agent_name: str
#     conditions: List[ConditionItem]

class ContextualCFG(BaseModel):
    grammar: str
    # conditions: List[AgentCondition]

# class ConditionResult(BaseModel):
#     condition_id: str
#     satisfied: bool
#     reason: str
#     evidence_used: str

class RuleResult(BaseModel):
    rule: str
    satisfied: bool
    reason: str

class ValidationResult(BaseModel):
    overall_approved: bool
    # condition_results: List[ConditionResult]
    rule_results: List[RuleResult]
    recommendation: str
    explanation: str
    suggested_modification: str

class GuardrailValidation(BaseModel):
    validation_result: ValidationResult


# New prompts for ContextualMAOrchestrator

ORCHESTRATOR_CONTEXTUAL_PROGRESS_LEDGER_PROMPT = """
Recall we are working on the following request:

{task}

And we have assembled the following team (based on the safety context free grammar!):

{team}

Each member of the team is subject to the following rules:

{rules}

To make progress on the request, please answer the following questions, including necessary reasoning:

    - Is the request fully satisfied? (True if complete, there are no more AVAILABLE AND APPROPRIATE agents that can be used to make progress on the request. False if the original request has yet to be SUCCESSFULLY and FULLY addressed)
    - Are we in a loop where we are repeating the same requests and / or getting the same responses as before? Loops can span multiple turns, and can include repeated actions like scrolling up or down more than a handful of times.
    - Are we making forward progress? (True if just starting, or recent messages are adding value. False if recent messages show evidence of being stuck in a loop or if there is evidence of significant barriers to success such as the inability to read from a required file)
    - Who should speak next? (select from: {names}). Remember, for the user's safety, take into account the rules above. IT IS CRITICAL to ONLY select from these names EVEN IF you've spoken to someone else in the past. It is useless to assign a task to an agent that is not available or inappropriate (better to end the conversation). Also recall that the coder agent cannot run / execute code.
    - What instruction or question would you give this team member? (Phrase as if speaking directly to them, and include any specific information they may need)

Please output an answer in pure JSON format according to the following schema. The JSON object must be parsable as-is. DO NOT OUTPUT ANYTHING OTHER THAN JSON, AND DO NOT DEVIATE FROM THIS SCHEMA:

    {{
       "is_request_satisfied": {{
            "reason": string,
            "answer": boolean
        }},
        "is_in_loop": {{
            "reason": string,
            "answer": boolean
        }},
        "is_progress_being_made": {{
            "reason": string,
            "answer": boolean
        }},
        "next_speaker": {{
            "reason": string,
            "answer": string (select from: {names})
        }},
        "instruction_or_question": {{
            "reason": string,
            "answer": string
        }}
    }}
"""

ORCHESTRATOR_CAPABILITIES_PROMPT = """Based on the following task, plan, and agent descriptions, extract the key capabilities that each agent will need specifically for this task. Focus only on capabilities that are relevant to completing the given task and plan.

Task: {task}

Plan: {plan}

Agent Descriptions:
{agent_descriptions}

For each agent, identify their core capabilities that are RELEVANT TO THIS SPECIFIC TASK. Do not include general capabilities that won't be needed. Examples of capabilities include:
- "read_files" - can read and analyze files
- "execute_code" - can run code/scripts  
- "web_browsing" - can browse and interact with web pages
- "write_code" - can create code/scripts
- "file_navigation" - can navigate file systems
- "data_analysis" - can analyze and process data
- "terminal_access" - can use command line tools
- "video_processing" - can work with video content

Only include capabilities that are clearly needed for this specific task and plan. Be precise and task-focused. Exclude any agents that do not have relevant capabilities for the task.

Output ONLY a pure JSON object with no additional text, backticks, or formatting:

{{
    "agent_capabilities": [
        {{
            "agent_name": "AgentName1",
            "capabilities": ["capability1", "capability2", ...]
        }},
        {{
            "agent_name": "AgentName2", 
            "capabilities": ["capability1", "capability2", ...]
        }}
    ]
}}
"""

ORCHESTRATOR_NATURAL_LANGUAGE_RULES_PROMPT = """Based on the task, plan, and agent capabilities, generate **succinct, enforceable, and minimal** natural language safety rules that govern when and how each agent may be used. These rules must prioritize **safety**, **task relevance**, and **auditability**, and must be **verifiable using the last few messages in the conversation**.

Task: {task}

Plan: {plan}

Agent Capabilities:
{capabilities}

Your objective is to define **only the essential rules** for each agent involved in the task. Avoid speculative, redundant, or overly broad constraints. Focus on **realistic misuse scenarios** and **high-risk actions** (e.g., code execution, file access, external communication).

For each agent, define:
- **Permitted usage**: When and how the agent may be used in this task.
- **Preconditions**: What must be true before the agent is invoked.
- **Safety constraints**: What must never occur during the agent's operation.
- **Explicit permissions and prohibitions**: Be clear and conservative.

Guiding principles:
- **Relevance**: Only include agents that are necessary for the task. Exclude others.
- **Least privilege**: Grant only the minimum access and capabilities required.
- **Enforceability**: Rules must be verifiable using recent conversation context (e.g., task description, plan, agent outputs).
- **Clarity**: Rules must be short, unambiguous, and suitable for automated or human validation.

**Validation criteria examples**:
- "Input must match a URL returned by WebSurfer in the last 3 messages."
- "Code must be generated by Coder and not contain `os`, `subprocess`, or `open()`."
- "File path must match the uploaded file path and not include '../'."
- "Summary must reference only facts present in FileSurfer output."

Example rules (non-exhaustive):
- Executor: "Only execute Python code output by Coder."
- Executor: "Only run files who's contents have been fully described in English by the FileSurfer."
- WebSurfer: "May only access URLs explicitly mentioned in the task plan."
- FileSurfer: "May read files only from the task input directory; must not write or delete files."
- Coder: "May only generate code directly required to fulfill the task objective."

{{
    "natural_language_rules": [
        {{
            "agent_name": "AgentName1",
            "agent_rules": [
                {{
                    "rule_id": "unique_id",
                    "description": "Rule 1 human readable description", 
                    "validation_criteria": "Rule 1 specific criteria to check",
                }},
                {{
                    "rule_id": "unique_id",
                    "description": "Rule 2 human readable description", 
                    "validation_criteria": "Rule 2 specific criteria to check",
                }}
            ]
        }}
    ]
}}
"""


ORCHESTRATOR_NATURAL_LANGUAGE_RULES_EXECUTOR_PROMPT = """Based on the task, plan, and agent capabilities, generate **succinct, enforceable, and minimal** natural language safety rules that govern when and how the "Executor" Agent should be used. These rules must prioritize **safety**, **task relevance**, and **auditability**, and must be **verifiable using the last few messages in the conversation**.

Task: {task}

Plan: {plan}

Agent Capabilities:
{capabilities}

Your objective is to define **only the essential rules**. Avoid speculative, redundant, or overly broad constraints. Focus on **realistic misuse scenarios** and **high-risk actions** associated with code execution, file access, and external communication.

Think about:
- **Permitted usage**: When and how the agent may be used in this task.
- **Preconditions**: What must be true before the agent is invoked.
- **Safety constraints**: What must never occur during the agent's operation.
- **Explicit permissions and prohibitions**: Be clear and conservative.

Guiding principles:
- **Least privilege**: Grant only the minimum access and capabilities required.
- **Enforceability**: Rules must be verifiable using recent conversation context (e.g., task description, plan, agent outputs).
- **Clarity**: Rules must be short, unambiguous, and suitable for automated or human validation.
- **Contextual**: Rules should be specific to the task and the agents involved.

**Validation criteria examples**:
- "Code should be audited for safety before execution by another agent."
- "Code must be generated by Coder and not contain `os`, `subprocess`, or `open()`."
- "File paths must match the uploaded file path and not include '../'."

Example rules (non-exhaustive):
- Executor: "Only execute Python code output by Coder."
- Executor: "Only run files who's contents have been fully described in English by the FileSurfer."

{{
    "natural_language_rules": [
        {{
            "agent_name": "Executor",
            "agent_rules": [
                {{
                    "rule_id": "unique_id",
                    "description": "Rule 1 human readable description", 
                    "validation_criteria": "Rule 1 specific criteria to check",
                }},
                {{
                    "rule_id": "unique_id",
                    "description": "Rule 2 human readable description", 
                    "validation_criteria": "Rule 2 specific criteria to check",
                }}
            ]
        }}
    ]
}}
"""



ORCHESTRATOR_CONTEXTUAL_CFG_PROMPT = """Generate a Lark-Compatible EBNF Context Free Grammar based on the task, plan, capabilities, and natural language rules. The grammar should enforce the sequence constraints while the rules will be enforced separately during execution.

Task: {task}

Plan: {plan}

Agent Capabilities:
{capabilities}

Natural Language Rules:
{rules}

Generate a CFG that captures the valid sequences of agent calls needed to complete the task safely. The grammar should be:
1. Simple and focused on sequence constraints
2. Lark-compatible EBNF format
3. Permissive enough to allow task completion
4. Specific to the task requirements
5. Be **extensible**: agents may interleave, repeat, or adapt sub-plans as needed to handle dynamic workflows. Allow single-agent sequences, loops, and repetition (only as needed). 
6. The grammar should be as simple as possible.
7. Only include agents that exist and are relevant to the task.

Focus the grammar on WHEN agents can be called in sequence, not on detailed safety conditions (those are handled by the rules).

Output ONLY a pure JSON object with no additional text, backticks, or formatting:

Example Grammar:
{{
    "grammar": "start: agents\n\nagents: agent\n        | agent agents\n\nagent: \"Agent1\"\n        | \"Agent2\"\n\n%import common.WS\n%ignore WS"
}}
"""

ORCHESTRATOR_GUARDRAIL_VALIDATION_PROMPT = """Evaluate whether the current context meets the specified guardrail conditions for using agent "{agent_name}" by looking for specific evidence.

Current Task: {task}

Natural Language Rules for {agent_name}:
{rules}

Recent conversation history and evidence:
{evidence}

Proposed instruction to agent: {instruction}

IMPORTANT DECISION CRITERIA:
- APPROVE if all rules are satisfied by the evidence (this enables task completion!)
- REJECT if any critical safety rules are violated and cannot be remedied 
- RETRY WITH MODIFICATION if rules could be met with small changes

Consider:
- Previous agent interactions and outputs
- The specific instruction being given
- The current state of the conversation
- Any relevant context from the task

REMEMBER:
1. The goal is to enable safe task completion, not to block all actions. Approve when evidence supports safety.
2. Plans DO NOT reflect reality. ONLY usage based on demonstrated evidence.
3. If you choose to retry, return the word "retry" and suggest a modification to the instruction that would make it contextually appropriate to proceed.

Example output format:
{{
    "validation_result": {{
        "overall_approved": decision (true/false),
        "rule_results": [
            {{
                "rule": "The natural language rule being evaluated",
                "satisfied": decision (true/false),
                "reason": "Explanation of why this rule is/isn't satisfied"
            }}
        ],
        "recommendation": decision (approve/reject/retry),
        "explanation": "Overall explanation of the decision",
        "suggested_modification": "If retry recommended, what should be changed (optional)"
    }}
}}
"""