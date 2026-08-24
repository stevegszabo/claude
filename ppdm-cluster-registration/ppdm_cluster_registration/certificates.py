import base64
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from .filters import build_filter


class CertificatesAPI:
    """CRUD operations for PPDM cluster certificates.

    Source of the certificate is the target cluster's Kubernetes API server;
    operations here push/manage that certificate on the PPDM side. Maps to
    /api/v2/certificates.
    """

    def __init__(self, client):
        """Wrap an authenticated PPDMClient for certificate operations."""
        self.client = client

    def list(self, address=None, id=None):
        """List PPDM certificates, optionally filtered by substring match on
        host (--address) and/or id.
        """
        filt = build_filter(None, host=address, id=id)
        params = {"filter": filt} if filt else None
        response = self.client.request("GET", "/certificates", params=params)
        return response["content"] if response else []

    def get(self, id):
        """Fetch a single certificate by ID."""
        return self.client.request("GET", "/certificates/{}".format(id))

    @staticmethod
    def compute_id(address, port):
        """Deterministic certificate id PPDM expects: base64("host:port:host")."""
        return base64.b64encode("{}:{}:host".format(address, port).encode()).decode()

    def create(self, address, port=6443, timeout=10):
        """Fetch the target cluster's Kubernetes API server certificate, push
        it to PPDM, then accept it -- PPDM's certificate flow requires
        POSTing the certificate, then a separate GET/PUT round trip to flip
        its state to ACCEPTED, confirmed with a final GET.
        """
        pem = self.fetch_certificate(address, port=port, timeout=timeout)
        info = self.describe_certificate(pem)
        cert_id = self.compute_id(address, port)
        create_payload = {
            "id": cert_id,
            "host": address,
            "port": port,
            "notValidBefore": info["not_valid_before"],
            "notValidAfter": info["not_valid_after"],
            "fingerprint": info["fingerprint"],
            "subjectName": info["subject"],
            "issuerName": info["issuer"],
            "state": "ACCEPTED",
            "type": "HOST",
            "verify": False,
        }
        self.client.request("POST", "/certificates", json=create_payload)

        current = self.get(cert_id)
        accept_payload = dict(current)
        accept_payload["state"] = "ACCEPTED"
        accept_payload["fingerprint"] = current["fingerprint"]
        self.client.request("PUT", "/certificates/{}".format(cert_id), json=accept_payload)

        confirmed = self.get(cert_id)
        if confirmed.get("state") != "ACCEPTED":
            raise ValueError(
                "Certificate {} was not accepted by PPDM (state={})".format(
                    cert_id, confirmed.get("state")
                )
            )
        return confirmed

    def update(self, address, port=6443, timeout=10):
        """Refresh a certificate in PPDM: re-fetch it from the cluster's
        Kubernetes API server and PUT the refreshed fields onto the
        existing PPDM record.
        """
        cert_id = self.compute_id(address, port)
        pem = self.fetch_certificate(address, port=port, timeout=timeout)
        info = self.describe_certificate(pem)

        current = self.get(cert_id)
        payload = dict(current)
        payload["notValidBefore"] = info["not_valid_before"]
        payload["notValidAfter"] = info["not_valid_after"]
        payload["fingerprint"] = info["fingerprint"]
        payload["subjectName"] = info["subject"]
        payload["issuerName"] = info["issuer"]
        payload["state"] = "ACCEPTED"

        return self.client.request("PUT", "/certificates/{}".format(cert_id), json=payload)

    def delete(self, id):
        """Delete a certificate by ID."""
        return self.client.request("DELETE", "/certificates/{}".format(id))

    def fetch_certificate(self, address, port=6443, timeout=10):
        """Connect to a cluster's Kubernetes API server via TLS and retrieve
        the certificate it presents, without verifying it -- the goal is to
        capture certs PPDM doesn't yet trust (self-signed, internal CA) so
        they can be pushed to PPDM as a trusted cert. Returns the leaf
        certificate in PEM format.
        """
        try:
            context = ssl._create_unverified_context()
            with socket.create_connection((address, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=address) as ssock:
                    der_cert = ssock.getpeercert(binary_form=True)
            return ssl.DER_cert_to_PEM_cert(der_cert)
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
        # not_valid_before/not_valid_after are deprecated in favor of the
        # *_utc variants as of cryptography 42, but those don't exist yet in
        # older installs (e.g. cryptography 41 -- AttributeError). Prefer
        # the new attribute when present, fall back otherwise; both
        # represent the same UTC instant, so the formatted output is
        # identical either way.
        not_valid_before = getattr(cert, "not_valid_before_utc", cert.not_valid_before)
        not_valid_after = getattr(cert, "not_valid_after_utc", cert.not_valid_after)
        return {
            "not_valid_before": not_valid_before.strftime(date_format),
            "not_valid_after": not_valid_after.strftime(date_format),
            "fingerprint": "".join("{:02X}".format(b) for b in fingerprint),
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
        }
