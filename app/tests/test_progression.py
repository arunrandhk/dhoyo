"""Milestones are sourced from real tournament teams and respect account privacy."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from test_organisations import accounts, service_clock, create_event, post, get
from app import app
from social import raw_state
import progression


@pytest.fixture
def progress_clock(monkeypatch, service_clock):
    monkeypatch.setattr(progression, 'now', lambda: service_clock['value'])
    return service_clock


def register(player, event, name='Team One'):
    result = post(player['client'], f"/api/tournaments/{event['id']}/registrations", dict(teamName=name))
    assert result.status_code == 201, result.json
    return result.json['registration']


def read(player, suffix='me'):
    response = get(player['client'], '/api/progression/' + suffix)
    assert response.status_code == 200, response.json
    return response.json


def complete(owner, event, clock):
    clock['value'] = datetime.fromisoformat(event['startsAt'])
    for action in ('start', 'complete'):
        response = post(owner['client'], f"/api/tournaments/{event['id']}/{action}")
        assert response.status_code == 200, response.json


def add_roster(event, registration, entries):
    with raw_state() as data:
        source = next(item for item in data['organisationService']['registrations']
                      if item['id'] == registration['id'])
        source['playerEmails'] = entries
        progression.sync_progress(data)


def test_live_lifecycle_earns_once_and_cannot_claim_custom_stats(accounts, progress_clock):
    owner, captain, other = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, progress_clock, publish=True)
    register(captain, event)
    before = read(captain)
    assert before['stats'] == dict(registeredTournaments=1, completedTournaments=0, sportsCompleted=0)
    assert [badge['id'] for badge in before['achievements'] if badge['unlocked']] == ['first-team']
    register(other, event, 'Team Two')
    complete(owner, event, progress_clock)
    after = read(captain)
    assert after['stats']['completedTournaments'] == 1
    assert [badge['id'] for badge in after['achievements'] if badge['unlocked']] == ['first-team', 'first-tournament']
    with raw_state() as data:
        first_journal = deepcopy(data['playerProgress'])
    assert read(captain) == after
    with raw_state() as data:
        assert data['playerProgress'] == first_journal
    assert post(captain['client'], '/api/progression/me', dict(completedTournaments=999)).status_code == 405
    assert get(captain['client'], '/api/progression/me?playerId=' + other['userId']).status_code == 400


def test_verified_email_members_and_captain_deduplicate_but_pending_invites_do_not_earn(accounts, progress_clock):
    owner, captain, member, pending = accounts('organisation'), accounts(), accounts(), accounts()
    event = create_event(owner, progress_clock, publish=True)
    registration = register(captain, event)
    add_roster(event, registration, [dict(email=' ' + member['email'].upper() + ' ', verified=True),
                                   dict(email=captain['email'], verified=True),
                                   dict(email=pending['email'], verified=False, acknowledgementStatus='pending')])
    assert read(captain)['stats']['registeredTournaments'] == 1
    assert read(member)['stats']['registeredTournaments'] == 1
    assert read(pending)['stats']['registeredTournaments'] == 0
    board = read(member, 'leaderboard?season=2035-Q1')
    assert {row['playerId'] for row in board['players']} == {captain['userId'], member['userId']}
    assert all(row['rank'] == 1 for row in board['players'])


def test_late_account_matching_and_acknowledgement_are_reconciled(accounts, progress_clock):
    owner, captain = accounts('organisation'), accounts()
    event = create_event(owner, progress_clock, publish=True)
    registration = register(captain, event)
    late_email = 'joined-later@example.invalid'
    add_roster(event, registration, [dict(email=late_email, verified=False, acknowledgementStatus='pending')])
    member = accounts(email=late_email)
    assert read(member)['stats']['registeredTournaments'] == 0
    add_roster(event, registration, [dict(email=late_email, verified=True, acknowledgementStatus='acknowledged')])
    assert read(member)['stats']['registeredTournaments'] == 1


def test_withdrawal_cancel_and_roster_removal_do_not_count(accounts, progress_clock):
    owner, captain, member = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, progress_clock, publish=True)
    registration = register(captain, event)
    add_roster(event, registration, [dict(email=member['email'], verified=True)])
    assert read(member)['stats']['registeredTournaments'] == 1
    add_roster(event, registration, [])
    assert read(member)['stats']['registeredTournaments'] == 0
    response = post(captain['client'], f"/api/tournaments/{event['id']}/registrations/me/cancel")
    assert response.status_code == 200
    assert read(captain)['stats']['registeredTournaments'] == 0
    assert not any(badge['unlocked'] for badge in read(captain)['achievements'])
    register(captain, event, 'Another Team')
    assert read(captain)['stats']['registeredTournaments'] == 1
    assert post(owner['client'], f"/api/tournaments/{event['id']}/cancel").status_code == 200
    assert read(captain)['stats']['registeredTournaments'] == 0
    assert read(captain, 'leaderboard?season=2035-Q1')['players'] == []


def test_frozen_account_binding_and_completion_survive_name_email_changes(accounts, progress_clock):
    owner, captain, member, other = accounts('organisation'), accounts(), accounts(), accounts()
    event = create_event(owner, progress_clock, publish=True)
    registration = register(captain, event)
    add_roster(event, registration, [dict(email=member['email'], verified=True)])
    with raw_state() as data:
        stored = data['accounts'].pop(member['email'])
        data['accounts']['changed-address@example.invalid'] = stored
        next(player for player in data['arena']['players'] if player['id'] == member['userId'])['name'] = 'New Name'
    assert read(member)['stats']['registeredTournaments'] == 1
    register(other, event, 'Other Team')
    complete(owner, event, progress_clock)
    before = read(member)
    with raw_state() as data:
        # Even if a future data migration removes a historical roster, completion
        # credits already recorded for the stable account ID remain earned.
        source = next(item for item in data['organisationService']['registrations'] if item['id'] == registration['id'])
        source['playerEmails'] = []
        next(player for player in data['arena']['players'] if player['id'] == member['userId'])['name'] = 'Newest Name'
    assert read(member)['stats']['completedTournaments'] == 1
    assert read(member)['achievements'] == before['achievements']


def test_quarter_uses_tournament_start_in_utc_and_sport_filter(accounts, progress_clock):
    owner, captain = accounts('organisation'), accounts()
    # 1 April locally is still 31 March in UTC.
    progress_clock['value'] = datetime(2035, 3, 30, tzinfo=timezone.utc)
    event = create_event(owner, progress_clock, publish=True,
                         startsAt='2035-04-01T00:30:00+05:30',
                         registrationClosesAt='2035-03-31T22:00:00+05:30')
    register(captain, event)
    q1 = read(captain, 'leaderboard?season=2035-Q1&sport=Football')
    assert q1['season']['timezone'] == 'UTC'
    assert q1['season']['endsAt'] == '2035-04-01T00:00:00+00:00'
    assert [row['playerId'] for row in q1['players']] == [captain['userId']]
    assert read(captain, 'leaderboard?season=2035-Q2')['players'] == []
    assert read(captain, 'leaderboard?season=2035-Q1&sport=Cricket')['players'] == []


@pytest.mark.parametrize('query', ['season=2035-Q0', 'season=2035-Q5', 'season=2035',
                                  'season=9999-Q4', 'season=2035-Q1&season=2035-Q2',
                                  'sport=Hacking', 'playerId=someone'])
def test_invalid_leaderboard_filters_are_rejected(accounts, progress_clock, query):
    player = accounts()
    assert get(player['client'], '/api/progression/leaderboard?' + query).status_code == 400


def test_board_excludes_demo_and_organisations_and_preserves_photo_privacy(accounts, progress_clock):
    owner, captain, viewer, inactive = accounts('organisation'), accounts(), accounts(), accounts()
    event = create_event(owner, progress_clock, publish=True)
    register(captain, event)
    avatar = 'https://example.invalid/private-player-photo.png'
    with raw_state() as data:
        player = next(player for player in data['arena']['players'] if player['id'] == captain['userId'])
        player.update(avatar=avatar, photoPrivacy='friends', wins=999999, gamesPlayed=999999)
        # Legacy arena awards have no effect on this separate participation board.
        data['arena'].setdefault('awards', []).append(dict(playerId=viewer['userId'], type='winner'))
        service = data['organisationService']
        source = service['registrations'][0]
        source['playerEmails'] = [dict(email=inactive['email'], verified=True)]
        data['accounts'][inactive['email']]['email_verified'] = False
        for fake in ('demo-user', owner['userId']):
            service['registrations'].append({**deepcopy(source), 'id':'fake-' + fake, 'playerId':fake})
    result = read(viewer, 'leaderboard?season=2035-Q1')
    assert [row['playerId'] for row in result['players']] == [captain['userId']]
    assert result['players'][0]['avatar'] == ''
    assert avatar not in str(result)
    assert 'email' not in str(result).lower()
    assert result['players'][0]['completedTournaments'] == 0
    assert read(captain, 'leaderboard?season=2035-Q1')['players'][0]['avatar'] == avatar
    assert read(owner, 'leaderboard?season=2035-Q1')['players'][0]['avatar'] == ''
    assert get(owner['client'], '/api/progression/me').status_code == 403
    assert get(app.test_client(), '/api/progression/me').status_code == 401
    assert get(app.test_client(), '/api/progression/leaderboard').status_code == 401


def test_milestone_targets_and_rank_ties_use_verified_completions(accounts, progress_clock):
    owner, captain, other = accounts('organisation'), accounts(), accounts()
    for index in range(5):
        event = create_event(owner, progress_clock, publish=True,
                             sport='Cricket' if index == 4 else 'Football')
        register(captain, event)
        register(other, event, 'Other Team')
        complete(owner, event, progress_clock)
        progress_clock['value'] += timedelta(days=1)
    result = read(captain)
    assert result['stats'] == dict(registeredTournaments=5, completedTournaments=5, sportsCompleted=2)
    assert all(badge['unlocked'] and badge['earnedAt'] for badge in result['achievements'])
    rows = read(captain, 'leaderboard?season=2035-Q1')['players']
    assert len(rows) == 2
    assert [row['rank'] for row in rows] == [1, 1]
    assert all(row['completedTournaments'] == 5 for row in rows)


@pytest.mark.parametrize('value', ['javascript:alert(1)', 'https://user:secret@example.invalid/photo.png',
                                  'data:image/svg+xml;base64,PHN2Zz4=', '//example.invalid/photo.png'])
def test_active_or_credentialed_avatar_sources_are_rejected(value):
    assert progression.safe_avatar(value) == ''
