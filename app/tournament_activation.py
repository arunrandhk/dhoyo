"""Private, expiring participation acknowledgements delivered to roster emails."""
from copy import deepcopy
import secrets
from urllib.parse import urlsplit, urlunsplit

from flask import jsonify, request
from auth import digest
import password_reset
from tournament_verification import normalize_email, timestamp, cleanup, consume_limits, rate_response, context


def registration_roster(tournament, value, existing=None):
    import organisations as org
    previous = existing.get('playerEmails', []) if existing else []
    if 'playerEmails' not in value and existing:
        return deepcopy(previous)
    entries = value.get('playerEmails', [])
    size = tournament.get('teamSize', 5)
    required = tournament.get('requirePlayerEmailVerification', False)
    if not isinstance(entries, list) or len(entries) > size or (required and len(entries) != size):
        raise org.ServiceError(f'Enter {size} player emails' if required else f'Enter at most {size} player emails')
    saved = {item['email']: item for item in previous}
    roster, emails = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'email'}:
            raise org.ServiceError('Provide each player email')
        email = normalize_email(entry['email'])
        if email in emails:
            raise org.ServiceError('Each player must have a different email address')
        emails.add(email)
        roster.append(deepcopy(saved[email]) if email in saved else
                      dict(email=email, verified=False, acknowledgementStatus='pending',
                           rosterId=secrets.token_urlsafe(24)))
    return roster


def find_player(service, record):
    event = next((e for e in service['tournaments'] if e['id'] == record['tournamentId']), None)
    registration = next((r for r in service['registrations'] if r['id'] == record['registrationId']), None)
    if not event or event['status'] == 'cancelled' or not registration or registration['status'] != 'registered':
        return None
    return next((p for p in registration.get('playerEmails', [])
                 if p.get('rosterId') == record['rosterId'] and p['email'] == record['email']), None)


def prune(service, current):
    records = service.setdefault('playerActivationLinks', {})
    for key in list(records):
        if records[key]['expires'] <= current or find_player(service, records[key]) is None:
            del records[key]
    return records


def send_activation(tournament_id):
    import organisations as org
    email = normalize_email(org.payload(('email',), ('email',))['email'])
    settings = password_reset.mail_settings(require_base_url=True)
    token = secrets.token_urlsafe(32)
    key = digest(token)
    with org.raw_state() as data:
        visitor, service, event, identity = context(data, tournament_id)
        if event.get('playerEmailConfirmation') != 'activation_link':
            raise org.ServiceError('This tournament uses verification codes', 409)
        registration = next((r for r in org.active_registrations(service, tournament_id)
                             if r['playerId'] == visitor['id']), None)
        player = next((p for p in (registration or {}).get('playerEmails', []) if p['email'] == email), None)
        if not player:
            raise org.ServiceError('Save this player email in your team before sending an activation link', 409)
        if player.get('acknowledgementStatus') == 'acknowledged':
            return jsonify(email=email, acknowledgementStatus='acknowledged')
        if settings is None:
            return jsonify(error='Email delivery is not configured. Contact the organiser.'), 503
        current = timestamp()
        cleanup(service, current)
        records = prune(service, current)
        if len(records) >= 4096 or not consume_limits(service, [
                ('activation-email:' + email, 3, 900), ('activation-captain:' + visitor['id'], 150, 900),
                ('activation-ip:' + (request.remote_addr or ''), 300, 900),
                ('activation-resend:' + tournament_id + ':' + email, 1, 60)], current):
            return rate_response()
        record = dict(email=email, tournamentId=tournament_id, registrationId=registration['id'],
                      rosterId=player['rosterId'], expires=current + 86400, active=False)
        records[key] = record
        mail = dict(settings, purpose='tournament_activation', tournament_name=event['name'],
                    team_name=registration['teamName'])
    # Use the configured trusted origin; never build emailed URLs from the Host header.
    parsed = urlsplit(settings['base_url'])
    link = urlunsplit((parsed.scheme, parsed.netloc, '/tournament-acknowledgement', '', token))
    try:
        available, sent = password_reset.deliver_password_reset(mail, email, link)
    except Exception:
        available, sent = False, False
    with org.raw_state() as data:
        service = org.ensure_service(data)
        records = prune(service, timestamp())
        pending = records.get(key)
        player = find_player(service, record)
        if not available or not sent or pending is None or player is None:
            records.pop(key, None)
            return jsonify(error='Activation email could not be sent. Please try again.'), 503
        pending['active'] = True
        player['activationSentAt'] = org.now().isoformat()
    return jsonify(email=email, acknowledgementStatus='pending', message='Activation link sent. Awaiting player acknowledgement.')


def acknowledge():
    import organisations as org
    token = org.payload(('token',), ('token',))['token']
    if not isinstance(token, str) or len(token) != 43:
        raise org.ServiceError('This activation link is invalid or has expired', 400)
    with org.raw_state() as data:
        service = org.ensure_service(data)
        records = prune(service, timestamp())
        record = records.get(digest(token))
        player = find_player(service, record) if record and record.get('active') else None
        if player is None:
            raise org.ServiceError('This activation link is invalid or has expired', 400)
        player.update(acknowledgementStatus='acknowledged', verified=True)
        player.setdefault('acknowledgedAt', org.now().isoformat())
        player.setdefault('verifiedAt', player['acknowledgedAt'])
        return jsonify(acknowledgementStatus='acknowledged', message='Your participation has been acknowledged.')
