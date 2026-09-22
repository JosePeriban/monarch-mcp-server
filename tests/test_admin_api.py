from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest
from monarch_mcp_server import admin_api

KEY = 'a' * 48

@pytest.fixture
def setup(monkeypatch):
    class MFARequired(Exception):
        pass
    client = MagicMock(token='private-session-token')
    client.login = AsyncMock()
    client.multi_factor_authenticate = AsyncMock()
    client.get_accounts = AsyncMock(return_value={'accounts': []})
    store = MagicMock()
    clear = MagicMock()
    monkeypatch.setattr(admin_api, 'MonarchMoney', MagicMock(return_value=client))
    monkeypatch.setattr(admin_api, 'RequireMFAException', MFARequired)
    monkeypatch.setattr(admin_api, 'secure_session', store)
    monkeypatch.setattr(admin_api, 'clear_client_cache', clear)
    return admin_api.create_admin_app(KEY), client, store, clear, MFARequired

@pytest.mark.asyncio
async def test_auth_required(setup):
    app, client, store, _, _ = setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as http:
        for path in ['/auth/login', '/auth/token']:
            r = await http.post(path, json={'token': 'secret'})
            assert r.status_code == 401
        assert (await http.get('/auth/status')).status_code == 401
    client.login.assert_not_called()
    store.save_authenticated_session.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['password', 'mfa', 'token'])
async def test_validated_session_saved(setup, mode):
    app, client, store, clear, mfa = setup
    payload = {'email': 'user@example.com', 'password': 'private-password'}
    path = '/auth/login'
    if mode == 'mfa':
        client.login.side_effect = mfa()
        payload['mfa_code'] = '123456'
    if mode == 'token':
        payload = {'token': 'private-token'}
        path = '/auth/token'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test', headers={'Authorization': f'Bearer {KEY}'}) as http:
        r = await http.post(path, json=payload)
        assert r.status_code == 200
        assert r.json() == {'status': 'authenticated'}
        assert r.headers['cache-control'] == 'no-store'
    client.get_accounts.assert_awaited_once()
    store.save_authenticated_session.assert_called_once_with(client)
    clear.assert_called_once()
    if mode == 'mfa':
        client.multi_factor_authenticate.assert_awaited_once_with('user@example.com', 'private-password', '123456')

@pytest.mark.asyncio
async def test_mfa_challenge_does_not_replace_session(setup):
    app, client, store, _, mfa = setup
    client.login.side_effect = mfa()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test', headers={'Authorization': f'Bearer {KEY}'}) as http:
        r = await http.post('/auth/login', json={'email': 'a', 'password': 'b'})
        assert r.status_code == 202
        assert r.json()['status'] == 'mfa_required'
    store.save_authenticated_session.assert_not_called()

@pytest.mark.asyncio
async def test_upstream_failure_redacted_and_old_session_preserved(setup):
    app, client, store, clear, _ = setup
    client.get_accounts.side_effect = RuntimeError('sensitive-token-password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test', headers={'Authorization': f'Bearer {KEY}'}) as http:
        r = await http.post('/auth/token', json={'token': 'sensitive-token-password'})
        assert r.status_code == 502
        assert 'sensitive' not in r.text
    store.save_authenticated_session.assert_not_called()
    store.delete_token.assert_not_called()
    clear.assert_not_called()

@pytest.mark.asyncio
async def test_validation_and_rate_limit(setup):
    app, client, store, _, _ = setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test', headers={'Authorization': f'Bearer {KEY}'}) as http:
        assert (await http.post('/auth/token', json={'token': 123})).status_code == 400
        assert (await http.post('/auth/token', content='x')).status_code == 415
        assert (await http.post('/auth/token', content='x' * 17000, headers={'Content-Type': 'application/json'})).status_code == 413
        for _ in range(7):
            await http.post('/auth/token', json={})
        assert (await http.post('/auth/token', json={'token': 't'})).status_code == 429
    store.save_authenticated_session.assert_not_called()
