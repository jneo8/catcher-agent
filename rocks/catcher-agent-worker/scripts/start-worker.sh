#!/bin/bash

set -e

# Change to /app directory
cd /app

# Add /app to PYTHONPATH so Python can find the catcher_agent module
export PYTHONPATH=/app:$PYTHONPATH

# Start the Temporal worker
python3 -m catcher_agent_worker.worker
