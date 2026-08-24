from .filters import build_filter
from .resolve import resolve_id as _resolve_id


class RegistrationsAPI:
    """CRUD operations for PPDM cluster registrations.

    A Kubernetes cluster registration is represented in the PPDM public
    REST API as an Inventory Source of type KUBERNETES.
    Maps to /api/v2/inventory-sources.
    """

    RESOURCE_TYPE = "KUBERNETES"

    def __init__(self, client):
        """Wrap an authenticated PPDMClient for cluster registration
        operations.
        """
        self.client = client

    def list(self, name=None, id=None):
        """List KUBERNETES cluster registrations, optionally filtered by
        substring match on name and/or id.
        """
        filt = build_filter('type eq "{}"'.format(self.RESOURCE_TYPE), name=name, id=id)
        params = {"filter": filt} if filt else None
        response = self.client.request("GET", "/inventory-sources", params=params)
        return response["content"] if response else []

    def get(self, id):
        """Fetch a single cluster registration by ID."""
        return self.client.request("GET", "/inventory-sources/{}".format(id))

    def create(self, name, address, credential_id, port=6443,
               distribution_type=None, update_mode=None, configurations=None):
        """Register a new Kubernetes cluster with PPDM."""
        payload = {
            "name": name,
            "type": self.RESOURCE_TYPE,
            "address": address,
            "port": port,
            "credentials": {"id": credential_id},
        }
        k8s_details = {}
        if distribution_type is not None:
            k8s_details["distributionType"] = distribution_type
        if update_mode is not None:
            k8s_details["updateMode"] = update_mode
        if configurations is not None:
            k8s_details["configurations"] = configurations
        if k8s_details:
            payload["details"] = {"k8s": k8s_details}
        return self.client.request("POST", "/inventory-sources", json=payload)

    def update(self, id, address=None, credential_id=None, update_mode=None, configurations=None):
        """Full update (PUT) of a cluster registration. Fetches the current
        object and merges in the supplied changes before sending it back as
        a complete replacement -- PPDM's inventory-sources endpoint accepts
        a full-document PUT (confirmed against Dell's own reference
        PowerShell automation, which performs a plain PUT with an arbitrary
        body, and a Dell engineer's worked GET-modify-PUT example for
        updating a Kubernetes inventory source's configuration), the same
        pattern CredentialsAPI.update() already uses.
        """
        current = self.get(id)
        payload = dict(current)
        payload.pop("_links", None)
        if address is not None:
            payload["address"] = address
        if credential_id is not None:
            payload["credentials"] = {"id": credential_id}

        k8s_details = dict(current.get("details", {}).get("k8s", {}))
        if update_mode is not None:
            k8s_details["updateMode"] = update_mode
        if configurations is not None:
            k8s_details["configurations"] = configurations
        if k8s_details:
            payload.setdefault("details", {})["k8s"] = k8s_details

        return self.client.request("PUT", "/inventory-sources/{}".format(id), json=payload)

    def delete(self, id):
        """Delete a cluster registration by ID."""
        return self.client.request("DELETE", "/inventory-sources/{}".format(id))

    def cleanup(self, id):
        """Unassign the cluster's assets from any protection policies and
        asset (resource) groups.

        PPDM refuses to delete a Kubernetes inventory source while its
        assets are still assigned to a protection policy or belong to an
        asset group ("Failed to delete inventory source due to the assets
        of the inventory source being protected by protection policies or
        being part of asset groups."); this performs the unassignment PPDM
        requires before delete() will succeed. No-ops if the cluster has no
        assets, or none of them have such assignments.
        """
        assets = self._list_assets(id)

        policy_to_assets = {}
        group_to_assets = {}
        for asset in assets:
            asset_id = asset["id"]
            policy_id = asset.get("protectionPolicyId")
            if policy_id:
                policy_to_assets.setdefault(policy_id, []).append(asset_id)
            for group in asset.get("resourceGroups") or []:
                group_id = group.get("id")
                if group_id:
                    group_to_assets.setdefault(group_id, []).append(asset_id)

        for policy_id, asset_ids in policy_to_assets.items():
            self.client.request(
                "POST", "/protection-policies/{}/asset-unassignments".format(policy_id),
                json=asset_ids,
            )

        for group_id, asset_ids in group_to_assets.items():
            self.client.request(
                "POST", "/resource-groups/{}/resource-unassignments-batch".format(group_id),
                json={
                    "requests": [
                        {"id": asset_id, "body": {"resourceType": "ASSET", "resourceId": asset_id}}
                        for asset_id in asset_ids
                    ]
                },
            )

        return {
            "assets_processed": len(assets),
            "protection_policies_unassigned": sorted(policy_to_assets),
            "asset_groups_unassigned": sorted(group_to_assets),
        }

    def _list_assets(self, id):
        """List the Kubernetes assets (namespaces, PVCs) belonging to this
        cluster.

        Filters server-side on both `type` and `inventorySourceRefs.id` --
        the latter is a top-level array-of-refs field PPDM's filter language
        does support, unlike the deeply nested `details.k8s.inventorySourceId`
        (confirmed against Dell's own reference automation,
        ppdm_k8s_reporting.py in github.com/dell/powerprotect-data-manager,
        which filters /assets by cluster the same way).
        """
        filt = 'type eq "{}" and inventorySourceRefs.id eq "{}"'.format(self.RESOURCE_TYPE, id)
        response = self.client.request("GET", "/assets", params={"filter": filt})
        return response["content"] if response else []

    def resolve_id(self, name=None, id=None):
        """Resolve a cluster registration ID from either an explicit ID or
        a name lookup. Raises ValueError if the name does not resolve to
        exactly one registration.
        """
        return _resolve_id(self.list, "cluster registration", "--id", name=name, id=id)
