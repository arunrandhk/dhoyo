"""Reminder privacy, membership, timing and durable mail reservation regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from test_organisations import accounts, service_clock, create_event, get, post, patch
from app import app
from social import raw_state
import reminders as module


@pytest.fixture
def clock(service_clock, monkeypatch):
    monkeypatch.setattr(module, 'now', lambda: service_clock['value'])
    return service_clock


@pytest.fixture
def mail(monkeypatch):
    import password_reset
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs: dict(provider='smtp', sender='test@example.invalid'))
    sent = []

    def deliver(settings, email, token):
        # A write transaction can be opened while delivery is happening. The
        # provider is never contacted under SQLite/PostgreSQL's shared lock.
        with raw_state() as data:
            data['mailLockCheck'] = True
        sent.append(dict(settings=settings, email=email, token=token))
        return True, True

    monkeypatch.setattr(password_reset, 'deliver_password_reset', deliver)
    return sent


def joined(accounts, clock, **kwargs):
    owner, captain, member = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, clock, publish=True, teamSize=1,
                         playerEmailConfirmation='activation_link', **kwargs)
    response = post(captain['client'], f"/api/tournaments/{event['id']}/registrations", dict(
        teamName='PRIVATE TEAM', playerEmails=[dict(email=member['email'])], notes='PRIVATE CAPTAIN NOTE'))
    assert response.status_code == 201, response.json
    return owner, captain, member, event


def reminders(player):
    result = get(player['client'], '/api/reminders')
    assert result.status_code == 200, result.json
    return result.json


def email_opt_in(player, **kwargs):
    result = patch(player['client'], '/api/reminders/preferences', dict(email=True, **kwargs))
    assert result.status_code == 200, result.json


def only_start_due(event, clock, hours=2):
    clock['value'] = module.instant(event['startsAt']) - timedelta(hours=hours)
    with raw_state() as data:
        target = next(item for item in data['organisationService']['tournaments'] if item['id'] == event['id'])
        target['registrationClosesAt'] = (clock['value'] - timedelta(minutes=1)).isoformat()


def test_inbox_is_authenticated_private_and_defaults_to_no_email(accounts, clock):
    owner, captain, member, event = joined(accounts, clock)
    spectator = accounts()
    assert get(app.test_client(), '/api/reminders').status_code == 401
    own, roster = reminders(captain), reminders(member)
    assert own['currentUserId'] == captain['userId']
    assert roster['currentUserId'] == member['userId']
    assert own['preferences'] == dict(inApp=True, email=False, leadHours=[24, 1])
    assert len(own['reminders']) == len(roster['reminders']) == 2
    assert own['unreadCount'] == 2
    assert {notice['kind'] for notice in own['reminders']} == {'starts', 'registration_closes'}
    assert all(item['tournamentId'] == event['id'] for item in roster['reminders'])
    assert reminders(spectator)['reminders'] == reminders(owner)['reminders'] == []
    for secret in ('PRIVATE TEAM', 'PRIVATE CAPTAIN NOTE', captain['email'], member['email']):
        assert secret not in str(roster)
    notice = own['reminders'][0]['id']
    assert patch(spectator['client'], '/api/reminders/' + notice, dict(read=True)).status_code == 404


def test_read_and_dismiss_state_is_persistent_and_separate_for_each_member(accounts, clock):
    _, captain, member, _ = joined(accounts, clock)
    notice = reminders(captain)['reminders'][0]['id']
    assert patch(captain['client'], '/api/reminders/' + notice, dict(read=True)).status_code == 200
    assert reminders(captain)['unreadCount'] == 1
    assert reminders(member)['unreadCount'] == 2
    assert patch(captain['client'], '/api/reminders/' + notice, dict(dismissed=True)).status_code == 200
    assert len(reminders(captain)['reminders']) == 1
    assert len(reminders(member)['reminders']) == 2
    assert patch(captain['client'], '/api/reminders/' + notice, dict(dismissed=False, read=False)).status_code == 200
    assert reminders(captain)['unreadCount'] == 2


@pytest.mark.parametrize('payload', [
    dict(email='yes'), dict(inApp=1), dict(leadHours=[]), dict(leadHours=[True]),
    dict(leadHours=[24, 24]), dict(leadHours=[3]), dict(userId='another'), dict(extra=True), {}])
def test_preference_validation(accounts, clock, payload):
    player = accounts()
    assert patch(player['client'], '/api/reminders/preferences', payload).status_code == 400


def test_preferences_do_not_modify_other_accounts(accounts, clock):
    _, captain, member, _ = joined(accounts, clock)
    saved = patch(captain['client'], '/api/reminders/preferences', dict(inApp=False, email=True, leadHours=[1, 6]))
    assert saved.status_code == 200
    assert saved.json['preferences'] == dict(inApp=False, email=True, leadHours=[6, 1])
    assert reminders(captain)['reminders'] == []
    assert reminders(member)['preferences'] == module.DEFAULT_PREFERENCES


def test_changed_schedules_get_fresh_ids_and_withdrawn_or_cancelled_events_disappear(accounts, clock):
    _, captain, member, event = joined(accounts, clock)
    old = next(item for item in reminders(member)['reminders'] if item['kind'] == 'starts')
    assert patch(member['client'], '/api/reminders/' + old['id'], dict(dismissed=True)).status_code == 200
    with raw_state() as data:
        tournament = next(item for item in data['organisationService']['tournaments'] if item['id'] == event['id'])
        tournament['startsAt'] = (module.instant(event['startsAt']) + timedelta(hours=1)).isoformat()
    changed = next(item for item in reminders(member)['reminders'] if item['kind'] == 'starts')
    assert changed['id'] != old['id']
    assert changed['targetAt'] != old['targetAt']
    assert changed['read'] is False
    assert patch(member['client'], '/api/reminders/' + old['id'], dict(read=True)).status_code == 404
    assert post(captain['client'], f"/api/tournaments/{event['id']}/registrations/me/cancel").status_code == 200
    assert reminders(member)['reminders'] == reminders(captain)['reminders'] == []


def test_cancelled_event_and_elapsed_deadlines_are_removed(accounts, clock):
    _, captain, _, event = joined(accounts, clock)
    clock['value'] = module.instant(event['registrationClosesAt']) + timedelta(seconds=1)
    assert [item['kind'] for item in reminders(captain)['reminders']] == ['starts']
    with raw_state() as data:
        next(item for item in data['organisationService']['tournaments'] if item['id'] == event['id'])['status'] = 'cancelled'
    assert reminders(captain)['reminders'] == []


def test_email_is_opt_in_and_mail_receipts_prevent_repeated_runs(accounts, clock, mail):
    _, captain, member, event = joined(accounts, clock)
    only_start_due(event, clock)
    assert module.send_due() == dict(sent=0, failed=0, uncertain=0, skipped=0)
    assert mail == []
    email_opt_in(member, inApp=False)
    assert module.send_due()['sent'] == 1
    assert module.send_due()['sent'] == 0
    assert len(mail) == 1 and mail[0]['email'] == member['email']
    settings = mail[0]['settings']
    assert settings['purpose'] == 'tournament_reminder'
    assert event['name'] in settings['reminder_text']
    assert 'IST' in settings['reminder_text']
    assert 'PRIVATE' not in settings['reminder_text']
    assert captain['email'] not in settings['reminder_text']


def test_late_worker_only_sends_nearest_passed_lead_and_repeats_at_next_lead(accounts, clock, mail):
    _, captain, _, event = joined(accounts, clock)
    email_opt_in(captain)
    only_start_due(event, clock, hours=2)
    assert module.send_due()['sent'] == 1  # 24-hour threshold
    only_start_due(event, clock, hours=.5)
    assert module.send_due()['sent'] == 1  # 1-hour threshold
    assert module.send_due()['sent'] == 0
    assert len(mail) == 2


def test_email_failures_retry_after_delay_with_three_attempt_limit(accounts, clock, mail, monkeypatch):
    import password_reset
    _, captain, _, event = joined(accounts, clock)
    only_start_due(event, clock)
    email_opt_in(captain)
    calls = []
    monkeypatch.setattr(password_reset, 'deliver_password_reset', lambda *args: (calls.append(True) or (True, False)))
    for index in range(3):
        assert module.send_due()['failed'] == 1
        assert module.send_due()['failed'] == 0
        clock['value'] += timedelta(minutes=6)
    assert module.send_due()['failed'] == 0
    assert len(calls) == 3


def test_uncertain_outcome_does_not_automatically_retry(accounts, clock, mail, monkeypatch):
    import password_reset
    _, captain, _, event = joined(accounts, clock)
    only_start_due(event, clock)
    email_opt_in(captain)

    def provider_timeout(*args):
        raise TimeoutError('synthetic provider timeout')

    monkeypatch.setattr(password_reset, 'deliver_password_reset', provider_timeout)
    assert module.send_due()['uncertain'] == 1
    clock['value'] += timedelta(minutes=16)
    assert module.send_due()['uncertain'] == 0


def test_parallel_workers_have_only_one_reservation(accounts, clock, mail):
    _, captain, _, event = joined(accounts, clock)
    only_start_due(event, clock)
    email_opt_in(captain)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: module.reserve_next(clock['value'], set()), range(2)))
    reserved = [item for item in results if item]
    assert len(reserved) == 1
    # A worker that disappears after reservation must not be reclaimed when it
    # is impossible to know whether the provider accepted its message.
    clock['value'] += timedelta(minutes=16)
    assert module.reserve_next(clock['value'], set()) is None
    with raw_state() as data:
        record = data['tournamentReminders']['users'][captain['userId']]['deliveries'][reserved[0]['id']]
        assert record['status'] == 'uncertain'


def test_dismissed_unverified_and_opted_out_accounts_never_receive_mail(accounts, clock, mail):
    _, captain, member, event = joined(accounts, clock)
    only_start_due(event, clock)
    email_opt_in(captain)
    email_opt_in(member)
    notice = reminders(captain)['reminders'][0]
    assert patch(captain['client'], '/api/reminders/' + notice['id'], dict(dismissed=True)).status_code == 200
    with raw_state() as data:
        data['accounts'][member['email']]['email_verified'] = False
    assert module.send_due()['sent'] == 0
    assert mail == []


def test_pre_delivery_check_honours_cancellation_and_opt_out(accounts, clock, mail):
    _, captain, _, event = joined(accounts, clock)
    only_start_due(event, clock)
    email_opt_in(captain)
    job = module.reserve_next(clock['value'], set())
    assert job
    assert patch(captain['client'], '/api/reminders/preferences', dict(email=False)).status_code == 200
    assert module.still_current(job, clock['value']) is False


def test_worker_cli_reports_missing_configuration_without_reserving(accounts, clock, monkeypatch):
    import password_reset
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs: None)
    result = app.test_cli_runner().invoke(args=['reminders', 'send-due'])
    assert result.exit_code != 0
    assert 'not configured' in result.output
    with raw_state() as data:
        assert not data.get('tournamentReminders')
