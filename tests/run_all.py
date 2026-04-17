"""
run_all.py — run every sgb-codec test file in dependency order and
summarise the combined results.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

TEST_FILES = [
    "test_m2_bch.py",
    "test_m3_prn.py",
    "test_m4_message.py",
    "test_m5_modulation.py",
]


def main() -> int:
    failures = []
    for name in TEST_FILES:
        path = os.path.join(HERE, name)
        print(f"\n########## {name} ##########")
        r = subprocess.run(
            [sys.executable, path],
            cwd=HERE,
            stdout=sys.stdout, stderr=sys.stderr,
        )
        if r.returncode != 0:
            failures.append(name)

    print("\n======================================")
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print("ALL TEST SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
