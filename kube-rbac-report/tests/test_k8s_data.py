import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import k8s_data  # noqa: E402


def make_role(name, rules=None, kind="V1Role"):
    cls = client.V1Role if kind == "V1Role" else client.V1ClusterRole
    return cls(metadata=client.V1ObjectMeta(name=name), rules=rules or [])


def make_rule(api_groups=None, resources=None, verbs=None, resource_names=None):
    return client.V1PolicyRule(
        api_groups=api_groups or [""],
        resources=resources or ["pods"],
        verbs=verbs or ["get"],
        resource_names=resource_names or [],
    )


def make_role_binding(name, role_ref_kind, role_ref_name, subjects=None):
    return client.V1RoleBinding(
        metadata=client.V1ObjectMeta(name=name),
        role_ref=client.V1RoleRef(
            api_group="rbac.authorization.k8s.io", kind=role_ref_kind, name=role_ref_name
        ),
        subjects=subjects or [client.RbacV1Subject(kind="ServiceAccount", name="sa", namespace="ns1")],
    )


def make_cluster_role_binding(name, role_ref_name, subjects=None):
    return client.V1ClusterRoleBinding(
        metadata=client.V1ObjectMeta(name=name),
        role_ref=client.V1RoleRef(
            api_group="rbac.authorization.k8s.io", kind="ClusterRole", name=role_ref_name
        ),
        subjects=subjects or [client.RbacV1Subject(kind="User", name="alice")],
    )


# --- converters --------------------------------------------------------------


def test_convert_policy_rule():
    rule = make_rule(resources=["pods", "secrets"], verbs=["get", "list"])
    pr = k8s_data.convert_policy_rule(rule)
    assert pr.resources == ["pods", "secrets"]
    assert pr.verbs == ["get", "list"]
    assert pr.resource_names == []
    assert pr.non_resource_urls == []


def test_convert_role():
    role = make_role("pod-reader", rules=[make_rule()])
    info = k8s_data.convert_role(role, "Role")
    assert info.name == "pod-reader"
    assert info.kind == "Role"
    assert len(info.rules) == 1


def test_convert_subject_and_role_ref():
    s = client.RbacV1Subject(kind="Group", name="devs", api_group="rbac.authorization.k8s.io")
    subj = k8s_data.convert_subject(s)
    assert subj.kind == "Group"
    assert subj.name == "devs"

    ref = client.V1RoleRef(api_group="rbac.authorization.k8s.io", kind="ClusterRole", name="view")
    role_ref = k8s_data.convert_role_ref(ref)
    assert role_ref.kind == "ClusterRole"
    assert role_ref.name == "view"


# --- fetch_cluster_roles ------------------------------------------------------


def test_fetch_cluster_roles_success():
    rbac_v1 = Mock()
    rbac_v1.list_cluster_role.return_value = Mock(
        items=[make_role("view", kind="V1ClusterRole"), make_role("edit", kind="V1ClusterRole")]
    )
    cluster_roles, warning = k8s_data.fetch_cluster_roles(rbac_v1)
    assert warning is None
    assert set(cluster_roles) == {"view", "edit"}
    assert cluster_roles["view"].kind == "ClusterRole"


def test_fetch_cluster_roles_failure_returns_warning():
    rbac_v1 = Mock()
    rbac_v1.list_cluster_role.side_effect = ApiException(status=403, reason="Forbidden")
    cluster_roles, warning = k8s_data.fetch_cluster_roles(rbac_v1)
    assert cluster_roles == {}
    assert "403" in warning
    assert "Forbidden" in warning


# --- fetch_namespace_report ---------------------------------------------------


def test_namespace_report_role_bound_binding():
    core_v1, rbac_v1 = Mock(), Mock()
    rbac_v1.list_namespaced_role.return_value = Mock(
        items=[make_role("pod-reader", rules=[make_rule()])]
    )
    rbac_v1.list_namespaced_role_binding.return_value = Mock(
        items=[make_role_binding("binding1", "Role", "pod-reader")]
    )
    report = k8s_data.fetch_namespace_report(core_v1, rbac_v1, "ns1", {}, None)
    assert report.error is None
    assert len(report.roles) == 1
    assert len(report.role_bindings) == 1
    b = report.role_bindings[0]
    assert b.resolved_role is not None
    assert b.resolved_role.name == "pod-reader"
    assert b.resolution_note is None


def test_namespace_report_cluster_role_resolved_binding():
    core_v1, rbac_v1 = Mock(), Mock()
    rbac_v1.list_namespaced_role.return_value = Mock(items=[])
    rbac_v1.list_namespaced_role_binding.return_value = Mock(
        items=[make_role_binding("binding1", "ClusterRole", "view")]
    )
    cluster_roles = {"view": k8s_data.RoleInfo(name="view", kind="ClusterRole", rules=[])}
    report = k8s_data.fetch_namespace_report(core_v1, rbac_v1, "ns1", cluster_roles, None)
    b = report.role_bindings[0]
    assert b.resolved_role is not None
    assert b.resolved_role.kind == "ClusterRole"
    assert b.resolution_note is None


def test_namespace_report_dangling_role_ref():
    core_v1, rbac_v1 = Mock(), Mock()
    rbac_v1.list_namespaced_role.return_value = Mock(items=[])
    rbac_v1.list_namespaced_role_binding.return_value = Mock(
        items=[make_role_binding("binding1", "Role", "missing-role")]
    )
    report = k8s_data.fetch_namespace_report(core_v1, rbac_v1, "ns1", {}, None)
    b = report.role_bindings[0]
    assert b.resolved_role is None
    assert "not found" in b.resolution_note


def test_namespace_report_dangling_cluster_role_ref():
    core_v1, rbac_v1 = Mock(), Mock()
    rbac_v1.list_namespaced_role.return_value = Mock(items=[])
    rbac_v1.list_namespaced_role_binding.return_value = Mock(
        items=[make_role_binding("binding1", "ClusterRole", "missing-cr")]
    )
    report = k8s_data.fetch_namespace_report(core_v1, rbac_v1, "ns1", {}, None)
    b = report.role_bindings[0]
    assert b.resolved_role is None
    assert "ClusterRole 'missing-cr' not found" in b.resolution_note


def test_namespace_report_cluster_role_list_failure_note():
    core_v1, rbac_v1 = Mock(), Mock()
    rbac_v1.list_namespaced_role.return_value = Mock(items=[])
    rbac_v1.list_namespaced_role_binding.return_value = Mock(
        items=[make_role_binding("binding1", "ClusterRole", "view")]
    )
    warning = "could not list ClusterRoles (403 Forbidden); ClusterRole-based roleRefs will be unresolvable"
    report = k8s_data.fetch_namespace_report(core_v1, rbac_v1, "ns1", {}, warning)
    b = report.role_bindings[0]
    assert b.resolved_role is None
    assert b.resolution_note == warning


def test_namespace_report_empty_namespace():
    core_v1, rbac_v1 = Mock(), Mock()
    rbac_v1.list_namespaced_role.return_value = Mock(items=[])
    rbac_v1.list_namespaced_role_binding.return_value = Mock(items=[])
    report = k8s_data.fetch_namespace_report(core_v1, rbac_v1, "ns1", {}, None)
    assert report.error is None
    assert report.roles == []
    assert report.role_bindings == []


def test_namespace_report_api_exception():
    core_v1, rbac_v1 = Mock(), Mock()
    rbac_v1.list_namespaced_role.side_effect = ApiException(status=403, reason="Forbidden")
    report = k8s_data.fetch_namespace_report(core_v1, rbac_v1, "ns1", {}, None)
    assert report.error is not None
    assert "403" in report.error


def test_namespace_report_verify_exists_not_found():
    core_v1, rbac_v1 = Mock(), Mock()
    core_v1.read_namespace.side_effect = ApiException(status=404, reason="Not Found")
    report = k8s_data.fetch_namespace_report(
        core_v1, rbac_v1, "ghost-ns", {}, None, verify_exists=True
    )
    assert report.error == "namespace not found"
    rbac_v1.list_namespaced_role.assert_not_called()


# --- fetch_cluster_report ------------------------------------------------------


def test_cluster_report_resolves_bindings():
    rbac_v1 = Mock()
    rbac_v1.list_cluster_role_binding.return_value = Mock(
        items=[make_cluster_role_binding("crb1", "view")]
    )
    cluster_roles = {"view": k8s_data.RoleInfo(name="view", kind="ClusterRole", rules=[])}
    report = k8s_data.fetch_cluster_report(rbac_v1, cluster_roles, None)
    assert report.error is None
    assert len(report.cluster_roles) == 1
    assert len(report.cluster_role_bindings) == 1
    assert report.cluster_role_bindings[0].resolved_role.name == "view"


def test_cluster_report_dangling_binding():
    rbac_v1 = Mock()
    rbac_v1.list_cluster_role_binding.return_value = Mock(
        items=[make_cluster_role_binding("crb1", "missing")]
    )
    report = k8s_data.fetch_cluster_report(rbac_v1, {}, None)
    b = report.cluster_role_bindings[0]
    assert b.resolved_role is None
    assert "not found" in b.resolution_note


def test_cluster_report_list_failure():
    rbac_v1 = Mock()
    rbac_v1.list_cluster_role_binding.side_effect = ApiException(status=500, reason="Boom")
    report = k8s_data.fetch_cluster_report(rbac_v1, {}, None)
    assert report.error is not None
    assert "500" in report.error


def test_cluster_report_cluster_roles_warning_propagates():
    rbac_v1 = Mock()
    warning = "could not list ClusterRoles (403 Forbidden); ClusterRole-based roleRefs will be unresolvable"
    report = k8s_data.fetch_cluster_report(rbac_v1, {}, warning)
    assert report.error == warning
    rbac_v1.list_cluster_role_binding.assert_not_called()


# --- resolve_cluster_context ---------------------------------------------------


_CONTEXTS = [
    {"name": "kubernetes-admin@kubernetes", "context": {"cluster": "kubernetes", "user": "kubernetes-admin"}},
    {"name": "other-ctx", "context": {"cluster": "other-cluster", "user": "other-user"}},
]


def test_resolve_cluster_context_uses_active_when_no_explicit_context():
    with patch.object(
        k8s_data.config, "list_kube_config_contexts", return_value=(_CONTEXTS, _CONTEXTS[0])
    ), patch.object(
        k8s_data.client.Configuration, "get_default_copy",
        return_value=Mock(host="https://192.168.2.102:6443"),
    ):
        ctx = k8s_data.resolve_cluster_context(None, None)
    assert ctx.context == "kubernetes-admin@kubernetes"
    assert ctx.cluster == "kubernetes"
    assert ctx.server == "https://192.168.2.102:6443"


def test_resolve_cluster_context_matches_explicit_context():
    with patch.object(
        k8s_data.config, "list_kube_config_contexts", return_value=(_CONTEXTS, _CONTEXTS[0])
    ), patch.object(
        k8s_data.client.Configuration, "get_default_copy",
        return_value=Mock(host="https://192.168.2.102:6443"),
    ):
        ctx = k8s_data.resolve_cluster_context(None, "other-ctx")
    assert ctx.context == "other-ctx"
    assert ctx.cluster == "other-cluster"


def test_resolve_cluster_context_in_cluster_fallback():
    with patch.object(
        k8s_data.config, "list_kube_config_contexts",
        side_effect=k8s_data.config.ConfigException("no kubeconfig"),
    ), patch.object(
        k8s_data.client.Configuration, "get_default_copy",
        return_value=Mock(host="https://10.0.0.1:443"),
    ):
        ctx = k8s_data.resolve_cluster_context(None, None)
    assert ctx.context == "in-cluster"
    assert ctx.cluster is None
    assert ctx.server == "https://10.0.0.1:443"
