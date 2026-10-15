"""Explicit Android Play Games linking and server-authoritative progress sync.

The native client proves a browser-approved session with a single-use PKCE
ticket. Google OAuth tokens exist only during this request and are never saved.
"""
import base64
import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import Blueprint, jsonify, request

from auth import COOKIE, current_user_id, digest
from password_reset import setting


play_games = Blueprint('play_games', __name__, url_prefix='/api/play-games')
TICKET_LIFETIME = 300
RATE_WINDOW = 15 * 60
MAX_ENTRIES = 2048
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
GAMES_ENDPOINT = 'https://games.googleapis.com/games/v1/'
INVALID_TICKET = 'This Play Games connection has expired or is invalid. Start again from your Dhoyo profile.'
UNAVAILABLE = 'Google Play Games is not configured yet. You can keep using Dhoyo.'


class NoRedirect(HTTPRedirectHandler):
    # Credentials and bearer tokens are sent only to these fixed Google origins.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


GOOGLE_HTTP = build_opener(NoRedirect())


class ProviderError(Exception):
    """A deliberately data-free error: provider bodies may contain credentials."""


def resource_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value))


def android_package():
    value = setting('ANDROID_PACKAGE_NAME', 'com.dhoyo.app')
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){1,9}', value) else 'com.dhoyo.app'


def store_url():
    value = setting('PLAY_STORE_URL')
    if not isinstance(value, str) or len(value) > 2048 or any(character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (parsed.scheme == 'https' and parsed.netloc == 'play.google.com'
                and parsed.path == '/store/apps/details' and not parsed.fragment
                and query.get('id') == [android_package()]
                and set(query) <= {'id', 'hl', 'gl'}
                and all(len(values) == 1 for values in query.values())):
            return value
    except ValueError:
        pass
    return None


def settings():
    from progression import BADGES
    application_id = setting('PLAY_GAMES_APPLICATION_ID')
    client_id = setting('PLAY_GAMES_WEB_CLIENT_ID')
    client_secret = setting('PLAY_GAMES_WEB_CLIENT_SECRET')
    leaderboard = setting('PLAY_GAMES_LEADERBOARD_ID') or None
    raw_map = setting('PLAY_GAMES_ACHIEVEMENTS_JSON', '{}')
    if (not isinstance(application_id, str) or not re.fullmatch(r'[1-9][0-9]{0,29}', application_id)
            or not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.apps\.googleusercontent\.com', client_id)
            or not isinstance(client_secret, str) or not 1 <= len(client_secret) <= 2048
            or any(character.isspace() for character in client_secret)
            or (leaderboard is not None and not resource_id(leaderboard))
            or not isinstance(raw_map, str) or len(raw_map) > 4096):
        return None
    try:
        achievements = json.loads(raw_map)
    except (ValueError, TypeError):
        return None
    if (not isinstance(achievements, dict) or set(achievements) - {item[0] for item in BADGES}
            or any(not resource_id(value) for value in achievements.values())
            or len(set(achievements.values())) != len(achievements)):
        return None
    return dict(application_id=application_id, client_id=client_id, client_secret=client_secret,
                achievements=achievements, leaderboard_id=leaderboard)


def private(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def cleanup(data, timestamp):
    tickets = data.setdefault('playGamesTickets', {})
    for key in list(tickets):
        if tickets[key]['expires'] <= timestamp:
            del tickets[key]
    rates = data.setdefault('playGamesRates', {})
    for key in list(rates):
        if rates[key]['until'] <= timestamp:
            del rates[key]
    return tickets, rates


def reserve_limits(data, specifications, timestamp):
    _, rates = cleanup(data, timestamp)
    keys = [(digest(scope), maximum) for scope, maximum in specifications]
    if (len(rates) + sum(key not in rates for key, _ in keys) > MAX_ENTRIES
            or any(rates.get(key, {}).get('count', 0) >= maximum for key, maximum in keys)):
        return False
    for key, _ in keys:
        rate = rates.setdefault(key, dict(count=0, until=timestamp + RATE_WINDOW))
        rate['count'] += 1
    return True


def limited():
    response = jsonify(error='Too many Play Games connection attempts. Try again in 15 minutes.')
    response.headers['Retry-After'] = str(RATE_WINDOW)
    return response, 429


def account_for(data, user_id):
    return next((account for account in data.get('accounts', {}).values()
                 if account.get('player_id') == user_id), None)


def active_session(data, user_id, session_digest):
    account = account_for(data, user_id)
    session = data.get('sessions', {}).get(session_digest)
    return bool(account and account.get('account_type', 'player') == 'player'
                and account.get('email_verified', True) and session
                and session.get('user_id') == user_id and session.get('expires', 0) > time.time())


@play_games.get('/config')
def config():
    configured = settings()
    return private(jsonify(storeUrl=store_url(), androidPackage=android_package(),
        playGamesEnabled=configured is not None,
        applicationId=configured['application_id'] if configured else None,
        leaderboardId=configured['leaderboard_id'] if configured else None))


@play_games.get('/status')
def status():
    from social import raw_state
    user_id = current_user_id()
    if not user_id:
        return jsonify(error='Sign in to view your Play Games connection.'), 401
    if request.args:
        return jsonify(error='Play Games status only supports your own account.'), 400
    with raw_state() as data:
        linked = data.get('playGamesLinks', {}).get(user_id)
        return private(jsonify(currentUserId=user_id, linked=bool(linked),
                               lastSyncedAt=linked.get('last_synced_at') if linked else None))


@play_games.post('/tickets')
def tickets():
    from social import body, raw_state
    if settings() is None:
        return jsonify(error=UNAVAILABLE), 503
    payload = body()
    challenge = payload.get('challenge')
    if set(payload) != {'challenge'} or not valid_challenge(challenge):
        return jsonify(error='The Android connection challenge is invalid. Open the Android app and try again.'), 400
    user_id = current_user_id()
    session_digest = digest(request.cookies.get(COOKIE, ''))
    with raw_state() as data:
        account = account_for(data, user_id)
        if not user_id or not account:
            return jsonify(error='Sign in to connect Google Play Games.'), 401
        if account.get('account_type', 'player') != 'player':
            return jsonify(error='Only player accounts can connect Google Play Games.'), 403
        if not active_session(data, user_id, session_digest):
            return jsonify(error='Sign in with an activated player account to connect Google Play Games.'), 401
        timestamp = time.time()
        if not reserve_limits(data, [('ticket-user:' + user_id, 10), ('ticket-ip:' + (request.remote_addr or ''), 20)], timestamp):
            return limited()
        records = data['playGamesTickets']
        if len(records) >= MAX_ENTRIES:
            return limited()
        ticket = secrets.token_urlsafe(32)
        records[digest(ticket)] = dict(user_id=user_id, challenge=challenge,
            session_digest=session_digest, expires=timestamp + TICKET_LIFETIME)
    return private(jsonify(ticket=ticket, expiresIn=TICKET_LIFETIME, currentUserId=user_id))


def valid_challenge(challenge):
    if not isinstance(challenge, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge):
        return False
    try:
        raw = base64.b64decode(challenge + '=', altchars=b'-_', validate=True)
        return len(raw) == 32 and base64.urlsafe_b64encode(raw).rstrip(b'=').decode() == challenge
    except ValueError:
        return False


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


def google_json(endpoint, *, method='GET', access_token=None, form=None):
    """Fixed HTTPS destinations, bounded JSON and no redirects or token logging."""
    if endpoint != TOKEN_ENDPOINT and not endpoint.startswith(GAMES_ENDPOINT):
        raise ProviderError()
    headers = {'Accept': 'application/json'}
    if access_token:
        headers['Authorization'] = 'Bearer ' + access_token
    encoded = None
    if form is not None:
        encoded = urlencode(form).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif method == 'POST':
        encoded = b''
    provider_request = Request(endpoint, data=encoded, headers=headers, method=method)
    try:
        with GOOGLE_HTTP.open(provider_request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise ProviderError()
            content = response.read(16385)
            if len(content) > 16384:
                raise ProviderError()
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ProviderError()
            return result
    except (HTTPError, URLError, HTTPException, OSError, ValueError, UnicodeError, TypeError):
        raise ProviderError() from None


def google_identity(configured, server_code):
    token_result = google_json(TOKEN_ENDPOINT, method='POST', form=dict(
        client_id=configured['client_id'], client_secret=configured['client_secret'],
        code=server_code, grant_type='authorization_code', redirect_uri=''))
    access_token = token_result.get('access_token')
    if (not isinstance(access_token, str) or not 1 <= len(access_token) <= 8192
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in access_token)
            or str(token_result.get('token_type', '')).casefold() != 'bearer'):
        raise ProviderError()
    # Discard refresh tokens immediately; linking alone does not authorise
    # background access. Every later sync needs explicit native authorisation.
    token_result.clear()
    verified = google_json(GAMES_ENDPOINT + 'applications/' + configured['application_id'] + '/verify', access_token=access_token)
    player_id = verified.get('player_id')
    if not isinstance(player_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', player_id):
        raise ProviderError()
    player_digest = digest('play-games:' + configured['application_id'] + ':' + player_id)
    return player_digest, access_token


def sync_targets(data, user_id, configured):
    from progression import sync_progress, badges_for, totals
    journal = sync_progress(data)
    badges = badges_for(journal, user_id)
    achievements = [configured['achievements'][badge['id']] for badge in badges
                    if badge['unlocked'] and badge['id'] in configured['achievements']]
    score = totals(journal, user_id)['completedTournaments'] if configured['leaderboard_id'] else None
    return achievements, score


@play_games.post('/connect')
def connect():
    from social import body, raw_state
    configured = settings()
    if configured is None:
        return jsonify(error=UNAVAILABLE), 503
    payload = body()
    if set(payload) != {'ticket', 'verifier', 'serverAuthCode'}:
        return jsonify(error=INVALID_TICKET), 400
    ticket, verifier, server_code = payload['ticket'], payload['verifier'], payload['serverAuthCode']
    if (not isinstance(ticket, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket)
            or not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier)
            or not isinstance(server_code, str) or not 1 <= len(server_code) <= 4096
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in server_code)):
        return jsonify(error=INVALID_TICKET), 400
    with raw_state() as data:
        if not reserve_limits(data, [('connect-ip:' + (request.remote_addr or ''), 30)], time.time()):
            return limited()
        record = data['playGamesTickets'].get(digest(ticket))
        if (not record or not secrets.compare_digest(record['challenge'], pkce_challenge(verifier))
                or not active_session(data, record['user_id'], record['session_digest'])):
            return jsonify(error=INVALID_TICKET), 400
        # Successful PKCE proof is single-use even if Google's exchange fails.
        del data['playGamesTickets'][digest(ticket)]
        user_id, session_digest = record['user_id'], record['session_digest']
    try:
        player_digest, access_token = google_identity(configured, server_code)
    except ProviderError:
        return jsonify(error='Google Play Games could not verify this connection. Start again and try once more.'), 502
    with raw_state() as data:
        if not active_session(data, user_id, session_digest):
            return jsonify(error=INVALID_TICKET), 400
        links = data.setdefault('playGamesLinks', {})
        linked = links.get(user_id)
        if linked and linked['player_digest'] != player_digest:
            return jsonify(error='Your Dhoyo account is already connected to a different Play Games profile.'), 409
        if any(value['player_digest'] == player_digest and owner != user_id for owner, value in links.items()):
            return jsonify(error='This Play Games profile is already connected to another Dhoyo account.'), 409
        if linked and linked.get('sync_until', 0) > time.time():
            return jsonify(error='A Play Games sync is already running. Please wait and try again.'), 409
        attempt = secrets.token_urlsafe(16)
        linked = links.setdefault(user_id, dict(player_digest=player_digest,
            application_id=configured['application_id'], linked_at=datetime.now(timezone.utc).isoformat()))
        linked.update(sync_attempt=attempt, sync_until=time.time() + 120)
        achievements, score = sync_targets(data, user_id, configured)
    unlocked = 0
    submitted = None
    complete = True
    # These calls use only progress derived from Dhoyo's persisted tournament
    # records. Client-supplied scores, achievements and Google player IDs are
    # rejected by the exact request schema above.
    for achievement in achievements:
        with raw_state() as data:
            if not active_session(data, user_id, session_digest):
                complete = False
                break
        try:
            google_json(GAMES_ENDPOINT + 'achievements/' + achievement + '/unlock', method='POST', access_token=access_token)
            unlocked += 1
        except ProviderError:
            complete = False
    if score is not None:
        with raw_state() as data:
            still_active = active_session(data, user_id, session_digest)
        if still_active:
            try:
                google_json(GAMES_ENDPOINT + 'leaderboards/' + configured['leaderboard_id'] + '/scores?' + urlencode({'score': str(score)}),
                            method='POST', access_token=access_token)
                submitted = score
            except ProviderError:
                complete = False
        else:
            complete = False
    access_token = None
    with raw_state() as data:
        linked = data.get('playGamesLinks', {}).get(user_id)
        if not active_session(data, user_id, session_digest):
            complete = False
        if linked and linked.get('sync_attempt') == attempt:
            linked.pop('sync_attempt', None)
            linked.pop('sync_until', None)
            if complete:
                linked['last_synced_at'] = datetime.now(timezone.utc).isoformat()
    return private(jsonify(linked=True, syncedAchievements=unlocked, submittedScore=submitted,
        syncComplete=complete, message='Your earned Dhoyo progress is synced with Google Play Games.' if complete else
        'Google Play Games is connected. Some progress could not sync; open the Android app to try again.'))
