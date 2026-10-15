"""Expiring email ownership proofs for private tournament player rosters.

Mail delivery and expensive OTP hashing run outside the shared state transaction.
Proof validation and registration consumption run in the registration transaction.
"""
from copy import deepcopy
import re
import secrets
import time

from flask import jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from auth import COOKIE, digest, test_demo_enabled
import password_reset


CODE_LIFETIME = 10 * 60
CODE_ATTEMPTS = 5
RATE_WINDOW = 15 * 60
RESEND_DELAY = 60
MAX_CHALLENGES = 4096
MAX_RATE_ENTRIES = 8192
INVALID_CODE = 'The player verification code is invalid or has expired. Request a new code.'
UNAVAILABLE = 'Player email verification is temporarily unavailable. Please try again later.'
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+')
CHALLENGE_PATTERN = re.compile(r'[A-Za-z0-9_-]{43}')


def normalize_email(value):
    from organisations import ServiceError
    if not isinstance(value, str):
        raise ServiceError('Enter a valid player email address')
    email = value.strip().casefold()
    if (len(email) > 254 or not EMAIL_PATTERN.fullmatch(email)
            or len(email.split('@')[0]) > 64 or email.startswith('.')
            or email.split('@')[0].endswith('.') or '..' in email):
        raise ServiceError('Enter a valid player email address')
    return email


def timestamp():
    from organisations import now
    return now().timestamp()


def cleanup(service, current):
    challenges = service.setdefault('playerEmailChallenges', {})
    for key in list(challenges):
        if challenges[key]['expires'] <= current:
            del challenges[key]
    limits = service.setdefault('playerEmailRateLimits', {})
    for key in list(limits):
        if limits[key]['until'] <= current:
            del limits[key]


def consume_limits(service, specifications, current):
    """Persist successful rate reservations even when delivery later fails."""
    limits = service['playerEmailRateLimits']
    keys = [(digest(scope), maximum, window) for scope, maximum, window in specifications]
    if len(limits) + sum(key not in limits for key, _, _ in keys) > MAX_RATE_ENTRIES:
        return False
    if any(limits.get(key, {}).get('count', 0) >= maximum for key, maximum, _ in keys):
        return False
    for key, _, window in keys:
        entry = limits.setdefault(key, dict(count=0, until=current + window))
        entry['count'] += 1
    return True


def rate_response():
    response = jsonify(error='Too many player verification requests. Wait before requesting another code.')
    response.headers['Retry-After'] = str(RESEND_DELAY)
    return response, 429


def context(data, tournament_id):
    """Recheck account, session and the event after work outside the lock."""
    import organisations as org
    visitor = org.actor(data, 'player')
    account_email, account = next((email, value) for email, value in data['accounts'].items()
                                 if value.get('player_id') == visitor['id'])
    if not test_demo_enabled():
        session = data.get('sessions', {}).get(digest(request.cookies.get(COOKIE, '')))
        if (not session or session['user_id'] != visitor['id']
                or session['expires'] <= time.time()):
            raise org.ServiceError('Sign in with a registered account to continue', 401)
    service = org.ensure_service(data)
    tournament = org.visible_tournament(service, tournament_id, visitor)
    if (tournament['status'] != 'open'
            or org.now() >= org.instant(tournament['registrationClosesAt'])):
        raise org.ServiceError('Registration is closed for this tournament', 409)
    registrations = org.active_registrations(service, tournament_id)
    existing = next((item for item in registrations if item['playerId'] == visitor['id']), None)
    if not existing and len(registrations) >= tournament['capacity']:
        raise org.ServiceError('This tournament is full', 409)
    identity = (visitor['id'], account_email, account.get('password_hash'), account.get('account_type', 'player'))
    return visitor, service, tournament, identity


def challenge_record(service, challenge_key, visitor, tournament_id, email, current):
    record = service['playerEmailChallenges'].get(challenge_key)
    if (not record or not record.get('active') or record.get('used')
            or record['expires'] <= current or record['playerId'] != visitor['id']
            or record['tournamentId'] != tournament_id or record['email'] != email):
        return None
    return record


def request_code(tournament_id):
    import organisations as org
    value = org.payload(('email',), ('email',))
    email = normalize_email(value['email'])
    invalid_fields = []
    settings = password_reset.mail_settings(require_base_url=False, invalid_fields=invalid_fields)
    challenge_id = secrets.token_urlsafe(32)
    challenge_key = digest(challenge_id)
    code = f'{secrets.randbelow(1_000_000):06d}'
    with org.raw_state() as data:
        visitor, service, tournament, identity = context(data, tournament_id)
        current = timestamp()
        cleanup(service, current)
        if settings is None:
            password_reset.log_mail_failure(password_reset.configured_mail_provider(), 'configuration',
                                            invalid_fields=invalid_fields)
            return jsonify(error=UNAVAILABLE), 503
        if len(service['playerEmailChallenges']) >= MAX_CHALLENGES:
            return rate_response()
        specifications = [('send-email:' + email, 3, RATE_WINDOW),
                          ('send-player:' + visitor['id'], 150, RATE_WINDOW),
                          ('send-ip:' + (request.remote_addr or ''), 300, RATE_WINDOW),
                          ('resend:' + visitor['id'] + ':' + tournament_id + ':' + email, 1, RESEND_DELAY)]
        if not consume_limits(service, specifications, current):
            return rate_response()
        service['playerEmailChallenges'][challenge_key] = dict(
            email=email, playerId=visitor['id'], tournamentId=tournament_id,
            codeHash=None, expires=current + CODE_LIFETIME, attempts=0,
            active=False, verified=False, used=False)
        event_name = tournament['name']

    # Rate reservations precede expensive hashing, and the pending record keeps
    # the bounded challenge collection safe under concurrent send requests.
    code_hash = generate_password_hash(code, method='scrypt')
    with org.raw_state() as data:
        service = org.ensure_service(data)
        cleanup(service, timestamp())
        pending = service['playerEmailChallenges'].get(challenge_key)
        try:
            visitor, service, tournament, current_identity = context(data, tournament_id)
        except org.ServiceError as error:
            service['playerEmailChallenges'].pop(challenge_key, None)
            return jsonify(error=str(error)), error.status
        if not pending or current_identity != identity:
            service['playerEmailChallenges'].pop(challenge_key, None)
            return jsonify(error='Your sign-in or tournament changed. Request a new player code.'), 409
        pending['codeHash'] = code_hash

    # A pending proof reserves no team or tournament capacity.
    try:
        available, sent = password_reset.deliver_tournament_player_code(settings, email, code, event_name)
    except Exception as error:
        password_reset.log_mail_failure(settings['provider'], 'send', error)
        available, sent = False, False
    with org.raw_state() as data:
        service = org.ensure_service(data)
        cleanup(service, timestamp())
        pending = service['playerEmailChallenges'].get(challenge_key)
        if not available or not sent:
            service['playerEmailChallenges'].pop(challenge_key, None)
            return jsonify(error=UNAVAILABLE), 503
        try:
            visitor, service, tournament, current_identity = context(data, tournament_id)
        except org.ServiceError as error:
            service['playerEmailChallenges'].pop(challenge_key, None)
            return jsonify(error=str(error)), error.status
        if not pending or current_identity != identity:
            service['playerEmailChallenges'].pop(challenge_key, None)
            return jsonify(error='Your sign-in or tournament changed. Request a new player code.'), 409
        # Only successful delivery replaces an earlier usable code for this email.
        for key, record in list(service['playerEmailChallenges'].items()):
            if (key != challenge_key and record['playerId'] == visitor['id']
                    and record['tournamentId'] == tournament_id and record['email'] == email):
                del service['playerEmailChallenges'][key]
        pending['active'] = True
    return jsonify(email=email, challengeId=challenge_id, expiresIn=CODE_LIFETIME,
                   message='A verification code has been sent to this player email.')


def verify_code(tournament_id):
    import organisations as org
    value = org.payload(('email', 'challengeId', 'code'), ('email', 'challengeId', 'code'))
    email = normalize_email(value['email'])
    challenge_id, code = value['challengeId'], value['code']
    challenge_key = digest(challenge_id) if (isinstance(challenge_id, str)
                                           and CHALLENGE_PATTERN.fullmatch(challenge_id)) else None
    valid_format = isinstance(code, str) and re.fullmatch(r'[0-9]{6}', code)
    with org.raw_state() as data:
        visitor, service, tournament, identity = context(data, tournament_id)
        current = timestamp()
        cleanup(service, current)
        if not consume_limits(service, [('verify-player:' + visitor['id'], 300, RATE_WINDOW),
                                        ('verify-ip:' + (request.remote_addr or ''), 600, RATE_WINDOW)], current):
            return rate_response()
        record = challenge_record(service, challenge_key, visitor, tournament_id, email, current)
        if record and record['verified']:
            return jsonify(email=email, challengeId=challenge_id, verified=True,
                           expiresIn=max(0, int(record['expires'] - current)))
        code_hash = None
        if record and record['attempts'] < CODE_ATTEMPTS:
            # Reserve an attempt first, so concurrent guesses share the five-attempt cap.
            record['attempts'] += 1
            code_hash = record['codeHash']
    if not valid_format:
        return jsonify(error=INVALID_CODE), 400
    matches = check_password_hash(code_hash or password_reset.DUMMY_CODE_HASH, code)
    if not code_hash or not matches:
        return jsonify(error=INVALID_CODE), 400
    with org.raw_state() as data:
        visitor, service, tournament, current_identity = context(data, tournament_id)
        current = timestamp()
        cleanup(service, current)
        record = challenge_record(service, challenge_key, visitor, tournament_id, email, current)
        if not record or record.get('codeHash') != code_hash or current_identity != identity:
            return jsonify(error=INVALID_CODE), 400
        record['verified'] = True
        record['verifiedAt'] = org.now().isoformat()
        return jsonify(email=email, challengeId=challenge_id, verified=True,
                       expiresIn=max(0, int(record['expires'] - current)))


def registration_roster(service, tournament, visitor, value, existing=None):
    """Validate every proof without consuming any, while the caller holds the lock."""
    import organisations as org
    if tournament.get('playerEmailConfirmation') == 'activation_link':
        from tournament_activation import registration_roster as activation_roster
        return activation_roster(tournament, value, existing), []
    required = tournament.get('requirePlayerEmailVerification', False)
    previous = existing.get('playerEmails', []) if existing else []
    if 'playerEmails' not in value:
        if existing:
            return deepcopy(previous), []
        if required:
            raise org.ServiceError('Add and verify an email for every player before registering')
        return [], []
    entries = value['playerEmails']
    team_size = tournament.get('teamSize', 5)
    if (not isinstance(entries, list) or not 0 <= len(entries) <= team_size
            or (required and len(entries) != team_size)):
        raise org.ServiceError(f'Add exactly {team_size} verified player emails' if required
                               else f'Add at most {team_size} verified player emails')
    current = timestamp()
    cleanup(service, current)
    saved = {item['email']: item for item in previous if item.get('verified')}
    emails, roster, proofs = set(), [], []
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) - {'email', 'challengeId'}
                or 'email' not in entry):
            raise org.ServiceError('Provide each player email and its verification challenge')
        email = normalize_email(entry['email'])
        if email in emails:
            raise org.ServiceError('Each player must have a different email address')
        emails.add(email)
        proof = None
        if email in saved:
            snapshot = deepcopy(saved[email])
        else:
            challenge_id = entry.get('challengeId')
            key = digest(challenge_id) if (isinstance(challenge_id, str)
                                           and CHALLENGE_PATTERN.fullmatch(challenge_id)) else None
            proof = challenge_record(service, key, visitor, tournament['id'], email, current)
            if not proof or not proof['verified']:
                raise org.ServiceError('Verify every player email with a valid code before registering')
            snapshot = dict(email=email, verified=True, verifiedAt=proof['verifiedAt'])
        roster.append(snapshot)
        if proof:
            proofs.append(proof)
    return roster, proofs


def consume_roster_proofs(proofs, registration_id):
    current = timestamp()
    for proof in proofs:
        proof.update(used=True, usedAt=current, registrationId=registration_id)
        proof.pop('codeHash', None)
