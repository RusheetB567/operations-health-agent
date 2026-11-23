"""Bounded, opt-in DNS and TCP diagnostics; no application traffic is sent."""
import argparse
import json
import math
import socket
import subprocess
import sys
import time


def endpoint(value):
    host, separator, port_text = value.rpartition(":")
    try:
        port = int(port_text)
    except ValueError:
        raise argparse.ArgumentTypeError("use HOST:PORT or [IPv6]:PORT") from None
    host = host.removeprefix("[").removesuffix("]")
    if not separator or not host or not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("host required; port must be 1–65535")
    return host, port


def timeout_seconds(value):
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 60:
        raise argparse.ArgumentTypeError("timeout must be finite and between 0 and 60 seconds")
    return number


def resolve(host, port, timeout):
    # OS DNS APIs have no portable timeout. A child process can be terminated
    # without leaving an unbounded resolver thread behind.
    script = (
        "import json,socket,sys; "
        "print(json.dumps(socket.getaddrinfo(sys.argv[1],int(sys.argv[2]),"
        "type=socket.SOCK_STREAM)))"
    )
    result = subprocess.run([sys.executable, "-c", script, host, str(port)],
                            capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise socket.gaierror("name resolution failed")
    return json.loads(result.stdout)


def probe(host, port, timeout=3):
    started = time.monotonic()
    deadline = started + timeout
    report = {"host": host, "port": port, "status": "error", "stage": "dns"}
    try:
        addresses = resolve(host, port, timeout)
        report["resolved_addresses"] = sorted({entry[4][0] for entry in addresses})
        report["stage"] = "tcp"
        failures = []
        for family, kind, protocol, _, address in addresses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                with socket.socket(family, kind, protocol) as connection:
                    connection.settimeout(remaining)
                    connection.connect(tuple(address))
                report["status"] = "reachable"
                break
            except ConnectionRefusedError:
                failures.append("refused")
            except TimeoutError:
                failures.append("timeout")
            except OSError:
                failures.append("unreachable")
        else:
            report["status"] = "refused" if failures and all(
                failure == "refused" for failure in failures) else (
                "timeout" if "timeout" in failures else "unreachable")
    except (subprocess.TimeoutExpired, TimeoutError):
        report["status"] = "timeout"
    except socket.gaierror:
        report["status"] = "dns_error"
    except (OSError, ValueError):
        report["status"] = "error"
    report["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
    return report
