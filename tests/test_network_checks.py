import argparse
import socket
import subprocess
import unittest
from unittest.mock import patch

from network_checks import endpoint, probe, timeout_seconds


class NetworkTests(unittest.TestCase):
    def test_endpoint_validation(self):
        self.assertEqual(endpoint("[::1]:443"), ("::1", 443))
        for value in ("host", "host:0", ":443", "host:65536"):
            with self.assertRaises(argparse.ArgumentTypeError):
                endpoint(value)

    def test_timeout_validation(self):
        for value in ("nan", "inf", "0", "61"):
            with self.assertRaises(argparse.ArgumentTypeError):
                timeout_seconds(value)

    def test_dns_failure(self):
        with patch("network_checks.resolve", side_effect=socket.gaierror):
            self.assertEqual(probe("missing.invalid", 443)["status"], "dns_error")

    def test_dns_timeout(self):
        with patch("network_checks.resolve", side_effect=subprocess.TimeoutExpired("dns", 1)):
            report = probe("example.invalid", 443)
        self.assertEqual((report["status"], report["stage"]), ("timeout", "dns"))

    def test_real_loopback_connection(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            report = probe("127.0.0.1", server.getsockname()[1])
        self.assertEqual(report["status"], "reachable")

    def test_refused_connection(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 12345))]
        with patch("network_checks.resolve", return_value=addresses):
            with patch("network_checks.socket.socket") as connection:
                connection.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError
                self.assertEqual(probe("localhost", 12345)["status"], "refused")

    def test_tcp_timeout(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 12345))]
        with patch("network_checks.resolve", return_value=addresses):
            with patch("network_checks.socket.socket") as connection:
                connection.return_value.__enter__.return_value.connect.side_effect = TimeoutError
                self.assertEqual(probe("localhost", 12345)["status"], "timeout")
