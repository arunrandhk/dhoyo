import os
import pytest

# Synthetic test-only secret also reaches subprocess/container-source tests.
# Production must supply its own persistent random key through private settings.
os.environ.setdefault('AUTH_JWT_SECRET', 'synthetic-test-only-jwt-key-0123456789abcdefghijklmnopqrstuvwxyz')

@pytest.fixture(autouse=True)
def legacy_demo_fixtures(request, monkeypatch):
    # Existing domain tests exercise the seeded fixture; authentication is covered
    # by test_auth with independent accounts and real session cookies.
    from app import app
    monkeypatch.setitem(app.config, 'TESTING', True)
    # Existing API fixtures exercise domain behavior; encryption has separate
    # strict tests that disable this test-only compatibility switch.
    monkeypatch.setitem(app.config, 'AUTH_TEST_ALLOW_PLAINTEXT', True)
    if request.node.path.name != 'test_auth.py':
        monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', True)
