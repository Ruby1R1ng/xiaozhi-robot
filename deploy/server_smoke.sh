#!/usr/bin/env bash
set -euo pipefail

set -a
source /etc/xiaozhi-search.env
set +a

export TAVILY_SEARCH_DEPTH=basic
export TAVILY_MAX_RESULTS=3
export TAVILY_MONTHLY_CREDIT_BUDGET=900
export TAVILY_CACHE_TTL_SECONDS=1800
export TAVILY_USAGE_DB=/var/lib/xiaozhi-search/usage.sqlite3

cd /opt/xiaozhi-search
exec /opt/xiaozhi-search/.venv/bin/python \
  /tmp/xiaozhi-search-deploy/server_search_smoke.py
