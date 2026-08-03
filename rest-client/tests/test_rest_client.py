#!/usr/bin/env python3
"""Integration tests for rest_client.py, one per HTTP method, run against a
live Vault dev server (VAULT_ADDR/VAULT_TOKEN). Uses the 'monster' kv-v2
mount as a real read/write backend; test methods are ordered (test_01..06)
since each stage depends on state left by the previous one.
"""
import json
import os
import subprocess
import sys
import unittest
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "rest_client.py")


def run_cli(args, stdin_text=""):
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=15,
    )


class RestClientVaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ.get("VAULT_ADDR")
        cls.token = os.environ.get("VAULT_TOKEN")
        if not cls.base_url or not cls.token:
            raise unittest.SkipTest("VAULT_ADDR/VAULT_TOKEN not set")

        cls.common = ["--base-url", cls.base_url, "-H", f"X-Vault-Token: {cls.token}"]
        cls.key = f"rest-client-test-{uuid.uuid4().hex[:8]}"
        cls.data_path = f"v1/monster/data/{cls.key}"
        cls.metadata_path = f"v1/monster/metadata/{cls.key}"
        cls.list_path = "v1/monster/metadata"

    @classmethod
    def tearDownClass(cls):
        run_cli(["delete", cls.metadata_path] + cls.common)

    def test_01_get(self):
        result = run_cli(["get", "v1/sys/health", "--base-url", self.base_url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HTTP 200", result.stdout)
        self.assertIn('"initialized": true', result.stdout)

    def test_02_post_creates_secret(self):
        payload = json.dumps({"data": {"foo": "bar"}})
        result = run_cli(["post", self.data_path] + self.common, stdin_text=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HTTP 200", result.stdout)
        self.assertIn('"version": 1', result.stdout)

    def test_03_put_replaces_secret(self):
        payload = json.dumps({"data": {"foo": "baz"}})
        result = run_cli(["put", self.data_path] + self.common, stdin_text=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"version": 2', result.stdout)

        readback = run_cli(["get", self.data_path] + self.common)
        self.assertIn('"foo": "baz"', readback.stdout)

    def test_04_list_shows_secret(self):
        result = run_cli(["list", self.list_path] + self.common)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HTTP 200", result.stdout)
        self.assertIn(self.key, result.stdout)

    def test_05_patch_partial_update(self):
        payload = json.dumps({"data": {"extra": "field"}})
        result = run_cli(
            ["patch", self.data_path] + self.common
            + ["-H", "Content-Type: application/merge-patch+json"],
            stdin_text=payload,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"version": 3', result.stdout)

        readback = run_cli(["get", self.data_path] + self.common)
        self.assertIn('"foo": "baz"', readback.stdout)
        self.assertIn('"extra": "field"', readback.stdout)

    def test_06_delete_removes_secret(self):
        result = run_cli(["delete", self.data_path] + self.common)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HTTP 204", result.stdout)

        readback = run_cli(["get", self.data_path] + self.common)
        self.assertIn("HTTP 404", readback.stdout)


if __name__ == "__main__":
    unittest.main()
