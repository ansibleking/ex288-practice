#!/bin/bash
# Test script: pushes an empty commit to trigger the pipeline via webhook
set -e
echo "Pushing empty commit to trigger pipeline..."
git commit --allow-empty -m "trigger pipeline test $(date)"
git push origin main
echo "Push complete. Watch for a new PipelineRun with:"
echo "  tkn pipelinerun list -n <your-namespace> --watch"
