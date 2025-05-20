# Multi-Agent Systems Execute Arbitrary Malicious Code

Arxiv: https://arxiv.org/abs/2503.12188

We demonstrate a novel prompt-injection method for multi-agent jailbreaking that we call "control-flow hijacking".
In this method, a resource that an individual agent in a multi-agent system (MAS) is directed to access contains a false error message which directs the MAS to perform an action.
We show that this method can be used to jailbreak a MAS with a single injected prompt, and that it is effective across several models, MAS types, injection modalities, network topologies, and other configurations.

Given a set of agents with file-system access and the ability to execute code, are able to use this method to conduct arbitrary code execution on Microsoft's Magentic One MAS, MetaGPT's Data Interpreter, and CrewAI (details on running CrewAI experiments to come soon).

## Setup

```bash
# Set up the environments needed for running the attacks
./setup.sh

# Generate text-based template attacks
python templates/generate_template_attacks.py --ip <insert your IP address here, default is 127.0.0.1>

# For video surfer attacks you will need to install moviepy (might cause some pip errors)
./templates/generate_video_inputs.sh
```

Also ensure that you have a `.env` file containing your AI system API keys.

In a separate terminal (potentially on a remote server), run the socket server (this is the server that will receive the attacks, and it will hang):

```bash
python socket_recipient.py

# OR, to run this in the background:
nohup python socket_recipient.py &
```

## Running the Autogen-based attacks

NOTE: These multi-agent systems will be running attacks on your local machine. Proceed with caution.

```bash
source autogen_venv/bin/activate
./autogen_attacks.sh <num_trials> (defaults to 1)
deactivate
```

## Running the Metagpt-based attacks

```bash
source metagpt_venv/bin/activate
./metagpt_attacks.sh <num_trials> (defaults to 1)
deactivate
```

Note: If you want to use alternative attacks, you may have to make small configuration changes to `{metagpt,autogen}_attacks.sh`. Specifically, you will have to change the `url`, `content_dir`, and `ip` arguments.

