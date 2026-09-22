"""Private REST session setup, isolated from the MCP listener and tools."""
import asyncio
from collections import deque
import hmac
import time

from monarchmoney import MonarchMoney, RequireMFAException
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from monarch_mcp_server.client import clear_client_cache
from monarch_mcp_server.secure_session import secure_session


def create_admin_app(api_key: str) -> Starlette:
    if len(api_key) < 32:
        raise ValueError('Admin API key must contain at least 32 characters')
    attempts = deque()
    lock = asyncio.Lock()

    def response(data, status=200):
        return JSONResponse(data, status_code=status, headers={'Cache-Control': 'no-store'})

    async def handle(request: Request):
        supplied = request.headers.get('authorization', '')
        if not hmac.compare_digest(supplied.encode(), ('Bearer ' + api_key).encode()):
            return response({'error': 'unauthorized'}, 401)
        if request.method == 'GET':
            return response({'session_saved': bool(secure_session.load_token())})
        now = time.monotonic()
        while attempts and attempts[0] <= now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            return response({'error': 'rate_limited', 'retry_after_seconds': 60}, 429)
        attempts.append(now)
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            return response({'error': 'application_json_required'}, 415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return response({'error': 'body_too_large'}, 413)
        import json
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return response({'error': 'invalid_json'}, 400)
        fields = {'token'} if request.url.path.endswith('/token') else {'email', 'password', 'mfa_code'}
        required = {'token'} if 'token' in fields else {'email', 'password'}
        if (not isinstance(data, dict) or set(data) - fields or not required <= set(data)
                or any(not isinstance(v, str) or not v.strip() for v in data.values())):
            return response({'error': 'invalid_fields'}, 400)
        try:
            async with asyncio.timeout(45):
                async with lock:
                    if 'token' in fields:
                        client = MonarchMoney(token=data['token'].strip())
                    else:
                        client = MonarchMoney()
                        try:
                            await client.login(data['email'], data['password'],
                                               use_saved_session=False, save_session=False)
                        except RequireMFAException:
                            if not data.get('mfa_code'):
                                return response({'status': 'mfa_required',
                                                 'next': 'Repeat login with email, password and mfa_code'}, 202)
                            await client.multi_factor_authenticate(data['email'], data['password'], data['mfa_code'])
                    # Verify before replacing the existing session. Return no account data.
                    await client.get_accounts()
                    if not client.token:
                        return response({'error': 'no_session_returned'}, 502)
                    secure_session.save_authenticated_session(client)
                    clear_client_cache()
        except TimeoutError:
            return response({'error': 'monarch_timeout'}, 504)
        except OSError:
            return response({'error': 'session_or_network_unavailable'}, 503)
        except Exception:
            # Upstream exceptions can include credential-bearing request payloads.
            return response({'error': 'monarch_login_or_validation_failed'}, 502)
        return response({'status': 'authenticated'})

    return Starlette(routes=[
        Route('/auth/status', handle, methods=['GET']),
        Route('/auth/login', handle, methods=['POST']),
        Route('/auth/token', handle, methods=['POST']),
    ])
