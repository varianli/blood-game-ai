# Security

## Deployment boundary

BloodGame AI is designed for a trusted local network during an in-person event.
It has not been hardened for direct public-Internet exposure and does not provide
production-grade identity, rate limiting, TLS termination, or persistent session
storage.

## Secrets

- Prefer the `DEEPSEEK_API_KEY` environment variable.
- `config.json` and `.env*` are intentionally ignored by Git.
- Never paste a production key into an issue, log, screenshot, or committed file.
- Rotate a key immediately if it is ever committed or publicly shared.

## Reporting a vulnerability

Please use the repository's private GitHub security-advisory flow rather than a
public issue when a report contains exploit details or sensitive information.
