from flask import Blueprint, redirect, render_template, request, session, url_for

from . import k8s

bp = Blueprint("rbac", __name__)


def _selected_namespaces() -> list[str]:
    return [ns for ns in request.args.getlist("ns") if ns]


def _current_context() -> str | None:
    return session.get("kube_context") or None


@bp.route("/context", methods=["POST"])
def set_context():
    context = request.form.get("context") or ""
    if context:
        session["kube_context"] = context
    else:
        session.pop("kube_context", None)
    next_url = request.form.get("next") or url_for("rbac.index")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("rbac.index")
    return redirect(next_url)


@bp.route("/")
def index():
    return render_template("index.html")


# --- ClusterRole -----------------------------------------------------------


@bp.route("/clusterroles")
def clusterrole_list():
    roles = k8s.list_cluster_roles(context=_current_context())
    return render_template(
        "list.html",
        title="ClusterRoles",
        resource_kind="clusterroles",
        namespaced=False,
        items=roles,
    )


@bp.route("/clusterroles/<name>")
def clusterrole_detail(name):
    role = k8s.get_cluster_role(name, context=_current_context())
    return render_template("clusterrole_detail.html", role=role)


# --- ClusterRoleBinding ------------------------------------------------------


@bp.route("/clusterrolebindings")
def clusterrolebinding_list():
    bindings = k8s.list_cluster_role_bindings(context=_current_context())
    return render_template(
        "list.html",
        title="ClusterRoleBindings",
        resource_kind="clusterrolebindings",
        namespaced=False,
        items=bindings,
    )


@bp.route("/clusterrolebindings/<name>")
def clusterrolebinding_detail(name):
    binding = k8s.get_cluster_role_binding(name, context=_current_context())
    return render_template("clusterrolebinding_detail.html", binding=binding)


# --- Role --------------------------------------------------------------------


@bp.route("/roles")
def role_list():
    ctx = _current_context()
    all_namespaces = k8s.list_namespaces(context=ctx)
    selected = _selected_namespaces()
    items = k8s.list_roles(selected, context=ctx) if selected else []
    return render_template(
        "list.html",
        title="Roles",
        resource_kind="roles",
        namespaced=True,
        items=items,
        all_namespaces=all_namespaces,
        selected_namespaces=selected,
    )


@bp.route("/roles/<namespace>/<name>")
def role_detail(namespace, name):
    role = k8s.get_role(namespace, name, context=_current_context())
    return render_template("role_detail.html", role=role)


# --- RoleBinding ---------------------------------------------------------------


@bp.route("/rolebindings")
def rolebinding_list():
    ctx = _current_context()
    all_namespaces = k8s.list_namespaces(context=ctx)
    selected = _selected_namespaces()
    items = k8s.list_role_bindings(selected, context=ctx) if selected else []
    return render_template(
        "list.html",
        title="RoleBindings",
        resource_kind="rolebindings",
        namespaced=True,
        items=items,
        all_namespaces=all_namespaces,
        selected_namespaces=selected,
    )


@bp.route("/rolebindings/<namespace>/<name>")
def rolebinding_detail(namespace, name):
    binding = k8s.get_role_binding(namespace, name, context=_current_context())
    return render_template("rolebinding_detail.html", binding=binding)
