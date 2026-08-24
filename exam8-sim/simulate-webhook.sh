#!/bin/bash
# Simulates a GitHub push webhook directly against the EventListener,
# bypassing the need for real GitHub -> cluster network reachability.
set -e
NAMESPACE="${1:-exam8-sim}"
ROUTE=$(oc get route el-maven-build-eventlistener -n "$NAMESPACE" -o jsonpath='{.spec.host}')

if [ -z "$ROUTE" ]; then
  echo "EventListener route not found in namespace $NAMESPACE"
  echo "Run: oc expose svc el-maven-build-eventlistener -n $NAMESPACE"
  exit 1
fi

echo "Sending simulated GitHub push payload to: http://$ROUTE"
curl -X POST "http://$ROUTE" \
  -H "Content-Type: application/json" \
  -d '{
    "repository": {"clone_url": "https://github.com/ansibleking/ex288-practice.git"},
    "head_commit": {"id": "main"}
  }'
echo ""
echo "Check for a new PipelineRun with:"
echo "  tkn pipelinerun list -n $NAMESPACE --watch"
