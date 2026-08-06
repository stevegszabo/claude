def _build_filter(base_filter, name=None, id=None):
    clauses = [base_filter] if base_filter else []
    if id:
        clauses.append('id lk "%{}%"'.format(id))
    if name:
        clauses.append('name lk "%{}%"'.format(name))
    return " and ".join(clauses) if clauses else None


class RegistrationsAPI:
    """CRUD operations for PPDM cluster registrations.

    A Kubernetes cluster registration is represented in the PPDM public
    REST API as an Inventory Source of type KUBERNETES.
    Maps to /api/v2/inventory-sources.
    """

    RESOURCE_TYPE = "KUBERNETES"

    def __init__(self, client):
        self.client = client

    def list(self, name=None, id=None):
        filt = _build_filter('type eq "{}"'.format(self.RESOURCE_TYPE), name=name, id=id)
        params = {"filter": filt} if filt else None
        response = self.client.request("GET", "/inventory-sources", params=params)
        return response["content"] if response else []

    def get(self, id):
        return self.client.request("GET", "/inventory-sources/{}".format(id))

    def create(self, name, address, credential_id, port=6443,
               distribution_type=None, update_mode=None):
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
        if k8s_details:
            payload["details"] = {"k8s": k8s_details}
        return self.client.request("POST", "/inventory-sources", json=payload)

    def update(self, id, credential_id=None, update_mode=None, configurations=None):
        """Partially update a cluster registration.

        The PPDM public API does not expose a full-replace (PUT) operation
        for inventory sources of type KUBERNETES -- only PATCH, scoped to
        `details.k8s` (per the InventorySourcePatchRequest schema: `id` +
        `details`). `credential_id` is included as a top-level `credentials`
        field defensively, since whether credential rotation is honored via
        this endpoint is version-dependent; if it is ignored, delete and
        recreate the registration with the new credential instead.
        """
        k8s_details = {}
        if update_mode is not None:
            k8s_details["updateMode"] = update_mode
        if configurations is not None:
            k8s_details["configurations"] = configurations

        payload = {"id": id}
        if k8s_details:
            payload["details"] = {"k8s": k8s_details}
        if credential_id is not None:
            payload["credentials"] = {"id": credential_id}

        return self.client.request("PATCH", "/inventory-sources/{}".format(id), json=payload)

    def delete(self, id):
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
        filt = 'kubernetes.inventorySourceId eq "{}"'.format(id)
        response = self.client.request("GET", "/assets", params={"filter": filt})
        return response["content"] if response else []

    def resolve_id(self, name=None, id=None):
        if id:
            return id
        if not name:
            raise ValueError("Either id or name must be provided")
        matches = self.list(name=name)
        if len(matches) == 0:
            raise ValueError("No cluster registration found matching name: {}".format(name))
        if len(matches) > 1:
            raise ValueError(
                "Cluster name '{}' matched {} results; use --id instead".format(
                    name, len(matches)
                )
            )
        return matches[0]["id"]
