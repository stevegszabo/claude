import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import report  # noqa: E402


def test_parse_args_defaults():
    args = report.parse_args([])
    assert args.namespaces is None
    assert args.output_dir == "reports"
    assert args.kubeconfig is None
    assert args.context is None


def test_expand_namespaces_none():
    assert report.expand_namespaces(None) is None
    assert report.expand_namespaces([]) is None


def test_expand_namespaces_repeated_flags():
    assert report.expand_namespaces(["ns1", "ns2"]) == ["ns1", "ns2"]


def test_expand_namespaces_comma_separated():
    assert report.expand_namespaces(["ns1,ns2", "ns3"]) == ["ns1", "ns2", "ns3"]


def test_expand_namespaces_strips_whitespace_and_blanks():
    assert report.expand_namespaces([" ns1 , ,ns2 "]) == ["ns1", "ns2"]


def test_parse_args_output_dir_and_context():
    args = report.parse_args(["-o", "out", "--context", "my-ctx", "--kubeconfig", "/tmp/kc"])
    assert args.output_dir == "out"
    assert args.context == "my-ctx"
    assert args.kubeconfig == "/tmp/kc"
