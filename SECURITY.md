# Security

jspX is a local learning simulation, not a production SCADA system.

## Development credentials

- Never commit real passwords, tokens, certificates, or customer data.
- Keep local values in `.env`; commit only safe example values and placeholders.
- If a secret is committed accidentally, revoke or rotate it rather than only deleting it from a later commit.

## Network exposure

- Docker service ports are intended to bind to localhost during development.
- MQTT currently has no production authentication or TLS configuration.
- Do not expose this stack to an untrusted network or use it to control real equipment.

## Future hardening

Production use would require authentication, TLS, secret management, access control, and a security review.