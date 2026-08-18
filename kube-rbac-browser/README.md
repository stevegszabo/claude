# kube-rbac-browser

A read-only web GUI for browsing Kubernetes RBAC resources: `ClusterRole`,
`ClusterRoleBinding`, `Role`, and `RoleBinding`. It uses whatever
kubeconfig/context is currently active on the machine it runs on.

## Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```sh
gunicorn wsgi:app --bind 0.0.0.0:8080
```

Then open http://localhost:8080/.

The app reads `KUBECONFIG` (if set) or `~/.kube/config`. By default it
browses the kubeconfig's `current-context`, but a "Context" dropdown in the
page header lists every cluster/context defined in the kubeconfig — pick
one to browse it instead. The selection is per-browser-session (stored in
a session cookie) and doesn't change your shell's active kubectl context.

## Pages

- `/clusterroles`, `/clusterroles/<name>`
- `/clusterrolebindings`, `/clusterrolebindings/<name>`
- `/roles?ns=<namespace>&ns=<namespace>...`, `/roles/<namespace>/<name>`
- `/rolebindings?ns=<namespace>&ns=<namespace>...`, `/rolebindings/<namespace>/<name>`

`Role` and `RoleBinding` are namespace-scoped, so their list pages start
with a namespace multi-select — pick one or more namespaces to list
resources across all of them.

This app is read-only: it never creates, modifies, or deletes anything in
the cluster.
