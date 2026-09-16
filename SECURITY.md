# Security Policy

## Supported Versions

The following versions of `fn-ignis` are currently supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4   | :x:                |

`fn-ignis` is a beta (`0.x`). Only the current minor line receives security updates; older lines
are not backported.

## Reporting a Vulnerability

The `fnIgnis` (`fn-ignis`) team at **FINOLABS** takes the security and integrity of our codebase and self-hosted deployments seriously.

If you believe you have found a security vulnerability in `fnIgnis`:

1. **Do not open a public GitHub issue.**
2. Please report the issue privately by contacting the maintainers or sending an email to fioenix@finolabs.io.
3. Include details of the vulnerability:
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if known)

We will acknowledge receipt of your vulnerability report within 48 hours and work with you to remediate the issue responsibly before public disclosure.

## Security Practices

- **Zero-Token Local Ingress**: `fn-ignis` runs local ETL parsers without transmitting raw
  collected data to third-party LLM APIs.
- **Fernet Credential Encryption**: Stored platform credentials and browser session state are
  encrypted with Fernet, which is AES-128-CBC for confidentiality with HMAC-SHA256 for
  authentication, under a 256-bit key split between the two. The key comes from
  `IGNIS_ENCRYPTION_KEY`; if it is absent the process falls back to an ephemeral key, so anything
  encrypted in that state does not survive a restart.
- **Parameterized Queries**: Database access uses driver placeholders rather than string
  interpolation — `%s` on PostgreSQL and `?` on SQLite.
- **No Hardcoded Secrets**: Nothing secret is committed to the repository. Two different stores
  hold two different kinds of credential, and they have different risks:
  - **Static deployment configuration** — the database connection settings and
    `IGNIS_ENCRYPTION_KEY` — is read from environment variables in a single `.env` file, which is
    gitignored. Generated MCP client configurations carry the path to that file
    (`IGNIS_ENV_FILE`) rather than copies of the values.
  - **Platform OAuth tokens and browser-session credentials** are not kept in that file. They are
    encrypted and stored in the database, in `platform_credentials`, under the key above. Securing
    the environment file therefore does not secure these; the database holding them needs its own
    access control and backup handling.

### Known limitations

Stated so an operator can judge the risk rather than infer a guarantee:

- **No key rotation support in the current release.** Encrypted values are readable only under the
  key that wrote them; there is no dual-key decryption path, so replacing
  `IGNIS_ENCRYPTION_KEY` makes existing ciphertext unreadable. Re-authenticate each connector after
  changing it.
- **Browser-driven connectors run with the operator's own session** on the operator's machine.
  Their credentials and platform terms are the operator's responsibility.
- **PII sanitization is applied at ingress and before rendering**, but it is pattern-based and is
  not a guarantee that every identifier has been removed from collected third-party content.
