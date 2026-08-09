"""Direct unit tests for CredentialsAPI, independent of the CLI layer.

Unlike tests/test_cli_smoke.py (which mocks requests.request end-to-end),
these tests mock the PPDMClient directly and assert against
client.request's call arguments.
"""
import unittest
from unittest.mock import MagicMock

from ppdm_cluster_registration.client import PPDMClient
from ppdm_cluster_registration.credentials import CredentialsAPI


class CredentialsAPITests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=PPDMClient)
        self.api = CredentialsAPI(self.client)

    def test_list_builds_type_and_name_filter(self):
        self.client.request.return_value = {"content": [{"id": "c1"}]}
        result = self.api.list(name="prod")
        self.assertEqual(result, [{"id": "c1"}])
        method, path = self.client.request.call_args.args
        self.assertEqual((method, path), ("GET", "/credentials"))
        filt = self.client.request.call_args.kwargs["params"]["filter"]
        self.assertIn('type eq "KUBERNETES"', filt)
        self.assertIn('name lk "%prod%"', filt)

    def test_list_builds_id_filter(self):
        self.client.request.return_value = {"content": []}
        self.api.list(id="c1")
        filt = self.client.request.call_args.kwargs["params"]["filter"]
        self.assertIn('type eq "KUBERNETES"', filt)
        self.assertIn('id lk "%c1%"', filt)

    def test_list_returns_empty_list_for_empty_response(self):
        self.client.request.return_value = None
        self.assertEqual(self.api.list(), [])

    def test_get_uses_id_in_path(self):
        self.client.request.return_value = {"id": "c1"}
        self.api.get("c1")
        self.client.request.assert_called_once_with("GET", "/credentials/c1")

    def test_create_defaults_username_to_null(self):
        self.api.create(name="prod-cred", token="tok")
        method, path = self.client.request.call_args.args
        payload = self.client.request.call_args.kwargs["json"]
        self.assertEqual((method, path), ("POST", "/credentials"))
        self.assertEqual(payload["name"], "prod-cred")
        self.assertEqual(payload["username"], "null")
        self.assertEqual(payload["password"], "tok")
        self.assertEqual(payload["type"], "KUBERNETES")
        self.assertEqual(payload["method"], "TOKEN")
        self.assertFalse(payload["internal"])

    def test_create_honors_explicit_username(self):
        self.api.create(name="prod-cred", token="tok", username="svc-account")
        payload = self.client.request.call_args.kwargs["json"]
        self.assertEqual(payload["username"], "svc-account")

    def test_update_merges_current_values_and_omits_password_if_no_token(self):
        self.client.request.side_effect = [
            {"id": "c1", "name": "old-name", "username": "null",
             "type": "KUBERNETES", "method": "TOKEN", "internal": False},
            {"id": "c1", "name": "old-name"},
        ]
        self.api.update("c1", username="new-user")

        get_call = self.client.request.call_args_list[0]
        self.assertEqual(get_call.args, ("GET", "/credentials/c1"))

        put_call = self.client.request.call_args_list[1]
        self.assertEqual(put_call.args, ("PUT", "/credentials/c1"))
        payload = put_call.kwargs["json"]
        self.assertEqual(payload["id"], "c1")
        self.assertEqual(payload["name"], "old-name")
        self.assertEqual(payload["username"], "new-user")
        self.assertNotIn("password", payload)

    def test_update_includes_password_when_token_given(self):
        self.client.request.side_effect = [
            {"id": "c1", "name": "old-name", "username": "null",
             "type": "KUBERNETES", "method": "TOKEN", "internal": False},
            {"id": "c1"},
        ]
        self.api.update("c1", token="new-token")
        payload = self.client.request.call_args_list[1].kwargs["json"]
        self.assertEqual(payload["password"], "new-token")

    def test_delete_uses_id_in_path(self):
        self.api.delete("c1")
        self.client.request.assert_called_once_with("DELETE", "/credentials/c1")

    def test_resolve_id_returns_id_directly_without_listing(self):
        self.assertEqual(self.api.resolve_id(id="c1"), "c1")
        self.client.request.assert_not_called()

    def test_resolve_id_resolves_unique_name_match(self):
        self.client.request.return_value = {"content": [{"id": "c1", "name": "prod-cred"}]}
        self.assertEqual(self.api.resolve_id(name="prod-cred"), "c1")

    def test_resolve_id_raises_when_neither_id_nor_name_given(self):
        with self.assertRaises(ValueError):
            self.api.resolve_id()
        self.client.request.assert_not_called()

    def test_resolve_id_raises_on_no_match(self):
        self.client.request.return_value = {"content": []}
        with self.assertRaises(ValueError):
            self.api.resolve_id(name="missing")

    def test_resolve_id_raises_on_ambiguous_match_mentions_credential_id_flag(self):
        self.client.request.return_value = {
            "content": [{"id": "c1"}, {"id": "c2"}],
        }
        with self.assertRaisesRegex(ValueError, "--credential-id"):
            self.api.resolve_id(name="dup")


if __name__ == "__main__":
    unittest.main()
