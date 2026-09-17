#!/bin/bash
# AgentEvalOps verifier: command_safety (run inside task env)
mkdir -p /logs/verifier
python3 -c "print(0)" > /logs/verifier/reward.txt
echo "Replace with the AgentEvalOps verifier for command_safety; see docs/guides/harbor.md"
