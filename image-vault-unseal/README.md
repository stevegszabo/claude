# image-vault-unseal

A sidecar container that automatically unseals a HashiCorp Vault server running in Kubernetes, plus the Helm chart wiring needed to deploy it alongside Vault.

## How it works

Vault starts up sealed and needs a threshold of Shamir unseal key shares submitted before it will serve traffic. `unseal/unseal.py` automates that step so an operator doesn't have to do it by hand every time Vault (re)starts.

It runs as a **sidecar** container in the same pod as `vault`, not an init container — init containers run to completion *before* the main container starts, so one couldn't reach Vault's API yet. A sidecar starts concurrently with `vault` and shares the pod's network namespace, so it can reach Vault at `127.0.0.1`.

The script (stdlib-only Python, no dependencies):

1. Reads all files in a mounted directory as unseal key shares — one file per key.
2. Polls `GET /v1/sys/seal-status` on Vault.
3. If Vault is sealed, submits each key share via `PUT /v1/sys/unseal` until the threshold is met.
4. Loops forever on a fixed interval, so it also re-unseals Vault automatically after any future restart.

Configuration is via environment variables, all optional:

| Variable | Default | Purpose |
|---|---|---|
| `VAULT_ADDR` | `http://127.0.0.1:8200` | Vault API address |
| `UNSEAL_KEYS_DIR` | `/vault/unseal-keys` | Directory containing one file per key share |
| `POLL_INTERVAL_SECONDS` | `10` | How often to check seal status |
| `REQUEST_TIMEOUT_SECONDS` | `5` | HTTP timeout for Vault API calls |

The key shares themselves are never baked into the image or the chart — they come from a Kubernetes `Secret` mounted as a volume at runtime (see below).

## Building the Docker image

The image is defined by `unseal/Dockerfile` (`python:3.13-alpine` base).

Build locally:

```bash
cd unseal
docker build -t vault-unseal:local .
```

Build and push a tagged release to Docker Hub:

```bash
cd unseal
docker build -t docker.io/steveszabo/vault-unseal:1.0.0 .
docker push docker.io/steveszabo/vault-unseal:1.0.0
```

The published image is `docker.io/steveszabo/vault-unseal:1.0.0`, referenced by tag in the Helm values below.

## Configuring the Helm deployment

`unseal/vault/` is a vendored copy of the official [`hashicorp/vault`](https://github.com/hashicorp/vault-helm) Helm chart, pinned to version `0.34.0` to match what's deployed. Two values files matter here:

- **`unseal/vault/values.yaml`** — the chart's untouched, vendored defaults. Left as-is so upstream chart updates stay easy to diff.
- **`unseal/vault/values-local.yaml`** — the deploy-time override file layered on top via `-f`. This is where the sidecar is actually wired in, under `server.extraContainers` and `server.volumes`:

  ```yaml
  server:
    extraContainers:
      - name: vault-unsealer
        image: docker.io/steveszabo/vault-unseal:1.0.0
        env:
          - name: VAULT_ADDR
            value: http://127.0.0.1:8200
        volumeMounts:
          - name: unseal-keys
            mountPath: /vault/unseal-keys
            readOnly: true
        resources:
          requests:
            cpu: 10m
            memory: 32Mi
          limits:
            cpu: 50m
            memory: 64Mi
    volumes:
      - name: unseal-keys
        secret:
          secretName: unseal
  ```

  `server.volumes` mounts the existing `unseal` Kubernetes Secret into the pod (one key per file), and `server.extraContainers` runs the sidecar image against it. This requires a `Secret` named `unseal` to already exist in the target namespace, with each unseal key share as a separate key/value entry.

Deploy or upgrade with both values files:

```bash
helm upgrade vault unseal/vault -n base-vault -f unseal/vault/values-local.yaml
```

The chart sets `server.updateStrategyType: OnDelete` on the Vault StatefulSet on purpose, so a config change doesn't trigger an automatic rolling restart (which would reseal Vault). To roll the updated pod template onto an already-running pod, delete it manually and let the StatefulSet recreate it:

```bash
kubectl delete pod vault-0 -n base-vault
```
