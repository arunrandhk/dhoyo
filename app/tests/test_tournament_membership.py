"""Active tournament membership belongs to captains and every saved roster email."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from urllib.parse import urlsplit

import pytest

from test_organisations import accounts, service_clock, create_event, post, patch, get
from app import app
from auth import digest
from social import raw_state
import password_reset


@pytest.fixture
def membership_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs: dict(
        provider='smtp', sender='tests@example.invalid', base_url='https://localhost/sportspace'))

    def send_code(settings, email, code, tournament_name):
        sent.append(dict(email=email, code=code))
        return True, True

    def send_activation(settings, email, link):
        sent.append(dict(email=email, link=link))
        return True, True

    monkeypatch.setattr(password_reset, 'deliver_tournament_player_code', send_code)
    monkeypatch.setattr(password_reset, 'deliver_password_reset', send_activation)
    return sent


def register(captain, event, emails=None, name='First Team'):
    payload = dict(teamName=name)
    if emails is not None:
        payload['playerEmails'] = emails
    return post(captain['client'], f"/api/tournaments/{event['id']}/registrations", payload)


def roster_entry(captain, event, email, mail):
    if event['playerEmailConfirmation'] == 'activation_link':
        return dict(email=email)
    path = f"/api/tournaments/{event['id']}/player-emails"
    requested = post(captain['client'], path + '/request-code', dict(email=email))
    assert requested.status_code == 200, requested.json
    challenge = requested.json['challengeId']
    verified = post(captain['client'], path + '/verify-code',
                    dict(email=email, challengeId=challenge, code=mail[-1]['code']))
    assert verified.status_code == 200, verified.json
    return dict(email=email, challengeId=challenge)


def registration_snapshot(captain, event):
    with raw_state() as data:
        return deepcopy(next(item for item in data['organisationService']['registrations']
                             if item['tournamentId'] == event['id']
                             and item['playerId'] == captain['userId']))


@pytest.mark.parametrize('acknowledged', [False, True], ids=['pending', 'acknowledged'])
def test_email_only_member_cannot_be_registered_by_another_captain(
        accounts, service_clock, membership_mail, acknowledged):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1,
                         requirePlayerEmailVerification=True, playerEmailConfirmation='activation_link')
    email = 'email-only-member@example.invalid'
    assert register(first, event, [dict(email=email)]).status_code == 201
    with raw_state() as data:
        assert email not in data['accounts']
    if acknowledged:
        sent = post(first['client'], f"/api/tournaments/{event['id']}/player-emails/send-activation",
                    dict(email=email))
        assert sent.status_code == 200, sent.json
        token = urlsplit(membership_mail[-1]['link']).fragment
        accepted = post(app.test_client(), '/api/auth/tournament-acknowledgement', dict(token=token))
        assert accepted.status_code == 200, accepted.json
    original = registration_snapshot(first, event)
    duplicate = register(second, event, [dict(email=' EMAIL-ONLY-MEMBER@Example.Invalid ')], 'Second Team')
    assert duplicate.status_code == 409, duplicate.json
    assert registration_snapshot(first, event) == original
    saved = get(owner['client'], f"/api/tournaments/{event['id']}/registrations").json['registrations']
    assert len(saved) == 1


def test_conflicting_roster_edit_rolls_back_and_own_roster_can_still_be_edited(accounts, service_clock):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=2,
                         requirePlayerEmailVerification=True, playerEmailConfirmation='activation_link')
    first_roster = [dict(email='occupied@example.invalid'), dict(email='first-other@example.invalid')]
    second_roster = [dict(email='second-one@example.invalid'), dict(email='second-two@example.invalid')]
    assert register(first, event, first_roster).status_code == 201
    assert register(second, event, second_roster, 'Second Team').status_code == 201
    original = registration_snapshot(second, event)
    path = f"/api/tournaments/{event['id']}/registrations/me"
    rejected = patch(second['client'], path, dict(
        teamName='Conflicting Edit', notes='This edit must roll back',
        playerEmails=[dict(email=' OCCUPIED@Example.Invalid '), second_roster[1]]))
    assert rejected.status_code == 409, rejected.json
    assert registration_snapshot(second, event) == original
    renamed = patch(second['client'], path, dict(teamName='Renamed Team'))
    assert renamed.status_code == 200, renamed.json
    assert registration_snapshot(second, event)['playerEmails'] == original['playerEmails']
    reordered = patch(second['client'], path,
                      dict(teamName='Renamed Team', playerEmails=second_roster[::-1]))
    assert reordered.status_code == 200, reordered.json
    assert registration_snapshot(second, event)['playerEmails'] == original['playerEmails'][::-1]


def test_membership_is_scoped_to_one_tournament(accounts, service_clock):
    owner, captain = accounts('organisation'), accounts()
    events = [create_event(owner, service_clock, publish=True, teamSize=1,
                           requirePlayerEmailVerification=True, playerEmailConfirmation='activation_link')
              for _ in range(2)]
    for event in events:
        result = register(captain, event, [dict(email='shared-member@example.invalid')])
        assert result.status_code == 201, result.json


@pytest.mark.parametrize('participant', ['captain', 'member'])
def test_registered_player_cannot_register_again_after_logging_in(accounts, service_clock, participant):
    owner, captain, member = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1,
                         playerEmailConfirmation='activation_link')
    assert register(captain, event, [dict(email=member['email'])]).status_code == 201
    player = captain if participant == 'captain' else member
    assert post(player['client'], '/api/auth/logout').status_code == 200
    signed_in = app.test_client()
    login = post(signed_in, '/api/auth/login', dict(
        email=player['email'].upper(), password=player['payload']['password']))
    assert login.status_code == 200, login.json
    listed = get(signed_in, '/api/tournaments').json['tournaments'][0]
    assert listed['isParticipant'] is True
    assert bool(listed['myRegistration']) == (participant == 'captain')
    duplicate = post(signed_in, f"/api/tournaments/{event['id']}/registrations", dict(
        teamName='Second Team', playerEmails=[dict(email='another-member@example.invalid')]))
    assert duplicate.status_code == 409, duplicate.json
    with raw_state() as data:
        assert len(data['organisationService']['registrations']) == 1


def test_later_member_account_sees_membership_without_captain_privileges_or_private_details(
        accounts, service_clock):
    owner, captain, spectator = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1,
                         requirePlayerEmailVerification=True, playerEmailConfirmation='activation_link',
                         registrationQuestions=[dict(id='contact', label='Contact', type='text', required=True)])
    member_email = 'later-member@example.invalid'
    path = f"/api/tournaments/{event['id']}/registrations"
    private = dict(teamName='Private Team Name', notes='Private captain notes',
                   answers=dict(contact='Private contact answer'), playerEmails=[dict(email=member_email)])
    created = post(captain['client'], path, private)
    assert created.status_code == 201, created.json
    with raw_state() as data:
        assert member_email not in data['accounts']
    member = accounts(email=member_email.upper())

    def listed(player):
        response = get(player['client'], '/api/tournaments')
        assert response.status_code == 200, response.json
        return next(item for item in response.json['tournaments'] if item['id'] == event['id'])

    own = listed(captain)
    assert own['isParticipant'] is True
    assert own['myRegistration'] == created.json['registration']
    assert listed(spectator)['isParticipant'] is False
    member_view = listed(member)
    assert member_view['isParticipant'] is True
    assert member_view['myRegistration'] is None
    assert member_view['myRegistrationHistory'] == []
    assert 'registrations' not in member_view
    for secret in (member_email, private['teamName'], private['notes'], private['answers']['contact']):
        assert secret not in str(member_view)
    rejected_edit = patch(member['client'], path + '/me', dict(teamName='Member Cannot Edit'))
    assert rejected_edit.status_code == 404, rejected_edit.json
    rejected_cancel = post(member['client'], path + '/me/cancel')
    assert rejected_cancel.status_code == 404, rejected_cancel.json
    assert registration_snapshot(captain, event)['status'] == 'registered'
    cancelled = post(captain['client'], path + '/me/cancel')
    assert cancelled.status_code == 200, cancelled.json
    assert listed(member)['isParticipant'] is False


@pytest.mark.parametrize('release', ['cancel', 'remove'])
def test_cancelled_or_removed_member_can_join_another_team(accounts, service_clock, release):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1,
                         playerEmailConfirmation='activation_link')
    roster = [dict(email='released-member@example.invalid')]
    assert register(first, event, roster).status_code == 201
    path = f"/api/tournaments/{event['id']}/registrations/me"
    if release == 'cancel':
        released = post(first['client'], path + '/cancel')
    else:
        released = patch(first['client'], path, dict(teamName='First Team', playerEmails=[]))
    assert released.status_code == 200, released.json
    accepted = register(second, event, roster, 'Second Team')
    assert accepted.status_code == 201, accepted.json


@pytest.mark.parametrize('confirmation', ['activation_link', 'code'])
def test_registered_member_cannot_captain_another_team_while_omitting_their_email(
        accounts, service_clock, membership_mail, confirmation):
    owner, first = accounts('organisation'), accounts()
    member = accounts(email='existing-member@example.invalid')
    event = create_event(owner, service_clock, publish=True, teamSize=1,
                         playerEmailConfirmation=confirmation)
    entry = roster_entry(first, event, member['email'].upper(), membership_mail)
    assert register(first, event, [entry]).status_code == 201
    rejected = register(member, event, name='Member Creates Another Team')
    assert rejected.status_code == 409, rejected.json
    with raw_state() as data:
        assert len(data['organisationService']['registrations']) == 1


@pytest.mark.parametrize('confirmation', ['activation_link', 'code'])
def test_captains_account_email_cannot_be_added_to_another_team(
        accounts, service_clock, membership_mail, confirmation):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1,
                         playerEmailConfirmation=confirmation)
    assert register(first, event).status_code == 201
    entry = roster_entry(second, event, first['email'].upper(), membership_mail)
    rejected = register(second, event, [entry], 'Second Team')
    assert rejected.status_code == 409, rejected.json
    if confirmation == 'code':
        with raw_state() as data:
            proof = data['organisationService']['playerEmailChallenges'][digest(entry['challengeId'])]
            assert not proof['used']


def test_concurrent_activation_registrations_cannot_claim_the_same_member(accounts, service_clock):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, publish=True, teamSize=1,
                         requirePlayerEmailVerification=True, playerEmailConfirmation='activation_link')

    def submit(captain):
        return register(captain, event, [dict(email='shared-member@example.invalid')], captain['name']).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(submit, (first, second)))
    assert sorted(statuses) == [201, 409]
    with raw_state() as data:
        assert len(data['organisationService']['registrations']) == 1
