# Media deployment

This fork uses `compose.media.yaml` for Media (`media.anaideia.dev`,
`192.168.1.99`). `DEPLOY.md` describes the upstream author's infrastructure,
not this installation. The initial Media service is read-only.

## Configuration

Keep `.env` private (mode 0600), outside Git. Required settings:

- `MONARCH_IMAGE_TAG`: deployed Git commit
- `HOST_PORT`: an unused host TCP port
- `PUBLIC_URL` and `OAUTH_AUDIENCE`: the public HTTPS origin
- `OAUTH_ISSUER` and `OAUTH_JWKS_URI`: verified authorization server endpoints

The identity provider must restrict access to the owner's account and issue
resource-specific tokens with `monarch:read`. Configure the MCP-compatible
OAuth discovery/PKCE/client registration flow before publishing the route.
The Monarch service validates tokens; it is not an authorization server.

Use `docker compose -f compose.media.yaml config --quiet` to validate, then
`docker compose -f compose.media.yaml up -d --build`. The host binding defaults
to loopback. For the existing Home Assistant tunnel on another machine,
set `MONARCH_BIND_IP=192.168.1.99` only after authentication is verified.
Keep the router's inbound ports closed. Cloudflare Tunnel routes the chosen
hostname to `http://192.168.1.99:<HOST_PORT>`; it does not replace OAuth.
The tunnel is remotely managed, so its routes must be edited through the
Cloudflare management API. Its connector token is not a management API token.

Monarch session data is stored in the dedicated `monarch-mcp_monarch-session`
Docker volume. Provision only the existing Monarch session, or configure
headless login using the documented environment settings. Never include
credentials or session files in the image, logs, Git, or command arguments.
The image build excludes local credentials with `.dockerignore`.

## Verification before enabling the route

1. `/healthz` returns healthy.
2. MCP requests with absent, invalid, or wrong-audience tokens fail.
3. Protected-resource metadata identifies the expected public origin and issuer.
4. A valid owner token can initialize MCP and list tools, including goals.
5. Write tools are absent from the initial read-only deployment.
6. A read-only Monarch call succeeds using the stored session.
7. Repeat the protocol and authentication checks through the HTTPS route.
8. Complete OAuth login in Codex and ChatGPT and verify a read-only call.

Preserve the session volume during upgrades and rollbacks. Rebuild a prior
reviewed commit/tag to roll back; do not use `down -v`.
