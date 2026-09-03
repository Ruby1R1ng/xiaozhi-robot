#!/usr/bin/env bash
set -euo pipefail

temporary_file="$(mktemp /etc/xiaozhi-search.env.XXXXXX)"
trap 'rm -f "$temporary_file"' EXIT

tr -d '\r' < /etc/xiaozhi-search.env > "$temporary_file"
chown root:root "$temporary_file"
chmod 600 "$temporary_file"
mv "$temporary_file" /etc/xiaozhi-search.env
trap - EXIT
