"""Direct unit tests for CertificatesAPI, independent of the CLI layer."""
import datetime
import ssl
import unittest
from unittest.mock import MagicMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ppdm_cluster_registration.client import PPDMClient
from ppdm_cluster_registration.certificates import CertificatesAPI


def _make_self_signed_pem(common_name="my-cluster", issuer_common_name=None):
    """Build a small self-signed test certificate and return it as PEM text."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, issuer_common_name or common_name)]
    )
    not_before = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    not_after = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class CertificatesAPITests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=PPDMClient)
        self.api = CertificatesAPI(self.client)

    def test_list_with_no_filters_omits_params_filter(self):
        self.client.request.return_value = {"content": [{"id": "cert1"}]}
        result = self.api.list()
        self.assertEqual(result, [{"id": "cert1"}])
        method, path = self.client.request.call_args.args
        self.assertEqual((method, path), ("GET", "/certificates"))
        self.assertIsNone(self.client.request.call_args.kwargs["params"])

    def test_list_builds_name_filter(self):
        self.client.request.return_value = {"content": []}
        self.api.list(name="my-cluster")
        filt = self.client.request.call_args.kwargs["params"]["filter"]
        self.assertEqual(filt, 'name lk "%my-cluster%"')

    def test_list_builds_id_filter(self):
        self.client.request.return_value = {"content": []}
        self.api.list(id="cert1")
        filt = self.client.request.call_args.kwargs["params"]["filter"]
        self.assertEqual(filt, 'id lk "%cert1%"')

    def test_list_returns_empty_list_for_empty_response(self):
        self.client.request.return_value = None
        self.assertEqual(self.api.list(), [])

    def test_get_uses_id_in_path(self):
        self.client.request.return_value = {"id": "cert1"}
        self.api.get("cert1")
        self.client.request.assert_called_once_with("GET", "/certificates/cert1")

    @patch("ppdm_cluster_registration.certificates.ssl.get_server_certificate")
    def test_fetch_certificate_returns_pem_from_server(self, mock_get_cert):
        mock_get_cert.return_value = "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
        result = self.api.fetch_certificate("k8s-api.example.com", port=6443)
        mock_get_cert.assert_called_once_with(("k8s-api.example.com", 6443), timeout=10)
        self.assertEqual(result, mock_get_cert.return_value)

    @patch("ppdm_cluster_registration.certificates.ssl.get_server_certificate")
    def test_fetch_certificate_passes_custom_timeout(self, mock_get_cert):
        self.api.fetch_certificate("k8s-api.example.com", port=6443, timeout=3)
        mock_get_cert.assert_called_once_with(("k8s-api.example.com", 6443), timeout=3)

    @patch("ppdm_cluster_registration.certificates.ssl.get_server_certificate")
    def test_fetch_certificate_wraps_ssl_error(self, mock_get_cert):
        mock_get_cert.side_effect = ssl.SSLError("handshake failure")
        with self.assertRaises(ValueError) as ctx:
            self.api.fetch_certificate("k8s-api.example.com")
        self.assertIn("k8s-api.example.com", str(ctx.exception))
        self.assertIn("6443", str(ctx.exception))

    @patch("ppdm_cluster_registration.certificates.ssl.get_server_certificate")
    def test_fetch_certificate_wraps_connection_error(self, mock_get_cert):
        mock_get_cert.side_effect = ConnectionRefusedError("connection refused")
        with self.assertRaises(ValueError):
            self.api.fetch_certificate("k8s-api.example.com")

    def test_describe_certificate_extracts_expected_fields(self):
        pem = _make_self_signed_pem(common_name="my-cluster", issuer_common_name="my-ca")
        info = self.api.describe_certificate(pem)

        self.assertEqual(info["not_valid_before"], "2024-01-01T00:00:00.000Z")
        self.assertEqual(info["not_valid_after"], "2025-01-01T00:00:00.000Z")
        self.assertEqual(info["subject"], "CN=my-cluster")
        self.assertEqual(info["issuer"], "CN=my-ca")

        fingerprint = info["fingerprint"]
        self.assertEqual(len(fingerprint), 64)  # SHA-256 digest = 32 bytes = 64 hex chars
        int(fingerprint, 16)  # raises ValueError if not valid hex

    def test_describe_certificate_fingerprint_matches_independent_computation(self):
        pem = _make_self_signed_pem()
        cert = x509.load_pem_x509_certificate(pem.encode())
        expected = "".join("{:02X}".format(b) for b in cert.fingerprint(hashes.SHA256()))

        info = self.api.describe_certificate(pem)
        self.assertEqual(info["fingerprint"], expected)


if __name__ == "__main__":
    unittest.main()
