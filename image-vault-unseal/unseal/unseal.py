#!/usr/bin/env python3
"""Sidecar that watches the local Vault instance and unseals it using
Shamir key shares mounted from the `unseal` Kubernetes secret.

Runs as a long-lived container alongside `vault` in the same pod (sharing
its network namespace), polling until Vault is reachable and re-unsealing
any time it comes back up sealed (e.g. after a restart).
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
KEYS_DIR = os.environ.get("UNSEAL_KEYS_DIR", "/vault/unseal-keys")
POLL_INTERVAL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "10"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "5"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("vault-unsealer")


def load_unseal_keys(keys_dir):
    keys = []
    for name in sorted(os.listdir(keys_dir)):
        path = os.path.join(keys_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            key = f.read().strip()
        if key:
            keys.append(key)
    if not keys:
        raise RuntimeError(f"no unseal keys found in {keys_dir}")
    return keys


def vault_request(method, path, payload=None):
    url = f"{VAULT_ADDR}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read())


def get_seal_status():
    return vault_request("GET", "/v1/sys/seal-status")


def unseal(keys):
    status = get_seal_status()
    if not status.get("initialized", False):
        log.warning("vault is not initialized yet; skipping unseal")
        return False
    if not status.get("sealed", True):
        return True

    log.info("vault is sealed; submitting unseal keys")
    for key in keys:
        status = vault_request("PUT", "/v1/sys/unseal", {"key": key})
        if not status.get("sealed", True):
            log.info("vault unsealed")
            return True

    log.info(
        "submitted %d key share(s), still sealed (progress %s/%s)",
        len(keys),
        status.get("progress"),
        status.get("t"),
    )
    return not status.get("sealed", True)


def main():
    keys = load_unseal_keys(KEYS_DIR)
    log.info("loaded %d unseal key share(s) from %s", len(keys), KEYS_DIR)

    while True:
        try:
            unseal(keys)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            log.info("vault not reachable yet at %s (%s)", VAULT_ADDR, exc)
        except Exception:
            log.exception("error while checking/unsealing vault")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
