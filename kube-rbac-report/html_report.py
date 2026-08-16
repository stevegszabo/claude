"""Render NamespaceReport / ClusterReport data into standalone HTML files."""

from datetime import datetime, timezone

import jinja2

from k8s_data import ClusterReport, NamespaceReport

_STYLE = """
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
       margin: 2rem; color: #1a1a1a; background: #fff; }
h1 { margin-bottom: 0.1rem; }
.meta { color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }
h2 { border-bottom: 2px solid #ddd; padding-bottom: 0.3rem; margin-top: 2rem; }
details { border: 1px solid #ddd; border-radius: 6px; margin: 0.6rem 0; padding: 0.5rem 0.8rem; }
details > summary { font-weight: 600; cursor: pointer; padding: 0.2rem 0; }
table { border-collapse: collapse; width: 100%; margin: 0.5rem 0; font-size: 0.9rem; }
th, td { border: 1px solid #ddd; padding: 0.35rem 0.6rem; text-align: left; vertical-align: top; }
th { background: #f5f5f5; }
code { background: #f0f0f0; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.85em; }
.error-banner { background: #fdecea; border: 1px solid #f5c6cb; color: #611a15;
                padding: 0.8rem 1rem; border-radius: 6px; margin: 1rem 0; }
.empty-note { color: #666; font-style: italic; }
.warning-badge { display: inline-block; background: #fff3cd; border: 1px solid #ffe69c;
                 color: #664d03; padding: 0.3rem 0.6rem; border-radius: 4px; font-size: 0.85rem; }
.resolved-label { color: #444; font-size: 0.85rem; margin: 0.4rem 0 0.2rem; }
.sub-heading { font-weight: 600; margin: 0.6rem 0 0.2rem; }
"""

_MACROS = """
{% macro rules_table(rules) -%}
{% if rules %}
<table>
<tr><th>API Groups</th><th>Resources</th><th>Resource Names</th><th>Verbs</th><th>Non-Resource URLs</th></tr>
{% for rule in rules %}
<tr>
<td>{% for g in rule.api_groups %}<code>{{ g if g else '""' }}</code> {% endfor %}</td>
<td>{% for r in rule.resources %}<code>{{ r }}</code> {% endfor %}</td>
<td>{% for n in rule.resource_names %}<code>{{ n }}</code> {% endfor %}</td>
<td>{% for v in rule.verbs %}<code>{{ v }}</code> {% endfor %}</td>
<td>{% for u in rule.non_resource_urls %}<code>{{ u }}</code> {% endfor %}</td>
</tr>
{% endfor %}
</table>
{% else %}
<p class="empty-note">No rules.</p>
{% endif %}
{%- endmacro %}

{% macro role_details(role) -%}
<details>
<summary>{{ role.kind }}: {{ role.name }}</summary>
{{ rules_table(role.rules) }}
</details>
{%- endmacro %}

{% macro binding_details(binding) -%}
<details>
<summary>{{ binding.name }}</summary>
<div class="sub-heading">Subjects</div>
{% if binding.subjects %}
<table>
<tr><th>Kind</th><th>Name</th><th>Namespace</th><th>API Group</th></tr>
{% for s in binding.subjects %}
<tr><td>{{ s.kind }}</td><td>{{ s.name }}</td><td>{{ s.namespace or '' }}</td><td>{{ s.api_group or '' }}</td></tr>
{% endfor %}
</table>
{% else %}
<p class="empty-note">No subjects.</p>
{% endif %}
<div class="sub-heading">Role Ref</div>
<p><code>{{ binding.role_ref.kind }}</code> / <code>{{ binding.role_ref.name }}</code></p>
{% if binding.resolution_note %}
<p><span class="warning-badge">{{ binding.resolution_note }}</span></p>
{% elif binding.resolved_role %}
<p class="resolved-label">Rules (resolved from {{ binding.resolved_role.kind }} '{{ binding.resolved_role.name }}')</p>
{{ rules_table(binding.resolved_role.rules) }}
{% endif %}
</details>
{%- endmacro %}
"""

_BASE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<style>""" + _STYLE + """</style>
</head>
<body>
<h1>{{ title }}</h1>
<p class="meta">Generated {{ generated_at }}</p>
"""

_NAMESPACE_TEMPLATE_SRC = (
    _MACROS
    + _BASE_HEAD
    + """
{% if report.error %}
<div class="error-banner">Error: {{ report.error }}</div>
{% else %}
{% if not report.roles and not report.role_bindings %}
<p class="empty-note">No Roles or RoleBindings found in this namespace.</p>
{% else %}
<h2>Roles ({{ report.roles|length }})</h2>
{% if report.roles %}
{% for role in report.roles %}{{ role_details(role) }}{% endfor %}
{% else %}
<p class="empty-note">No Roles in this namespace.</p>
{% endif %}

<h2>RoleBindings ({{ report.role_bindings|length }})</h2>
{% if report.role_bindings %}
{% for binding in report.role_bindings %}{{ binding_details(binding) }}{% endfor %}
{% else %}
<p class="empty-note">No RoleBindings in this namespace.</p>
{% endif %}
{% endif %}
{% endif %}
</body>
</html>
"""
)

_CLUSTER_TEMPLATE_SRC = (
    _MACROS
    + _BASE_HEAD
    + """
{% if report.error %}
<div class="error-banner">Error: {{ report.error }}</div>
{% endif %}
{% if not report.error or report.cluster_roles %}
<h2>ClusterRoles ({{ report.cluster_roles|length }})</h2>
{% if report.cluster_roles %}
{% for role in report.cluster_roles %}{{ role_details(role) }}{% endfor %}
{% else %}
<p class="empty-note">No ClusterRoles found.</p>
{% endif %}
{% endif %}

{% if not report.error %}
<h2>ClusterRoleBindings ({{ report.cluster_role_bindings|length }})</h2>
{% if report.cluster_role_bindings %}
{% for binding in report.cluster_role_bindings %}{{ binding_details(binding) }}{% endfor %}
{% else %}
<p class="empty-note">No ClusterRoleBindings found.</p>
{% endif %}
{% endif %}
</body>
</html>
"""
)

_ENV = jinja2.Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
_NAMESPACE_TEMPLATE = _ENV.from_string(_NAMESPACE_TEMPLATE_SRC)
_CLUSTER_TEMPLATE = _ENV.from_string(_CLUSTER_TEMPLATE_SRC)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def render_namespace_report(report: NamespaceReport) -> str:
    return _NAMESPACE_TEMPLATE.render(
        report=report,
        title=f"RBAC Report: namespace {report.namespace}",
        generated_at=_now(),
    )


def render_cluster_report(report: ClusterReport) -> str:
    return _CLUSTER_TEMPLATE.render(
        report=report,
        title="RBAC Report: cluster-level roles",
        generated_at=_now(),
    )
