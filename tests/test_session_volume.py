"""Session cleanup must retain the configured Docker volume directory."""
from importlib import import_module


def test_delete_token_retains_configured_store(monkeypatch, tmp_path):
    module = import_module('monarch_mcp_server.secure_session')
    token_file = tmp_path / 'session'
    token_file.write_text('test-token')
    monkeypatch.setenv('SESSION_STORE_PATH', str(token_file))
    monkeypatch.setattr(module, '_TOKEN_FILE', token_file)
    monkeypatch.setattr(module, '_TOKEN_DIR', tmp_path)
    manager = object.__new__(module.SecureMonarchSession)
    manager._delete_token_file()
    assert not token_file.exists()
    assert tmp_path.is_dir()
