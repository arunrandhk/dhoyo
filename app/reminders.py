"""Private tournament reminders and an opt-in mail worker.

The inbox is derived from current membership and schedule on every request. Mail
jobs reserve deliveries transactionally, then contact providers outside the lock.
"""
import hashlib
import json
import re
import secrets
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from organisations import ServiceError, active_registrations, actor, ensure_service, is_participant
from social import body, raw_state


reminders = Blueprint('reminders', __name__, url_prefix='/api/reminders')
DEFAULT_PREFERENCES = dict(inApp=True, email=True, whatsapp=False, leadHours=[24, 1])
ALLOWED_LEADS = (1, 6, 24, 48)
MAX_SAVED_STATES = 512
MAX_DELIVERIES = 512
MAX_ATTEMPTS = 3
RETRY_SECONDS = 5 * 60
RESERVATION_SECONDS = 15 * 60
MAX_USER_ATTEMPTS_PER_HOUR = 20
WHATSAPP_CODE_LIFETIME = 10 * 60
WHATSAPP_CODE_ATTEMPTS = 5


def now():
    return datetime.now(timezone.utc)


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def service(data):
    return data.setdefault('tournamentReminders', {}).setdefault('users', {})


def user_settings(data, user_id):
    value = service(data).setdefault(user_id, {})
    value.setdefault('preferences', dict(DEFAULT_PREFERENCES, leadHours=[24, 1]))
    value.setdefault('states', {})
    value.setdefault('deliveries', {})
    return value


def whatsapp_settings():
    import password_reset
    access_token = password_reset.setting('WHATSAPP_ACCESS_TOKEN')
    phone_number_id = password_reset.setting('WHATSAPP_PHONE_NUMBER_ID')
    reminder_template = password_reset.setting('WHATSAPP_REMINDER_TEMPLATE')
    verify_template = password_reset.setting('WHATSAPP_VERIFY_TEMPLATE')
    version = password_reset.setting('WHATSAPP_GRAPH_API_VERSION', 'v25.0')
    language = password_reset.setting('WHATSAPP_TEMPLATE_LANGUAGE', 'en_US')
    if (not isinstance(access_token, str) or not access_token or any(ch.isspace() for ch in access_token)
            or not isinstance(phone_number_id, str) or not re.fullmatch(r'[0-9]{5,30}', phone_number_id)
            or not isinstance(reminder_template, str) or not re.fullmatch(r'[a-z0-9_]{1,128}', reminder_template)
            or not isinstance(verify_template, str) or not re.fullmatch(r'[a-z0-9_]{1,128}', verify_template)
            or not isinstance(version, str) or not re.fullmatch(r'v[0-9]{1,2}\.[0-9]{1,2}', version)
            or not isinstance(language, str) or not re.fullmatch(r'[a-z]{2,3}_[A-Z]{2}', language)):
        return None
    return dict(access_token=access_token, phone_number_id=phone_number_id,
                reminder_template=reminder_template, verify_template=verify_template,
                version=version, language=language)


def send_whatsapp_template(settings, recipient, template, parameters):
    body = dict(messaging_product='whatsapp', to=recipient.lstrip('+'), type='template',
                template=dict(name=template, language=dict(code=settings['language']), components=[
                    dict(type='body', parameters=[dict(type='text', text=value[:1000]) for value in parameters])
                ]))
    endpoint = 'https://graph.facebook.com/' + settings['version'] + '/' + settings['phone_number_id'] + '/messages'
    request = Request(endpoint, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        'Authorization': 'Bearer ' + settings['access_token'], 'Content-Type': 'application/json',
        'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            return response.status in (200, 201) and bool(result.get('messages'))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        status = error.code if isinstance(error, HTTPError) else 0
        current_app.logger.warning('WhatsApp reminder delivery failed: stage=send http_status=%s', status)
        return False


def reminder_id(tournament_id, kind, target):
    # A changed schedule gets fresh read/dismiss and delivery state. No player
    # identity or roster information is encoded in the public notice identifier.
    value = '\0'.join((tournament_id, kind, target.isoformat()))
    return 'reminder-' + hashlib.sha256(value.encode()).hexdigest()[:32]


def upcoming(data, user_id, email, at):
    """Only fields already public on a joined event can reach a reminder."""
    tournaments = ensure_service(data)
    organisations = {item['id']: item for item in tournaments['organisations']}
    notices = []
    for event in tournaments['tournaments']:
        if event.get('status') not in ('open', 'live'):
            continue
        if not is_participant(active_registrations(tournaments, event['id']), user_id, email):
            continue
        for kind, field, title in (
                ('starts', 'startsAt', 'Tournament starts'),
                ('registration_closes', 'registrationClosesAt', 'Registration closes')):
            target = instant(event.get(field))
            if target is None or target <= at:
                continue
            notices.append(dict(id=reminder_id(event['id'], kind, target),
                                kind=kind, title=title, tournamentId=event['id'],
                                tournamentName=event.get('name', 'Tournament'),
                                organisationName=organisations.get(event.get('organisationId'), {}).get('name', ''),
                                sport=event.get('sport', ''), targetAt=target.isoformat(),
                                timezone=event.get('timezone', 'UTC'), route='#tournaments'))
    return sorted(notices, key=lambda item: (item['targetAt'], item['id']))


def trim(value, notices, at):
    active = {item['id'] for item in notices}
    value['states'] = {key: state for key, state in value['states'].items() if key in active}
    for key, delivery in list(value['deliveries'].items()):
        target = instant(delivery.get('targetAt'))
        if target is None or target < at - timedelta(days=7):
            del value['deliveries'][key]
        elif delivery['status'] == 'sending' and delivery['reservedAt'] + RESERVATION_SECONDS < at.timestamp():
            # A crashed worker may have submitted its message. Do not reclaim
            # an uncertain reservation and risk sending the same message twice.
            delivery['status'] = 'uncertain'


def due_lead(notice, preferences, at):
    remaining = (instant(notice['targetAt']) - at).total_seconds()
    eligible = [hours for hours in preferences['leadHours'] if remaining <= hours * 3600]
    return min(eligible) if remaining > 0 and eligible else None


def public_notices(value, notices, at):
    if not value['preferences']['inApp']:
        return []
    result = []
    for notice in notices:
        state = value['states'].get(notice['id'], {})
        if not state.get('dismissed'):
            result.append(dict(notice, read=state.get('read', False),
                               due=due_lead(notice, value['preferences'], at) is not None))
    return result


@reminders.errorhandler(ServiceError)
def reminder_error(error):
    return jsonify(error=str(error)), error.status


@reminders.get('')
def inbox():
    import password_reset
    at = now()
    with raw_state() as data:
        visitor = actor(data)
        value = user_settings(data, visitor['id'])
        notices = upcoming(data, visitor['id'], visitor['email'], at)
        trim(value, notices, at)
        visible = public_notices(value, notices, at)
        account = data.get('accounts', {}).get(visitor['email'], {})
        return jsonify(currentUserId=visitor['id'], preferences=value['preferences'], reminders=visible[:100],
                       unreadCount=sum(not item['read'] for item in visible),
                       totalCount=len(visible), serverTime=at.isoformat(),
                       emailDeliveryConfigured=password_reset.mail_settings(require_base_url=False) is not None,
                       whatsappDeliveryConfigured=whatsapp_settings() is not None,
                       phonePresent=bool(account.get('phone')),
                       phoneVerified=account.get('phone_verified') is True)


@reminders.patch('/preferences')
def preferences():
    payload = body()
    if not payload or set(payload) - {'inApp', 'email', 'whatsapp', 'leadHours'}:
        raise ServiceError('Choose in-app, email, WhatsApp and reminder lead time preferences')
    for key in ('inApp', 'email', 'whatsapp'):
        if key in payload and type(payload[key]) is not bool:
            raise ServiceError('Reminder choices must be true or false')
    if 'leadHours' in payload:
        hours = payload['leadHours']
        if (not isinstance(hours, list) or not 1 <= len(hours) <= len(ALLOWED_LEADS)
                or any(type(hour) is not int or hour not in ALLOWED_LEADS for hour in hours)
                or len(set(hours)) != len(hours)):
            raise ServiceError('Choose distinct reminder lead times of 1, 6, 24 or 48 hours')
    with raw_state() as data:
        visitor = actor(data)
        value = user_settings(data, visitor['id'])
        if payload.get('whatsapp') is True:
            account = data.get('accounts', {}).get(visitor['email'], {})
            if not account.get('phone') or account.get('phone_verified') is not True:
                raise ServiceError('Verify your phone number before enabling WhatsApp reminders')
        value['preferences'].update(payload)
        value['preferences']['leadHours'] = sorted(value['preferences']['leadHours'], reverse=True)
        return jsonify(currentUserId=visitor['id'], preferences=value['preferences'])


@reminders.post('/whatsapp-verification')
def whatsapp_verification():
    payload = body()
    action = payload.get('action')
    if action == 'send' and set(payload) == {'action'}:
        settings = whatsapp_settings()
        if settings is None:
            raise ServiceError('WhatsApp delivery is not configured for this service', 503)
        code = f'{secrets.randbelow(1_000_000):06d}'
        code_hash = generate_password_hash(code, method='scrypt')
        with raw_state() as data:
            visitor = actor(data, 'player')
            account = data.get('accounts', {}).get(visitor['email'], {})
            phone = account.get('phone')
            if not isinstance(phone, str) or not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
                raise ServiceError('Add a valid phone number to your account before enabling WhatsApp')
            rates = data.setdefault('whatsappReminderVerificationRates', {})
            at = time.time()
            for key in list(rates):
                if rates[key]['until'] <= at:
                    del rates[key]
            rate_key = hashlib.sha256((visitor['id'] + '|' + (request.remote_addr or '')).encode()).hexdigest()
            if rates.get(rate_key, {}).get('count', 0) >= 3:
                raise ServiceError('Too many WhatsApp verification requests. Try again in 15 minutes.', 429)
            rate = rates.setdefault(rate_key, dict(count=0, until=at + 15 * 60))
            rate['count'] += 1
            records = data.setdefault('whatsappReminderVerifications', {})
            record = dict(phone=phone, code_hash=code_hash,
                          expires=at + WHATSAPP_CODE_LIFETIME, attempts=0)
            records[visitor['id']] = record
            verification_hash = record['code_hash']
        if not send_whatsapp_template(settings, phone, settings['verify_template'], [code]):
            with raw_state() as data:
                record = data.setdefault('whatsappReminderVerifications', {}).get(visitor['id'])
                if record and record.get('code_hash') == verification_hash:
                    data['whatsappReminderVerifications'].pop(visitor['id'], None)
            raise ServiceError('WhatsApp could not send the verification code. Check the sender setup and try again.', 503)
        return jsonify(currentUserId=visitor['id'], message='A verification code was sent to your account phone number.')

    if action != 'verify' or set(payload) != {'action', 'code'} or not isinstance(payload.get('code'), str) or not re.fullmatch(r'[0-9]{6}', payload['code']):
        raise ServiceError('Request a WhatsApp code, then enter the six-digit code')
    with raw_state() as data:
        visitor = actor(data, 'player')
        account = data.get('accounts', {}).get(visitor['email'], {})
        record = data.setdefault('whatsappReminderVerifications', {}).get(visitor['id'])
        if (not record or record.get('expires', 0) <= time.time()
                or record.get('phone') != account.get('phone')
                or record.get('attempts', 0) >= WHATSAPP_CODE_ATTEMPTS):
            raise ServiceError('The WhatsApp verification code expired. Request a new code.', 400)
        record['attempts'] += 1
        password_hash = record['code_hash']
        expected_phone = record['phone']
    valid = check_password_hash(password_hash, payload['code'])
    with raw_state() as data:
        visitor = actor(data, 'player')
        account = data.get('accounts', {}).get(visitor['email'], {})
        record = data.setdefault('whatsappReminderVerifications', {}).get(visitor['id'])
        if (not valid or not record or record.get('code_hash') != password_hash
                or record.get('expires', 0) <= time.time() or record.get('phone') != expected_phone
                or account.get('phone') != expected_phone):
            raise ServiceError('The WhatsApp verification code is incorrect or expired', 400)
        account['phone_verified'] = True
        account['phone_verified_at'] = int(time.time())
        del data['whatsappReminderVerifications'][visitor['id']]
        value = user_settings(data, visitor['id'])
        value['preferences']['whatsapp'] = True
        return jsonify(currentUserId=visitor['id'], phoneVerified=True,
                       preferences=value['preferences'], message='WhatsApp reminders are enabled.')


@reminders.patch('/<notice_id>')
def update_notice(notice_id):
    payload = body()
    if not payload or set(payload) - {'read', 'dismissed'} or any(type(value) is not bool for value in payload.values()):
        raise ServiceError('Choose a read or dismissed state')
    at = now()
    with raw_state() as data:
        visitor = actor(data)
        value = user_settings(data, visitor['id'])
        notices = upcoming(data, visitor['id'], visitor['email'], at)
        trim(value, notices, at)
        if notice_id not in {notice['id'] for notice in notices}:
            raise ServiceError('Reminder not found', 404)
        states = value['states']
        if notice_id not in states and len(states) >= MAX_SAVED_STATES:
            oldest = min(states, key=lambda key: states[key]['updatedAt'])
            del states[oldest]
        state = states.setdefault(notice_id, dict(read=False, dismissed=False))
        state.update(payload)
        state['updatedAt'] = at.isoformat()
        return jsonify(currentUserId=visitor['id'], id=notice_id, read=state['read'], dismissed=state['dismissed'])


def email_content(notice):
    target = instant(notice['targetAt'])
    try:
        zone = ZoneInfo(notice['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        zone = timezone.utc
    when = target.astimezone(zone).strftime('%d %b %Y, %I:%M %p %Z')
    subject = 'Dhoyo reminder: ' + notice['title'].lower()
    text = (notice['tournamentName'] + '\n' + notice['title'] + ': ' + when + '\n' +
            'Sport: ' + notice['sport'] + '\n\n' +
            'You are receiving this because email reminders are enabled in your Dhoyo preferences.\n' +
            'Open Dhoyo > Reminders to view the current schedule or turn email reminders off.\n' +
            'The organiser may change the schedule; check tournament details before travelling.\n')
    return subject, text


def reserve_next(at, excluded, channel='email'):
    """Commit one per-delivery reservation before contacting a provider."""
    with raw_state() as data:
        accounts = data.get('accounts', {})
        for email, account in accounts.items():
            user_id = account.get('player_id')
            if (not user_id or account.get('account_type', 'player') != 'player'
                    or account.get('email_verified') is False):
                continue
            value = user_settings(data, user_id)
            if not value['preferences'].get(channel, False):
                continue
            recipient = email
            if channel == 'whatsapp':
                recipient = account.get('phone')
                if account.get('phone_verified') is not True or not isinstance(recipient, str):
                    continue
            notices = upcoming(data, user_id, email, at)
            trim(value, notices, at)
            deliveries = value['deliveries']
            recent_attempts = sum(sum(timestamp > at.timestamp() - 3600 for timestamp in record.get('attemptTimes', []))
                                  for record in deliveries.values())
            if recent_attempts >= MAX_USER_ATTEMPTS_PER_HOUR:
                continue
            for notice in notices:
                hours = due_lead(notice, value['preferences'], at)
                if hours is None or value['states'].get(notice['id'], {}).get('dismissed'):
                    continue
                delivery_id = notice['id'] + ':' + channel + ':' + str(hours)
                key = (user_id, delivery_id)
                if key in excluded:
                    continue
                previous = deliveries.get(delivery_id)
                if previous:
                    if previous['status'] != 'failed' or previous['attempts'] >= MAX_ATTEMPTS or previous['retryAt'] > at.timestamp():
                        continue
                elif len(deliveries) >= MAX_DELIVERIES:
                    continue
                reservation = secrets.token_hex(16)
                attempts = (previous or {}).get('attempts', 0) + 1
                attempt_times = (previous or {}).get('attemptTimes', []) + [at.timestamp()]
                deliveries[delivery_id] = dict(status='sending', reservation=reservation,
                                               reservedAt=at.timestamp(), attempts=attempts,
                                               attemptTimes=attempt_times, targetAt=notice['targetAt'])
                return dict(userId=user_id, email=email, phone=account.get('phone'), recipient=recipient,
                            channel=channel, id=delivery_id, reservation=reservation,
                            notice=notice, hours=hours)
    return None


def still_current(job, at):
    """Recheck opt-out, cancellation and schedule immediately before delivery."""
    with raw_state() as data:
        account = data.get('accounts', {}).get(job['email'])
        value = service(data).get(job['userId'])
        if (not account or account.get('player_id') != job['userId'] or account.get('email_verified') is False
                or not value or not value['preferences'].get(job['channel'], False)
                or value['states'].get(job['notice']['id'], {}).get('dismissed')):
            return False
        if job['channel'] == 'whatsapp' and (account.get('phone_verified') is not True
                                             or account.get('phone') != job.get('phone')):
            return False
        return any(notice['id'] == job['notice']['id'] and due_lead(notice, value['preferences'], at) == job['hours']
                   for notice in upcoming(data, job['userId'], job['email'], at))


def finish(job, status, at):
    with raw_state() as data:
        value = service(data).get(job['userId'], {})
        record = value.get('deliveries', {}).get(job['id'])
        if record and record.get('reservation') == job['reservation'] and record['status'] == 'sending':
            record['status'] = status
            record['updatedAt'] = at.isoformat()
            if status == 'failed':
                record['retryAt'] = at.timestamp() + RETRY_SECONDS


def send_due(limit=100):
    import password_reset
    email_settings = password_reset.mail_settings(require_base_url=False)
    wa_settings = whatsapp_settings()
    totals = dict(sent=0, failed=0, uncertain=0, skipped=0,
                  email_configured=int(email_settings is not None),
                  whatsapp_configured=int(wa_settings is not None))
    if email_settings is None and wa_settings is None:
        return totals
    for channel, settings in (('email', email_settings), ('whatsapp', wa_settings)):
        if settings is None:
            continue
        seen = set()
        for _ in range(limit):
            job = reserve_next(now(), seen, channel)
            if job is None:
                break
            seen.add((job['userId'], job['id']))
            if not still_current(job, now()):
                finish(job, 'skipped', now())
                totals['skipped'] += 1
                continue
            try:
                if channel == 'email':
                    subject, message = email_content(job['notice'])
                    _, delivered = password_reset.deliver_password_reset(
                        dict(settings, purpose='tournament_reminder', reminder_subject=subject, reminder_text=message),
                        job['recipient'], '')
                else:
                    target = instant(job['notice']['targetAt'])
                    try:
                        zone = ZoneInfo(job['notice']['timezone'])
                    except (ZoneInfoNotFoundError, TypeError, ValueError):
                        zone = timezone.utc
                    when = target.astimezone(zone).strftime('%d %b %Y, %I:%M %p %Z')
                    delivered = send_whatsapp_template(settings, job['recipient'], settings['reminder_template'],
                        [job['notice']['tournamentName'], job['notice']['title'], when, job['notice']['sport']])
                status = 'sent' if delivered else 'failed'
            except Exception:
                # The provider may have accepted the message. Leave an uncertain
                # receipt, never a reusable reservation, and avoid personal logs.
                status = 'uncertain'
            finish(job, status, now())
            totals[status] += 1
    return totals


@reminders.cli.command('send-due')
@click.option('--limit', type=click.IntRange(1, 500), default=100, show_default=True)
def send_due_command(limit):
    """Send opted-in, currently due tournament emails (schedule every 5 minutes)."""
    try:
        totals = send_due(limit)
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo(' '.join(key + '=' + str(value) for key, value in totals.items()))
