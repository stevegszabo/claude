def _build_filter(base_filter, name=None, id=None):
    clauses = [base_filter] if base_filter else []
    if id:
        clauses.append('id lk "%{}%"'.format(id))
    if name:
        clauses.append('name lk "%{}%"'.format(name))
    return " and ".join(clauses) if clauses else None


class CredentialsAPI:
    """CRUD operations for PPDM Credentials, scoped to Kubernetes/TOKEN
    credentials (the service-account token used to register a cluster).

    Maps to /api/v2/credentials on the PPDM public REST API.
    """

    RESOURCE_TYPE = "KUBERNETES"

    def __init__(self, client):
        self.client = client

    def list(self, name=None, id=None):
        filt = _build_filter('type eq "{}"'.format(self.RESOURCE_TYPE), name=name, id=id)
        params = {"filter": filt} if filt else None
        response = self.client.request("GET", "/credentials", params=params)
        return response["content"] if response else []

    def get(self, id):
        return self.client.request("GET", "/credentials/{}".format(id))

    def create(self, name, token, username="null"):
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
        return self.client.request("DELETE", "/credentials/{}".format(id))

    def resolve_id(self, name=None, id=None):
        """Resolve a credential ID from either an explicit ID or a name
        lookup. Raises ValueError if the name does not resolve to exactly
        one credential.
        """
        if id:
            return id
        if not name:
            raise ValueError("Either id or name must be provided")
        matches = self.list(name=name)
        if len(matches) == 0:
            raise ValueError("No credential found matching name: {}".format(name))
        if len(matches) > 1:
            raise ValueError(
                "Credential name '{}' matched {} results; use --credential-id instead".format(
                    name, len(matches)
                )
            )
        return matches[0]["id"]
