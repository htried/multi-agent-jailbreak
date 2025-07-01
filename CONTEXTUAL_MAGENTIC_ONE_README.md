# ContextualMAOrchestrator: Capability-Based Guardrails for Multi-Agent Systems

## Overview

The ContextualMAOrchestrator extends the MagenticOne architecture with sophisticated capability-based guardrails and contextual constraint generation. This system provides enhanced safety while maintaining the flexibility needed for complex task execution.

## Key Features

### 1. **Automatic Capability Extraction**
- Analyzes agent descriptions to identify core capabilities
- Creates structured capability profiles for each agent
- Examples: `execute_code`, `read_files`, `web_browsing`, `terminal_access`

### 2. **Contextual CFG Generation**
- Generates Context-Free Grammars tailored to specific tasks
- Includes safety conditions based on agent capabilities
- Balances functionality requirements with security constraints

### 3. **Real-Time Guardrail Validation**
- Validates safety conditions before agent execution
- Uses conversation history as evidence for decision-making
- Provides detailed reasoning for all safety decisions

### 4. **Intelligent Failure Handling**
- **Option 1**: End conversation with detailed explanation
- **Option 2**: Switch to alternative agent
- **Option 3**: Retry with modifications (limited to one attempt)
- Always explains WHY guardrails were triggered

## Architecture

```
ContextualMAOrchestrator
├── Capability Extraction
│   ├── Parse agent descriptions
│   ├── Identify core capabilities
│   └── Create capability profiles
├── Contextual CFG Generation
│   ├── Analyze task requirements
│   ├── Generate grammar rules
│   └── Add safety conditions
├── Guardrail Validation
│   ├── Check conditions before execution
│   ├── Evaluate conversation evidence
│   └── Make safety decisions
└── Failure Handling
    ├── Detailed explanations
    ├── Alternative strategies
    └── Retry mechanisms
```

## How It Works

### Phase 1: Initialization
1. **Extract Facts**: Analyze the task and gather relevant information
2. **Create Plan**: Generate execution strategy based on available agents
3. **Extract Capabilities**: Identify what each agent can do
4. **Generate CFG**: Create contextual grammar with safety conditions

### Phase 2: Execution with Guardrails
1. **Speaker Selection**: Choose next agent based on CFG constraints
2. **Guardrail Check**: Validate safety conditions for selected agent
3. **Evidence Evaluation**: Analyze conversation history for compliance
4. **Decision Making**: Approve, reject, or request modifications
5. **Execution**: Proceed if guardrails pass, handle failures otherwise

## Example Safety Conditions

### For Executor Agent:
```json
{
  "only_python_scripts": {
    "description": "Only execute Python scripts, not shell commands",
    "validation_criteria": "Check that code uses Python syntax and no shell escapes",
    "applies_when": "Before any code execution"
  },
  "safe_file_operations": {
    "description": "Restrict file operations to safe directories",
    "validation_criteria": "Ensure no access to system directories or sensitive files",
    "applies_when": "When file I/O operations are requested"
  },
  "verified_code": {
    "description": "Code must be reviewed by Coder agent first",
    "validation_criteria": "Previous message from Coder agent contains code review",
    "applies_when": "Before executing any user-generated code"
  }
}
```

### For WebSurfer Agent:
```json
{
  "approved_domains": {
    "description": "Only access specified or reputable websites",
    "validation_criteria": "URL must be in approved list or match safe patterns",
    "applies_when": "Before any web navigation"
  },
  "no_downloads": {
    "description": "Prevent file downloads",
    "validation_criteria": "No download commands or file save operations",
    "applies_when": "During web browsing activities"
  },
  "read_only_browsing": {
    "description": "No form submissions or uploads",
    "validation_criteria": "Only GET requests, no POST/PUT operations",
    "applies_when": "For all web interactions"
  }
}
```

## Usage Examples

### Basic Usage
```python
from multiagents.contextual_magentic_one import ContextualMagenticOne
from autogen_ext.models.openai import OpenAIChatCompletionClient

client = OpenAIChatCompletionClient(model="gpt-4o")
team = ContextualMagenticOne(client=client)

# The system will automatically:
# 1. Extract agent capabilities
# 2. Generate contextual safety conditions
# 3. Validate guardrails during execution
result = await team.run_stream(task="Your task here")
```

### With Web Browsing
```python
team = ContextualMagenticOne(
    client=client,
    include_web_surfer=True
)
# Additional guardrails for web browsing will be automatically generated
```

### Human-in-the-Loop Mode
```python
team = ContextualMagenticOne(
    client=client,
    hil_mode=True
)
# Human oversight for sensitive operations
```

## Safety Features

### Least Privilege Principle
- Only allows minimum capabilities needed for the task
- Restricts agent transitions based on necessity
- Prevents unnecessary access to sensitive capabilities

### Context-Aware Conditions
- Safety rules adapt to the specific task
- Considers task requirements when setting restrictions
- Balances functionality with security needs

### Evidence-Based Validation
- Uses conversation history to validate conditions
- Checks for proper preparation before risky operations
- Requires appropriate context for sensitive actions

### Transparent Decision Making
- Provides detailed explanations for all safety decisions
- Shows which conditions passed or failed
- Explains the evidence used in decision-making

## Configuration Options

### Agent Selection
```python
ContextualMagenticOne(
    client=client,
    include_web_surfer=True,    # Enable web browsing capabilities
    include_video_surfer=True,  # Enable video processing
    hil_mode=True,             # Human-in-the-loop oversight
)
```

### Customization Parameters
```python
# The orchestrator supports all standard MagenticOne parameters
# plus enhanced safety features are automatically applied
```

## Error Handling

### Guardrail Failures
When guardrails fail, the system provides:
1. **Detailed Explanation**: Why the guardrail was triggered
2. **Evidence Summary**: What evidence was evaluated
3. **Suggested Actions**: How to proceed safely
4. **Alternative Paths**: Other agents or approaches to try

### Example Failure Response
```
Guardrail validation failed for Executor:
- Condition 'verified_code' not satisfied
- Reason: No prior code review found in conversation history
- Evidence: Last 10 messages analyzed, no Coder agent output found
- Suggestion: Have Coder agent review the code first
- Alternative: Switch to FileSurfer for analysis tasks
```

## Best Practices

### 1. Task Design
- Be specific about requirements and constraints
- Mention any security or safety concerns explicitly
- Provide context about the environment and data sensitivity

### 2. Monitoring
- Review generated guardrails for appropriateness
- Monitor logs for guardrail activations
- Understand why certain restrictions are applied

### 3. Human Oversight
- Use HIL mode for sensitive operations
- Review and approve guardrail decisions when needed
- Provide additional context when guardrails are too restrictive

### 4. Iterative Refinement
- Adjust task descriptions based on guardrail feedback
- Learn from guardrail failures to improve task specifications
- Use alternative approaches when suggested by the system

## Comparison with Standard MagenticOne

| Feature | MagenticOne | ContextualMagenticOne |
|---------|-------------|----------------------|
| Agent Coordination | ✅ | ✅ |
| Task Planning | ✅ | ✅ |
| Safety Constraints | ❌ | ✅ Capability-based |
| Contextual Rules | ❌ | ✅ Task-specific CFG |
| Guardrail Validation | ❌ | ✅ Real-time checking |
| Failure Explanation | ❌ | ✅ Detailed reasoning |
| Alternative Strategies | ❌ | ✅ Intelligent fallbacks |

## Integration

The ContextualMAOrchestrator is designed as a drop-in replacement for the standard MagenticOneOrchestrator:

```python
# Standard MagenticOne
from autogen_agentchat.teams import MagenticOneGroupChat

# Enhanced with contextual guardrails
from multiagents.contextual_magentic_one import ContextualMagenticOne
```

All existing MagenticOne features are preserved while adding the new safety capabilities.

## Future Enhancements

### Planned Features
1. **Custom Guardrail Templates**: Pre-defined safety templates for common scenarios
2. **Learning from Failures**: Improve guardrail generation based on past failures
3. **User-Defined Conditions**: Allow manual specification of additional safety rules
4. **Risk Assessment**: Automatic risk scoring for different agent combinations
5. **Audit Logging**: Comprehensive logging of all safety decisions

### Research Directions
1. **Adaptive Guardrails**: Dynamic adjustment based on task progress
2. **Multi-Level Security**: Different security levels for different task types
3. **Collaborative Safety**: Agents working together to ensure safety
4. **Formal Verification**: Mathematical proof of safety properties

## Conclusion

The ContextualMAOrchestrator represents a significant advancement in multi-agent system safety. By automatically generating and enforcing capability-based guardrails, it provides the security needed for production deployments while maintaining the flexibility that makes MagenticOne powerful.

The system's transparent decision-making and intelligent failure handling ensure that users understand and can work with the safety mechanisms rather than being blocked by them. This approach makes multi-agent systems safer without sacrificing their utility.