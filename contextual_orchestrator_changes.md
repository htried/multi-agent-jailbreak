# ContextualMAOrchestrator Improvements

## Changes Made

### 1. Task-Specific Capabilities Generation
- **Before**: Generated general capabilities for each agent regardless of the task
- **After**: Generates capabilities specific to the current task and plan
- Updated `ORCHESTRATOR_CAPABILITIES_PROMPT` to include task and plan context
- Modified `_extract_agent_capabilities()` to use task-specific prompting

### 2. New Natural Language Rules Generation Step
- **Added**: New `_generate_natural_language_rules()` method
- **Added**: `ORCHESTRATOR_NATURAL_LANGUAGE_RULES_PROMPT` for generating human-readable safety rules
- Rules are generated based on the extracted task-specific capabilities
- Rules focus on when/how agents should be used safely

### 3. Updated Workflow
The new workflow is now:
1. Extract task-specific capabilities 
2. Generate natural language rules based on capabilities
3. Generate CFG based on capabilities and rules  
4. Enforce both CFG and natural language rules during execution

### 4. Enhanced CFG Generation
- Updated `_generate_contextual_cfg()` to use both capabilities and natural language rules
- CFG now focuses on sequence constraints while rules handle detailed safety conditions
- More intelligent grammar generation based on task context

### 5. JSON Response Cleaning
- **Added**: `_clean_json_response()` method to handle model responses with backticks and "json" labels
- Removes markdown code block formatting (`\`\`\`json` and `\`\`\``)
- Cleans up any remaining backticks
- Applied to all JSON parsing operations

### 6. Enhanced Guardrail Validation
- Updated `_validate_guardrails()` to check both structured conditions AND natural language rules
- More comprehensive safety validation
- Better error handling and logging for JSON parsing issues

### 7. Improved Prompts
- All prompts now explicitly request "pure JSON object with no additional text, backticks, or formatting"
- Task-specific context included where relevant
- Clearer instructions for model responses

## Key Benefits

1. **More Relevant Capabilities**: Only extracts capabilities needed for the specific task
2. **Human-Readable Rules**: Natural language rules are easier to understand and validate
3. **Better Safety**: Dual enforcement of CFG constraints and natural language rules
4. **Robust JSON Parsing**: Handles various model response formats gracefully
5. **Task-Focused**: All components are now tailored to the specific task context

## Example Workflow

For a task like "Analyze a Python file and suggest improvements":

1. **Capabilities**: FileSurfer gets "read_files", Coder gets "code_analysis", "write_code" 
2. **Rules**: "FileSurfer can only read .py files", "Coder must analyze before suggesting changes"
3. **CFG**: Simple sequence allowing FileSurfer → Coder interactions
4. **Enforcement**: Both sequence (CFG) and safety conditions (rules) are validated

This approach provides more intelligent, task-specific constraints while maintaining strong safety guarantees.