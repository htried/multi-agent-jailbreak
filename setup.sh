#! /bin/bash

# Create autogen venv
python -m venv autogen_venv
source autogen_venv/bin/activate

# Install autogen
pip install -r autogen_requirements.txt
deactivate

# Create metagpt venv
python -m venv metagpt_venv
source metagpt_venv/bin/activate

git clone https://github.com/geekan/MetaGPT.git
pip install -e MetaGPT
pip install -r metagpt_requirements.txt

if [ ! -f ~/.metagpt/config2.yaml ]; then
    metagpt --init-config
    echo "Please navigate to ~/.metagpt/config2.yaml and fill in your OpenAI, Gemini, and other API tokens."
fi

deactivate

echo "Setup complete. You can now activate the autogen venv with 'source autogen_venv/bin/activate' and the metagpt venv with 'source metagpt_venv/bin/activate'."
echo "To run autogen attacks, activate the autogen venv and run './autogen_attacks.sh <num_trials> (defaults to 1)'"
echo "To run metagpt attacks, activate the metagpt venv and run './metagpt_attacks.sh <num_trials> (defaults to 1)'"
echo "See the README for more details."