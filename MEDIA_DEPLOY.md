# Media deployment through OpenAI Secure MCP Tunnel

Media (`media.anaideia.dev`, amd64) runs two Docker services: Monarch serves
Streamable HTTP on a dedicated Docker network; the official OpenAI tunnel client
connects to it and makes outbound HTTPS connections to OpenAI. The MCP port is not published. A separate REST setup listener is published
only on Media loopback port 8001, protected by a dedicated API key. No Cloudflare route or separate MCP OAuth provider is
used. The server keeps upstream's optional OAuth support. Monarch Money itself
still requires a saved Monarch session.

## REST login setup

See [REST_AUTH.md](REST_AUTH.md) for remote SSH forwarding and JSON requests.
Create `.admin-api-key` before starting Compose. It must contain a random secret
of at least 32 characters and be readable by container UID 10001. Keep it out
of Git and images; the Compose secret mount makes it available only to Monarch.

## Start the private server

```sh
docker compose -f compose.media.yaml up -d --build monarch-mcp
```

The initial deployment is read-only. Session data lives in the dedicated
`monarch-mcp_monarch-session` volume. Keep sessions and credentials out of Git,
images and logs. `DEPLOY.md` describes the upstream author's unrelated public
hosting setup, not this installation.

## Activate the tunnel later

Create a tunnel at https://platform.openai.com/settings/organization/tunnels
and associate it with the intended ChatGPT workspace and Platform organization.
Use a runtime API key with Tunnels Read + Use, not an admin key. Restrict who can
use the tunnel: its callers share access to this personal Monarch session.

Create `.env.tunnel` beside the Compose file, with mode 0600, containing:

```dotenv
CONTROL_PLANE_TUNNEL_ID=tunnel_YOUR_ID
CONTROL_PLANE_API_KEY=YOUR_RUNTIME_KEY
```

Then run:

```sh
docker compose -f compose.media.yaml --profile tunnel build tunnel-client
docker compose -f compose.media.yaml --profile tunnel up -d
docker compose -f compose.media.yaml logs --tail 30 tunnel-client
```

Select the tunnel in ChatGPT's developer-mode app setup. Account permissions and
workspace association must be verified before expecting it to appear in ChatGPT
or a supported Codex surface. The tunnel cannot connect until the ID/key exist.
Its health/admin listener is loopback-only inside its container.

The tunnel image packages official `openai/tunnel-client` release v0.0.14 for
Linux amd64 and verifies the published SHA-256 before extraction. Check
https://github.com/openai/tunnel-client/releases/latest when planning upgrades;
update version and checksum together after reviewing the release.

## Checks and rollback

Check container health, initialize MCP, list goal tools, and verify mutations
are absent. After tunnel activation, verify readiness and an end-to-end read
through the target OpenAI client. Without tunnel credentials only local Docker
checks are possible. Preserve the session volume during upgrades or rollback;
never use `down -v`. Do not add a host port or public proxy to this unauthenticated
HTTP service.

Reference: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
