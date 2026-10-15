"""Google sign-in receives origin-compatible headers without exposing link tokens."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app


def test_google_page_headers_allow_provider_and_keep_private_routes_referrer_free(monkeypatch):
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', 'synthetic.apps.googleusercontent.com')
    client = app.test_client()
    page = client.get('/static/sportspace/index.html', base_url='https://localhost')
    assert page.status_code == 200
    assert page.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    assert page.headers['Cross-Origin-Opener-Policy'] == 'same-origin-allow-popups'
    policy = page.headers['Content-Security-Policy']
    for source in ('https://accounts.google.com/gsi/client', 'https://accounts.google.com/gsi/style',
                   'frame-src https://accounts.google.com/gsi/'):
        assert source in policy
    assert "script-src 'self' https://accounts.google.com/gsi/client;" in policy
    local = client.get('/static/sportspace/index.html', base_url='http://localhost')
    assert local.headers['Referrer-Policy'] == 'no-referrer-when-downgrade'
    for path in ('/api/auth/google/config', '/tournament-acknowledgement'):
        response = client.get(path, base_url='https://localhost')
        assert response.headers['Referrer-Policy'] == 'no-referrer'


def test_google_disabled_keeps_account_page_referrer_free(monkeypatch):
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', '')
    response = app.test_client().get('/static/sportspace/index.html', base_url='https://localhost')
    assert response.headers['Referrer-Policy'] == 'no-referrer'
