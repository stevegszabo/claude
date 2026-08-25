"""Direct unit tests for CertificatesAPI, independent of the CLI layer."""
import base64
import contextlib
import datetime
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ppdm_cluster_registration.client import PPDMClient
from ppdm_cluster_registration.certificates import CertificatesAPI


def _make_self_signed_cert_and_key(common_name="my-cluster", issuer_common_name=None):
    """Build a small self-signed test certificate and return (cert_pem, key_pem)."""
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
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem


def _make_self_signed_pem(common_name="my-cluster", issuer_common_name=None):
    """Build a small self-signed test certificate and return it as PEM text."""
    cert_pem, _ = _make_self_signed_cert_and_key(common_name, issuer_common_name)
    return cert_pem


@contextlib.contextmanager
def _local_tls_server(cert_pem, key_pem):
    """Start a background thread serving exactly one TLS connection on
    127.0.0.1, presenting the given cert/key. Yields the bound port.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem") as certfile, \
            tempfile.NamedTemporaryFile(mode="w", suffix=".pem") as keyfile:
        certfile.write(cert_pem)
        certfile.flush()
        keyfile.write(key_pem)
        keyfile.flush()
        context.load_cert_chain(certfile.name, keyfile.name)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def serve():
            try:
                conn, _ = listener.accept()
                with context.wrap_socket(conn, server_side=True):
                    pass
            except OSError:
                pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield port
        finally:
            listener.close()
            thread.join(timeout=2)


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

    def test_list_builds_address_filter(self):
        self.client.request.return_value = {"content": []}
        self.api.list(address="192.168.2.102")
        filt = self.client.request.call_args.kwargs["params"]["filter"]
        self.assertEqual(filt, 'host lk "%192.168.2.102%"')

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

    def test_delete_uses_id_in_path(self):
        self.api.delete("cert1")
        self.client.request.assert_called_once_with("DELETE", "/certificates/cert1")

    def test_fetch_certificate_returns_pem_matching_server_cert(self):
        cert_pem, key_pem = _make_self_signed_cert_and_key(common_name="my-cluster")
        with _local_tls_server(cert_pem, key_pem) as port:
            result = self.api.fetch_certificate("127.0.0.1", port=port, timeout=5)
        info = self.api.describe_certificate(result)
        self.assertEqual(info["subject"], "CN=my-cluster")

    @patch("ppdm_cluster_registration.certificates.socket.create_connection")
    def test_fetch_certificate_passes_address_port_and_timeout(self, mock_create_connection):
        mock_create_connection.side_effect = OSError("stop before the TLS handshake")
        with self.assertRaises(ValueError):
            self.api.fetch_certificate("k8s-api.example.com", port=6443, timeout=3)
        mock_create_connection.assert_called_once_with(("k8s-api.example.com", 6443), timeout=3)

    @patch("ppdm_cluster_registration.certificates.socket.create_connection")
    def test_fetch_certificate_wraps_ssl_error(self, mock_create_connection):
        mock_create_connection.side_effect = ssl.SSLError("handshake failure")
        with self.assertRaises(ValueError) as ctx:
            self.api.fetch_certificate("k8s-api.example.com")
        self.assertIn("k8s-api.example.com", str(ctx.exception))
        self.assertIn("6443", str(ctx.exception))

    @patch("ppdm_cluster_registration.certificates.socket.create_connection")
    def test_fetch_certificate_wraps_connection_error(self, mock_create_connection):
        mock_create_connection.side_effect = ConnectionRefusedError("connection refused")
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

    def test_compute_id_is_deterministic(self):
        expected = base64.b64encode(b"192.168.2.102:6443:host").decode()
        self.assertEqual(self.api.compute_id("192.168.2.102", 6443), expected)
        self.assertEqual(self.api.compute_id("192.168.2.102", 6443), expected)

    def test_create_follows_post_get_put_get_flow(self):
        pem = _make_self_signed_pem(common_name="my-cluster", issuer_common_name="my-ca")
        expected_id = base64.b64encode(b"192.168.2.102:6443:host").decode()
        current = {
            "id": expected_id, "host": "192.168.2.102", "port": 6443,
            "fingerprint": "SERVER-COMPUTED-FINGERPRINT", "state": "UNKNOWN",
        }
        confirmed = {"id": expected_id, "state": "ACCEPTED"}
        self.client.request.side_effect = [
            {"id": expected_id},  # POST response (unused)
            current,              # GET #1
            {},                   # PUT response (unused)
            confirmed,             # GET #2
        ]

        with patch.object(self.api, "fetch_certificate", return_value=pem) as mock_fetch:
            result = self.api.create("192.168.2.102", port=6443)
        mock_fetch.assert_called_once_with("192.168.2.102", port=6443, timeout=10)
        self.assertEqual(result, confirmed)

        calls = self.client.request.call_args_list
        self.assertEqual(len(calls), 4)

        post_method, post_path = calls[0].args
        self.assertEqual((post_method, post_path), ("POST", "/certificates"))
        post_payload = calls[0].kwargs["json"]
        self.assertEqual(post_payload["host"], "192.168.2.102")
        self.assertEqual(post_payload["port"], 6443)
        self.assertEqual(post_payload["notValidBefore"], "2024-01-01T00:00:00.000Z")
        self.assertEqual(post_payload["notValidAfter"], "2025-01-01T00:00:00.000Z")
        self.assertEqual(post_payload["subjectName"], "CN=my-cluster")
        self.assertEqual(post_payload["issuerName"], "CN=my-ca")
        self.assertEqual(len(post_payload["fingerprint"]), 64)
        self.assertEqual(post_payload["state"], "ACCEPTED")
        self.assertEqual(post_payload["type"], "HOST")
        self.assertEqual(post_payload["verify"], False)
        self.assertEqual(post_payload["id"], expected_id)

        self.assertEqual(calls[1].args, ("GET", "/certificates/{}".format(expected_id)))

        put_method, put_path = calls[2].args
        self.assertEqual((put_method, put_path), ("PUT", "/certificates/{}".format(expected_id)))
        put_payload = calls[2].kwargs["json"]
        self.assertEqual(put_payload["state"], "ACCEPTED")
        self.assertEqual(put_payload["fingerprint"], "SERVER-COMPUTED-FINGERPRINT")
        self.assertEqual(put_payload["host"], "192.168.2.102")  # carried over from GET #1

        self.assertEqual(calls[3].args, ("GET", "/certificates/{}".format(expected_id)))

    def test_create_raises_when_not_accepted(self):
        pem = _make_self_signed_pem()
        self.client.request.side_effect = [
            {"id": "cert1"},                              # POST response
            {"id": "cert1", "fingerprint": "f", "state": "UNKNOWN"},  # GET #1
            {},                                            # PUT response
            {"id": "cert1", "state": "REJECTED"},          # GET #2
        ]

        with patch.object(self.api, "fetch_certificate", return_value=pem):
            with self.assertRaises(ValueError) as ctx:
                self.api.create("192.168.2.102", port=6443)
        self.assertIn("REJECTED", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
