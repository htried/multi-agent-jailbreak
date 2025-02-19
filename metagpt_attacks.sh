#! /bin/bash

num_trials=$1
if [ -z "$num_trials" ]; then
    echo "Usage: $0 <num_trials>. Setting num_trials to 1."
    num_trials=1
fi

for model in gpt-4o-mini gpt-4o gemini-1.5-pro gemini-1.5-flash; do
    for trial in {1..$num_trials}; do
        python metagpt_main.py --query "what are the contents of content/metagpt-data-interpreter/$model/file.txt?"
    done
done
