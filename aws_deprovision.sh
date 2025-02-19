#! /bin/bash

aws bedrock delete-provisioned-model-throughput \
    --inference-profile-identifier "us.anthropic.claude-3-5-haiku-20241022-v1:0" \
    --model-id "anthropic.claude-3-5-haiku-20241022-v1:0" \
    --region us-east-2

aws bedrock delete-inference-profile \
    --inference-profile-identifier "us.anthropic.claude-3-5-haiku-20241022-v1:0" \
    --region us-east-2