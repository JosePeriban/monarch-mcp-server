# Remote Monarch session setup

This API is deployed separately from MCP, at **Media loopback port 8001**.
It requires an independent bearer API key from `.admin-api-key` and works
while the MCP remains read-only. It is not an OpenAI API key or Monarch token.
The OpenAI MCP tunnel does not provide an ordinary REST URL for these endpoints.

From a computer with SSH access to Media, keep this command running:

```sh
ssh -N -L 127.0.0.1:18001:127.0.0.1:8001 joseperiban@media.anaideia.dev
```

Then send requests to `http://127.0.0.1:18001` using curl, Postman, or another
HTTP client. SSH encrypts traffic to Media. Do not publish port 8001 to the
internet or send credentials over unencrypted LAN HTTP.

On the Mac mini, the generated key is stored in this checkout's
`.admin-api-key` (mode 0600). Copy it into your HTTP client's Bearer Token
field. Do not paste it or Monarch credentials into chat. Administrators on
Media can retrieve it with `docker compose -f compose.media.yaml exec -T
monarch-mcp cat /run/secrets/monarch_admin_key` from the deployment directory.

## Requests

All requests require `Authorization: Bearer YOUR_ADMIN_API_KEY`.
POST requests require `Content-Type: application/json`.

| Method | Path | JSON body / result |
| --- | --- | --- |
| GET | `/auth/status` | Returns `session_saved` (presence only, not a live validation). |
| POST | `/auth/login` | `{"email":"you@example.com","password":"YOUR_PASSWORD"}` |
| POST | `/auth/login` | If MFA is requested, repeat with email, password, and `"mfa_code":"123456"`. |
| POST | `/auth/token` | `{"token":"YOUR_BROWSER_SESSION_TOKEN"}` for an existing browser session / SSO. |

Success is HTTP 200 with `{"status":"authenticated"}`. HTTP 202 with
`{"status":"mfa_required",...}` means repeat the login with the MFA code.
Validation uses a read of Monarch accounts before saving; no account data or
credentials are returned. Passwords and MFA codes are not persisted. Session
tokens persist in the Docker volume, and the MCP client cache is cleared so
subsequent calls use the new session without restarting.

For curl, create a private JSON request file in a temporary directory and run:

```sh
curl --fail-with-body http://127.0.0.1:18001/auth/login \
  -H "Authorization: Bearer $(cat .admin-api-key)" \
  -H 'Content-Type: application/json' \
  --data-binary @/path/to/private-login.json
```

Delete the request file after use. For token import change the URL to
`/auth/token` and use the token JSON body above.

Failed validation leaves the previous session intact. Errors are sanitized:
401 = API key missing/incorrect; 400/415 = invalid request; 413 = body over
16 KiB; 429 = more than 10 authenticated submissions per minute; 502 = Monarch
rejected login/validation or another upstream failure; 503 = storage/network
unavailable; 504 = timeout. A 502 alone does not prove a token expired.
No access/request-body logging is enabled on the REST listener.
