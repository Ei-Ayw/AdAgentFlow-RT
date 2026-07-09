#!/usr/bin/env bash
# 用法: source scripts/use_mock_llm.sh   或   bash scripts/use_mock_llm.sh 'python ...'
# 回退到本地 mock 模式（零网络、零成本）

if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  export USE_MOCK_LLM=true
  unset ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
  echo "🧪 Mock LLM 模式已开启（source）"
else
  export USE_MOCK_LLM=true
  unset ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
  CMD="$@"
  echo "🧪 Mock LLM 模式已开启"
  if [ -n "$CMD" ]; then
    bash -c "$CMD"
  fi
fi
