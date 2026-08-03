# rest-client

A generic command-line REST API client (`rest_client.py`) supporting GET, POST, PUT,
PATCH, DELETE, and LIST, with JSON payloads read from a file or stdin.

## Requirements

- Python 3
- [`requests`](https://pypi.org/project/requests/)

```bash
pip3 install requests
```

## Usage

```bash
./rest_client.py <get|post|put|patch|delete|list> <path> [options]
```

`<path>` is joined with `--base-url` to form the full request URL.

### Options

| Flag | Description |
| --- | --- |
| `--base-url URL` | Base URL to prefix `<path>` with. Defaults to `$REST_CLIENT_BASE_URL` if not given. |
| `-H, --header "Key: Value"` | Extra request header. Repeatable. |
| `-q, --query "key=value"` | Query string parameter. Repeatable. |
| `-f, --data-file PATH` | Read the JSON payload from this file. |
| `--timeout SECONDS` | Request timeout (default: 30). |
| `-k, --insecure` | Disable TLS certificate verification. |
| `--raw` | Print the response body raw instead of pretty-printed JSON. |

### JSON payload

For `post`, `put`, and `patch`, the JSON payload is read, in order of precedence:

1. From the file given via `-f/--data-file`
2. Otherwise from stdin, if data is piped in
3. Otherwise no body is sent

The payload is validated as JSON before the request is sent.

### Output

Prints the response status line followed by the pretty-printed JSON body (or raw text if
the body isn't JSON, or always raw with `--raw`).

Exit codes:
- `0` — request completed (regardless of HTTP status code, e.g. a 404 still exits 0)
- `1` — network error (connection refused, timeout, etc.)
- `2` — usage error (missing base URL, malformed header/query flag, invalid JSON payload)

## Examples

These examples target a local HashiCorp Vault dev server, using the `VAULT_ADDR` and
`VAULT_TOKEN` environment variables Vault sets up for you. They work the same way against
any REST API — just swap in a different `--base-url` and auth header.

**GET**
```bash
./rest_client.py get v1/sys/health --base-url "$VAULT_ADDR"
```

**POST** (payload from stdin)
```bash
echo '{"data":{"foo":"bar"}}' | ./rest_client.py post v1/monster/data/myapp \
  --base-url "$VAULT_ADDR" -H "X-Vault-Token: $VAULT_TOKEN"
```

**PUT** (payload from a file)
```bash
./rest_client.py put v1/monster/data/myapp \
  --base-url "$VAULT_ADDR" -H "X-Vault-Token: $VAULT_TOKEN" -f payload.json
```

**PATCH** (partial update; Vault's kv-v2 requires the JSON Merge Patch content type)
```bash
echo '{"data":{"extra":"field"}}' | ./rest_client.py patch v1/monster/data/myapp \
  --base-url "$VAULT_ADDR" -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "Content-Type: application/merge-patch+json"
```

**DELETE**
```bash
./rest_client.py delete v1/monster/data/myapp \
  --base-url "$VAULT_ADDR" -H "X-Vault-Token: $VAULT_TOKEN"
```

**LIST** (non-standard HTTP verb used by Vault-style APIs; for kv-v2 this targets the
mount's `metadata` path, not `data`)
```bash
./rest_client.py list v1/monster/metadata \
  --base-url "$VAULT_ADDR" -H "X-Vault-Token: $VAULT_TOKEN"
```

You can also avoid repeating `--base-url` by exporting it once:
```bash
export REST_CLIENT_BASE_URL="$VAULT_ADDR"
./rest_client.py get v1/sys/health
```

## Running the tests

`tests/test_rest_client.py` runs one integration test per HTTP method against a live Vault
dev server (using `VAULT_ADDR`/`VAULT_TOKEN`), exercising a real secret's lifecycle:
create (POST) → replace (PUT) → list → partial update (PATCH) → read → delete. It cleans up
the test secret afterward.

```bash
python3 -m unittest discover -s tests -v
```
