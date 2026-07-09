#!/usr/bin/env bash
# 用法（任选其一）：
#   ANTHROPIC_AUTH_TOKEN=xxx bash scripts/use_real_llm.sh
#   ANTHROPIC_AUTH_TOKEN=xxx source scripts/use_real_llm.sh
# 之后所有 python 脚本自动调用 minimax 真实 LLM

if [ -z "$ANTHROPIC_AUTH_TOKEN" ]; then
  echo "❌ ANTHROPIC_AUTH_TOKEN 未设置"
  echo "👉 请: export ANTHROPIC_AUTH_TOKEN=你的真实key"
  echo "   然后: source scripts/use_real_llm.sh"
  echo "  或者一行搞定:  ANTHROPIC_AUTH_TOKEN=xxx bash scripts/use_real_llm.sh"
  exit 1
fi

# 如果 source 调用，1 表示激活
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  export ANTHROPIC_BASE_URL="https://api.minimaxi.com"
  export ANTHROPIC_DEFAULT_HAIKU_MODEL="MiniMax-M3"
  export ANTHROPIC_DEFAULT_SONNET_MODEL="MiniMax-M3"
  export USE_MOCK_LLM=false
  echo "✅ 真实 LLM 模式已开启（source）"
  echo "   base  : $ANTHROPIC_BASE_URL"
  echo "   model : $ANTHROPIC_DEFAULT_HAIKU_MODEL"
  echo "👉 直接跑 python scripts/demo_local.py / load_test.py"
else
  # 直接 bash 调用，导出给子进程使用
  export ANTHROPIC_BASE_URL="https://api.minimaxi.com"
  export ANTHROPIC_DEFAULT_HAIKU_MODEL="MiniMax-M3"
  export ANTHROPIC_DEFAULT_SONNET_MODEL="MiniMax-M3"
  export USE_MOCK_LLM=false
  CMD="$@"
  echo "✅ 真实 LLM 模式已开启"
  echo "   base  : $ANTHROPIC_BASE_URL"
  echo "   model : $ANTHROPIC_DEFAULT_HAIKU_MODEL"
  if [ -n "$CMD" ]; then
    echo "🚀 运行: $CMD"
    bash -c "$CMD"
  else
    echo "👉 用法: ANTHROPIC_AUTH_TOKEN=xxx bash scripts/use_real_llm.sh 'python scripts/demo_local.py'"
  fi
fi
