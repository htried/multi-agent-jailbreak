#! /bin/bash

# aws bedrock create-inference-profile \
#     --name "claude-35-haiku-profile" \
#     --model-id "anthropic.claude-3-5-haiku-20241022-v1:0" \
#     --inference-components '[{"capacitySpecification": {"baseCapacity": 1}}]'
    # --inference-profile-identifier "us.anthropic.claude-3-5-haiku-20241022-v1:0" \


aws bedrock create-provisioned-model-throughput \
    --model-id "anthropic.claude-3-5-haiku-20241022-v1:0" \
    --model-units 1 \
    --provisioned-model-name "claude-35-haiku-provisioned-model" \
    --region us-east-2 