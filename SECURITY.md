# Security

jspX is a local learning simulation, not production SCADA. The Compose port
binds to `127.0.0.1`, and the HTTP command API has no authentication or TLS.
Do not expose it to an untrusted network or connect it to real equipment.
Production use would require authentication, access control, TLS, rate limits,
secret management, and a security review. Never commit real credentials.
