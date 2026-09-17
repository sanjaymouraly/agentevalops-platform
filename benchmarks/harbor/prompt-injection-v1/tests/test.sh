#!/bin/bash
# AgentEvalOps verifier: prompt_injection (run inside task env)
mkdir -p /logs/verifier
python3 -c "print(0)" > /logs/verifier/reward.txt
echo "Replace with the AgentEvalOps verifier for prompt_injection; see docs/guides/harbor.md"
