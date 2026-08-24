import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from .filters import build_filter


class CertificatesAPI:
    """CRUD operations for PPDM cluster certificates.

    Source of the certificate is the target cluster's Kubernetes API server;
    operations here push/manage that certificate on the PPDM side. Endpoint
    path(s) and payload shape TBD -- pending PPDM certificate-resource
    research (see registrations.py / credentials.py for the equivalent
    research already done for the other two resource types).
    """

    def __init__(self, client):
        """Wrap an authenticated PPDMClient for certificate operations."""
        self.client = client

    def list(self, name=None, id=None):
        """List PPDM certificates, optionally filtered by substring match on
        name and/or id.
        """
        filt = build_filter(None, name=name, id=id)
        params = {"filter": filt} if filt else None
        response = self.client.request("GET", "/certificates", params=params)
        return response["content"] if response else []

    def get(self, id):
        """Fetch a single certificate by ID."""
        return self.client.request("GET", "/certificates/{}".format(id))

    def create(self, cluster_id=None, cluster_name=None):
        pass

    def update(self, id):
        pass

    def delete(self, id):
        pass

    def fetch_certificate(self, address, port=6443, timeout=10):
        """Connect to a cluster's Kubernetes API server via TLS and retrieve
        the certificate it presents, without verifying it -- the goal is to
        capture certs PPDM doesn't yet trust (self-signed, internal CA) so
        they can be pushed to PPDM as a trusted cert. Returns the leaf
        certificate in PEM format.
        """
        try:
            return ssl.get_server_certificate((address, port), timeout=timeout)
        except (ssl.SSLError, OSError) as err:
            raise ValueError(
                "Could not retrieve certificate from {}:{}: {}".format(address, port, err)
            ) from err

    @staticmethod
    def describe_certificate(pem):
        """Parse a PEM certificate (as returned by fetch_certificate()) into
        the fields relevant to deciding whether to trust it.
        """
        cert = x509.load_pem_x509_certificate(pem.encode())
        fingerprint = cert.fingerprint(hashes.SHA256())
        date_format = "%Y-%m-%dT%H:%M:%S.000Z"
        return {
            "not_valid_before": cert.not_valid_before.strftime(date_format),
            "not_valid_after": cert.not_valid_after.strftime(date_format),
            "fingerprint": "".join("{:02X}".format(b) for b in fingerprint),
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
        }
