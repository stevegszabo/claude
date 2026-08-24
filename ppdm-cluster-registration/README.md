# PPDM Kubernetes Cluster Registration

A Python CLI for registering and managing Kubernetes clusters with Dell
PowerProtect Data Manager (PPDM) via its public REST API
(`https://developer.dell.com/apis/4378`).

## What is PPDM?

[PowerProtect Data Manager](https://www.dell.com/en-us/shop/storage-servers-and-networking-for-business/sf/powerprotect-data-manager)
is Dell's enterprise data protection platform. It provides centralized backup,
recovery, and data-protection governance across an organization's workloads —
virtual machines, physical/file systems, databases, and (via the Kubernetes
inventory source this tool targets) containerized applications — from a single
console and API.

Concretely, PPDM:

- **Discovers and inventories protectable assets.** Before anything can be
  backed up, its source must be *registered* with PPDM as an inventory
  source (for Kubernetes, this means pointing PPDM at a cluster's API server
  and giving it credentials to talk to it — exactly what this tool automates).
  PPDM then discovers the individual protectable assets within that source
  (e.g. Kubernetes namespaces and their PVCs).
- **Applies protection policies.** Administrators define policies (schedule,
  retention, backup target) and assign discovered assets to them, either
  manually or automatically as new assets appear.
- **Executes and tracks backup/restore jobs.** PPDM orchestrates the actual
  backup and restore operations against its storage targets (e.g. Dell Data
  Domain, cloud object storage) and reports job status, compliance, and
  capacity through its UI and API.

This tool operates entirely on the *registration* side of that lifecycle —
creating the credential and inventory-source records PPDM needs before it can
discover and protect anything in a cluster — not on policies, jobs, or backup
data itself.

It covers:

1. **Authentication** — login/logout against `/api/v2/login` and `/api/v2/logout`,
   producing a Bearer token used for every subsequent call.
2. **Cluster credentials** — the Kubernetes service-account token PPDM uses to
   talk to a cluster. Backed by PPDM's `Credentials` resource
   (`/api/v2/credentials`), scoped to `type: KUBERNETES`, `method: TOKEN`.
3. **Cluster registrations** — the registered cluster itself. Backed by
   PPDM's `Inventory Source` resource (`/api/v2/inventory-sources`), scoped to
   `type: KUBERNETES`.
4. **Cluster certificates** — the cluster's Kubernetes API server certificate,
   which PPDM needs to trust (e.g. when it's self-signed or signed by an
   internal CA). Backed by PPDM's `Certificates` resource (`/api/v2/certificates`).

Credentials and cluster registrations support the full list, get, create,
update, and delete set. Certificates currently support list and get; create
is a local-testing tool for extracting a cluster's certificate (see
[`certificate`](#certificate--manage-cluster-certificates) below), and
update/delete aren't implemented yet.

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
register_cluster.py credential create --name NAME [--token TOKEN] [--username USER] [--skip-if-exists]
register_cluster.py credential update --id ID [--name NAME] [--token TOKEN] [--username USER]
register_cluster.py credential delete --id ID [--yes]
```

`create --token` follows the same fallback order as `--password`: the flag,
then the `PPDM_TOKEN` environment variable, then an interactive prompt (via
`getpass`, not echoed) if neither is set. `update --token` has no such
fallback — it's optional, and omitting it means "leave the token
unchanged," so a rotation must be requested explicitly.

`update` fetches the current credential and merges in only the fields you
pass, then submits a full replacement (PPDM's `/credentials/{id}` only
supports `PUT`, not `PATCH`).

**`--skip-if-exists`:** PPDM's create call fails if a credential with that name
already exists. Passing `--skip-if-exists` looks up the name first (exact match)
and, if found, prints a short message and exits successfully without attempting
the create (and without resolving/prompting for a token) — useful for re-running
a create from a script/pipeline idempotently.

### `cluster` — manage cluster registrations

```bash
register_cluster.py cluster list [--name SUBSTR] [--id SUBSTR]
register_cluster.py cluster get --id ID
register_cluster.py cluster create --name NAME --address HOST \
    [--k8s-port PORT] (--credential-id ID | --credential-name NAME) \
    [--distribution-type TANZU_GUEST_CLUSTER|VANILLA_ON_VSPHERE|NON_VSPHERE] \
    [--update-mode AUTO|MANUAL] [--config KEY=VALUE ...] [--skip-if-exists]
register_cluster.py cluster update --id ID \
    [--address HOST] \
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

**`--skip-if-exists`:** PPDM's create call fails if a registration with that name
already exists. Passing `--skip-if-exists` looks up the name first (exact match)
and, if found, prints a short message and exits successfully without attempting
the create — useful for re-running a create from a script/pipeline idempotently.

**Note on `update`:** unlike credential update, `cluster update` fetches the
current registration and sends the merged result back via a full-replace
`PUT` to `/inventory-sources/{id}` — the same fetch-merge-replace pattern
`credential update` uses. This is what makes changing `--address` (the
Kubernetes API server host/IP, e.g. after the cluster's endpoint moves)
possible, alongside the credential reference and `details.k8s` fields
(controller configuration entries, update mode).

### `certificate` — manage cluster certificates

```bash
register_cluster.py certificate list [--name SUBSTR] [--id SUBSTR]
register_cluster.py certificate get --id ID
register_cluster.py certificate create --address HOST [--k8s-port PORT] \
    (--cluster-id ID | --cluster-name NAME)
register_cluster.py certificate update --id ID
register_cluster.py certificate delete --id ID [--yes]
```

`list`/`get` are implemented, against PPDM's `/api/v2/certificates`
endpoint. `update`/`delete` are scaffolded but not yet implemented (no-ops).

**`create` is currently a local-testing tool, not a PPDM push.** It connects
directly to the Kubernetes API server at `--address`/`--k8s-port` over TLS
and extracts the certificate it presents, without verifying it — the whole
point is to capture certs PPDM doesn't yet trust (self-signed, or signed by
an internal CA). It prints the certificate's validity window, SHA-256
fingerprint (64-character hex, no separators), subject, and issuer:

```bash
register_cluster.py --server ppdm.example.com certificate create \
  --address k8s-api.example.com --cluster-name my-cluster
```

```json
{
  "not_valid_before": "2026-08-08T16:16:24.000Z",
  "not_valid_after": "2027-08-08T16:21:24.000Z",
  "fingerprint": "06F723A541232F51F601061C8A697BE6EE46743EEE9AFACB23E14D20FF54FA68",
  "subject": "CN=kube-apiserver",
  "issuer": "CN=kubernetes"
}
```

`--cluster-id`/`--cluster-name` is required and resolved the same way
`cluster create` resolves `--credential-name`, but is currently unused —
reserved for once pushing the certificate to PPDM is implemented; nothing
is sent to PPDM by `create` yet.

### Filtering

`list` builds a PPDM filter expression under the hood
(`type eq "KUBERNETES" and name lk "%<name>%"`, PPDM's own filter syntax) —
the same substring-match convention Dell's own reference scripts use, so
`--name` doesn't need to be an exact match. Certificates aren't scoped to a
`type`, so their `list` filter is name/id substring matching only, no
`type eq ...` clause.

## Development

```bash
pip install -r requirements.txt
python -m py_compile ppdm_cluster_registration/*.py register_cluster.py
python -m unittest discover -s tests -v
```

`tests/test_cli_smoke.py` mocks `requests.request` (stdlib `unittest.mock`,
no extra dependency) to exercise every credential and cluster operation
end-to-end through the CLI without needing a real PPDM appliance — it asserts
the exact HTTP method, URL, and JSON body sent for each call.
`tests/test_credentials_api.py`, `tests/test_registrations_api.py`, and
`tests/test_certificates_api.py` instead test `CredentialsAPI`/
`RegistrationsAPI`/`CertificatesAPI` directly against a mocked `PPDMClient`,
independent of the CLI layer — covering filter/payload construction,
`resolve_id` matching, `cleanup()`'s per-policy/per-group unassignment
batching, and certificate parsing. This test suite itself is still
mock-only (no real PPDM appliance involved). Separately: the `cluster
update` full-PUT rework described above (including `--address`) **has been
tested against a live PPDM appliance and confirmed working**, and
`certificate create`'s Kubernetes-side extraction/parsing (`fetch_certificate`/
`describe_certificate`) **has been tested against a real Kubernetes API
server and confirmed working**. Other operations have not been verified
live — do that before relying on them in production.

## Project layout

| Path | Description |
|---|---|
| `ppdm_cluster_registration/client.py` | `PPDMClient`: login/logout, generic authenticated request |
| `ppdm_cluster_registration/credentials.py` | `CredentialsAPI`: cluster credential CRUD |
| `ppdm_cluster_registration/registrations.py` | `RegistrationsAPI`: cluster registration CRUD |
| `ppdm_cluster_registration/certificates.py` | `CertificatesAPI`: cluster certificate list/get, plus Kubernetes API cert extraction/parsing |
| `ppdm_cluster_registration/cli.py` | argparse CLI wiring |
| `ppdm_cluster_registration/exceptions.py` | `PPDMAPIError` |
| `ppdm_cluster_registration/filters.py` | shared PPDM filter-expression builder |
| `ppdm_cluster_registration/resolve.py` | shared name/ID resolution helper |
| `register_cluster.py` | entry point |
| `tests/test_cli_smoke.py` | mocked-HTTP smoke tests (CLI end-to-end) |
| `tests/test_credentials_api.py` | direct `CredentialsAPI` unit tests |
| `tests/test_registrations_api.py` | direct `RegistrationsAPI` unit tests |
| `tests/test_certificates_api.py` | direct `CertificatesAPI` unit tests |

## Reference

- Dell PPDM Public REST API: https://developer.dell.com/apis/4378/versions/20.1.0
- Endpoint paths, verbs, and schemas verified against the PPDM public v2
  OpenAPI spec and Dell's own reference automation scripts
  (`github.com/dell/powerprotect-data-manager`).
