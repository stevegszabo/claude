"""Thin wrapper around the Kubernetes RBAC/Core APIs.

Reads whatever kubeconfig is active on the host (respects the KUBECONFIG env
var). Every call accepts an optional `context` name so the browsing UI can
target a specific cluster/context from the kubeconfig instead of always
using its current-context; a client is built per context with
`config.new_client_from_config` (rather than mutating the process-global
default config) and cached, since a request may be served for any context
at any time.
"""

from __future__ import annotations

import os

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

_clients: dict[str | None, tuple[client.RbacAuthorizationV1Api, client.CoreV1Api]] = {}


class RBACBrowserError(Exception):
    """Raised for problems talking to the Kubernetes API, with an HTTP-ish status."""

    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.message = message
        self.status = status


def list_contexts() -> tuple[list[str], str | None]:
    """Return (all context names, current-context name) from the kubeconfig."""
    try:
        contexts, active = config.list_kube_config_contexts(
            config_file=os.environ.get("KUBECONFIG")
        )
    except config.config_exception.ConfigException as exc:
        raise RBACBrowserError(
            f"Could not load a kubeconfig (checked $KUBECONFIG / ~/.kube/config): {exc}",
            status=500,
        ) from exc
    names = [c["name"] for c in contexts]
    default_name = active["name"] if active else None
    return names, default_name


def _get_clients(context: str | None) -> tuple[client.RbacAuthorizationV1Api, client.CoreV1Api]:
    if context not in _clients:
        try:
            api_client = config.new_client_from_config(
                config_file=os.environ.get("KUBECONFIG"), context=context
            )
        except config.config_exception.ConfigException as exc:
            raise RBACBrowserError(
                f"Could not load kubeconfig context {context!r}: {exc}", status=400
            ) from exc
        _clients[context] = (
            client.RbacAuthorizationV1Api(api_client),
            client.CoreV1Api(api_client),
        )
    return _clients[context]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ApiException as exc:
        if exc.status == 404:
            raise RBACBrowserError("Resource not found.", status=404) from exc
        if exc.status in (401, 403):
            raise RBACBrowserError(
                f"The selected kubeconfig context is not authorized for this action "
                f"({exc.status}): {exc.reason}",
                status=exc.status,
            ) from exc
        raise RBACBrowserError(f"Kubernetes API error: {exc.reason}", status=exc.status or 500) from exc


def list_namespaces(context: str | None = None) -> list[str]:
    _, core = _get_clients(context)
    result = _call(core.list_namespace)
    return sorted(ns.metadata.name for ns in result.items)


def list_cluster_roles(context: str | None = None):
    rbac, _ = _get_clients(context)
    result = _call(rbac.list_cluster_role)
    return sorted(result.items, key=lambda r: r.metadata.name)


def get_cluster_role(name: str, context: str | None = None):
    rbac, _ = _get_clients(context)
    return _call(rbac.read_cluster_role, name)


def list_cluster_role_bindings(context: str | None = None):
    rbac, _ = _get_clients(context)
    result = _call(rbac.list_cluster_role_binding)
    return sorted(result.items, key=lambda r: r.metadata.name)


def get_cluster_role_binding(name: str, context: str | None = None):
    rbac, _ = _get_clients(context)
    return _call(rbac.read_cluster_role_binding, name)


def list_roles(namespaces: list[str], context: str | None = None):
    rbac, _ = _get_clients(context)
    items = []
    for ns in namespaces:
        result = _call(rbac.list_namespaced_role, ns)
        items.extend(result.items)
    return sorted(items, key=lambda r: (r.metadata.namespace, r.metadata.name))


def get_role(namespace: str, name: str, context: str | None = None):
    rbac, _ = _get_clients(context)
    return _call(rbac.read_namespaced_role, name, namespace)


def list_role_bindings(namespaces: list[str], context: str | None = None):
    rbac, _ = _get_clients(context)
    items = []
    for ns in namespaces:
        result = _call(rbac.list_namespaced_role_binding, ns)
        items.extend(result.items)
    return sorted(items, key=lambda r: (r.metadata.namespace, r.metadata.name))


def get_role_binding(namespace: str, name: str, context: str | None = None):
    rbac, _ = _get_clients(context)
    return _call(rbac.read_namespaced_role_binding, name, namespace)
