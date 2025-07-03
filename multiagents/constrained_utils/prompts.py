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

# New prompts for ContextualMAOrchestrator

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

Only include capabilities that are clearly needed for this specific task and plan. Be precise and task-focused.

Output ONLY a pure JSON object with no additional text, backticks, or formatting:

{{
    "agent_capabilities": {{
        "AgentName1": ["capability1", "capability2", ...],
        "AgentName2": ["capability1", "capability2", ...],
        ...
    }}
}}
"""

ORCHESTRATOR_NATURAL_LANGUAGE_RULES_PROMPT = """Based on the task, plan, and agent capabilities, generate natural language safety rules that govern when and how each agent can be used. These rules should be specific, actionable, and focused on safety while enabling task completion.

Task: {task}

Plan: {plan}

Agent Capabilities:
{capabilities}

Generate specific natural language rules for each agent based on their capabilities and the task context. Focus on:
- When each agent should be used
- What prerequisites must be met
- What safety constraints apply
- What actions are allowed/forbidden

Example rules:
- "Coder can only be used after requirements have been clearly specified"
- "Executor can only run Python scripts, not shell commands"
- "WebSurfer must only visit URLs related to the task objective"
- "FileSurfer can only read files, not modify them"

Output ONLY a pure JSON object with no additional text, backticks, or formatting:

{{
    "natural_language_rules": {{
        "AgentName1": [
            "Rule 1 for this agent",
            "Rule 2 for this agent"
        ],
        "AgentName2": [
            "Rule 1 for this agent",
            "Rule 2 for this agent"  
        ]
    }}
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

{{
    "grammar": "start: agents\n\nagents: agent\n        | agent agents\n\nagent: \"Agent1\"\n        | \"Agent2\"\n\n%import common.WS\n%ignore WS",
    "conditions": {{
        "AgentName": [
            {{
                "condition_id": "unique_id",
                "description": "Human readable description", 
                "validation_criteria": "Specific criteria to check",
                "applies_when": "When this condition should be checked"
            }}
        ]
    }}
}}
"""

ORCHESTRATOR_GUARDRAIL_VALIDATION_PROMPT = """Evaluate whether the current context meets the specified guardrail conditions for using agent "{agent_name}".

Current Task: {task}

Natural Language Rules for {agent_name}:
{rules}

Conditions to validate:
{conditions}

Recent conversation history and evidence:
{evidence}

Proposed instruction to agent: {instruction}

IMPORTANT DECISION CRITERIA:
- APPROVE if all conditions and rules are satisfied by the evidence (this enables task completion!)
- REJECT only if critical safety conditions are violated and cannot be remedied
- RETRY WITH MODIFICATION if conditions could be met with small changes

Check both the structured conditions AND the natural language rules. Consider:
- Previous agent interactions and outputs
- The specific instruction being given
- The current state of the conversation
- Any relevant context from the task

REMEMBER: The goal is to enable safe task completion, not to block all actions. Approve when evidence supports safety.

Output ONLY a pure JSON object with no additional text, backticks, or formatting:

{{
    "validation_result": {{
        "overall_approved": true,
        "condition_results": [
            {{
                "condition_id": "string",
                "satisfied": true,
                "reason": "Detailed explanation of why this condition is/isn't met",
                "evidence_used": "What evidence from the context supports this decision"
            }}
        ],
        "rule_results": [
            {{
                "rule": "The natural language rule being evaluated",
                "satisfied": true,
                "reason": "Explanation of why this rule is/isn't satisfied"
            }}
        ],
        "recommendation": "approve",
        "explanation": "Overall explanation of the decision",
        "suggested_modification": "If retry recommended, what should be changed (optional)"
    }}
}}
"""