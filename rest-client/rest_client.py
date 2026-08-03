#!/usr/bin/env python3
"""Generic command-line REST API client."""
import argparse
import json
import os
import sys

import requests


def build_parser():
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "path", help="Request path, joined with --base-url to form the full URL"
    )
    parent.add_argument(
        "--base-url",
        default=os.environ.get("REST_CLIENT_BASE_URL"),
        help="Base URL to prefix the path with (default: $REST_CLIENT_BASE_URL)",
    )
    parent.add_argument(
        "-H",
        "--header",
        action="append",
        default=[],
        metavar="KEY: VALUE",
        help="Extra request header, repeatable, e.g. -H 'X-Vault-Token: ...'",
    )
    parent.add_argument(
        "-q",
        "--query",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Query string parameter, repeatable",
    )
    parent.add_argument(
        "-f",
        "--data-file",
        metavar="PATH",
        help="Read the JSON payload from this file (default: stdin, if piped)",
    )
    parent.add_argument(
        "--timeout", type=float, default=30, help="Request timeout in seconds (default: 30)"
    )
    parent.add_argument(
        "-k",
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification",
    )
    parent.add_argument(
        "--raw",
        action="store_true",
        help="Print the response body raw instead of pretty-printed JSON",
    )

    parser = argparse.ArgumentParser(description="Generic command-line REST API client")
    subparsers = parser.add_subparsers(dest="method", required=True)
    for method in ("get", "post", "put", "patch", "delete", "list"):
        subparsers.add_parser(method, parents=[parent], help=f"Send an HTTP {method.upper()} request")

    return parser


def parse_headers(raw_headers):
    headers = {}
    for item in raw_headers:
        if ":" in item:
            key, _, value = item.partition(":")
        elif "=" in item:
            key, _, value = item.partition("=")
        else:
            print(f"error: invalid header '{item}', expected 'Key: Value'", file=sys.stderr)
            sys.exit(2)
        headers[key.strip()] = value.strip()
    return headers


def parse_query_params(raw_params):
    params = {}
    for item in raw_params:
        if "=" not in item:
            print(f"error: invalid query param '{item}', expected 'key=value'", file=sys.stderr)
            sys.exit(2)
        key, _, value = item.partition("=")
        params[key.strip()] = value.strip()
    return params


def read_payload(args):
    if args.data_file:
        try:
            with open(args.data_file, "r") as f:
                text = f.read()
        except OSError as e:
            print(f"error: could not read data file: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.method in ("post", "put", "patch") and not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        return None

    text = text.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"error: payload is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)


def print_response(response, raw):
    print(f"HTTP {response.status_code} {response.reason}")
    if raw:
        print(response.text)
        return
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        if response.text:
            print(response.text)


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.base_url:
        print(
            "error: no base URL given (use --base-url or set $REST_CLIENT_BASE_URL)",
            file=sys.stderr,
        )
        sys.exit(2)

    headers = parse_headers(args.header)
    params = parse_query_params(args.query)
    payload = read_payload(args)
    url = args.base_url.rstrip("/") + "/" + args.path.lstrip("/")

    try:
        response = requests.request(
            args.method.upper(),
            url,
            headers=headers,
            params=params,
            json=payload,
            timeout=args.timeout,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        print(f"error: request failed: {e}", file=sys.stderr)
        sys.exit(1)

    print_response(response, args.raw)


if __name__ == "__main__":
    main()
