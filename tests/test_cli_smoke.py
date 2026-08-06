"""Smoke tests for the PPDM cluster registration CLI.

Uses only unittest.mock (no extra test dependency) to fake out `requests`,
so every credential/cluster operation can be exercised end-to-end through
the CLI without a real PPDM appliance. Each test asserts the exact HTTP
method, URL, and JSON body sent for every call PPDM would receive.
"""
import contextlib
import io
import unittest
from unittest import mock

from ppdm_cluster_registration.cli import main

BASE = "https://ppdm.example.com:8443/api/v2"


class FakeResponse:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json_body = json_body
        self.content = b"{}" if json_body is not None else b""

    def json(self):
        if self._json_body is None:
            raise ValueError("response has no JSON body")
        return self._json_body

    @property
    def text(self):
        return str(self._json_body)


def sequenced_request(responses):
    """Returns (mock_fn, calls) where mock_fn pops one FakeResponse per
    call (in order) and calls records (method, url, kwargs) for each call.
    """
    calls = []
    queue = list(responses)

    def _fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if not queue:
            raise AssertionError("Unexpected extra HTTP call: {} {}".format(method, url))
        return queue.pop(0)

    return _fake, calls


LOGIN_OK = FakeResponse(200, {"access_token": "fake-token", "expires_in": 3600})
LOGOUT_OK = FakeResponse(204, None)


def run_cli(argv, responses):
    fake, calls = sequenced_request(responses)
    stdout = io.StringIO()
    with mock.patch("requests.request", side_effect=fake):
        with contextlib.redirect_stdout(stdout):
            exit_code = main([
                "--server", "ppdm.example.com",
                "--user", "admin",
                "--password", "sekret",
            ] + argv)
    return exit_code, stdout.getvalue(), calls


class CredentialCLITests(unittest.TestCase):
    def test_list(self):
        exit_code, out, calls = run_cli(
            ["credential", "list", "--name", "prod"],
            [LOGIN_OK, FakeResponse(200, {"content": [{"id": "c1", "name": "prod-cred"}]}), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("prod-cred", out)

        method, url, kwargs = calls[1]
        self.assertEqual(method, "GET")
        self.assertEqual(url, BASE + "/credentials")
        self.assertIn('type eq "KUBERNETES"', kwargs["params"]["filter"])
        self.assertIn('name lk "%prod%"', kwargs["params"]["filter"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-token")

    def test_get(self):
        exit_code, out, calls = run_cli(
            ["credential", "get", "--id", "c1"],
            [LOGIN_OK, FakeResponse(200, {"id": "c1", "name": "prod-cred"}), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "GET")
        self.assertEqual(url, BASE + "/credentials/c1")

    def test_create(self):
        exit_code, out, calls = run_cli(
            ["credential", "create", "--name", "prod-cred", "--token", "sa-token-123"],
            [LOGIN_OK, FakeResponse(201, {"id": "c1", "name": "prod-cred"}), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(url, BASE + "/credentials")
        body = kwargs["json"]
        self.assertEqual(body["name"], "prod-cred")
        self.assertEqual(body["password"], "sa-token-123")
        self.assertEqual(body["type"], "KUBERNETES")
        self.assertEqual(body["method"], "TOKEN")

    def test_update(self):
        exit_code, out, calls = run_cli(
            ["credential", "update", "--id", "c1", "--token", "new-token"],
            [
                LOGIN_OK,
                FakeResponse(200, {"id": "c1", "name": "prod-cred", "username": "null",
                                    "type": "KUBERNETES", "method": "TOKEN", "internal": False}),
                FakeResponse(200, {"id": "c1", "name": "prod-cred"}),
                LOGOUT_OK,
            ],
        )
        self.assertEqual(exit_code, 0)
        get_method, get_url, _ = calls[1]
        self.assertEqual((get_method, get_url), ("GET", BASE + "/credentials/c1"))
        put_method, put_url, put_kwargs = calls[2]
        self.assertEqual(put_method, "PUT")
        self.assertEqual(put_url, BASE + "/credentials/c1")
        self.assertEqual(put_kwargs["json"]["password"], "new-token")
        self.assertEqual(put_kwargs["json"]["name"], "prod-cred")

    def test_delete(self):
        exit_code, out, calls = run_cli(
            ["credential", "delete", "--id", "c1", "--yes"],
            [LOGIN_OK, FakeResponse(204, None), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("deleted", out)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "DELETE")
        self.assertEqual(url, BASE + "/credentials/c1")


class ClusterCLITests(unittest.TestCase):
    def test_list(self):
        exit_code, out, calls = run_cli(
            ["cluster", "list"],
            [LOGIN_OK, FakeResponse(200, {"content": [{"id": "k1", "name": "my-cluster"}]}), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("my-cluster", out)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "GET")
        self.assertEqual(url, BASE + "/inventory-sources")
        self.assertIn('type eq "KUBERNETES"', kwargs["params"]["filter"])

    def test_get(self):
        exit_code, out, calls = run_cli(
            ["cluster", "get", "--id", "k1"],
            [LOGIN_OK, FakeResponse(200, {"id": "k1", "name": "my-cluster"}), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "GET")
        self.assertEqual(url, BASE + "/inventory-sources/k1")

    def test_create_with_credential_id(self):
        exit_code, out, calls = run_cli(
            ["cluster", "create", "--name", "my-cluster", "--address", "10.0.0.5",
             "--credential-id", "c1"],
            [LOGIN_OK, FakeResponse(201, {"id": "k1", "name": "my-cluster"}), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(url, BASE + "/inventory-sources")
        body = kwargs["json"]
        self.assertEqual(body["name"], "my-cluster")
        self.assertEqual(body["type"], "KUBERNETES")
        self.assertEqual(body["address"], "10.0.0.5")
        self.assertEqual(body["port"], 6443)
        self.assertEqual(body["credentials"], {"id": "c1"})

    def test_create_with_credential_name_resolves_id(self):
        exit_code, out, calls = run_cli(
            ["cluster", "create", "--name", "my-cluster", "--address", "10.0.0.5",
             "--credential-name", "prod-cred"],
            [
                LOGIN_OK,
                FakeResponse(200, {"content": [{"id": "c1", "name": "prod-cred"}]}),
                FakeResponse(201, {"id": "k1", "name": "my-cluster"}),
                LOGOUT_OK,
            ],
        )
        self.assertEqual(exit_code, 0)
        resolve_method, resolve_url, _ = calls[1]
        self.assertEqual((resolve_method, resolve_url), ("GET", BASE + "/credentials"))
        create_method, create_url, create_kwargs = calls[2]
        self.assertEqual(create_kwargs["json"]["credentials"], {"id": "c1"})

    def test_update(self):
        exit_code, out, calls = run_cli(
            ["cluster", "update", "--id", "k1", "--update-mode", "MANUAL"],
            [LOGIN_OK, FakeResponse(200, {"id": "k1", "name": "my-cluster"}), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(url, BASE + "/inventory-sources/k1")
        self.assertEqual(kwargs["json"]["details"]["k8s"]["updateMode"], "MANUAL")

    def test_delete(self):
        exit_code, out, calls = run_cli(
            ["cluster", "delete", "--id", "k1", "--yes"],
            [LOGIN_OK, FakeResponse(204, None), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("deleted", out)
        method, url, kwargs = calls[1]
        self.assertEqual(method, "DELETE")
        self.assertEqual(url, BASE + "/inventory-sources/k1")

    def test_delete_with_cleanup(self):
        exit_code, out, calls = run_cli(
            ["cluster", "delete", "--id", "k1", "--yes", "--cleanup"],
            [
                LOGIN_OK,
                FakeResponse(200, {"content": [
                    {"id": "a1", "protectionPolicyId": "p1", "resourceGroups": [{"id": "g1"}]},
                ]}),
                FakeResponse(204, None),
                FakeResponse(207, {"responses": []}),
                FakeResponse(204, None),
                LOGOUT_OK,
            ],
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Cleaned up 1 asset(s)", out)
        self.assertIn("deleted", out)

        assets_method, assets_url, assets_kwargs = calls[1]
        self.assertEqual(assets_method, "GET")
        self.assertEqual(assets_url, BASE + "/assets")
        self.assertEqual(assets_kwargs["params"]["filter"], 'kubernetes.inventorySourceId eq "k1"')

        unassign_policy_method, unassign_policy_url, unassign_policy_kwargs = calls[2]
        self.assertEqual(unassign_policy_method, "POST")
        self.assertEqual(unassign_policy_url, BASE + "/protection-policies/p1/asset-unassignments")
        self.assertEqual(unassign_policy_kwargs["json"], ["a1"])

        unassign_group_method, unassign_group_url, unassign_group_kwargs = calls[3]
        self.assertEqual(unassign_group_method, "POST")
        self.assertEqual(unassign_group_url, BASE + "/resource-groups/g1/resource-unassignments-batch")
        self.assertEqual(
            unassign_group_kwargs["json"],
            {"requests": [{"id": "a1", "body": {"resourceType": "ASSET", "resourceId": "a1"}}]},
        )

        delete_method, delete_url, _ = calls[4]
        self.assertEqual(delete_method, "DELETE")
        self.assertEqual(delete_url, BASE + "/inventory-sources/k1")

    def test_delete_with_cleanup_no_assets_is_noop(self):
        exit_code, out, calls = run_cli(
            ["cluster", "delete", "--id", "k1", "--yes", "--cleanup"],
            [LOGIN_OK, FakeResponse(200, {"content": []}), FakeResponse(204, None), LOGOUT_OK],
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Cleaned up 0 asset(s)", out)
        delete_method, delete_url, _ = calls[2]
        self.assertEqual(delete_method, "DELETE")
        self.assertEqual(delete_url, BASE + "/inventory-sources/k1")


class ErrorHandlingTests(unittest.TestCase):
    def test_api_error_exits_nonzero(self):
        # The client always attempts logout on exit, even after a failed
        # request, so the fake response queue includes a trailing logout.
        stderr = io.StringIO()
        fake, calls = sequenced_request(
            [LOGIN_OK, FakeResponse(404, {"message": "not found"}), LOGOUT_OK]
        )
        with mock.patch("requests.request", side_effect=fake):
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = main([
                    "--server", "ppdm.example.com", "--user", "admin", "--password", "sekret",
                    "credential", "get", "--id", "missing",
                ])
        self.assertEqual(exit_code, 1)
        self.assertIn("404", stderr.getvalue())

    def test_login_failure(self):
        stderr = io.StringIO()
        fake, calls = sequenced_request([FakeResponse(401, {"message": "bad credentials"})])
        with mock.patch("requests.request", side_effect=fake):
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = main([
                    "--server", "ppdm.example.com", "--user", "admin", "--password", "wrong",
                    "credential", "list",
                ])
        self.assertEqual(exit_code, 1)
        self.assertIn("401", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
