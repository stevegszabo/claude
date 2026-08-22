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
    cred_create.add_argument(
        "--token", default=None,
        help="Kubernetes service-account token. Falls back to the PPDM_TOKEN env var, then an interactive prompt.",
    )
    cred_create.add_argument("--username", default="null")
    cred_create.add_argument(
        "--skip-if-exists", action="store_true", dest="skip_if_exists",
        help=(
            "Check whether a credential with this exact name already exists "
            "before creating; if so, skip (no-op) instead of letting PPDM's "
            "create call fail."
        ),
    )

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
    clus_create.add_argument(
        "--skip-if-exists", action="store_true", dest="skip_if_exists",
        help=(
            "Check whether a cluster registration with this exact name already "
            "exists before creating; if so, skip (no-op) instead of letting "
            "PPDM's create call fail."
        ),
    )

    clus_update = cluster_action.add_parser("update", help="Update a cluster registration")
    clus_update.add_argument("--id", required=True)
    clus_update.add_argument("--address", help="New Kubernetes API server host/IP")
    cred_group = clus_update.add_mutually_exclusive_group()
    cred_group.add_argument("--credential-id", help="ID of an existing KUBERNETES credential")
    cred_group.add_argument("--credential-name", help="Name of an existing KUBERNETES credential")
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
    """Resolve the PPDM password, checked in this order: the --password
    flag, then the PPDM_PASSWORD env var, then an interactive (unechoed)
    prompt. Required for every command, unlike _resolve_token.
    """
    if args.password:
        return args.password
    env_password = os.environ.get("PPDM_PASSWORD")
    if env_password:
        return env_password
    return getpass.getpass("PPDM password for {}@{}: ".format(args.user, args.server))


def _resolve_token(args):
    """Resolve the Kubernetes service-account token for `credential create`,
    checked in the same order as _resolve_password: flag, then PPDM_TOKEN
    env var, then an interactive (unechoed) prompt.

    Not used for `credential update`, where --token is optional and
    omitting it means "leave the token unchanged" -- a fallback there would
    incorrectly prompt for/consume a token on updates that aren't rotating it.
    """
    if args.token:
        return args.token
    env_token = os.environ.get("PPDM_TOKEN")
    if env_token:
        return env_token
    return getpass.getpass("Kubernetes service-account token: ")


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
    """Dispatch a `credential` subcommand (list/get/create/update/delete)
    to the matching CredentialsAPI call and print the result.
    """
    api = CredentialsAPI(client)
    if args.action == "list":
        _print(api.list(name=args.name, id=args.id))
    elif args.action == "get":
        _print(api.get(args.id))
    elif args.action == "create":
        if args.skip_if_exists:
            existing = [c for c in api.list(name=args.name) if c.get("name") == args.name]
            if existing:
                print("Credential '{}' already exists, skipping.".format(args.name))
                return
        _print(api.create(name=args.name, token=_resolve_token(args), username=args.username))
    elif args.action == "update":
        _print(api.update(args.id, name=args.name, token=args.token, username=args.username))
    elif args.action == "delete":
        if not args.yes and not _confirm("Delete credential {}?".format(args.id)):
            print("Aborted.")
            return
        api.delete(args.id)
        print("Credential {} deleted.".format(args.id))


def _run_cluster(client, args):
    """Dispatch a `cluster` subcommand (list/get/create/update/delete) to
    the matching RegistrationsAPI call and print the result. For
    create/update, resolves --credential-name to an ID via CredentialsAPI
    first, since RegistrationsAPI itself only accepts a credential ID.
    """
    api = RegistrationsAPI(client)
    if args.action == "list":
        _print(api.list(name=args.name, id=args.id))
    elif args.action == "get":
        _print(api.get(args.id))
    elif args.action == "create":
        if args.skip_if_exists:
            existing = [c for c in api.list(name=args.name) if c.get("name") == args.name]
            if existing:
                print("Cluster registration '{}' already exists, skipping.".format(args.name))
                return
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
            address=args.address,
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
