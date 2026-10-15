"""The native bridge verifies PKCE/session ownership and publishes earned data."""
import io
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from http.client import IncompleteRead
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from test_organisations import accounts, service_clock, create_event, get, post
from app import app
import auth
import play_games
import social

HTTP_JSON = play_games.google_json

SERVER_CODE = 'synthetic-once-only-server-code'
ACCESS_TOKEN = 'synthetic-private-access-token'
REFRESH_TOKEN = 'synthetic-private-refresh-token'
PLAYER_ID = 'synthetic-google-player-id'
CLIENT_SECRET = 'synthetic-game-server-secret'
BASE = '/api/play-games/'


@pytest.fixture
def configured(accounts, monkeypatch):
    values = dict(PLAY_GAMES_APPLICATION_ID='123456789',
        PLAY_GAMES_WEB_CLIENT_ID='synthetic-server.apps.googleusercontent.com',
        PLAY_GAMES_WEB_CLIENT_SECRET=CLIENT_SECRET,
        PLAY_GAMES_ACHIEVEMENTS_JSON=json.dumps({'first-team': 'achievement_team',
            'first-tournament': 'achievement_finish', 'five-tournaments': 'achievement_five',
            'multi-sport': 'achievement_sports'}),
        PLAY_GAMES_LEADERBOARD_ID='leaderboard_lifetime', ANDROID_PACKAGE_NAME='com.dhoyo.app',
        PLAY_STORE_URL='https://play.google.com/store/apps/details?id=com.dhoyo.app')
    for key, value in values.items():
        monkeypatch.setitem(app.config, key, value)
    calls = []
    def provider(endpoint, **kwargs):
        calls.append((endpoint, kwargs))
        if endpoint == play_games.TOKEN_ENDPOINT:
            return dict(access_token=ACCESS_TOKEN, token_type='Bearer', refresh_token=REFRESH_TOKEN)
        if '/applications/' in endpoint:
            return dict(player_id=PLAYER_ID)
        return {'kind': 'synthetic#success'}
    monkeypatch.setattr(play_games, 'google_json', provider)
    return SimpleNamespace(make=accounts, native=app.test_client(), calls=calls, provider=provider)


def approval(player, verifier=None):
    verifier = verifier or secrets.token_urlsafe(32)
    response = post(player['client'], BASE + 'tickets', {'challenge': play_games.pkce_challenge(verifier)})
    assert response.status_code == 200, response.json
    assert response.json['expiresIn'] == 300
    return dict(ticket=response.json['ticket'], verifier=verifier, serverAuthCode=SERVER_CODE)


def connect(configured, payload):
    return post(configured.native, BASE + 'connect', payload)


def test_config_public_safe_optional_store_link_and_status_private(configured):
    response = get(configured.native, BASE + 'config')
    assert response.status_code == 200
    assert response.json == dict(storeUrl='https://play.google.com/store/apps/details?id=com.dhoyo.app',
        androidPackage='com.dhoyo.app', playGamesEnabled=True, applicationId='123456789', leaderboardId='leaderboard_lifetime')
    assert response.headers['Cache-Control'] == 'no-store'
    assert get(configured.native, BASE + 'status').status_code == 401
    player = configured.make()
    assert get(player['client'], BASE + 'status').json == dict(currentUserId=player['userId'], linked=False, lastSyncedAt=None)
    assert get(player['client'], BASE + 'status?playerId=other').status_code == 400
    assert post(configured.native, BASE + 'tickets', {}).status_code == 401


@pytest.mark.parametrize('name,value', [
    ('PLAY_GAMES_WEB_CLIENT_ID', None), ('PLAY_GAMES_WEB_CLIENT_ID', 'bad-client'),
    ('PLAY_GAMES_WEB_CLIENT_SECRET', None), ('PLAY_GAMES_WEB_CLIENT_SECRET', 'bad\nsecret'),
    ('PLAY_GAMES_APPLICATION_ID', None), ('PLAY_GAMES_APPLICATION_ID', '../wrong'),
    ('PLAY_GAMES_ACHIEVEMENTS_JSON', '{bad'), ('PLAY_GAMES_ACHIEVEMENTS_JSON', '[]'),
    ('PLAY_GAMES_ACHIEVEMENTS_JSON', '{"unknown":"achievement_id"}'),
    ('PLAY_GAMES_ACHIEVEMENTS_JSON', '{"first-team":"../inject"}'),
    ('PLAY_GAMES_ACHIEVEMENTS_JSON', '{"first-team":[]}'),
    ('PLAY_GAMES_ACHIEVEMENTS_JSON', '{"first-team":"same","first-tournament":"same"}'),
    ('PLAY_GAMES_LEADERBOARD_ID', '../wrong'),
])
def test_unconfigured_bridge_refuses_tickets_and_connect(configured, monkeypatch, name, value):
    monkeypatch.setitem(app.config, name, value)
    assert get(configured.native, BASE + 'config').json['playGamesEnabled'] is False
    player = configured.make()
    assert post(player['client'], BASE + 'tickets', {'challenge': play_games.pkce_challenge('x' * 43)}).status_code == 503
    assert connect(configured, {}).status_code == 503
    assert configured.calls == []


@pytest.mark.parametrize('value', ['http://play.google.com/store/apps/details?id=com.dhoyo.app',
    'https://play.google.com.evil.invalid/store/apps/details?id=com.dhoyo.app',
    'https://play.google.com@evil.invalid/store/apps/details?id=com.dhoyo.app',
    'https://play.google.com/store/apps/details?id=another.app',
    'https://play.google.com/store/apps/details?id=com.dhoyo.app&id=other.app',
    'https://play.google.com/store/apps/details?id=com.dhoyo.app#token', 'javascript:alert(1)'])
def test_store_link_rejects_untrusted_or_mismatched_urls(configured, monkeypatch, value):
    monkeypatch.setitem(app.config, 'PLAY_STORE_URL', value)
    assert get(configured.native, BASE + 'config').json['storeUrl'] is None


def test_ticket_and_connection_proofs_private_single_use_and_no_cookie_native(configured, caplog):
    caplog.set_level('DEBUG')
    player = configured.make()
    payload = approval(player)
    with social.raw_state() as data:
        stored = data['playGamesTickets'][auth.digest(payload['ticket'])]
        assert stored['user_id'] == player['userId']
        assert payload['ticket'] not in json.dumps(data)
        assert payload['verifier'] not in json.dumps(data)
    assert configured.native.get_cookie(auth.COOKIE) is None
    response = connect(configured, payload)
    assert response.status_code == 200
    assert response.json == dict(linked=True, syncedAchievements=0, submittedScore=0, syncComplete=True,
        message='Your earned Dhoyo progress is synced with Google Play Games.')
    assert connect(configured, payload).status_code == 400
    linked = get(player['client'], BASE + 'status')
    assert linked.json['linked'] and linked.json['lastSyncedAt']
    with social.raw_state() as data:
        serialized = json.dumps(data)
        assert data['playGamesTickets'] == {}
        assert data['playGamesLinks'][player['userId']]['player_digest']
    for secret in (payload['ticket'], payload['verifier'], SERVER_CODE, ACCESS_TOKEN, REFRESH_TOKEN, PLAYER_ID, CLIENT_SECRET):
        assert secret not in serialized
        assert secret not in response.get_data(as_text=True)
        assert secret not in linked.get_data(as_text=True)
        assert secret not in caplog.text
    exchange = configured.calls[0]
    assert exchange[0] == play_games.TOKEN_ENDPOINT
    assert exchange[1]['form'] == dict(client_id='synthetic-server.apps.googleusercontent.com',
        client_secret=CLIENT_SECRET, code=SERVER_CODE, grant_type='authorization_code', redirect_uri='')
    assert configured.calls[1][0] == play_games.GAMES_ENDPOINT + 'applications/123456789/verify'


def test_only_verified_players_with_live_session_can_approve(configured):
    owner = configured.make('organisation')
    assert post(owner['client'], BASE + 'tickets', {'challenge': play_games.pkce_challenge('x' * 43)}).status_code == 403
    player = configured.make()
    with social.raw_state() as data:
        data['accounts'][player['email']]['email_verified'] = False
    assert post(player['client'], BASE + 'tickets', {'challenge': play_games.pkce_challenge('x' * 43)}).status_code == 401
    assert configured.calls == []


@pytest.mark.parametrize('challenge', ['', 'x' * 42, 'x' * 44, '+' * 43, 'z' * 43, None])
def test_invalid_pkce_challenges_rejected(configured, challenge):
    player = configured.make()
    assert post(player['client'], BASE + 'tickets', {'challenge': challenge}).status_code == 400


def test_wrong_verifier_cannot_consume_valid_ticket_and_old_tickets_expire(configured):
    player = configured.make()
    payload = approval(player)
    wrong = dict(payload, verifier='wrong' * 12)
    assert connect(configured, wrong).status_code == 400
    assert configured.calls == []
    assert connect(configured, payload).status_code == 200
    payload = approval(player)
    with social.raw_state() as data:
        data['playGamesTickets'][auth.digest(payload['ticket'])]['expires'] = time.time() - 1
    configured.calls.clear()
    assert connect(configured, payload).status_code == 400
    assert configured.calls == []


@pytest.mark.parametrize('state', ['logout', 'expiry', 'pending', 'organisation'])
def test_original_session_and_player_role_revalidated_before_exchange(configured, state):
    player = configured.make()
    payload = approval(player)
    with social.raw_state() as data:
        account = data['accounts'][player['email']]
        if state == 'logout':
            data['sessions'].clear()
        elif state == 'expiry':
            for session in data['sessions'].values():
                session['expires'] = time.time() - 1
        elif state == 'pending':
            account['email_verified'] = False
        else:
            account['account_type'] = 'organisation'
    assert connect(configured, payload).status_code == 400
    assert configured.calls == []


def test_exchange_and_sync_run_outside_shared_state_and_recheck_session(configured, monkeypatch):
    player = configured.make()
    payload = approval(player)
    original_state = social.raw_state
    depth = [0]
    @contextmanager
    def tracked():
        with original_state() as data:
            depth[0] += 1
            try:
                yield data
            finally:
                depth[0] -= 1
    monkeypatch.setattr(social, 'raw_state', tracked)
    def provider(endpoint, **kwargs):
        assert depth[0] == 0
        result = configured.provider(endpoint, **kwargs)
        if '/applications/' in endpoint:
            with original_state() as data:
                data['sessions'].clear()
        return result
    monkeypatch.setattr(play_games, 'google_json', provider)
    assert connect(configured, payload).status_code == 400
    with original_state() as data:
        assert data.get('playGamesLinks', {}) == {}
    assert len(configured.calls) == 2


def test_google_identity_cannot_be_replaced_or_shared_between_accounts(configured, monkeypatch):
    first, second = configured.make(), configured.make()
    assert connect(configured, approval(first)).status_code == 200
    assert connect(configured, approval(second)).status_code == 409
    def other_identity(endpoint, **kwargs):
        return dict(player_id='different-player') if '/applications/' in endpoint else configured.provider(endpoint, **kwargs)
    monkeypatch.setattr(play_games, 'google_json', other_identity)
    assert connect(configured, approval(first)).status_code == 409


def test_native_request_does_not_accept_client_scores_badges_or_player_ids(configured):
    player = configured.make()
    payload = approval(player)
    for key, value in [('score', 999999), ('achievements', ['achievement_five']), ('playerId', 'forged')]:
        assert connect(configured, dict(payload, **{key: value})).status_code == 400
    assert configured.calls == []


def test_authoritative_tournament_completion_unlocks_earned_badges_and_lifetime_score(configured, service_clock):
    owner, captain, opponent = configured.make('organisation'), configured.make(), configured.make()
    event = create_event(owner, service_clock, publish=True)
    for member, name in [(captain, 'First Team'), (opponent, 'Second Team')]:
        assert post(member['client'], '/api/tournaments/' + event['id'] + '/registrations', {'teamName': name}).status_code == 201
    service_clock['value'] = datetime.fromisoformat(event['startsAt'])
    for action in ('start', 'complete'):
        assert post(owner['client'], '/api/tournaments/' + event['id'] + '/' + action).status_code == 200
    with social.raw_state() as data:
        next(p for p in data['arena']['players'] if p['id'] == captain['userId'])['awards']['Star'] = 999
    response = connect(configured, approval(captain))
    assert response.status_code == 200
    assert response.json['syncedAchievements'] == 2
    assert response.json['submittedScore'] == 1
    endpoints = [endpoint for endpoint, _ in configured.calls]
    assert play_games.GAMES_ENDPOINT + 'achievements/achievement_team/unlock' in endpoints
    assert play_games.GAMES_ENDPOINT + 'achievements/achievement_finish/unlock' in endpoints
    assert not any('achievement_five' in endpoint or 'achievement_sports' in endpoint for endpoint in endpoints)
    assert endpoints[-1] == play_games.GAMES_ENDPOINT + 'leaderboards/leaderboard_lifetime/scores?score=1'


def test_partial_sync_reports_failure_without_claiming_complete_or_storing_tokens(configured, monkeypatch):
    player = configured.make()
    def fail_score(endpoint, **kwargs):
        if '/leaderboards/' in endpoint:
            raise play_games.ProviderError()
        return configured.provider(endpoint, **kwargs)
    monkeypatch.setattr(play_games, 'google_json', fail_score)
    response = connect(configured, approval(player))
    assert response.status_code == 200
    assert response.json['linked'] and response.json['syncComplete'] is False
    assert response.json['submittedScore'] is None
    linked = get(player['client'], BASE + 'status').json
    assert linked['linked'] and linked['lastSyncedAt'] is None
    monkeypatch.setattr(play_games, 'google_json', configured.provider)
    assert connect(configured, approval(player)).json['syncComplete'] is True


def test_provider_failure_consumes_ticket_without_linking_and_invalid_response_fails_closed(configured, monkeypatch):
    player = configured.make()
    payload = approval(player)
    def failure(*args, **kwargs):
        raise play_games.ProviderError()
    monkeypatch.setattr(play_games, 'google_json', failure)
    assert connect(configured, payload).status_code == 502
    monkeypatch.setattr(play_games, 'google_json', configured.provider)
    assert connect(configured, payload).status_code == 400
    assert get(player['client'], BASE + 'status').json['linked'] is False
    monkeypatch.setattr(play_games, 'google_json', lambda *_, **__: dict(access_token='bad\ntoken', token_type='Bearer'))
    assert connect(configured, approval(player)).status_code == 502


def test_concurrent_replay_only_one_request_reaches_google(configured):
    player = configured.make()
    payload = approval(player)
    def attempt(_):
        return post(app.test_client(), BASE + 'connect', payload).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(attempt, range(2)))
    assert sorted(codes) == [200, 400]
    assert sum(endpoint == play_games.TOKEN_ENDPOINT for endpoint, _ in configured.calls) == 1


def test_ticket_rates_bounded_and_native_csrf_transport_headers_required(configured):
    player = configured.make()
    for _ in range(10):
        approval(player)
    assert post(player['client'], BASE + 'tickets', {'challenge': play_games.pkce_challenge('x' * 43)}).status_code == 429
    assert configured.native.post(BASE + 'connect', json={}, base_url='https://localhost').status_code == 403
    assert configured.native.post(BASE + 'connect', json={}, headers={'X-Dhoyo-Request': '1', 'Origin': 'https://evil.invalid'}, base_url='https://localhost').status_code == 403
    assert configured.native.get(BASE + 'config', base_url='http://public.example.invalid').status_code == 403


def test_ticket_storage_and_connect_rate_limits_remain_bounded(configured, monkeypatch):
    player = configured.make()
    monkeypatch.setattr(play_games, 'MAX_ENTRIES', 2)
    approval(player)
    approval(player)
    assert post(player['client'], BASE + 'tickets', {'challenge': play_games.pkce_challenge('x' * 43)}).status_code == 429
    with social.raw_state() as data:
        assert len(data['playGamesTickets']) == 2
        assert len(data['playGamesRates']) == 2
    monkeypatch.setattr(play_games, 'MAX_ENTRIES', 2048)
    unknown = dict(ticket='x' * 43, verifier='x' * 43, serverAuthCode=SERVER_CODE)
    for _ in range(30):
        assert connect(configured, unknown).status_code == 400
    assert connect(configured, unknown).status_code == 429
    assert configured.calls == []


def test_linking_without_configured_awards_or_leaderboard_is_supported(configured, monkeypatch):
    monkeypatch.setitem(app.config, 'PLAY_GAMES_ACHIEVEMENTS_JSON', '{}')
    monkeypatch.setitem(app.config, 'PLAY_GAMES_LEADERBOARD_ID', None)
    player = configured.make()
    response = connect(configured, approval(player))
    assert response.json['syncComplete'] is True
    assert response.json['submittedScore'] is None
    assert response.json['syncedAchievements'] == 0
    assert len(configured.calls) == 2


@pytest.mark.parametrize('body,status', [(b'[]', 200), (b'{invalid', 200), (b'{}', 500), (b'x' * 16385, 200)])
def test_google_http_response_validation_does_not_expose_provider_body(configured, monkeypatch, body, status):
    class Response(io.BytesIO):
        pass
    def opened(request, timeout):
        result = Response(body)
        result.status = status
        return result
    monkeypatch.setattr(play_games.GOOGLE_HTTP, 'open', opened)
    with pytest.raises(play_games.ProviderError):
        HTTP_JSON(play_games.TOKEN_ENDPOINT, method='POST', form={'code': SERVER_CODE})


@pytest.mark.parametrize('failure', ['http', 'network', 'incomplete'])
def test_google_http_errors_are_sanitized_and_redirects_disallowed(configured, monkeypatch, failure, caplog):
    def opened(request, timeout):
        if failure == 'http':
            raise HTTPError(play_games.TOKEN_ENDPOINT, 401, ACCESS_TOKEN, {}, io.BytesIO(REFRESH_TOKEN.encode()))
        if failure == 'incomplete':
            raise IncompleteRead(ACCESS_TOKEN.encode())
        raise URLError(ACCESS_TOKEN)
    monkeypatch.setattr(play_games.GOOGLE_HTTP, 'open', opened)
    with pytest.raises(play_games.ProviderError) as error:
        HTTP_JSON(play_games.TOKEN_ENDPOINT, method='POST', form={'code': SERVER_CODE})
    assert str(error.value) == ''
    assert ACCESS_TOKEN not in caplog.text and REFRESH_TOKEN not in caplog.text
    assert play_games.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid') is None
    with pytest.raises(play_games.ProviderError):
        HTTP_JSON('https://evil.invalid/token')


@pytest.mark.parametrize('claim', [{}, {'playerId': PLAYER_ID}, {'player_id': '../bad'}, {'player_id': None}])
def test_application_identity_verification_requires_server_returned_player_id(configured, monkeypatch, claim):
    player = configured.make()
    def provider(endpoint, **kwargs):
        return claim if '/applications/' in endpoint else configured.provider(endpoint, **kwargs)
    monkeypatch.setattr(play_games, 'google_json', provider)
    assert connect(configured, approval(player)).status_code == 502
    assert get(player['client'], BASE + 'status').json['linked'] is False
