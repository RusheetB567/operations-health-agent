"""Inject three known defects into temporary copies and verify tests reject them."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = (
    ("failed-services-return-success", "service_monitor.py",
     'return 1 if report["status"] == "warning" else 0', 'return 0',
     "test_service_regressions"),
    ("duplicate-service-names-accepted", "service_monitor.py",
     'if name in names:', 'if False:', "test_service_monitor"),
    ("http-readiness-comparison-inverted", "http_checks.py",
     'report["http_status"] == expected_status', 'report["http_status"] != expected_status',
     "test_http_checks"),
)


def run():
    results = []
    for name, filename, before, after, module in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="agent-regression-") as directory:
            copy = Path(directory)
            for source in ROOT.glob("*.py"):
                shutil.copy2(source, copy / source.name)
            shutil.copytree(ROOT / "tests", copy / "tests", ignore=shutil.ignore_patterns("__pycache__"))
            target = copy / filename
            content = target.read_text(encoding="utf-8")
            if content.count(before) != 1:
                results.append({"mutation": name, "status": "invalid_anchor"})
                continue
            target.write_text(content.replace(before, after, 1), encoding="utf-8")
            try:
                process = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                                          "-p", module + ".py", "-q"], cwd=copy,
                                         capture_output=True, text=True, timeout=30)
                # Import/collection errors do not count as catching a behavioural defect.
                caught = process.returncode != 0 and "FAIL:" in process.stderr and "ImportError" not in process.stderr
                results.append({"mutation": name, "status": "detected" if caught else "not_detected"})
            except subprocess.TimeoutExpired:
                results.append({"mutation": name, "status": "timed_out"})
    print(json.dumps({"checks": results}, indent=2))
    return 0 if all(item["status"] == "detected" for item in results) else 1


if __name__ == "__main__":
    sys.exit(run())
