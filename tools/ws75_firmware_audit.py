#!/usr/bin/env python3
"""Read-only offline SHA-256 audit of NVIDIA firmware files. No installation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def audit(root, manifest):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("firmware root must be a directory")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("manifest requires a nonempty files list")
    seen, results = set(), []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("file entry must be an object")
        name, expected = item.get("path"), item.get("sha256")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("invalid or duplicate firmware path")
        seen.add(name)
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts or chr(92) in name:
            raise ValueError("unsafe firmware path")
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected):
            raise ValueError("sha256 must be 64 hex characters")
        target = root / rel
        if not target.resolve(strict=False).is_relative_to(root):
            raise ValueError("firmware path escapes root")
        if not target.is_file():
            results.append({"path": name, "status": "missing"})
            continue
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        results.append({"path": name, "status": "match" if digest.hexdigest() == expected.lower() else "mismatch"})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware_root", type=Path)
    parser.add_argument("manifest", type=Path, help="JSON: {files:[{path,sha256}]}")
    args = parser.parse_args(argv)
    try:
        results = audit(args.firmware_root, json.loads(args.manifest.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"audit error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"files": results, "compatible_with_ws75": "unverified"}, indent=2))
    return 0 if all(item["status"] == "match" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
