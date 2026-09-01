import base64
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes


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

        PPDM's /certificates endpoint does not honor the `filter` query
        param used by the other resources (confirmed via live testing --
        it silently returns every certificate regardless of the filter
        sent), so matching is done client-side here instead.
        """
        response = self.client.request("GET", "/certificates")
        certs = response["content"] if response else []
        if address:
            certs = [c for c in certs if address in c.get("host", "")]
        if id:
            certs = [c for c in certs if id in c.get("id", "")]
        return certs

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
        # older installs (e.g. cryptography 41 -- AttributeError). hasattr()
        # only touches the attribute that actually gets used -- unlike
        # getattr(cert, "..._utc", cert.not_valid_before), whose default
        # argument is evaluated eagerly and would trip the deprecation
        # warning on every call even when *_utc is available. Both
        # attributes represent the same UTC instant, so the formatted
        # output is identical either way.
        if hasattr(cert, "not_valid_before_utc"):
            not_valid_before = cert.not_valid_before_utc
            not_valid_after = cert.not_valid_after_utc
        else:
            not_valid_before = cert.not_valid_before
            not_valid_after = cert.not_valid_after
        return {
            "not_valid_before": not_valid_before.strftime(date_format),
            "not_valid_after": not_valid_after.strftime(date_format),
            "fingerprint": "".join("{:02X}".format(b) for b in fingerprint),
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
        }
