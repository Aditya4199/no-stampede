#!/usr/bin/env bash
set -e

URL="${1:-http://localhost:8080}"
echo "Running burst tests against $URL"

# We run the python script. Ensure requirements are installed.
# Using 20,000 requests for stampede as requested by prompt.
python3 scripts/burst.py --url "$URL" --requests 20000 --concurrency 200 --users 500
