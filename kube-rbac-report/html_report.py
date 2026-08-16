"""Render NamespaceReport / ClusterReport data into standalone HTML files."""

from datetime import datetime, timezone

import jinja2

from k8s_data import ClusterContext, ClusterReport, NamespaceReport

_STYLE = """
:root {
  --color-bg: #eef1f6;
  --color-surface: #ffffff;
  --color-surface-alt: #f8fafc;
  --color-border: #dde3ec;
  --color-text: #1e293b;
  --color-text-muted: #64748b;
  --color-accent: #2563eb;
  --color-accent-dark: #1e3a8a;
  --color-accent-soft: #dbeafe;
  --color-role-badge-bg: #dbeafe;
  --color-role-badge-text: #1e40af;
  --color-clusterrole-badge-bg: #e0e7ff;
  --color-clusterrole-badge-text: #3730a3;
  --color-warning-bg: #fff7e6;
  --color-warning-border: #f6c976;
  --color-warning-text: #7a4e00;
  --color-error-bg: #fdecea;
  --color-error-border: #f3aca5;
  --color-error-text: #7f1d1d;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  margin: 0; padding: 2.5rem 1.5rem 4rem;
  color: var(--color-text); background: var(--color-bg);
  line-height: 1.5;
}
.page {
  max-width: 1100px; margin: 0 auto; background: var(--color-surface);
  border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(30, 41, 59, 0.08);
}
h1 {
  margin: 0; padding: 1.6rem 2rem;
  background: linear-gradient(135deg, var(--color-accent-dark), var(--color-accent));
  color: #fff; font-size: 1.5rem; letter-spacing: 0.01em;
  border-bottom: 3px solid var(--color-accent-dark);
}
.meta {
  color: var(--color-text-muted); font-size: 0.85rem;
  background: var(--color-surface); margin: 0; padding: 0.6rem 2rem 0;
}
.meta::before { content: "\\1F551\\FE0E  "; }
.context-line {
  color: var(--color-text-muted); font-size: 0.85rem;
  background: var(--color-surface); margin: 0; padding: 0.3rem 2rem 0;
}
.context-line::before { content: "\\1F310\\FE0E  "; }
.context-line strong { color: var(--color-text); font-weight: 600; }
.context-line code { font-size: 0.85em; }
.stats-bar {
  background: var(--color-surface); margin: 0; padding: 0.6rem 2rem 1.4rem;
  border-bottom: 1px solid var(--color-border); display: flex; gap: 0.6rem; flex-wrap: wrap;
}
.stats-bar:empty { display: none; }
.stat-pill {
  display: inline-block; background: var(--color-accent-soft); color: var(--color-accent-dark);
  font-size: 0.85rem; font-weight: 600; padding: 0.3rem 0.75rem; border-radius: 999px;
}
main { display: block; padding: 1.5rem 2rem 2rem; }
h2 {
  border: none; border-left: 4px solid var(--color-accent); background: var(--color-surface-alt);
  padding: 0.45rem 0.8rem; margin-top: 2rem; border-radius: 0 6px 6px 0;
  font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-accent-dark);
}
details {
  border: 1px solid var(--color-border); border-left: 3px solid var(--color-accent);
  border-radius: 8px; margin: 0.7rem 0; padding: 0.6rem 0.9rem;
  background: var(--color-surface); box-shadow: 0 1px 2px rgba(30, 41, 59, 0.04);
  transition: box-shadow 0.15s ease;
}
details:hover { box-shadow: 0 2px 6px rgba(30, 41, 59, 0.1); }
details > summary {
  font-weight: 600; cursor: pointer; padding: 0.2rem 0; list-style: none;
  display: flex; align-items: center; gap: 0.5rem;
}
details > summary::-webkit-details-marker { display: none; }
details > summary::before {
  content: "\\25B8"; display: inline-block; color: var(--color-accent);
  transition: transform 0.15s ease; font-size: 0.8em;
}
details[open] > summary::before { transform: rotate(90deg); }
.kind-badge {
  display: inline-block; font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.03em; padding: 0.15rem 0.5rem; border-radius: 999px;
}
.kind-badge.kind-role, .kind-badge.kind-rolebinding {
  background: var(--color-role-badge-bg); color: var(--color-role-badge-text);
}
.kind-badge.kind-clusterrole, .kind-badge.kind-clusterrolebinding {
  background: var(--color-clusterrole-badge-bg); color: var(--color-clusterrole-badge-text);
}
table { border-collapse: collapse; width: 100%; margin: 0.6rem 0; font-size: 0.88rem;
        border-radius: 6px; overflow: hidden; }
th, td { border: 1px solid var(--color-border); padding: 0.4rem 0.65rem; text-align: left; vertical-align: top; }
th { background: var(--color-accent-dark); color: #fff; font-weight: 600; font-size: 0.8rem;
     text-transform: uppercase; letter-spacing: 0.03em; }
tbody tr:nth-child(even) { background: var(--color-surface-alt); }
tbody tr:hover { background: var(--color-accent-soft); }
code { background: var(--color-accent-soft); color: var(--color-accent-dark);
       padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.85em; }
.error-banner {
  background: var(--color-error-bg); border: 1px solid var(--color-error-border);
  color: var(--color-error-text); padding: 0.8rem 1rem; border-radius: 6px; margin: 1rem 0;
  font-weight: 600;
}
.error-banner::before { content: "\\2715  "; }
.empty-note { color: var(--color-text-muted); font-style: italic; }
.warning-badge {
  display: inline-block; background: var(--color-warning-bg); border: 1px solid var(--color-warning-border);
  color: var(--color-warning-text); padding: 0.3rem 0.6rem; border-radius: 4px; font-size: 0.85rem;
  font-weight: 600;
}
.warning-badge::before { content: "\\26A0\\FE0E  "; }
.resolved-label { color: var(--color-text-muted); font-size: 0.85rem; margin: 0.4rem 0 0.2rem; }
.sub-heading {
  font-weight: 700; margin: 0.7rem 0 0.3rem; font-size: 0.8rem; text-transform: uppercase;
  letter-spacing: 0.04em; color: var(--color-text-muted);
}
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
<summary><span class="kind-badge kind-{{ role.kind|lower }}">{{ role.kind }}</span> {{ role.name }}</summary>
{{ rules_table(role.rules) }}
</details>
{%- endmacro %}

{% macro binding_details(binding, kind='RoleBinding') -%}
<details>
<summary><span class="kind-badge kind-{{ kind|lower }}">{{ kind }}</span> {{ binding.name }}</summary>
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
<div class="page">
<h1>{{ title }}</h1>
<p class="meta">Generated {{ generated_at }}</p>
<p class="context-line">Context: <strong>{{ cluster_context.context }}</strong>{% if cluster_context.cluster %} &middot; Cluster: <strong>{{ cluster_context.cluster }}</strong>{% endif %}{% if cluster_context.server %} &middot; Server: <code>{{ cluster_context.server }}</code>{% endif %}</p>
"""

_NAMESPACE_TEMPLATE_SRC = (
    _MACROS
    + _BASE_HEAD
    + """
<div class="stats-bar">
{% if not report.error %}
<span class="stat-pill">{{ report.roles|length }} Role{{ 's' if report.roles|length != 1 }}</span>
<span class="stat-pill">{{ report.role_bindings|length }} RoleBinding{{ 's' if report.role_bindings|length != 1 }}</span>
{% endif %}
</div>
<main>
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
</main>
</div>
</body>
</html>
"""
)

_CLUSTER_TEMPLATE_SRC = (
    _MACROS
    + _BASE_HEAD
    + """
<div class="stats-bar">
{% if not report.error %}
<span class="stat-pill">{{ report.cluster_roles|length }} ClusterRole{{ 's' if report.cluster_roles|length != 1 }}</span>
<span class="stat-pill">{{ report.cluster_role_bindings|length }} ClusterRoleBinding{{ 's' if report.cluster_role_bindings|length != 1 }}</span>
{% endif %}
</div>
<main>
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
{% for binding in report.cluster_role_bindings %}{{ binding_details(binding, kind='ClusterRoleBinding') }}{% endfor %}
{% else %}
<p class="empty-note">No ClusterRoleBindings found.</p>
{% endif %}
{% endif %}
</main>
</div>
</body>
</html>
"""
)

_ENV = jinja2.Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
_NAMESPACE_TEMPLATE = _ENV.from_string(_NAMESPACE_TEMPLATE_SRC)
_CLUSTER_TEMPLATE = _ENV.from_string(_CLUSTER_TEMPLATE_SRC)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def render_namespace_report(report: NamespaceReport, cluster_context: ClusterContext) -> str:
    return _NAMESPACE_TEMPLATE.render(
        report=report,
        cluster_context=cluster_context,
        title=f"RBAC Report: namespace {report.namespace}",
        generated_at=_now(),
    )


def render_cluster_report(report: ClusterReport, cluster_context: ClusterContext) -> str:
    return _CLUSTER_TEMPLATE.render(
        report=report,
        cluster_context=cluster_context,
        title="RBAC Report: cluster-level roles",
        generated_at=_now(),
    )
