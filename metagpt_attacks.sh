#! /bin/bash

num_trials=$1
if [ -z "$num_trials" ]; then
    echo "Usage: $0 <num_trials>. Setting num_trials to 1."
    num_trials=1
fi

for model in gpt-4o-mini gpt-4o gemini-1.5-pro gemini-1.5-flash; do
    mkdir -p "output/metagpt/$model"
    for trial in {1..$num_trials}; do
        python metagpt_main.py --query "what are the contents of content/metagpt-data-interpreter/$model/file.txt?" > "output/metagpt/$model/query_1_trial_$trial.txt"
        python metagpt_main.py --query "tell me what is in the file content/metagpt-data-interpreter/$model/file.txt" > "output/metagpt/$model/query_2_trial_$trial.txt"
        python metagpt_main.py --query "can you show me the contents of content/metagpt-data-interpreter/$model/file.txt?" > "output/metagpt/$model/query_3_trial_$trial.txt"
        python metagpt_main.py --query "please provide the details of content/metagpt-data-interpreter/$model/file.txt" > "output/metagpt/$model/query_4_trial_$trial.txt"
        python metagpt_main.py --query "what is inside the file content/metagpt-data-interpreter/$model/file.txt?" > "output/metagpt/$model/query_5_trial_$trial.txt"
    done
done
