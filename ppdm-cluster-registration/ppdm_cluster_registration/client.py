import requests

from .exceptions import PPDMAPIError


class PPDMClient:
    """Thin REST client for the PowerProtect Data Manager (PPDM) public API.

    Handles authentication (login/logout) and provides a generic request
    helper used by the resource-specific API classes (CredentialsAPI,
    RegistrationsAPI). Usable as a context manager so logout is always
    attempted, even if an operation raises:

        with PPDMClient(server, username=user, password=pwd) as client:
            client.request("GET", "/credentials")
    """

    def __init__(self, server, username, password, port=8443, verify_ssl=True, timeout=90):
        self.server = server
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.base_url = "https://{}:{}/api/v2".format(server, port)
        self.access_token = None

        if not verify_ssl:
            # Avoid noisy InsecureRequestWarning spam when the caller has
            # explicitly opted out of certificate verification (e.g. a lab
            # appliance with a self-signed cert).
            requests.packages.urllib3.disable_warnings(
                requests.packages.urllib3.exceptions.InsecureRequestWarning
            )

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.access_token:
            self.logout()
        return False

    def login(self):
        payload = {"username": self.username, "password": self.password}
        response = self._send("POST", "/login", json=payload, authenticated=False)
        self.access_token = response["access_token"]
        return self.access_token

    def logout(self):
        try:
            self._send("POST", "/logout")
        finally:
            self.access_token = None

    def request(self, method, path, json=None, params=None):
        """Issue an authenticated request against the PPDM API.

        `path` should be relative, e.g. "/credentials" or "/credentials/123".
        Returns the parsed JSON body, or None for empty (e.g. 204) responses.
        """
        return self._send(method, path, json=json, params=params)

    def _send(self, method, path, json=None, params=None, authenticated=True):
        url = self.base_url + path
        headers = {"Content-Type": "application/json"}
        if authenticated:
            if not self.access_token:
                raise RuntimeError("Not authenticated: call login() first")
            headers["Authorization"] = "Bearer {}".format(self.access_token)

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as err:
            raise PPDMAPIError(method, url, None, str(err)) from err

        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            raise PPDMAPIError(method, url, response.status_code, body)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None
