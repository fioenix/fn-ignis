# Security Policy

## Supported Versions

The following versions of `fn-ignis` are currently supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

The `fn-ignis` team takes the security and integrity of our codebase and self-hosted deployments seriously.

If you believe you have found a security vulnerability in `fn-ignis`:

1. **Do not open a public GitHub issue.**
2. Please report the issue privately by contacting the maintainers or sending an email to security@fioenix.dev.
3. Include details of the vulnerability:
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if known)

We will acknowledge receipt of your vulnerability report within 48 hours and work with you to remediate the issue responsibly before public disclosure.

## Security Practices

- **Zero-Token Local Ingress**: `fn-ignis` runs local ETL parsers without transmitting raw customer data to third-party proprietary LLM APIs.
- **AES-256-GCM Session Storage**: Any persistent browser session cookies are stored in encrypted format.
- **Strict Parameterized Queries**: All database queries use parameterized placeholders (`%s`) to prevent SQL injection.
- **No Hardcoded Secrets**: Secrets and database credentials must always be provided via environment variables (`.env`).
