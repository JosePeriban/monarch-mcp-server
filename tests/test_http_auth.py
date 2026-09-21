"""Remote transport must never start without authentication."""

from dataclasses import replace
from importlib import import_module

import httpx
import pytest

from monarch_mcp_server.config import OAuthConfig

app_module = import_module("monarch_mcp_server.app")


def oauth_config(**changes):
    values = dict(
        issuer="https://idp.example.com/",
        audience="https://monarch.example.com",
        jwks_uri="https://idp.example.com/jwks.json",
        read_scope="monarch:read",
        write_scope="monarch:write",
        public_url="https://monarch.example.com",
    )
    values.update(changes)
    return OAuthConfig(**values)


@pytest.mark.parametrize("missing", ["issuer", "audience", "jwks_uri", "all"])
def test_http_refuses_incomplete_oauth(monkeypatch, missing):
    changes = {missing: None} if missing != "all" else dict(
        issuer=None, audience=None, jwks_uri=None
    )
    monkeypatch.setattr(app_module, "config", replace(
        app_module.config, transport="http", oauth=oauth_config(**changes)
    ))
    with pytest.raises(ValueError, match="HTTP transport requires OAuth"):
        app_module._build_fastmcp()


def test_stdio_remains_available_without_oauth(monkeypatch):
    monkeypatch.setattr(app_module, "config", replace(
        app_module.config, transport="stdio",
        oauth=oauth_config(issuer=None, audience=None, jwks_uri=None)
    ))
    assert app_module._build_fastmcp() is not None


@pytest.mark.asyncio
async def test_http_rejects_unauthenticated_requests(monkeypatch):
    monkeypatch.setattr(app_module, "config", replace(
        app_module.config, transport="http", oauth=oauth_config()
    ))
    server = app_module._build_fastmcp()
    transport = httpx.ASGITransport(app=server.streamable_http_app())
    async with httpx.AsyncClient(transport=transport, base_url="https://monarch.example.com") as client:
        response = await client.post(app_module.config.mcp_path, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list"
        })
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]
