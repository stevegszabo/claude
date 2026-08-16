# kube-rbac-report

Generates standalone HTML reports of a Kubernetes cluster's RBAC configuration:
one report per namespace (Roles + RoleBindings) plus a single cluster-level
report (ClusterRoles + ClusterRoleBindings). When a RoleBinding or
ClusterRoleBinding points at a ClusterRole, that ClusterRole's rules are
resolved and shown inline.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

Report on every namespace plus the cluster-level report, using the current
kubeconfig context, writing to `./reports/`:

```bash
.venv/bin/python report.py
```

Limit to specific namespaces (repeatable and/or comma-separated):

```bash
.venv/bin/python report.py -n kube-system -n default
.venv/bin/python report.py -n kube-system,default
```

Other options:

```
-o, --output-dir DIR   Directory to write HTML files into (default: ./reports)
--kubeconfig PATH       Override kubeconfig path (default: standard resolution)
--context NAME          Override kubeconfig context (default: current-context)
```

Output: `reports/cluster.html` and `reports/<namespace>.html` for each
namespace reported on.

Exit codes: `0` clean run, `1` fatal error (couldn't connect / enumerate
namespaces — nothing written), `2` partial (one or more namespaces or the
cluster report hit an API error, but the run completed and other reports
were still written). Dangling roleRefs are shown as warnings in the report
itself and never affect the exit code.

## Running tests

```bash
.venv/bin/python -m pytest tests/
```

Unit tests build real `kubernetes.client` model objects and mock the API
clients, so no cluster is needed.

## Manual verification against a real cluster

1. Run with no arguments against your current context and open the
   generated files in `reports/` to sanity-check rendering against real
   cluster data.
2. To exercise every code path (Role/RoleBinding, ClusterRole resolution,
   dangling refs, ClusterRoleBindings) in one shot, create a disposable
   namespace and apply a sample manifest, e.g.:

   ```bash
   kubectl create namespace rbac-report-test
   kubectl apply -n rbac-report-test -f - <<'EOF'
   apiVersion: rbac.authorization.k8s.io/v1
   kind: Role
   metadata:
     name: pod-reader
   rules:
   - apiGroups: [""]
     resources: ["pods"]
     verbs: ["get", "list"]
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: RoleBinding
   metadata:
     name: pod-reader-binding
   subjects:
   - kind: ServiceAccount
     name: default
     namespace: rbac-report-test
   roleRef:
     kind: Role
     name: pod-reader
     apiGroup: rbac.authorization.k8s.io
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: RoleBinding
   metadata:
     name: view-binding
   subjects:
   - kind: ServiceAccount
     name: default
     namespace: rbac-report-test
   roleRef:
     kind: ClusterRole
     name: view
     apiGroup: rbac.authorization.k8s.io
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: RoleBinding
   metadata:
     name: dangling-binding
   subjects:
   - kind: ServiceAccount
     name: default
     namespace: rbac-report-test
   roleRef:
     kind: Role
     name: does-not-exist
     apiGroup: rbac.authorization.k8s.io
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRole
   metadata:
     name: rbac-report-test-cluster-role
   rules:
   - apiGroups: [""]
     resources: ["nodes"]
     verbs: ["get", "list"]
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRoleBinding
   metadata:
     name: rbac-report-test-cluster-binding
   subjects:
   - kind: ServiceAccount
     name: default
     namespace: rbac-report-test
   roleRef:
     kind: ClusterRole
     name: rbac-report-test-cluster-role
     apiGroup: rbac.authorization.k8s.io
   EOF

   .venv/bin/python report.py -n rbac-report-test
   .venv/bin/python report.py -o reports  # regenerate reports/cluster.html
   ```

3. Inspect `reports/rbac-report-test.html` and `reports/cluster.html`, then
   clean up:

   ```bash
   kubectl delete namespace rbac-report-test
   kubectl delete clusterrole rbac-report-test-cluster-role
   kubectl delete clusterrolebinding rbac-report-test-cluster-binding
   ```
