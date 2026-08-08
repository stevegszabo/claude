from .filters import build_filter
from .resolve import resolve_id as _resolve_id


class CredentialsAPI:
    """CRUD operations for PPDM Credentials, scoped to Kubernetes/TOKEN
    credentials (the service-account token used to register a cluster).

    Maps to /api/v2/credentials on the PPDM public REST API.
    """

    RESOURCE_TYPE = "KUBERNETES"

    def __init__(self, client):
        """Wrap an authenticated PPDMClient for credential operations."""
        self.client = client

    def list(self, name=None, id=None):
        """List KUBERNETES credentials, optionally filtered by substring
        match on name and/or id.
        """
        filt = build_filter('type eq "{}"'.format(self.RESOURCE_TYPE), name=name, id=id)
        params = {"filter": filt} if filt else None
        response = self.client.request("GET", "/credentials", params=params)
        return response["content"] if response else []

    def get(self, id):
        """Fetch a single credential by ID."""
        return self.client.request("GET", "/credentials/{}".format(id))

    def create(self, name, token, username="null"):
        """Create a credential. `username` defaults to the literal string
        "null": Kubernetes TOKEN credentials have no meaningful username,
        but PPDM's schema requires the field non-empty. This matches Dell's
        own convention (see credsmgmt.py in
        github.com/dell/powerprotect-data-manager), not a bug.
        """
        payload = {
            "name": name,
            "username": username,
            "password": token,
            "type": self.RESOURCE_TYPE,
            "method": "TOKEN",
            "internal": False,
        }
        return self.client.request("POST", "/credentials", json=payload)

    def update(self, id, name=None, token=None, username=None):
        """Full update (PUT) of a credential. The PPDM API has no PATCH for
        credentials, so the current object is fetched and merged with the
        supplied changes before being sent back as a complete replacement.
        """
        current = self.get(id)
        payload = {
            "id": id,
            "name": name if name is not None else current.get("name"),
            "username": username if username is not None else current.get("username"),
            "type": current.get("type", self.RESOURCE_TYPE),
            "method": current.get("method", "TOKEN"),
            "internal": current.get("internal", False),
        }
        if token is not None:
            payload["password"] = token
        return self.client.request("PUT", "/credentials/{}".format(id), json=payload)

    def delete(self, id):
        """Delete a credential by ID."""
        return self.client.request("DELETE", "/credentials/{}".format(id))

    def resolve_id(self, name=None, id=None):
        """Resolve a credential ID from either an explicit ID or a name
        lookup. Raises ValueError if the name does not resolve to exactly
        one credential.
        """
        return _resolve_id(self.list, "credential", "--credential-id", name=name, id=id)
