"""Tournament roster proofs use fake mail and isolated real account sessions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from auth import COOKIE, digest
from social import raw_state
import password_reset
import tournament_verification as verification
from test_organisations import (accounts, service_clock, create_event, post, patch, get)


@pytest.fixture
def mail(monkeypatch):
    sent = []
    settings = dict(provider='smtp', sender='tests@example.invalid')
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs: settings)

    def deliver(config, recipient, code, tournament_name):
        # This transaction would fail while an outer SQLite writer held the lock.
        with raw_state() as data:
            assert data['organisationService']['playerEmailChallenges']
        sent.append(dict(email=recipient, code=code, tournament=tournament_name))
        return True, True

    monkeypatch.setattr(password_reset, 'deliver_tournament_player_code', deliver)
    return sent


def request_code(player, event, email):
    return post(player['client'], f"/api/tournaments/{event['id']}/player-emails/request-code", {'email': email})


def verify_code(player, event, email, challenge, code):
    return post(player['client'], f"/api/tournaments/{event['id']}/player-emails/verify-code",
                dict(email=email, challengeId=challenge, code=code))


def verified_email(player, event, email, mail):
    requested = request_code(player, event, email)
    assert requested.status_code == 200, requested.get_data(as_text=True)
    verified = verify_code(player, event, email, requested.json['challengeId'], mail[-1]['code'])
    assert verified.status_code == 200, verified.get_data(as_text=True)
    return dict(email=email.strip().casefold(), challengeId=requested.json['challengeId'])


def register(player, event, emails=None, **overrides):
    payload = dict(teamName='Synthetic Team')
    payload.update(overrides)
    if emails is not None:
        payload['playerEmails'] = emails
    return post(player['client'], f"/api/tournaments/{event['id']}/registrations", payload)


def record(challenge):
    with raw_state() as data:
        return data['organisationService']['playerEmailChallenges'].get(digest(challenge))


def test_tournament_verification_flag_is_legacy_safe_strict_and_locked(accounts, service_clock):
    owner = accounts('organisation')
    assert create_event(owner, service_clock)['requirePlayerEmailVerification'] is False
    for invalid in ('true', 1, None, []):
        from test_organisations import event_payload
        assert post(owner['client'], '/api/tournaments',
                    event_payload(service_clock, requirePlayerEmailVerification=invalid)).status_code == 400
    event = create_event(owner, service_clock, publish=True, requirePlayerEmailVerification=True)
    assert event['requirePlayerEmailVerification'] is True
    changed = patch(owner['client'], f"/api/tournaments/{event['id']}", {'requirePlayerEmailVerification': False})
    assert changed.status_code == 409


def test_every_player_gets_private_verified_roster_and_single_use_proof(accounts, service_clock, mail):
    owner, player, spectator = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=2, requirePlayerEmailVerification=True)
    emails = [verified_email(player, event, ' FIRST.Player@Example.Invalid ', mail),
              verified_email(player, event, 'second.player@example.invalid', mail)]
    assert [entry['email'] for entry in mail] == [entry['email'] for entry in emails]
    assert all(entry['tournament'] == event['name'] for entry in mail)
    for entry, message in zip(emails, mail):
        assert re.fullmatch(r'[A-Za-z0-9_-]{43}', entry['challengeId'])
        stored = record(entry['challengeId'])
        assert message['code'] not in stored.values()
        assert 'code' not in stored
        assert stored['codeHash'].startswith('scrypt:')
    response = register(player, event, emails)
    assert response.status_code == 201
    roster = response.json['registration']['playerEmails']
    assert roster == [dict(email=item['email'], verified=True, verifiedAt=service_clock['value'].isoformat())
                      for item in emails]
    assert all(record(item['challengeId'])['used'] for item in emails)
    assert all('codeHash' not in record(item['challengeId']) for item in emails)
    for item in emails:
        assert verify_code(player, event, item['email'], item['challengeId'], '000000').status_code == 400
    public = get(spectator['client'], '/api/tournaments').json
    assert 'first.player@example.invalid' not in str(public)
    assert 'registrations' not in public['tournaments'][0]
    own = get(player['client'], '/api/tournaments').json['tournaments'][0]
    assert own['myRegistration']['playerEmails'] == roster
    managed = get(owner['client'], f"/api/tournaments/{event['id']}/registrations").json
    assert managed['registrations'][0]['playerEmails'] == roster


def test_required_registration_rejects_bypass_duplicates_and_unverified_proofs(accounts, service_clock, mail):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=2, requirePlayerEmailVerification=True)
    assert register(player, event).status_code == 400
    assert register(player, event, []).status_code == 400
    first = verified_email(player, event, 'first@example.invalid', mail)
    assert register(player, event, [first]).status_code == 400
    assert register(player, event, [first, dict(first, email='FIRST@example.invalid')]).status_code == 400
    pending = request_code(player, event, 'second@example.invalid')
    second = dict(email='second@example.invalid', challengeId=pending.json['challengeId'])
    assert register(player, event, [first, second]).status_code == 400
    assert not record(first['challengeId'])['used']
    assert verify_code(player, event, second['email'], second['challengeId'], mail[-1]['code']).status_code == 200
    assert register(player, event, [first, second]).status_code == 201


def test_challenges_bound_to_captain_event_and_email_without_burning_other_proof(accounts, service_clock, mail):
    owner, player, other = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1, requirePlayerEmailVerification=True)
    another = create_event(owner, service_clock, publish=True, teamSize=1, requirePlayerEmailVerification=True)
    requested = request_code(player, event, 'one@example.invalid')
    challenge, code = requested.json['challengeId'], mail[-1]['code']
    assert verify_code(other, event, 'one@example.invalid', challenge, code).status_code == 400
    assert verify_code(player, another, 'one@example.invalid', challenge, code).status_code == 400
    assert verify_code(player, event, 'different@example.invalid', challenge, code).status_code == 400
    assert record(challenge)['attempts'] == 0
    assert verify_code(player, event, 'one@example.invalid', challenge, code).status_code == 200
    proof = [dict(email='one@example.invalid', challengeId=challenge)]
    assert register(other, event, proof).status_code == 400
    assert register(player, another, proof).status_code == 400
    assert register(player, event, proof).status_code == 201


def test_five_attempt_limit_and_expiry_are_enforced(accounts, service_clock, mail):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1)
    requested = request_code(player, event, 'one@example.invalid')
    challenge, code = requested.json['challengeId'], mail[-1]['code']
    wrong = '999999' if code != '999999' else '888888'
    for _ in range(6):
        assert verify_code(player, event, 'one@example.invalid', challenge, wrong).status_code == 400
    assert record(challenge)['attempts'] == 5
    assert verify_code(player, event, 'one@example.invalid', challenge, code).status_code == 400
    service_clock['value'] += timedelta(seconds=61)
    proof = verified_email(player, event, 'one@example.invalid', mail)
    service_clock['value'] += timedelta(seconds=600)
    assert register(player, event, [proof]).status_code == 400
    assert verify_code(player, event, proof['email'], proof['challengeId'], mail[-1]['code']).status_code == 400
    assert record(proof['challengeId']) is None


def test_parallel_guesses_share_attempt_cap_and_hash_without_transaction(accounts, service_clock, mail, monkeypatch):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1)
    requested = request_code(player, event, 'one@example.invalid')
    challenge, code = requested.json['challengeId'], mail[-1]['code']
    wrong = '999999' if code != '999999' else '888888'
    token = player['client'].get_cookie(COOKIE).value
    check = verification.check_password_hash

    def unlocked_check(code_hash, supplied):
        with raw_state():
            pass
        return check(code_hash, supplied)

    monkeypatch.setattr(verification, 'check_password_hash', unlocked_check)

    def guess(_):
        client = app.test_client()
        client.set_cookie(COOKIE, token)
        return verify_code(dict(client=client), event, 'one@example.invalid', challenge, wrong).status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert list(executor.map(guess, range(6))) == [400] * 6
    assert record(challenge)['attempts'] == 5


def test_failed_resend_preserves_old_code_and_persists_send_limits(accounts, service_clock, mail, monkeypatch):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1)
    requested = request_code(player, event, 'one@example.invalid')
    challenge, code = requested.json['challengeId'], mail[-1]['code']
    assert request_code(player, event, 'one@example.invalid').status_code == 429
    assert len(mail) == 1
    service_clock['value'] += timedelta(seconds=61)
    monkeypatch.setattr(password_reset, 'deliver_tournament_player_code', lambda *args: (True, False))
    failed = request_code(player, event, 'one@example.invalid')
    assert failed.status_code == 503
    assert record(challenge)['active'] is True
    with raw_state() as data:
        service = data['organisationService']
        assert len(service['playerEmailChallenges']) == 1
        assert service['playerEmailRateLimits'][digest('send-email:one@example.invalid')]['count'] == 2
    assert verify_code(player, event, 'one@example.invalid', challenge, code).status_code == 200
    assert request_code(player, event, 'one@example.invalid').status_code == 429


def test_successful_resend_replaces_previous_code(accounts, service_clock, mail):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True)
    requested = request_code(player, event, 'one@example.invalid')
    old_challenge, old_code = requested.json['challengeId'], mail[-1]['code']
    service_clock['value'] += timedelta(seconds=61)
    newer = request_code(player, event, 'one@example.invalid')
    assert newer.status_code == 200
    assert record(old_challenge) is None
    assert verify_code(player, event, 'one@example.invalid', old_challenge, old_code).status_code == 400
    assert verify_code(player, event, 'one@example.invalid', newer.json['challengeId'], mail[-1]['code']).status_code == 200


def test_unconfigured_and_exceptional_mail_returns_clear_failure(accounts, service_clock, mail, monkeypatch):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True)
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs: None)
    assert request_code(player, event, 'one@example.invalid').status_code == 503
    assert not mail
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs: dict(provider='smtp'))

    def failed(*args):
        raise RuntimeError('Synthetic transport failure')

    monkeypatch.setattr(password_reset, 'deliver_tournament_player_code', failed)
    assert request_code(player, event, 'one@example.invalid').status_code == 503
    with raw_state() as data:
        assert data['organisationService']['playerEmailChallenges'] == {}
        assert data['organisationService']['playerEmailRateLimits'][digest('send-email:one@example.invalid')]['count'] == 1


@pytest.mark.parametrize('change', ['cancel', 'deadline', 'session', 'identity', 'full'])
def test_delivery_rechecks_context_before_activating(accounts, service_clock, mail, monkeypatch, change):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True, capacity=2)

    def delivered(*args):
        with raw_state() as data:
            service = data['organisationService']
            stored = next(item for item in service['tournaments'] if item['id'] == event['id'])
            if change == 'cancel':
                stored['status'] = 'cancelled'
            elif change == 'deadline':
                stored['registrationClosesAt'] = service_clock['value'].isoformat()
            elif change == 'session':
                data['sessions'] = {}
            elif change == 'identity':
                data['accounts'][player['email']]['password_hash'] = 'changed-during-delivery'
            else:
                for number in range(2):
                    service['registrations'].append(dict(
                        id=f'synthetic-{number}', tournamentId=event['id'], playerId=f'other-{number}',
                        playerName='Other Player', teamName=f'Other {number}', status='registered'))
        return True, True

    monkeypatch.setattr(password_reset, 'deliver_tournament_player_code', delivered)
    response = request_code(player, event, 'one@example.invalid')
    assert response.status_code == (401 if change == 'session' else 409)
    with raw_state() as data:
        assert not data['organisationService']['playerEmailChallenges']


def test_invalid_registration_preserves_proofs_and_duplicate_team_email_rejected(accounts, service_clock, mail):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1, requirePlayerEmailVerification=True,
                         registrationQuestions=[dict(id='level', label='Level', type='text', required=True)])
    proof = verified_email(first, event, 'shared@example.invalid', mail)
    other_proof = verified_email(second, event, 'shared@example.invalid', mail)
    assert register(first, event, [proof]).status_code == 400
    assert not record(proof['challengeId'])['used']
    assert register(first, event, [proof], answers=dict(level='beginner')).status_code == 201
    # An unverified email probe cannot reveal another team's private membership.
    probe = register(second, event, [{'email': 'shared@example.invalid'}],
                     answers=dict(level='beginner'), teamName='Another Team')
    assert probe.status_code == 400
    assert 'Verify every player email' in probe.json['error']
    rejected = register(second, event, [other_proof], answers=dict(level='beginner'), teamName='Another Team')
    assert rejected.status_code == 409
    assert not record(other_proof['challengeId'])['used']


def test_roster_edits_preserve_existing_and_require_new_proofs_for_changed_players(accounts, service_clock, mail):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=2, requirePlayerEmailVerification=True)
    first = verified_email(player, event, 'one@example.invalid', mail)
    second = verified_email(player, event, 'two@example.invalid', mail)
    created = register(player, event, [first, second]).json['registration']
    path = f"/api/tournaments/{event['id']}/registrations/me"
    renamed = patch(player['client'], path, dict(teamName='Renamed Team'))
    assert renamed.status_code == 200
    assert renamed.json['registration']['playerEmails'] == created['playerEmails']
    unchanged = patch(player['client'], path, dict(teamName='Renamed Team',
                      playerEmails=[{'email': second['email']}, {'email': first['email']}]))
    assert unchanged.status_code == 200
    bad = patch(player['client'], path, dict(teamName='Renamed Team',
                playerEmails=[{'email': first['email']}, {'email': 'new@example.invalid'}]))
    assert bad.status_code == 400
    fresh = verified_email(player, event, 'new@example.invalid', mail)
    updated = patch(player['client'], path, dict(teamName='Renamed Team',
                    playerEmails=[{'email': first['email']}, fresh]))
    assert updated.status_code == 200
    assert [item['email'] for item in updated.json['registration']['playerEmails']] == [first['email'], fresh['email']]
    assert record(fresh['challengeId'])['used']


def test_cancellation_re_registration_requires_fresh_proof(accounts, service_clock, mail):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1, requirePlayerEmailVerification=True)
    proof = verified_email(player, event, 'one@example.invalid', mail)
    assert register(player, event, [proof]).status_code == 201
    assert post(player['client'], f"/api/tournaments/{event['id']}/registrations/me/cancel").status_code == 200
    assert register(player, event, [proof]).status_code == 400
    service_clock['value'] += timedelta(seconds=61)
    fresh = verified_email(player, event, 'one@example.invalid', mail)
    assert register(player, event, [fresh]).status_code == 201


def test_optional_player_rosters_still_require_verification(accounts, service_clock, mail):
    owner, player, other = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=3)
    assert register(player, event, [{'email': 'one@example.invalid'}]).status_code == 400
    proof = verified_email(player, event, 'one@example.invalid', mail)
    assert register(player, event, [proof]).status_code == 201
    assert register(other, event, [], teamName='Legacy Team').status_code == 201
    cleared = patch(player['client'], f"/api/tournaments/{event['id']}/registrations/me",
                    dict(teamName='Synthetic Team', playerEmails=[]))
    assert cleared.status_code == 200
    assert cleared.json['registration']['playerEmails'] == []


def test_request_access_capacity_and_email_validation(accounts, service_clock, mail):
    owner, player, other = accounts('organisation'), accounts(), accounts()
    draft = create_event(owner, service_clock)
    assert request_code(player, draft, 'one@example.invalid').status_code == 404
    event = create_event(owner, service_clock, publish=True)
    assert request_code(owner, event, 'one@example.invalid').status_code == 403
    for email in ('not-email', 'a@localhost', 'a@domain..invalid', 'a\nname@example.invalid', '.a@example.invalid', 7):
        assert request_code(player, event, email).status_code == 400
    assert register(player, event).status_code == 201
    assert register(other, event, teamName='Other Team').status_code == 201
    late = accounts()
    assert request_code(late, event, 'one@example.invalid').status_code == 409
    # Existing captains can still verify replacements for roster edits in a full event.
    assert request_code(player, event, 'one@example.invalid').status_code == 200
    service_clock['value'] += timedelta(days=2)
    assert request_code(other, event, 'other@example.invalid').status_code == 409


def test_global_recipient_rate_limit_and_cleanup(accounts, service_clock, mail):
    owner = accounts('organisation')
    event = create_event(owner, service_clock, publish=True)
    players = [accounts() for _ in range(4)]
    for player in players[:3]:
        assert request_code(player, event, 'one@example.invalid').status_code == 200
    assert request_code(players[3], event, 'ONE@example.invalid').status_code == 429
    assert len(mail) == 3
    service_clock['value'] += timedelta(seconds=901)
    assert request_code(players[3], event, 'one@example.invalid').status_code == 200
    with raw_state() as data:
        assert len(data['organisationService']['playerEmailChallenges']) == 1


@pytest.mark.parametrize('scope,maximum', [('send-player:', 150), ('send-ip:', 300)])
def test_sender_and_ip_rate_caps_reject_send(accounts, service_clock, mail, scope, maximum):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True)
    suffix = player['userId'] if scope == 'send-player:' else '127.0.0.1'
    with raw_state() as data:
        data['organisationService']['playerEmailRateLimits'][digest(scope + suffix)] = dict(
            count=maximum, until=service_clock['value'].timestamp() + 900)
    assert request_code(player, event, 'one@example.invalid').status_code == 429
    assert mail == []


def test_capacity_failure_does_not_consume_verified_proof(accounts, service_clock, mail):
    owner, player, first, second = accounts('organisation'), accounts(), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1)
    proof = verified_email(player, event, 'one@example.invalid', mail)
    assert register(first, event, teamName='First Team').status_code == 201
    assert register(second, event, teamName='Second Team').status_code == 201
    assert register(player, event, [proof]).status_code == 409
    assert not record(proof['challengeId'])['used']
    assert post(second['client'], f"/api/tournaments/{event['id']}/registrations/me/cancel").status_code == 200
    assert register(player, event, [proof]).status_code == 201


def test_verification_rechecks_session_after_hashing(accounts, service_clock, mail, monkeypatch):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True)
    requested = request_code(player, event, 'one@example.invalid')
    challenge, code = requested.json['challengeId'], mail[-1]['code']
    check = verification.check_password_hash

    def revoked_during_hash(code_hash, supplied):
        matches = check(code_hash, supplied)
        with raw_state() as data:
            data['sessions'] = {}
        return matches

    monkeypatch.setattr(verification, 'check_password_hash', revoked_during_hash)
    assert verify_code(player, event, 'one@example.invalid', challenge, code).status_code == 401
    assert not record(challenge)['verified']
    assert record(challenge)['attempts'] == 1


def test_denied_send_requests_do_not_hash_otp(accounts, service_clock, mail, monkeypatch):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True)
    draft = create_event(owner, service_clock)
    generate = verification.generate_password_hash
    hashed = []

    def count_hash(code, **kwargs):
        # Pending reservations are committed, and expensive work runs unlocked.
        with raw_state() as data:
            assert any(item['codeHash'] is None
                       for item in data['organisationService']['playerEmailChallenges'].values())
        hashed.append(code)
        return generate(code, **kwargs)

    monkeypatch.setattr(verification, 'generate_password_hash', count_hash)
    assert request_code(owner, event, 'one@example.invalid').status_code == 403
    assert request_code(player, draft, 'one@example.invalid').status_code == 404
    assert hashed == []
    settings = password_reset.mail_settings
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs: None)
    assert request_code(player, event, 'one@example.invalid').status_code == 503
    assert hashed == []
    monkeypatch.setattr(password_reset, 'mail_settings', settings)
    assert request_code(player, event, 'one@example.invalid').status_code == 200
    assert len(hashed) == 1
    assert request_code(player, event, 'one@example.invalid').status_code == 429
    assert len(hashed) == 1
