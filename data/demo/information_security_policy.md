# Information Security Policy

## Framework

The information security management system (ISMS) is aligned with
**ISO/IEC 27001:2022**. Control selection and risk treatment follow Annex A;
the statement of applicability is reviewed at least annually.

## Access Control

Access to internal systems follows the **least-privilege principle**: users
receive the minimum permissions required for their role. All access rights
are reviewed **quarterly**; unused accounts are disabled after 60 days of
inactivity.

Privileged access (production databases, cloud consoles, deployment
pipelines) additionally requires **multi-factor authentication** and is
granted only through the access-request workflow with manager approval.

## Backups

Backups are taken daily and are **encrypted at rest** using AES-256.
Restorability is verified through scheduled restore tests: a random backup
set is restored to an isolated environment **every month**, and the outcome
is recorded in the operations log.

Backup encryption keys are stored in the key management service, separated
from the backup storage itself.

## Cryptography

Data in transit is protected with TLS 1.2 or higher. Secrets and API keys
are stored in a dedicated vault; hard-coding credentials in source code is
prohibited and monitored by CI checks (see Section 4.2 of the secure
development standard).

## Vendor Management

Vendors processing company data undergo a security assessment before
onboarding and are re-assessed every two years. SOC 2 Type II or ISO 27001
certification is accepted as assessment evidence.
