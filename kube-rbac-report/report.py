#!/usr/bin/env python3
"""Generate per-namespace and cluster-level Kubernetes RBAC HTML reports.

Usage:
    python report.py [-n NAMESPACE ...] [-o OUTPUT_DIR] [--kubeconfig PATH] [--context CTX]
"""

import argparse
import os
import sys
from typing import List, Optional

import html_report
import k8s_data


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="report.py",
        description="Generate per-namespace and cluster-level Kubernetes RBAC HTML reports.",
    )
    parser.add_argument(
        "-n",
        "--namespace",
        action="append",
        dest="namespaces",
        help="Limit to this namespace; repeatable and/or comma-separated. Default: all namespaces.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="reports",
        help="Directory to write HTML reports into (default: ./reports)",
    )
    parser.add_argument(
        "--kubeconfig",
        default=None,
        help="Path to kubeconfig (default: standard resolution, in-cluster fallback)",
    )
    parser.add_argument(
        "--context",
        default=None,
        help="kubeconfig context to use (default: current-context)",
    )
    return parser.parse_args(argv)


def expand_namespaces(raw: Optional[List[str]]) -> Optional[List[str]]:
    if not raw:
        return None
    out = []
    for item in raw:
        out.extend(p.strip() for p in item.split(",") if p.strip())
    return out or None


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    ns_filter = expand_namespaces(args.namespaces)

    try:
        core_v1, rbac_v1, cluster_context = k8s_data.build_api_clients(args.kubeconfig, args.context)
        namespaces = k8s_data.list_target_namespaces(core_v1, ns_filter)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    cluster_roles, cr_warning = k8s_data.fetch_cluster_roles(rbac_v1)
    if cr_warning:
        print(f"WARNING: {cr_warning}", file=sys.stderr)

    os.makedirs(args.output_dir, exist_ok=True)

    exit_code = 0

    cluster_report = k8s_data.fetch_cluster_report(rbac_v1, cluster_roles, cr_warning)
    if cluster_report.error:
        print(f"WARNING: cluster report: {cluster_report.error}", file=sys.stderr)
        exit_code = 2
    cluster_out_path = os.path.join(args.output_dir, "cluster.html")
    with open(cluster_out_path, "w", encoding="utf-8") as f:
        f.write(html_report.render_cluster_report(cluster_report, cluster_context))
    print(f"wrote {cluster_out_path}")

    for ns in namespaces:
        report = k8s_data.fetch_namespace_report(
            core_v1, rbac_v1, ns, cluster_roles, cr_warning, verify_exists=bool(ns_filter)
        )
        if report.error:
            print(f"WARNING: {ns}: {report.error}", file=sys.stderr)
            exit_code = 2
        out_path = os.path.join(args.output_dir, f"{ns}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_report.render_namespace_report(report, cluster_context))
        print(f"wrote {out_path}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
