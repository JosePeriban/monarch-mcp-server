"""Send JSON from stdin to the local REST API (also usable through SSH exec)."""
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request


def main():
    paths = {'/auth/status', '/auth/login', '/auth/token'}
    if len(sys.argv) != 2 or sys.argv[1] not in paths:
        raise SystemExit('Usage: python -m monarch_mcp_server.admin_request /auth/{status,login,token}')
    path = sys.argv[1]
    key = Path(os.environ['ADMIN_API_KEY_FILE']).read_text().strip()
    data = None if path == '/auth/status' else sys.stdin.buffer.read(16385)
    if data is not None and len(data) > 16384:
        raise SystemExit('Request body exceeds 16 KiB')
    request = urllib.request.Request(
        'http://127.0.0.1:' + os.getenv('ADMIN_API_PORT', '8001') + path,
        data=data, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            print(response.read().decode())
    except urllib.error.HTTPError as error:
        print(error.read().decode())
        raise SystemExit(1)
    except (OSError, urllib.error.URLError):
        raise SystemExit('REST API unavailable')


if __name__ == '__main__':
    main()
