"""Kubernetes API access, data model, and RBAC gathering/resolution logic."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


# --- Data model -------------------------------------------------------------


@dataclass
class PolicyRule:
    api_groups: List[str] = field(default_factory=list)
    resources: List[str] = field(default_factory=list)
    resource_names: List[str] = field(default_factory=list)
    verbs: List[str] = field(default_factory=list)
    non_resource_urls: List[str] = field(default_factory=list)


@dataclass
class Subject:
    kind: str  # "User" | "Group" | "ServiceAccount"
    name: str
    namespace: Optional[str] = None
    api_group: Optional[str] = None


@dataclass
class RoleRef:
    kind: str  # "Role" | "ClusterRole"
    name: str
    api_group: str = "rbac.authorization.k8s.io"


@dataclass
class RoleInfo:
    name: str
    kind: str  # "Role" | "ClusterRole"
    rules: List[PolicyRule] = field(default_factory=list)


@dataclass
class RoleBindingInfo:
    name: str
    subjects: List[Subject]
    role_ref: RoleRef
    resolved_role: Optional[RoleInfo] = None
    resolution_note: Optional[str] = None


@dataclass
class NamespaceReport:
    namespace: str
    roles: List[RoleInfo] = field(default_factory=list)
    role_bindings: List[RoleBindingInfo] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ClusterReport:
    cluster_roles: List[RoleInfo] = field(default_factory=list)
    cluster_role_bindings: List[RoleBindingInfo] = field(default_factory=list)
    error: Optional[str] = None


# --- Cluster access -----------------------------------------------------------


def load_config(kubeconfig: Optional[str], context: Optional[str]) -> None:
    try:
        config.load_kube_config(config_file=kubeconfig, context=context)
    except config.ConfigException:
        config.load_incluster_config()


def build_api_clients(
    kubeconfig: Optional[str], context: Optional[str]
) -> Tuple[client.CoreV1Api, client.RbacAuthorizationV1Api]:
    load_config(kubeconfig, context)
    return client.CoreV1Api(), client.RbacAuthorizationV1Api()


def list_target_namespaces(
    core_v1: client.CoreV1Api, namespace_filter: Optional[List[str]]
) -> List[str]:
    if namespace_filter:
        return sorted(set(namespace_filter))
    return sorted(ns.metadata.name for ns in core_v1.list_namespace().items)


# --- Converters (kubernetes client model objects -> our dataclasses) --------


def convert_policy_rule(r) -> PolicyRule:
    return PolicyRule(
        api_groups=r.api_groups or [],
        resources=r.resources or [],
        resource_names=r.resource_names or [],
        verbs=r.verbs or [],
        non_resource_urls=r.non_resource_urls or [],
    )


def convert_role(obj, kind: str) -> RoleInfo:
    """Works for both V1Role and V1ClusterRole -- same shape."""
    return RoleInfo(
        name=obj.metadata.name,
        kind=kind,
        rules=[convert_policy_rule(r) for r in (obj.rules or [])],
    )


def convert_subject(s) -> Subject:
    return Subject(kind=s.kind, name=s.name, namespace=s.namespace, api_group=s.api_group)


def convert_role_ref(ref) -> RoleRef:
    return RoleRef(kind=ref.kind, name=ref.name, api_group=ref.api_group)


# --- Fetching -----------------------------------------------------------------


def fetch_cluster_roles(
    rbac_v1: client.RbacAuthorizationV1Api,
) -> Tuple[Dict[str, RoleInfo], Optional[str]]:
    """Lists all ClusterRoles once. Returns (name -> RoleInfo, warning_or_None). Never raises."""
    try:
        items = rbac_v1.list_cluster_role().items
    except ApiException as e:
        return {}, (
            f"could not list ClusterRoles ({e.status} {e.reason}); "
            "ClusterRole-based roleRefs will be unresolvable"
        )
    return {cr.metadata.name: convert_role(cr, "ClusterRole") for cr in items}, None


def _resolve_role_ref(
    role_ref: RoleRef,
    role_index: Dict[str, RoleInfo],
    cluster_roles: Dict[str, RoleInfo],
    cluster_roles_warning: Optional[str],
    scope_label: str,
) -> Tuple[Optional[RoleInfo], Optional[str]]:
    if role_ref.kind == "Role":
        resolved = role_index.get(role_ref.name)
        if resolved is None:
            return None, f"Role '{role_ref.name}' not found in {scope_label}"
        return resolved, None
    if role_ref.kind == "ClusterRole":
        if cluster_roles_warning:
            return None, cluster_roles_warning
        resolved = cluster_roles.get(role_ref.name)
        if resolved is None:
            return None, f"ClusterRole '{role_ref.name}' not found"
        return resolved, None
    return None, f"unrecognized roleRef kind '{role_ref.kind}'"


def fetch_namespace_report(
    core_v1: client.CoreV1Api,
    rbac_v1: client.RbacAuthorizationV1Api,
    namespace: str,
    cluster_roles: Dict[str, RoleInfo],
    cluster_roles_warning: Optional[str],
    verify_exists: bool = False,
) -> NamespaceReport:
    if verify_exists:
        try:
            core_v1.read_namespace(namespace)
        except ApiException as e:
            if e.status == 404:
                return NamespaceReport(namespace=namespace, error="namespace not found")
            return NamespaceReport(
                namespace=namespace, error=f"could not verify namespace ({e.status} {e.reason})"
            )

    try:
        roles = [convert_role(r, "Role") for r in rbac_v1.list_namespaced_role(namespace).items]
        rb_items = rbac_v1.list_namespaced_role_binding(namespace).items
    except ApiException as e:
        return NamespaceReport(namespace=namespace, error=f"{e.status} {e.reason}")

    role_index = {r.name: r for r in roles}
    bindings = []
    for rb in rb_items:
        role_ref = convert_role_ref(rb.role_ref)
        subjects = [convert_subject(s) for s in (rb.subjects or [])]
        resolved, note = _resolve_role_ref(
            role_ref, role_index, cluster_roles, cluster_roles_warning, f"namespace '{namespace}'"
        )
        bindings.append(
            RoleBindingInfo(
                name=rb.metadata.name,
                subjects=subjects,
                role_ref=role_ref,
                resolved_role=resolved,
                resolution_note=note,
            )
        )
    return NamespaceReport(namespace=namespace, roles=roles, role_bindings=bindings)


def fetch_cluster_report(
    rbac_v1: client.RbacAuthorizationV1Api,
    cluster_roles: Dict[str, RoleInfo],
    cluster_roles_warning: Optional[str],
) -> ClusterReport:
    if cluster_roles_warning:
        return ClusterReport(
            cluster_roles=list(cluster_roles.values()), error=cluster_roles_warning
        )

    try:
        crb_items = rbac_v1.list_cluster_role_binding().items
    except ApiException as e:
        return ClusterReport(
            cluster_roles=list(cluster_roles.values()), error=f"{e.status} {e.reason}"
        )

    bindings = []
    for crb in crb_items:
        role_ref = convert_role_ref(crb.role_ref)
        subjects = [convert_subject(s) for s in (crb.subjects or [])]
        resolved, note = _resolve_role_ref(
            role_ref, {}, cluster_roles, cluster_roles_warning, "cluster scope"
        )
        bindings.append(
            RoleBindingInfo(
                name=crb.metadata.name,
                subjects=subjects,
                role_ref=role_ref,
                resolved_role=resolved,
                resolution_note=note,
            )
        )
    return ClusterReport(
        cluster_roles=sorted(cluster_roles.values(), key=lambda r: r.name),
        cluster_role_bindings=bindings,
    )
