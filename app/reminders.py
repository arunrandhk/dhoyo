"""Private tournament reminders and an opt-in mail worker.

The inbox is derived from current membership and schedule on every request. Mail
jobs reserve deliveries transactionally, then contact providers outside the lock.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from flask import Blueprint, jsonify, request

from organisations import ServiceError, active_registrations, actor, ensure_service, is_participant
from social import body, raw_state


reminders = Blueprint('reminders', __name__, url_prefix='/api/reminders')
DEFAULT_PREFERENCES = dict(inApp=True, email=False, leadHours=[24, 1])
ALLOWED_LEADS = (1, 6, 24, 48)
MAX_SAVED_STATES = 512
MAX_DELIVERIES = 512
MAX_ATTEMPTS = 3
RETRY_SECONDS = 5 * 60
RESERVATION_SECONDS = 15 * 60
MAX_USER_ATTEMPTS_PER_HOUR = 20


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
        return jsonify(currentUserId=visitor['id'], preferences=value['preferences'], reminders=visible[:100],
                       unreadCount=sum(not item['read'] for item in visible),
                       totalCount=len(visible), serverTime=at.isoformat(),
                       emailDeliveryConfigured=password_reset.mail_settings(require_base_url=False) is not None)


@reminders.patch('/preferences')
def preferences():
    payload = body()
    if not payload or set(payload) - {'inApp', 'email', 'leadHours'}:
        raise ServiceError('Choose in-app, email and reminder lead time preferences')
    for key in ('inApp', 'email'):
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
        value['preferences'].update(payload)
        value['preferences']['leadHours'] = sorted(value['preferences']['leadHours'], reverse=True)
        return jsonify(currentUserId=visitor['id'], preferences=value['preferences'])


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
            'You are receiving this because your account is a participant and you opted in to tournament emails.\n' +
            'Open Dhoyo > Reminders to view the current schedule or turn email reminders off.\n' +
            'The organiser may change the schedule; check tournament details before travelling.\n')
    return subject, text


def reserve_next(at, excluded):
    """Commit one per-delivery reservation before handing data to a mailer."""
    with raw_state() as data:
        accounts = data.get('accounts', {})
        users = service(data)
        for email, account in accounts.items():
            user_id = account.get('player_id')
            value = users.get(user_id)
            if not value or not value['preferences']['email'] or account.get('email_verified') is False:
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
                delivery_id = notice['id'] + ':email:' + str(hours)
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
                return dict(userId=user_id, email=email, id=delivery_id,
                            reservation=reservation, notice=notice, hours=hours)
    return None


def still_current(job, at):
    """Recheck opt-out, cancellation and schedule immediately before delivery."""
    with raw_state() as data:
        account = data.get('accounts', {}).get(job['email'])
        value = service(data).get(job['userId'])
        if (not account or account.get('player_id') != job['userId'] or account.get('email_verified') is False
                or not value or not value['preferences']['email']
                or value['states'].get(job['notice']['id'], {}).get('dismissed')):
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
    settings = password_reset.mail_settings(require_base_url=False)
    if settings is None:
        raise ValueError('Email delivery is not configured. Configure the existing Gmail, Resend or SMTP mail settings.')
    totals = dict(sent=0, failed=0, uncertain=0, skipped=0)
    seen = set()
    for _ in range(limit):
        job = reserve_next(now(), seen)
        if job is None:
            break
        seen.add((job['userId'], job['id']))
        if not still_current(job, now()):
            finish(job, 'skipped', now())
            totals['skipped'] += 1
            continue
        subject, message = email_content(job['notice'])
        # No network call takes place while the shared database row is locked.
        try:
            _, delivered = password_reset.deliver_password_reset(
                dict(settings, purpose='tournament_reminder', reminder_subject=subject, reminder_text=message),
                job['email'], '')
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
