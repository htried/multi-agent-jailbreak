# Ensuring Contextual Control and Information Flow in Multi-Agent Systems

Code is based off of code for this paper: https://arxiv.org/abs/2503.12188.

This repo contains code for contextual flow defenses against control flow hijacking (the above paper) and IPI attacks more generally. For more information, see the accompanying docs/ folder.

The repo contains two attack scenarios: (1) a coding scenario based off of the original paper, and (2) a computer-use scenario. Each scenario has tasks associated with them (as defined in the `create_experiments_*.py` files).

There are a total of four attack goals: Reverse Shell (Coding, Control Flow Hijacking), Email Redirect (CUA, Control Flow Hijacking), Email Leakage (CUA, Accidental), Data Tainting (CUA, Accidental). In addition we evaluate on three traditional IPI frameworks: Vanilla, AgentDojo, and InjecAgent. The attack files will be placed in `content/` after the Setup step (below).

The repo also contains three defense settings: `magentic` (default MagenticOne), `contextual` (our defense), and `llama` (LlamaFirewall, a baseline).

## Setup

To begin, start by preparing your environment and the attack files. Attack files are generated or copied to ensure that nothing changes between agent rollouts.

```bash
# Set up the environments needed for running the attacks
./setup.sh

# Generate coding attacks
python templates/generate_template_attacks.py --ip <insert your IP address here, default is 127.0.0.1>

# Prepare CUA attacks
cp -rf content/cua_backup/* content/

# For video surfer attacks you will need to install moviepy (might cause some pip errors)
./templates/generate_video_inputs.sh
```

Also ensure that you have a `.env` file containing your AI system API keys.

Optionally, in a separate terminal (potentially on a remote server), you can run a socket server to monitor reverse shell creation (this is the server that will receive the attacks, and it will hang):

```bash
python socket_recipient.py

# OR, to run this in the background:
nohup python socket_recipient.py &
```

## Running an attack

NOTE: These multi-agent systems will be running attacks on your local machine. Proceed with caution.

To run our example attack:
```bash
source autogen_venv/bin/activate

# For cua attacks
cp -rf content/cua_backup/* content/

# For coding attacks
python templates/generate_template_attacks.py --ip <IP>

python quick_comparison.py --scenario {cua, coding} --method {contextual, llama, magentic}
```

For more comprehensive eval, please look at `create_experiment_*.py`!
