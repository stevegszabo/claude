# PPDM Kubernetes Cluster Registration

A Python CLI for registering and managing Kubernetes clusters with Dell
PowerProtect Data Manager (PPDM) via its public REST API
(`https://developer.dell.com/apis/4378`).

It covers:

1. **Authentication** — login/logout against `/api/v2/login` and `/api/v2/logout`,
   producing a Bearer token used for every subsequent call.
2. **Cluster credentials** — the Kubernetes service-account token PPDM uses to
   talk to a cluster. Backed by PPDM's `Credentials` resource
   (`/api/v2/credentials`), scoped to `type: KUBERNETES`, `method: TOKEN`.
3. **Cluster registrations** — the registered cluster itself. Backed by
   PPDM's `Inventory Source` resource (`/api/v2/inventory-sources`), scoped to
   `type: KUBERNETES`.

Each resource supports list, get, create, update, and delete.

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.7+ and the `requests` library.

## Authentication

Every command needs `--server` (PPDM DNS name or IP) and a password. The
password can be supplied three ways, checked in this order:

1. `-pwd/--password` on the command line (visible in shell history — avoid in shared environments)
2. `PPDM_PASSWORD` environment variable
3. Interactive prompt (via `getpass`, not echoed) if neither of the above is set

```bash
export PPDM_PASSWORD='...'
python register_cluster.py --server ppdm.example.com --user admin credential list
```

By default the client verifies the PPDM appliance's TLS certificate. Pass
`--insecure` to skip verification for a lab/PoC appliance using a
self-signed certificate.

## Typical end-to-end flow: registering a cluster

```bash
# 1. Create a credential from the Kubernetes service-account token
#    (see below for how to obtain the token)
python register_cluster.py --server ppdm.example.com credential create \
  --name my-cluster-cred --token "$(cat sa-token.txt)"

# 2. Register the cluster, referencing the credential by name (resolved to an ID)
python register_cluster.py --server ppdm.example.com cluster create \
  --name my-cluster \
  --address k8s-api.example.com \
  --credential-name my-cluster-cred
```

### Obtaining the Kubernetes service-account token

PPDM authenticates to the cluster using a Kubernetes service-account token
with permission to get/list/watch namespaces, PVs, PVCs, storage classes,
deployments, and pods across the cluster. Create the service account, cluster
role binding, and a token in the target cluster (via `kubectl`), then pass
that token to `credential create --token`. Provisioning the service account
itself is out of scope for this tool — it operates purely on the PPDM side.

## Command reference

Global options (apply before the resource subcommand):

| Option | Description |
|---|---|
| `-s, --server` | PPDM DNS name or IP (required) |
| `--port` | PPDM REST API port (default `8443`) |
| `-usr, --user` | PPDM username (default `admin`) |
| `-pwd, --password` | PPDM password (see [Authentication](#authentication)) |
| `--insecure` | Skip TLS certificate verification |

### `credential` — manage cluster credentials

```bash
register_cluster.py credential list [--name SUBSTR] [--id SUBSTR]
register_cluster.py credential get --id ID
register_cluster.py credential create --name NAME --token TOKEN [--username USER]
register_cluster.py credential update --id ID [--name NAME] [--token TOKEN] [--username USER]
register_cluster.py credential delete --id ID [--yes]
```

`update` fetches the current credential and merges in only the fields you
pass, then submits a full replacement (PPDM's `/credentials/{id}` only
supports `PUT`, not `PATCH`).

### `cluster` — manage cluster registrations

```bash
register_cluster.py cluster list [--name SUBSTR] [--id SUBSTR]
register_cluster.py cluster get --id ID
register_cluster.py cluster create --name NAME --address HOST \
    [--k8s-port PORT] (--credential-id ID | --credential-name NAME) \
    [--distribution-type TANZU_GUEST_CLUSTER|VANILLA_ON_VSPHERE|NON_VSPHERE] \
    [--update-mode AUTO|MANUAL] [--config KEY=VALUE ...]
register_cluster.py cluster update --id ID \
    [--credential-id ID | --credential-name NAME] \
    [--update-mode AUTO|MANUAL] [--config KEY=VALUE ...]
register_cluster.py cluster delete --id ID [--yes] [--cleanup]
```

**`--cleanup`:** PPDM refuses to delete an inventory source while its assets (namespaces,
PVCs, etc.) are still assigned to a protection policy or belong to an asset group, failing
with: *"Failed to delete inventory source due to the assets of the inventory source being
protected by protection policies or being part of asset groups."* Passing `--cleanup` looks up
the cluster's assets first and unassigns each one from any protection policy
(`POST /protection-policies/{id}/asset-unassignments`) and any asset group
(`POST /resource-groups/{id}/resource-unassignments-batch`) before deleting the registration.
Omit it if you'd rather manage those unassignments yourself (e.g. via the PPDM UI) first.

`--k8s-port` is the *Kubernetes* API server port (default `6443`) — distinct
from the top-level `--port`, which is PPDM's own REST API port.

**Note on `update`:** PPDM's `/inventory-sources/{id}` endpoint has no
full-replace `PUT` — only `PATCH`, scoped to the cluster's `details.k8s`
object (controller configuration entries, update mode) plus, defensively, the
credential reference. If your PPDM version doesn't honor a credential change
via this endpoint, delete and recreate the registration with the new
credential instead.

### Filtering

`list` builds a PPDM filter expression under the hood
(`type eq "KUBERNETES" and name lk "%<name>%"`, PPDM's own filter syntax) —
the same substring-match convention Dell's own reference scripts use, so
`--name` doesn't need to be an exact match.

## Development

```bash
pip install -r requirements.txt
python -m py_compile ppdm_cluster_registration/*.py register_cluster.py
python -m unittest discover -s tests -v
```

The test suite (`tests/test_cli_smoke.py`) mocks `requests.request` (stdlib
`unittest.mock`, no extra dependency) to exercise every credential and
cluster operation end-to-end through the CLI without needing a real PPDM
appliance — it asserts the exact HTTP method, URL, and JSON body sent for
each call. **It has not been run against a live PPDM appliance**; do that
before relying on this in production, particularly to confirm your PPDM
version's exact behavior for `cluster update` credential rotation (see note
above).

## Project layout

```
ppdm_cluster_registration/
├── client.py          PPDMClient: login/logout, generic authenticated request
├── credentials.py      CredentialsAPI: cluster credential CRUD
├── registrations.py    RegistrationsAPI: cluster registration CRUD
├── cli.py               argparse CLI wiring
└── exceptions.py        PPDMAPIError
register_cluster.py       entry point
tests/test_cli_smoke.py    mocked-HTTP smoke tests
```

## Reference

- Dell PPDM Public REST API: https://developer.dell.com/apis/4378/versions/20.1.0
- Endpoint paths, verbs, and schemas verified against the PPDM public v2
  OpenAPI spec and Dell's own reference automation scripts
  (`github.com/dell/powerprotect-data-manager`).
