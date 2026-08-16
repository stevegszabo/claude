import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import html_report  # noqa: E402
import k8s_data  # noqa: E402

_CTX = k8s_data.ClusterContext(
    context="kubernetes-admin@kubernetes", cluster="kubernetes", server="https://192.168.2.102:6443"
)


def test_render_namespace_report_empty():
    report = k8s_data.NamespaceReport(namespace="ns1")
    html = html_report.render_namespace_report(report, _CTX)
    assert "ns1" in html
    assert "No Roles or RoleBindings found" in html


def test_render_namespace_report_shows_cluster_context():
    report = k8s_data.NamespaceReport(namespace="ns1")
    html = html_report.render_namespace_report(report, _CTX)
    assert "kubernetes-admin@kubernetes" in html
    assert "192.168.2.102:6443" in html


def test_render_namespace_report_error():
    report = k8s_data.NamespaceReport(namespace="ns1", error="403 Forbidden")
    html = html_report.render_namespace_report(report, _CTX)
    assert "403 Forbidden" in html


def test_render_namespace_report_with_role_and_binding():
    role = k8s_data.RoleInfo(
        name="pod-reader",
        kind="Role",
        rules=[k8s_data.PolicyRule(api_groups=[""], resources=["pods"], verbs=["get"])],
    )
    binding = k8s_data.RoleBindingInfo(
        name="binding1",
        subjects=[k8s_data.Subject(kind="ServiceAccount", name="sa1", namespace="ns1")],
        role_ref=k8s_data.RoleRef(kind="Role", name="pod-reader"),
        resolved_role=role,
    )
    report = k8s_data.NamespaceReport(namespace="ns1", roles=[role], role_bindings=[binding])
    html = html_report.render_namespace_report(report, _CTX)
    assert "pod-reader" in html
    assert "binding1" in html
    assert "sa1" in html
    assert "pods" in html


def test_render_namespace_report_dangling_ref_shows_warning():
    binding = k8s_data.RoleBindingInfo(
        name="binding1",
        subjects=[],
        role_ref=k8s_data.RoleRef(kind="Role", name="missing"),
        resolution_note="Role 'missing' not found in namespace 'ns1'",
    )
    report = k8s_data.NamespaceReport(namespace="ns1", role_bindings=[binding])
    html = html_report.render_namespace_report(report, _CTX)
    assert "not found" in html
    assert "warning-badge" in html


def test_render_cluster_report_with_data():
    role = k8s_data.RoleInfo(name="view", kind="ClusterRole", rules=[])
    binding = k8s_data.RoleBindingInfo(
        name="crb1",
        subjects=[k8s_data.Subject(kind="User", name="alice")],
        role_ref=k8s_data.RoleRef(kind="ClusterRole", name="view"),
        resolved_role=role,
    )
    report = k8s_data.ClusterReport(cluster_roles=[role], cluster_role_bindings=[binding])
    html = html_report.render_cluster_report(report, _CTX)
    assert "view" in html
    assert "crb1" in html
    assert "alice" in html


def test_render_namespace_report_escapes_html_in_names():
    role = k8s_data.RoleInfo(
        name="<script>alert(1)</script>",
        kind="Role",
        rules=[],
    )
    report = k8s_data.NamespaceReport(namespace="ns1", roles=[role])
    html = html_report.render_namespace_report(report, _CTX)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
