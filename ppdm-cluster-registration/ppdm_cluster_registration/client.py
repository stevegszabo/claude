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
        """Store connection parameters. No network call happens until
        login() (or entering the context manager).

        If verify_ssl is False, also disables urllib3's InsecureRequestWarning
        to avoid noisy spam when the caller has explicitly opted out of
        certificate verification (e.g. a lab appliance with a self-signed cert).
        """
        self.server = server
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.base_url = "https://{}:{}/api/v2".format(server, port)
        self.access_token = None

        if not verify_ssl:
            requests.packages.urllib3.disable_warnings(
                requests.packages.urllib3.exceptions.InsecureRequestWarning
            )

    def __enter__(self):
        """Log in and return self, enabling the `with PPDMClient(...) as
        client:` pattern shown in the class docstring.
        """
        self.login()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Log out if a session was established. Returns False (never
        suppresses an exception raised inside the `with` block).
        """
        if self.access_token:
            self.logout()
        return False

    def login(self):
        """Authenticate against PPDM and store the returned access token
        for use by subsequent authenticated requests.
        """
        payload = {"username": self.username, "password": self.password}
        response = self._send("POST", "/login", json=payload, authenticated=False)
        self.access_token = response["access_token"]
        return self.access_token

    def logout(self):
        """Invalidate the current session with PPDM and clear the stored
        access token, even if the logout call itself fails.
        """
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
        """Send a single HTTP request to PPDM and return the parsed JSON
        body (or None for an empty response). Raises PPDMAPIError on a
        network failure or a non-2xx response.
        """
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
