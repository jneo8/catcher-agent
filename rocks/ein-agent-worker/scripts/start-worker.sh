#!/bin/bash

set -e

# Change to /app directory
cd /app

# Add /app to PYTHONPATH so Python can find the ein_agent module
export PYTHONPATH=/app:$PYTHONPATH

# Start the Temporal worker
python3 -m ein_agent_worker.worker
