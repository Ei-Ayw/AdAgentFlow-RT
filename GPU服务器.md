ssh -p 30421 root@connect.westd.seetacloud.com 
ephs5nm/WHkc
 已经部署了qwen服务：
 Qwen3-8B 模型已通过 vLLM 在 0.0.0.0:8000 启动，对外提供 OpenAI 兼容接口。
  
  服务信息
  
  ┌────────────┬───────────────────────────────────────────────────────────────┐
  │    项目    │                              值                               │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 模型       │ Qwen3-8B（Qwen3-8B-Instruct，本地缓存）                       │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 推理引擎   │ vLLM 0.23.0                                                   │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 后端       │ PyTorch + eager 模式（绕过 FlashInfer sampler，详见下方备注） │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 监听地址   │ http://0.0.0.0:8000                                           │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 上下文长度 │ 8192 tokens                                                   │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 数据类型   │ bfloat16                                                      │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 显存占用   │ ~88 GB / 96 GB                                                │
  ├────────────┼───────────────────────────────────────────────────────────────┤
  │ 健康检查   │ GET /health                                                   │
  └────────────┴───────────────────────────────────────────────────────────────┘

  调用接口

  Chat 接口（推荐）
  curl http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
      "model": "Qwen3-8B",
      "messages": [{"role": "user", "content": "你好"}],
      "max_tokens": 512,
      "temperature": 0.7
    }'

  Completions 接口
  curl http://localhost:8000/v1/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "Qwen3-8B", "prompt": "Hello", "max_tokens": 100}'

  OpenAI Python SDK（直接可用）
  from openai import OpenAI
  client = OpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")
  resp = client.chat.completions.create(
      model="Qwen3-8B",
      messages=[{"role": "user", "content": "你好"}],
      max_tokens=512,
  )
  print(resp.choices[0].message.content)