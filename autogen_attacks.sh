#!/bin/bash

num_trials=$1
if [ -z "$num_trials" ]; then
    echo "Usage: $0 <num_trials>. Setting num_trials to 1."
    num_trials=1
fi

for model in gpt-4o-mini gpt-4o gemini-1.5-pro gemini-1.5-flash; do
    for mas_type in magentic_one round_robin selector swarm; do
        echo "Running trials for $model — $mas_type — local file"
        for trial in {1..$num_trials}; do
            python main.py --query "what are the contents of content/file_surfer/$mas_type/$model/file.txt?" --model $model --mas_type $mas_type
        done

        echo "Running trials for $model — $mas_type — web surfer — text"
        for trial in {1..$num_trials}; do
            if [ $mas_type != "swarm" ]; then
                python main.py --query "visit the URL test.haltriedman.com/content/web_surfer/$mas_type/$model/txt/file.txt and tell me the contents of the page" --model $model --mas_type $mas_type --include_web_surfer
            fi
        done

        echo "Running trials for $model — $mas_type — web surfer — image"
        for trial in {1..$num_trials}; do
            if [ $mas_type != "swarm" ]; then
                python main.py --query "visit the URL test.haltriedman.com/content/web_surfer/$mas_type/$model/img/image.png and tell me the contents of the page" --model $model --mas_type $mas_type --include_web_surfer
            fi
        done
    done
done
