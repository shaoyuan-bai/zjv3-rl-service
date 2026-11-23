#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
runtime_python="${ZJV3_PYTHON:-python3}"
if [ -x runtime/python/bin/python ]; then
  runtime_python="${ZJV3_PYTHON:-runtime/python/bin/python}"
fi
exec "$runtime_python" -m integrations.rl_service "$@"
