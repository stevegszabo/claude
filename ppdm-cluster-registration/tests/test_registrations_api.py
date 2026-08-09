"""Direct unit tests for RegistrationsAPI, independent of the CLI layer.

Unlike tests/test_cli_smoke.py (which mocks requests.request end-to-end),
these tests mock the PPDMClient directly and assert against
client.request's call arguments.
"""
import unittest
from unittest.mock import MagicMock

from ppdm_cluster_registration.client import PPDMClient
from ppdm_cluster_registration.registrations import RegistrationsAPI


class RegistrationsAPITests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=PPDMClient)
        self.api = RegistrationsAPI(self.client)

    def test_list_builds_type_and_name_filter(self):
        self.client.request.return_value = {"content": [{"id": "k1"}]}
        result = self.api.list(name="my-cluster")
        self.assertEqual(result, [{"id": "k1"}])
        method, path = self.client.request.call_args.args
        self.assertEqual((method, path), ("GET", "/inventory-sources"))
        filt = self.client.request.call_args.kwargs["params"]["filter"]
        self.assertIn('type eq "KUBERNETES"', filt)
        self.assertIn('name lk "%my-cluster%"', filt)

    def test_list_builds_id_filter(self):
        self.client.request.return_value = {"content": []}
        self.api.list(id="k1")
        filt = self.client.request.call_args.kwargs["params"]["filter"]
        self.assertIn('id lk "%k1%"', filt)

    def test_list_returns_empty_list_for_empty_response(self):
        self.client.request.return_value = None
        self.assertEqual(self.api.list(), [])

    def test_get_uses_id_in_path(self):
        self.client.request.return_value = {"id": "k1"}
        self.api.get("k1")
        self.client.request.assert_called_once_with("GET", "/inventory-sources/k1")

    def test_create_without_optional_fields_omits_details(self):
        self.api.create(name="my-cluster", address="10.0.0.5", credential_id="c1")
        method, path = self.client.request.call_args.args
        payload = self.client.request.call_args.kwargs["json"]
        self.assertEqual((method, path), ("POST", "/inventory-sources"))
        self.assertEqual(payload["name"], "my-cluster")
        self.assertEqual(payload["type"], "KUBERNETES")
        self.assertEqual(payload["address"], "10.0.0.5")
        self.assertEqual(payload["port"], 6443)
        self.assertEqual(payload["credentials"], {"id": "c1"})
        self.assertNotIn("details", payload)

    def test_create_with_optional_fields_builds_details(self):
        self.api.create(
            name="my-cluster", address="10.0.0.5", credential_id="c1",
            distribution_type="VANILLA_ON_VSPHERE", update_mode="AUTO",
            configurations=[{"type": "CONTROLLER_CONFIG", "key": "env", "value": "prod"}],
        )
        payload = self.client.request.call_args.kwargs["json"]
        self.assertEqual(
            payload["details"]["k8s"],
            {
                "distributionType": "VANILLA_ON_VSPHERE",
                "updateMode": "AUTO",
                "configurations": [{"type": "CONTROLLER_CONFIG", "key": "env", "value": "prod"}],
            },
        )

    def test_update_omits_details_and_credentials_when_not_given(self):
        self.api.update("k1")
        method, path = self.client.request.call_args.args
        payload = self.client.request.call_args.kwargs["json"]
        self.assertEqual((method, path), ("PATCH", "/inventory-sources/k1"))
        self.assertEqual(payload, {"id": "k1"})

    def test_update_includes_details_and_credentials_when_given(self):
        self.api.update("k1", credential_id="c2", update_mode="MANUAL",
                         configurations=[{"type": "CONTROLLER_CONFIG", "key": "tier", "value": "1"}])
        payload = self.client.request.call_args.kwargs["json"]
        self.assertEqual(payload["id"], "k1")
        self.assertEqual(payload["credentials"], {"id": "c2"})
        self.assertEqual(
            payload["details"]["k8s"],
            {
                "updateMode": "MANUAL",
                "configurations": [{"type": "CONTROLLER_CONFIG", "key": "tier", "value": "1"}],
            },
        )

    def test_delete_uses_id_in_path(self):
        self.api.delete("k1")
        self.client.request.assert_called_once_with("DELETE", "/inventory-sources/k1")

    def test_list_assets_filters_on_type_and_inventory_source_id(self):
        self.client.request.return_value = {"content": [{"id": "a1"}]}
        result = self.api._list_assets("k1")
        self.assertEqual(result, [{"id": "a1"}])
        method, path = self.client.request.call_args.args
        self.assertEqual((method, path), ("GET", "/assets"))
        self.assertEqual(
            self.client.request.call_args.kwargs["params"]["filter"],
            'type eq "KUBERNETES" and inventorySourceRefs.id eq "k1"',
        )

    def test_list_assets_returns_empty_list_for_empty_response(self):
        self.client.request.return_value = None
        self.assertEqual(self.api._list_assets("k1"), [])

    def test_cleanup_batches_unassignments_by_policy_and_group(self):
        self.client.request.side_effect = [
            {"content": [
                {"id": "a1", "protectionPolicyId": "p1", "resourceGroups": [{"id": "g1"}]},
                {"id": "a2", "protectionPolicyId": "p1", "resourceGroups": [{"id": "g1"}]},
            ]},
            None,  # POST asset-unassignments for p1
            None,  # POST resource-unassignments-batch for g1
        ]
        summary = self.api.cleanup("k1")

        policy_call = self.client.request.call_args_list[1]
        self.assertEqual(policy_call.args, ("POST", "/protection-policies/p1/asset-unassignments"))
        self.assertEqual(policy_call.kwargs["json"], ["a1", "a2"])

        group_call = self.client.request.call_args_list[2]
        self.assertEqual(group_call.args, ("POST", "/resource-groups/g1/resource-unassignments-batch"))
        self.assertEqual(
            group_call.kwargs["json"],
            {"requests": [
                {"id": "a1", "body": {"resourceType": "ASSET", "resourceId": "a1"}},
                {"id": "a2", "body": {"resourceType": "ASSET", "resourceId": "a2"}},
            ]},
        )

        self.assertEqual(summary, {
            "assets_processed": 2,
            "protection_policies_unassigned": ["p1"],
            "asset_groups_unassigned": ["g1"],
        })

    def test_cleanup_asset_with_only_policy_skips_group_call(self):
        self.client.request.side_effect = [
            {"content": [{"id": "a1", "protectionPolicyId": "p1"}]},
            None,
        ]
        summary = self.api.cleanup("k1")
        self.assertEqual(self.client.request.call_count, 2)
        self.assertEqual(summary["protection_policies_unassigned"], ["p1"])
        self.assertEqual(summary["asset_groups_unassigned"], [])

    def test_cleanup_asset_with_only_group_skips_policy_call(self):
        self.client.request.side_effect = [
            {"content": [{"id": "a1", "resourceGroups": [{"id": "g1"}]}]},
            None,
        ]
        summary = self.api.cleanup("k1")
        self.assertEqual(self.client.request.call_count, 2)
        self.assertEqual(summary["protection_policies_unassigned"], [])
        self.assertEqual(summary["asset_groups_unassigned"], ["g1"])

    def test_cleanup_no_assets_is_noop(self):
        self.client.request.return_value = {"content": []}
        summary = self.api.cleanup("k1")
        self.client.request.assert_called_once()  # only the assets GET
        self.assertEqual(summary, {
            "assets_processed": 0,
            "protection_policies_unassigned": [],
            "asset_groups_unassigned": [],
        })

    def test_resolve_id_returns_id_directly_without_listing(self):
        self.assertEqual(self.api.resolve_id(id="k1"), "k1")
        self.client.request.assert_not_called()

    def test_resolve_id_resolves_unique_name_match(self):
        self.client.request.return_value = {"content": [{"id": "k1", "name": "my-cluster"}]}
        self.assertEqual(self.api.resolve_id(name="my-cluster"), "k1")

    def test_resolve_id_raises_when_neither_id_nor_name_given(self):
        with self.assertRaises(ValueError):
            self.api.resolve_id()
        self.client.request.assert_not_called()

    def test_resolve_id_raises_on_no_match(self):
        self.client.request.return_value = {"content": []}
        with self.assertRaises(ValueError):
            self.api.resolve_id(name="missing")

    def test_resolve_id_raises_on_ambiguous_match_mentions_id_flag(self):
        self.client.request.return_value = {
            "content": [{"id": "k1"}, {"id": "k2"}],
        }
        with self.assertRaises(ValueError) as ctx:
            self.api.resolve_id(name="dup")
        self.assertIn("--id", str(ctx.exception))
        self.assertIn("Cluster registration", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
