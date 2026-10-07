# Security Policy

## Supported version

Security fixes target the latest code on `main`. Older local checkouts are not
maintained as separate supported release lines.

## Reporting a vulnerability

Please **do not open a public issue** for a suspected security vulnerability.

Use GitHub's private vulnerability reporting flow for this repository:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Include the affected version/commit, impact, reproduction steps and any
   relevant logs with credentials, account identifiers and personal data removed.

If the private reporting UI is temporarily unavailable, contact the maintainer
through the GitHub profile rather than posting exploit details publicly.

## Security boundaries

Trade Alert is intentionally a local, read-only notifier:

- it has no broker login or order-execution capability;
- durable portfolio/thesis state belongs outside this repository;
- OAuth material, credentials, account identifiers and machine-specific secrets
  must never be committed;
- local configuration and alert state live outside Git under the user's local
  application-data directory;
- market headlines and provider payloads are untrusted external data and are
  treated as data, never as instructions;
- provider identifiers must be verified before they are used in a live profile.

Please include any boundary bypass, credential exposure, unsafe command
execution, or dependency/supply-chain issue in private security reports.
