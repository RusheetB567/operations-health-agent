"""HTTP readiness checks isolated in a child process for bounded DNS and I/O."""
import argparse
import json
import subprocess
import sys
import time
from urllib.parse import urlsplit


def http_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or (port is not None and port < 1)
                or any(ord(char) < 33 or ord(char) == 127 for char in value)):
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError(
            "use an HTTP(S) URL without credentials, query strings or fragments") from None
    return value


def check_http(url, timeout=3, expected_status=200):
    started = time.monotonic()
    report = {"url": url, "expected_status": expected_status}
    script = (
        "import http.client,json,sys; from urllib.parse import urlsplit; "
        "u=urlsplit(sys.argv[1]); "
        "cls=http.client.HTTPSConnection if u.scheme=='https' else http.client.HTTPConnection; "
        "c=cls(u.hostname,u.port,timeout=float(sys.argv[2])); "
        "c.request('GET',u.path or '/',headers={'User-Agent':'operations-health-agent'}); "
        "r=c.getresponse(); print(json.dumps({'http_status':r.status})); c.close()"
    )
    try:
        result = subprocess.run([sys.executable, "-c", script, url, str(timeout)],
                                capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode:
            report["status"] = "connection_error"
        else:
            report.update(json.loads(result.stdout))
            report["status"] = "ready" if report["http_status"] == expected_status else "unexpected_status"
    except subprocess.TimeoutExpired:
        report["status"] = "timeout"
    except (OSError, ValueError):
        report["status"] = "error"
    report["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
    return report
