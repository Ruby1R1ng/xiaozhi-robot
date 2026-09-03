import json

import web_search


query = "阿里云轻量应用服务器 官方文档"
first = web_search.web_search(query)
second = web_search.web_search(query)

print(
    json.dumps(
        {
            "first_success": first.get("success"),
            "first_count": first.get("count"),
            "first_credits": first.get("credits_used"),
            "second_cached": second.get("cached"),
            "monthly_used": second.get("monthly_credits_used"),
            "error_code": first.get("error_code"),
        },
        ensure_ascii=False,
    )
)
