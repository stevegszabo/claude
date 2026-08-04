#!/usr/bin/env python3
"""Entry point: register and manage Kubernetes clusters with Dell PPDM.

See README.md for usage examples. Run with -h for full CLI help.
"""
import sys

from ppdm_cluster_registration.cli import main

if __name__ == "__main__":
    sys.exit(main())
