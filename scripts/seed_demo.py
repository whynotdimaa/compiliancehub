"""Seed a demo tenant with policy documents matching the golden dataset.

Usage (stack must be running: `make up && make migrate`):
    python scripts/seed_demo.py [--base-url http://localhost:8000]

Idempotent: re-running skips already-uploaded filenames. After seeding, try:
    POST /api/v1/ask            {"question": "How long is personal data retained?"}
    POST /api/v1/evaluation/runs {}     # golden dataset scores the pipeline
"""
import argparse
import sys
import time
from pathlib import Path

import httpx

DEMO_DIR = Path(__file__).parent.parent / "data" / "demo"

TENANT = {
    "tenant_name": "Demo Corp",
    "tenant_slug": "demo",
    "admin_email": "admin@demo.io",
    "admin_password": "demo-password-1",
    "admin_full_name": "Demo Admin",
}

DOC_TYPES = {
    "data_protection_policy.md": "policy",
    "information_security_policy.md": "policy",
    "incident_response_plan.md": "policy",
}


def main(base_url: str) -> int:
    api = f"{base_url.rstrip('/')}/api/v1"
    client = httpx.Client(timeout=60.0)

    register = client.post(f"{api}/auth/register", json=TENANT)
    if register.status_code == 201:
        print(f"Registered tenant '{TENANT['tenant_slug']}'")
    elif register.status_code == 409:
        print(f"Tenant '{TENANT['tenant_slug']}' already exists")
    else:
        print(f"Registration failed: {register.status_code} {register.text}")
        return 1

    login = client.post(
        f"{api}/auth/login",
        json={
            "tenant_slug": TENANT["tenant_slug"],
            "email": TENANT["admin_email"],
            "password": TENANT["admin_password"],
        },
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    existing = {
        d["filename"] for d in client.get(f"{api}/documents", headers=headers).json()
    }

    uploaded: list[str] = []
    for path in sorted(DEMO_DIR.glob("*.md")):
        if path.name in existing:
            print(f"Skipping {path.name} (already uploaded)")
            continue
        response = client.post(
            f"{api}/documents",
            headers=headers,
            files={"file": (path.name, path.read_bytes(), "text/markdown")},
            data={"doc_type": DOC_TYPES.get(path.name, "policy")},
        )
        response.raise_for_status()
        uploaded.append(response.json()["id"])
        print(f"Uploaded {path.name}")

    deadline = time.time() + 180
    pending = set(uploaded)
    while pending and time.time() < deadline:
        time.sleep(3)
        for document_id in list(pending):
            status = client.get(
                f"{api}/documents/{document_id}/status", headers=headers
            ).json()
            if status["status"] == "ready":
                print(f"READY: {document_id} ({status['chunk_count']} chunks)")
                pending.discard(document_id)
            elif status["status"] == "failed":
                print(f"FAILED: {document_id} — {status['error']}")
                pending.discard(document_id)

    if pending:
        print(f"Timed out waiting for: {pending}")
        return 1

    print("\nDemo tenant ready.")
    print(f"  Login:    {TENANT['admin_email']} / {TENANT['admin_password']} (slug: demo)")
    print(f"  Swagger:  {base_url}/docs")
    print('  Try /ask: {"question": "How long is personal data retained?"}')
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    sys.exit(main(args.base_url))
