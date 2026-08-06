class PPDMAPIError(Exception):
    """Raised when the PPDM REST API returns a non-2xx response."""

    def __init__(self, method, url, status_code, body):
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(
            "{} {} failed with status {}: {}".format(method, url, status_code, body)
        )
