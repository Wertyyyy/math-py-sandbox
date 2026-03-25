vllm serve ../models/Qwen3.5-27B --port 8000 --tensor-parallel-size 2 --data-parallel-size 2 --max-model-len 262144 --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder
