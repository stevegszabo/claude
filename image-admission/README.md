# image-admission

A Kubernetes [mutating admission webhook](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/) that automatically labels namespaces for Pod Security Standards enforcement and Istio sidecar injection. It is implemented as a small Flask app and deployed via Helm.

> **Note:** despite the repo name, this controller does not inspect or mutate container images. It only intercepts `Namespace` `CREATE`/`UPDATE` requests.

## How it works

The webhook server exposes a single `POST /mutate` endpoint that the Kubernetes API server calls for every admission review matching its registered rules (`namespaces`, operations `CREATE`/`UPDATE`). For each request it walks through:

1. **Kind check** — if the object isn't a `Namespace`, the request is allowed through unmodified.
2. **Exempt list check** — if the namespace name is in a configured exempt list (mounted from a ConfigMap, e.g. `kube-system`, `default`, `calico-system`, etc.), it's allowed through unmodified.
3. **Operation check** — only `CREATE` and `UPDATE` operations are processed; anything else is allowed through unmodified.
4. **Label patch** — otherwise, the webhook returns a JSON Patch that adds/sets three labels on the namespace:
   - `pod-security.kubernetes.io/enforce` — the Pod Security Standards level to enforce (e.g. `restricted`)
   - `pod-security.kubernetes.io/enforce-version` — the Pod Security Standards version (e.g. `latest`)
   - `istio-injection` — whether Istio sidecar injection is enabled for the namespace

The webhook **never denies** a request — it always responds `allowed: true`, and only ever adds a JSON Patch when there are labels to set. This makes it a pure "auto-tagging" controller: it standardizes security-policy and service-mesh labels across namespaces without blocking any Kubernetes operations.

A `GET /health` endpoint is also exposed and used for liveness/readiness probes.

## Configuration

The server is configured via environment variables:

| Variable | Default | Description |
|---|---|---|
| `ADMISSION_SECURITY_POLICY_MODE` | `privileged` | Value written to `pod-security.kubernetes.io/enforce` |
| `ADMISSION_SECURITY_POLICY_VERSION` | `latest` | Value written to `pod-security.kubernetes.io/enforce-version` |
| `ADMISSION_ISTIO_INJECTION_MODE` | `disabled` | Value written to `istio-injection` |
| `ADMISSION_EXEMPT_NAMESPACES` | `namespaces.exempt` | Path to a newline-separated file of namespace names to skip |
| `ADMISSION_LOG_LEVEL` | `debug` | Log level (`debug`, `info`, `warning`, `error`, `critical`) |

The bundled Helm chart overrides several of these defaults (e.g. enforcing `restricted` Pod Security and enabling Istio injection by default — see `admission/helm/admission/values.yaml`).

The production server (gunicorn + gevent, TLS-terminated) is further tunable via `ADMISSION_BIND`, `ADMISSION_WORKERS`, `ADMISSION_THREADS`, `ADMISSION_TIMEOUT`, `ADMISSION_KEEP_ALIVE`, `ADMISSION_CRT`, and `ADMISSION_KEY`.

## Deployment

The controller ships as a container image plus a Helm chart at `admission/helm/admission`. Installing the chart:

- Deploys the webhook server behind a `Service`, serving HTTPS on port 8443.
- Registers a `MutatingWebhookConfiguration` (`admission.cloudserv.ca`) that targets the `/mutate` path for `namespaces` `CREATE`/`UPDATE` operations.
- Mounts the exempt-namespaces list from a `ConfigMap` and a TLS certificate/key from a `Secret` (also used as the webhook's `caBundle`).
- Wires `GET /health` into liveness and readiness probes.
