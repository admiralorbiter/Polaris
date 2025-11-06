#!/bin/bash
# Format code using development tools
# Usage: ./scripts/format.sh [check|fix]

MODE=${1:-fix}

if [ "$MODE" = "check" ]; then
    echo "Checking code formatting..."
    black --check .
    isort --check-only .
    flake8 .
elif [ "$MODE" = "fix" ]; then
    echo "Formatting code..."
    black .
    isort .
    echo "Checking with flake8..."
    flake8 .
    echo "Done!"
else
    echo "Usage: $0 [check|fix]"
    exit 1
fi
