"""零依赖的高置信度凭证扫描；只输出文件和行号，不回显秘密。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "generic_sk_token": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "github_token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._-]{24,}\b", re.I),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[tuple[str, int, str]] = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((str(path.relative_to(ROOT)), line_number, name))

    for filename, line_number, name in findings:
        print(f"{filename}:{line_number}: potential {name} (value redacted)")
    if findings:
        print(f"secret scan failed: {len(findings)} high-confidence finding(s)")
        return 1
    print("secret scan passed: no high-confidence secrets in tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
