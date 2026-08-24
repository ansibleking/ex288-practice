# Exercise 8: Pipeline with Trigger — Simulation Package

## Contents
- maven-app/          - minimal Maven Java project (pom.xml + App.java)
- pvc.yaml             - shared workspace PVC
- pipeline.yaml        - Pipeline with maven_repo + image_name params (git-clone -> maven-build)
- pipelinerun.yaml     - manual PipelineRun (edit maven_repo before running)
- triggerbinding.yaml  - extracts git-repo-url/git-revision from webhook payload
- triggertemplate.yaml - creates a PipelineRun from the extracted params (edit maven_repo)
- eventlistener.yaml   - listens for incoming webhook calls
- test-git-push.sh     - pushes empty commit to test real webhook trigger
- simulate-webhook.sh  - simulates a push payload directly (no GitHub needed)

## IMPORTANT: before running anything
Replace REPLACE_WITH_YOUR_MAVEN_REGISTRY_URL in BOTH pipelinerun.yaml and
triggertemplate.yaml with your actual Nexus Maven proxy URL, e.g.:
  http://<your-nexus-host>/repository/maven-public-new/

## Steps

1. Push this whole folder to your git fork under exam8-sim/, commit, push.

2. Create project and base objects:
   oc new-project exam8-sim
   oc create -f pvc.yaml
   oc create -f pipeline.yaml

3. Confirm required task names exist in your cluster (adjust taskRef kind if needed):
   oc get clustertasks
   oc get tasks -n exam8-sim
   (if git-clone/maven show under 'tasks', kind: Task in pipeline.yaml is correct;
    if under clustertasks, change kind: Task -> kind: ClusterTask)

4. Manual run first (prove params work before trusting the trigger):
   oc create -f pipelinerun.yaml
   tkn pipelinerun logs -f -n exam8-sim --last

5. Create the trigger chain:
   oc create -f triggerbinding.yaml
   oc create -f triggertemplate.yaml
   oc create -f eventlistener.yaml
   oc expose svc el-maven-build-eventlistener

6. Test the trigger WITHOUT needing GitHub reachability:
   ./simulate-webhook.sh exam8-sim

7. If GitHub really needs to reach your cluster and it can't (common in labs),
   use smee.io as a relay - see prior conversation notes on NO_PROXY handling
   if you're behind a corporate/lab Squid proxy.

8. Real git push test (only if webhook/network path is confirmed working):
   ./test-git-push.sh

9. Watch results:
   tkn pipelinerun list -n exam8-sim --watch
