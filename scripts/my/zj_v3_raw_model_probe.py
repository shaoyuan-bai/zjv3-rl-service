"""Probe the RK3588 export snapshot without attempting to bypass encryption.

The snapshot normally contains file manifests and logs, not the model bytes. This
script reports which model files are actually present and which runtime libraries
are available, so a real RKNN load can be distinguished from a path-only check.
"""
from __future__ import annotations

import json
from pathlib import Path

RAW = Path(r"D:\xwechat_files\wxid_dw65v2dasu9u22_4b64\msg\file\2026-10\raw\rk3588")
MODEL_ROOTS = ("/opt/export/rknn_model_crypto/zg", "/opt/export/rknn_model_crypto/zg_wheels")


def main() -> None:
    manifest = json.loads((RAW / "07-files.json").read_text(encoding="utf-8"))
    files = {entry.get("path"): entry for entry in manifest.get("files", [])}
    print("RKNN_RUNTIME", files.get("/opt/export/mc/bin/librknn_model.so", {}))
    for root in MODEL_ROOTS:
        entries = [v for k, v in files.items() if k and k.startswith(root + "/")]
        print(root, "manifest_entries=", len(entries))
        for item in entries:
            print(" ", item)
    logs = (RAW / "17-log-samples.txt").read_text(encoding="utf-8", errors="replace")
    print("LOAD_FAILURE_LINES")
    for line in logs.splitlines():
        if "rknn_model_crypto" in line or "解密" in line:
            print(line)


if __name__ == "__main__":
    main()
