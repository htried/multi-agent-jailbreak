#! /bin/bash

# Create autogen venv
python3.12 -m venv autogen_venv
source autogen_venv/bin/activate

# Install autogen
pip install -U pip
pip install -r autogen_requirements.txt
playwright install
deactivate

echo "Setup complete. You can now activate the autogen venv with 'source autogen_venv/bin/activate' and the metagpt venv with 'source metagpt_venv/bin/activate'."
echo "To run autogen attacks, activate the autogen venv and run './autogen_attacks.sh <num_trials> (defaults to 1)'"
echo "See the README for more details."