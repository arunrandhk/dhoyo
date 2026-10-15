"""Recipient acknowledgements remain private and tied to the saved roster."""
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from test_organisations import accounts, service_clock, create_event, post, patch, get
from app import app
from social import raw_state
import password_reset


@pytest.fixture
def activation_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(password_reset, 'mail_settings', lambda **kwargs:
                        dict(base_url='https://localhost/sportspace', sender='test@example.invalid', provider='smtp'))
    def deliver(settings, email, link):
        with raw_state() as data:
            assert data['organisationService']['playerActivationLinks']
        sent.append((email, link, settings))
        return True, True
    monkeypatch.setattr(password_reset, 'deliver_password_reset', deliver)
    return sent


def setup_team(accounts, clock):
    owner, captain = accounts('organisation'), accounts()
    event = create_event(owner, clock, publish=True, teamSize=1,
                         requirePlayerEmailVerification=True, playerEmailConfirmation='activation_link')
    response = post(captain['client'], f"/api/tournaments/{event['id']}/registrations",
                    dict(teamName='Invited team', playerEmails=[dict(email='player@example.invalid')]))
    assert response.status_code == 201, response.json
    assert response.json['registration']['playerEmails'][0]['acknowledgementStatus'] == 'pending'
    assert 'rosterId' not in response.json['registration']['playerEmails'][0]
    return owner, captain, event


def send(captain, event):
    return post(captain['client'], f"/api/tournaments/{event['id']}/player-emails/send-activation",
                dict(email='player@example.invalid'))


def test_acknowledgement_is_public_explicit_private_and_idempotent(accounts, service_clock, activation_mail):
    owner, captain, event = setup_team(accounts, service_clock)
    assert send(captain, event).status_code == 200
    token = urlsplit(activation_mail[-1][1]).fragment
    assert token and urlsplit(activation_mail[-1][1]).path == '/tournament-acknowledgement'
    anonymous = app.test_client()
    assert get(anonymous, '/tournament-acknowledgement').status_code == 200
    with raw_state() as data:
        assert token not in str(data['organisationService'])
        assert data['organisationService']['registrations'][-1]['playerEmails'][0]['acknowledgementStatus'] == 'pending'
    for _ in range(2):
        response = post(anonymous, '/api/auth/tournament-acknowledgement', dict(token=token))
        assert response.status_code == 200, response.json
        assert response.json['acknowledgementStatus'] == 'acknowledged'
    with raw_state() as data:
        player = data['organisationService']['registrations'][-1]['playerEmails'][0]
        assert player['verified'] and player['acknowledgedAt']
    assert send(captain, event).json['acknowledgementStatus'] == 'acknowledged'
    assert len(activation_mail) == 1


def test_changed_email_invalidates_link(accounts, service_clock, activation_mail):
    owner, captain, event = setup_team(accounts, service_clock)
    assert send(captain, event).status_code == 200
    token = urlsplit(activation_mail[-1][1]).fragment
    response = patch(captain['client'], f"/api/tournaments/{event['id']}/registrations/me",
                     dict(teamName='Invited team', playerEmails=[dict(email='replacement@example.invalid')]))
    assert response.status_code == 200, response.json
    assert post(app.test_client(), '/api/auth/tournament-acknowledgement', dict(token=token)).status_code == 400
    assert response.json['registration']['playerEmails'][0]['acknowledgementStatus'] == 'pending'


def test_expiry_cooldown_and_other_captain(accounts, service_clock, activation_mail):
    owner, captain, event = setup_team(accounts, service_clock)
    assert send(accounts(), event).status_code == 409
    assert send(captain, event).status_code == 200
    assert send(captain, event).status_code == 429
    token = urlsplit(activation_mail[-1][1]).fragment
    service_clock['value'] += timedelta(hours=25)
    assert post(app.test_client(), '/api/auth/tournament-acknowledgement', dict(token=token)).status_code == 400


def test_activation_mail_content():
    settings = dict(purpose='tournament_activation', tournament_name='Cup', team_name='Team')
    text = password_reset.email_text(settings, 'https://example.invalid/tournament-acknowledgement#opaque')
    assert '24 hours' in text and 'Acknowledge participation' in text and 'Cup' in text and 'Team' in text


def test_cancelled_team_cannot_acknowledge(accounts, service_clock, activation_mail):
    owner, captain, event = setup_team(accounts, service_clock)
    assert send(captain, event).status_code == 200
    token = urlsplit(activation_mail[-1][1]).fragment
    response = post(captain['client'], f"/api/tournaments/{event['id']}/registrations/me/cancel")
    assert response.status_code == 200, response.json
    assert post(app.test_client(), '/api/auth/tournament-acknowledgement', dict(token=token)).status_code == 400


def test_failed_email_does_not_claim_sent_or_acknowledged(accounts, service_clock, activation_mail, monkeypatch):
    owner, captain, event = setup_team(accounts, service_clock)
    monkeypatch.setattr(password_reset, 'deliver_password_reset', lambda *args: (True, False))
    assert send(captain, event).status_code == 503
    with raw_state() as data:
        player = data['organisationService']['registrations'][-1]['playerEmails'][0]
        assert player['acknowledgementStatus'] == 'pending'
        assert 'activationSentAt' not in player
        assert not data['organisationService']['playerActivationLinks']
