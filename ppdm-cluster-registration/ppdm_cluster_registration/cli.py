import argparse
import getpass
import json
import os
import sys

from .client import PPDMClient
from .credentials import CredentialsAPI
from .registrations import RegistrationsAPI
from .exceptions import PPDMAPIError


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="register_cluster.py",
        description="Register and manage Kubernetes clusters with Dell PowerProtect Data Manager (PPDM).",
    )
    parser.add_argument("-s", "--server", required=True, help="PPDM DNS name or IP")
    parser.add_argument("--port", type=int, default=8443, help="PPDM REST API port (default: 8443)")
    parser.add_argument("-usr", "--user", default="admin", help="PPDM username (default: admin)")
    parser.add_argument(
        "-pwd", "--password", default=None,
        help="PPDM password. Falls back to the PPDM_PASSWORD env var, then an interactive prompt.",
    )
    parser.add_argument(
        "--insecure", action="store_true",
        help="Skip TLS certificate verification (e.g. for a lab appliance with a self-signed cert).",
    )

    resource = parser.add_subparsers(dest="resource", required=True)

    credential = resource.add_parser("credential", help="Manage Kubernetes service-account credentials")
    credential_action = credential.add_subparsers(dest="action", required=True)

    cred_list = credential_action.add_parser("list", help="List credentials")
    cred_list.add_argument("--name", help="Filter by name (substring match)")
    cred_list.add_argument("--id", help="Filter by ID (substring match)")

    cred_get = credential_action.add_parser("get", help="Get a credential by ID")
    cred_get.add_argument("--id", required=True)

    cred_create = credential_action.add_parser("create", help="Create a credential")
    cred_create.add_argument("--name", required=True)
    cred_create.add_argument("--token", required=True, help="Kubernetes service-account token")
    cred_create.add_argument("--username", default="null")

    cred_update = credential_action.add_parser("update", help="Update a credential")
    cred_update.add_argument("--id", required=True)
    cred_update.add_argument("--name", help="New name")
    cred_update.add_argument("--token", help="New service-account token")
    cred_update.add_argument("--username", help="New username")

    cred_delete = credential_action.add_parser("delete", help="Delete a credential")
    cred_delete.add_argument("--id", required=True)
    cred_delete.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    cluster = resource.add_parser("cluster", help="Manage Kubernetes cluster registrations")
    cluster_action = cluster.add_subparsers(dest="action", required=True)

    clus_list = cluster_action.add_parser("list", help="List cluster registrations")
    clus_list.add_argument("--name", help="Filter by name (substring match)")
    clus_list.add_argument("--id", help="Filter by ID (substring match)")

    clus_get = cluster_action.add_parser("get", help="Get a cluster registration by ID")
    clus_get.add_argument("--id", required=True)

    clus_create = cluster_action.add_parser("create", help="Register a cluster")
    clus_create.add_argument("--name", required=True)
    clus_create.add_argument("--address", required=True, help="Kubernetes API server host/IP")
    clus_create.add_argument(
        "--k8s-port", type=int, default=6443, dest="k8s_port",
        help="Kubernetes API server port (default: 6443). Distinct from the top-level --port, which is PPDM's own API port.",
    )
    cred_group = clus_create.add_mutually_exclusive_group(required=True)
    cred_group.add_argument("--credential-id", help="ID of an existing KUBERNETES credential")
    cred_group.add_argument("--credential-name", help="Name of an existing KUBERNETES credential")
    clus_create.add_argument(
        "--distribution-type", choices=["TANZU_GUEST_CLUSTER", "VANILLA_ON_VSPHERE", "NON_VSPHERE"],
    )
    clus_create.add_argument("--update-mode", choices=["AUTO", "MANUAL"])
    clus_create.add_argument(
        "--config", action="append", metavar="KEY=VALUE",
        help="Set a controller configuration entry (repeatable)",
    )

    clus_update = cluster_action.add_parser("update", help="Update a cluster registration")
    clus_update.add_argument("--id", required=True)
    clus_update.add_argument("--credential-id")
    clus_update.add_argument("--credential-name")
    clus_update.add_argument("--update-mode", choices=["AUTO", "MANUAL"])
    clus_update.add_argument(
        "--config", action="append", metavar="KEY=VALUE",
        help="Set a controller configuration entry (repeatable)",
    )

    clus_delete = cluster_action.add_parser("delete", help="Delete a cluster registration")
    clus_delete.add_argument("--id", required=True)
    clus_delete.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    clus_delete.add_argument(
        "--cleanup", action="store_true",
        help=(
            "Before deleting, unassign the cluster's assets from any protection policies "
            "and asset groups, as PPDM requires."
        ),
    )

    return parser


def _resolve_password(args):
    if args.password:
        return args.password
    env_password = os.environ.get("PPDM_PASSWORD")
    if env_password:
        return env_password
    return getpass.getpass("PPDM password for {}@{}: ".format(args.user, args.server))


def _confirm(prompt):
    reply = input("{} (y/n) ".format(prompt)).strip().lower()
    return reply in ("y", "yes")


def _print(result):
    if result is not None:
        print(json.dumps(result, indent=2))


def _parse_configs(config_args):
    if not config_args:
        return None
    configurations = []
    for item in config_args:
        if "=" not in item:
            raise ValueError("--config must be in KEY=VALUE form, got: {}".format(item))
        key, value = item.split("=", 1)
        configurations.append({"type": "CONTROLLER_CONFIG", "key": key, "value": value})
    return configurations


def _run_credential(client, args):
    api = CredentialsAPI(client)
    if args.action == "list":
        _print(api.list(name=args.name, id=args.id))
    elif args.action == "get":
        _print(api.get(args.id))
    elif args.action == "create":
        _print(api.create(name=args.name, token=args.token, username=args.username))
    elif args.action == "update":
        _print(api.update(args.id, name=args.name, token=args.token, username=args.username))
    elif args.action == "delete":
        if not args.yes and not _confirm("Delete credential {}?".format(args.id)):
            print("Aborted.")
            return
        api.delete(args.id)
        print("Credential {} deleted.".format(args.id))


def _run_cluster(client, args):
    api = RegistrationsAPI(client)
    if args.action == "list":
        _print(api.list(name=args.name, id=args.id))
    elif args.action == "get":
        _print(api.get(args.id))
    elif args.action == "create":
        credentials_api = CredentialsAPI(client)
        credential_id = credentials_api.resolve_id(name=args.credential_name, id=args.credential_id)
        _print(api.create(
            name=args.name,
            address=args.address,
            credential_id=credential_id,
            port=args.k8s_port,
            distribution_type=args.distribution_type,
            update_mode=args.update_mode,
            configurations=_parse_configs(args.config),
        ))
    elif args.action == "update":
        credential_id = args.credential_id
        if args.credential_name:
            credentials_api = CredentialsAPI(client)
            credential_id = credentials_api.resolve_id(name=args.credential_name)
        _print(api.update(
            args.id,
            credential_id=credential_id,
            update_mode=args.update_mode,
            configurations=_parse_configs(args.config),
        ))
    elif args.action == "delete":
        if not args.yes and not _confirm("Delete cluster registration {}?".format(args.id)):
            print("Aborted.")
            return
        if args.cleanup:
            summary = api.cleanup(args.id)
            print(
                "Cleaned up {} asset(s): unassigned from {} protection polic{}, "
                "{} asset group{}.".format(
                    summary["assets_processed"],
                    len(summary["protection_policies_unassigned"]),
                    "y" if len(summary["protection_policies_unassigned"]) == 1 else "ies",
                    len(summary["asset_groups_unassigned"]),
                    "" if len(summary["asset_groups_unassigned"]) == 1 else "s",
                )
            )
        api.delete(args.id)
        print("Cluster registration {} deleted.".format(args.id))


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    password = _resolve_password(args)

    try:
        with PPDMClient(
            server=args.server,
            username=args.user,
            password=password,
            port=args.port,
            verify_ssl=not args.insecure,
        ) as client:
            if args.resource == "credential":
                _run_credential(client, args)
            elif args.resource == "cluster":
                _run_cluster(client, args)
    except PPDMAPIError as err:
        print("Error: {}".format(err), file=sys.stderr)
        return 1
    except ValueError as err:
        print("Error: {}".format(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
