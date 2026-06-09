#!/usr/bin/env python3
"""Pre-commit / CI secret scanner — blocks diffs containing secrets."""

import re
import sys

PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(?i)(?:api[_-]?key|api[_-]?secret|passphrase|password|token|secret)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"
    ),
    re.compile(r"(?i)ZTB_BYBIT_API_(?:KEY|SECRET|PASSPHRASE)\s*=\s*\S+"),
]

IGNORED_FILES: set[str] = {
    ".gitignore",
    ".pre-commit-config.yaml",
    "pyproject.toml",
}


def scan_file(path: str) -> list[str]:
    findings: list[str] = []
    try:
        with open(path) as f:
            for i, line in enumerate(f, 1):
                for pat in PATTERNS:
                    if pat.search(line):
                        findings.append(f"{path}:{i}: potential secret pattern")
                        break
    except Exception:
        pass
    return findings


def main() -> int:
    files = sys.argv[1:] if len(sys.argv) > 1 else []
    if not files:
        return 0
    findings: list[str] = []
    for f in files:
        base = f.rsplit("/", 1)[-1] if "/" in f else f
        if base in IGNORED_FILES:
            continue
        findings.extend(scan_file(f))
    if findings:
        for line in findings:
            print(line, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
