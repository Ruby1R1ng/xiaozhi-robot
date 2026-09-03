import os
import time

import httpx


api_key = os.environ["SILICONFLOW_API_KEY"]
started = time.monotonic()
response = httpx.post(
    "https://api.siliconflow.cn/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "model": "zai-org/GLM-5.2",
        "messages": [
            {
                "role": "user",
                "content": "请用不超过80个汉字总结：缓存可以减少重复请求的响应时间和费用。",
            }
        ],
        "stream": False,
        "max_tokens": 512,
        "reasoning_effort": "low",
        "thinking_budget": 128,
    },
    timeout=30,
)
elapsed = time.monotonic() - started
try:
    body = response.json()
except ValueError:
    body = {}
message = ((body.get("choices") or [{}])[0].get("message") or {})
print(
    {
        "status": response.status_code,
        "elapsed_seconds": round(elapsed, 2),
        "content": str(message.get("content") or "")[:160],
        "has_reasoning": bool(message.get("reasoning_content")),
        "usage": body.get("usage") or {},
        "error_code": body.get("code"),
        "error_message": str(body.get("message") or "")[:200],
    }
)
