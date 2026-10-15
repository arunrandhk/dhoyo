"""Organisation and booking regressions exercise real, isolated account sessions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from auth import COOKIE
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}
PASSWORD = 'synthetic-organisation-password-42'
BASE_URL = 'https://localhost'


def get(client, path, **kwargs):
    return client.get(path, base_url=BASE_URL, **kwargs)


def post(client, path, payload=None, **kwargs):
    return client.post(path, json={} if payload is None else payload,
                       headers=HEADERS, base_url=BASE_URL, **kwargs)


def patch(client, path, payload, **kwargs):
    return client.patch(path, json=payload, headers=HEADERS, base_url=BASE_URL, **kwargs)


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'organisations.sqlite3'))
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    counter = 0

    def create(kind='player', **overrides):
        nonlocal counter
        counter += 1
        client = app.test_client()
        payload = dict(name=f'Account {counter}', email=f'organisation-test-{counter}@example.invalid',
                       password=PASSWORD, sport='Football', city='Bengaluru',
                       state='Karnataka', country='India')
        if kind is not None:
            payload['accountType'] = kind
        if kind == 'organisation':
            payload['organisationName'] = f'Sport Club {counter}'
        payload.update(overrides)
        response = post(client, '/api/auth/register', payload)
        assert response.status_code == 201, response.get_data(as_text=True)
        return dict(client=client, email=payload['email'], payload=payload, **response.json)

    return create


@pytest.fixture
def service_clock(monkeypatch):
    import organisations
    clock = {'value': datetime(2035, 1, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr(organisations, 'now', lambda: clock['value'])
    return clock


def ground_payload(**overrides):
    return dict(name='Community football ground', sport='Football', city='Bengaluru',
                address='Synthetic Road 42', timezone='Asia/Kolkata', pricePerHour=800,
                opensAt='07:00', closesAt='22:00', **overrides)


def create_ground(owner, **overrides):
    payload = ground_payload()
    payload.update(overrides)
    response = post(owner['client'], '/api/grounds', payload)
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json['ground']


def slot_start(clock, hour=10, days=1, zone='Asia/Kolkata'):
    local_date = (clock['value'].astimezone(ZoneInfo(zone)) + timedelta(days=days)).date()
    return datetime.combine(local_date, datetime.min.time(), ZoneInfo(zone)).replace(hour=hour)


def event_payload(clock, ground=None, **overrides):
    starts = slot_start(clock)
    result = dict(name='Community Cup', sport='Football', eventType='physical' if ground else 'online',
                  startsAt=starts.isoformat(), timezone='Asia/Kolkata',
                  registrationClosesAt=(starts - timedelta(hours=1)).isoformat(),
                  capacity=2, durationHours=2)
    if ground:
        result['groundId'] = ground['id']
    result.update(overrides)
    return result


def create_event(owner, clock, ground=None, **overrides):
    response = post(owner['client'], '/api/tournaments', event_payload(clock, ground, **overrides))
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json['tournament']


def test_account_type_roundtrip_and_existing_player_default(accounts):
    player = accounts(None)
    owner = accounts('organisation', organisationName='South City Sports')
    assert player['accountType'] == 'player' and player['organisationId'] is None
    assert owner['accountType'] == 'organisation' and owner['organisationId']
    owner_id = owner['organisationId']
    identity = get(owner['client'], '/api/auth/me').json
    assert identity['userId'] == owner['userId']
    assert identity['accountType'] == 'organisation' and identity['organisationId'] == owner_id
    player_dashboard = get(player['client'], '/api/organisations/me')
    assert player_dashboard.status_code == 200
    assert player_dashboard.json['organisation'] is None
    assert player_dashboard.json['grounds'] == player_dashboard.json['tournaments'] == []
    assert get(owner['client'], '/api/organisations/me').status_code == 200
    assert get(owner['client'], '/api/arena').json['currentUserId'] == owner['userId']
    assert post(owner['client'], '/api/arena/awards', {'tier': 'Star'}).status_code == 403
    assert post(owner['client'], '/api/auth/logout').status_code == 200
    assert get(owner['client'], '/api/organisations/me').status_code == 401
    logged_in = post(owner['client'], '/api/auth/login', {'email': owner['email'].upper(), 'password': PASSWORD})
    assert logged_in.status_code == 200
    assert logged_in.json['accountType'] == 'organisation' and logged_in.json['organisationId'] == owner_id
    with raw_state() as data:
        assert PASSWORD not in str(data)
        assert data['accounts'][owner['email']]['password_hash'].startswith('scrypt:')


@pytest.mark.parametrize('change', [
    {'accountType': 'organizer'}, {'accountType': True},
    {'accountType': 'organisation', 'organisationName': ''},
    {'accountType': 'organisation', 'organisationName': 'x' * 101},
])
def test_registration_rejects_invalid_account_type_without_creating_identity(accounts, change):
    client = app.test_client()
    payload = dict(name='Synthetic owner', email='invalid-owner@example.invalid', password=PASSWORD,
                   sport='Football', city='Delhi', state='Delhi', country='India', **change)
    response = post(client, '/api/auth/register', payload)
    assert response.status_code == 400
    with raw_state() as data:
        assert 'invalid-owner@example.invalid' not in data.get('accounts', {})


def test_ground_role_authentication_csrf_and_forged_ownership(accounts, service_clock):
    owner, other, player = accounts('organisation'), accounts('organisation'), accounts()
    anonymous = app.test_client()
    assert get(anonymous, '/api/grounds').status_code == 401
    assert post(anonymous, '/api/grounds', ground_payload()).status_code == 401
    assert post(player['client'], '/api/grounds', ground_payload()).status_code == 403
    assert owner['client'].post('/api/grounds', json=ground_payload(), base_url=BASE_URL).status_code == 403
    assert owner['client'].post('/api/grounds', json=ground_payload(), base_url=BASE_URL,
                                headers={**HEADERS, 'Origin': 'https://attacker.example.invalid'}).status_code == 403
    forged = {**ground_payload(), 'ownerId': other['userId'], 'organisationId': other['organisationId']}
    assert post(owner['client'], '/api/grounds', forged).status_code == 400
    assert get(owner['client'], '/api/organisations/me').json['grounds'] == []
    ground = create_ground(owner)
    assert ground['organisationId'] == owner['organisationId']
    assert post(other['client'], '/api/tournaments', event_payload(service_clock, ground)).status_code == 403
    assert post(player['client'], '/api/tournaments', event_payload(service_clock)).status_code == 403


@pytest.mark.parametrize('change', [
    {'pricePerHour': True}, {'pricePerHour': -1}, {'sport': 'Unknown'},
    {'timezone': 'Not/AZone'}, {'opensAt': '07:30'}, {'closesAt': '07:00'},
    {'name': ' '}, {'address': ''},
])
def test_ground_validation(accounts, service_clock, change):
    owner = accounts('organisation')
    payload = ground_payload()
    payload.update(change)
    assert post(owner['client'], '/api/grounds', payload).status_code == 400


def test_bookings_persist_are_private_and_cancellation_releases_slot(accounts, service_clock):
    owner, player, other = accounts('organisation'), accounts(), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)
    url = f"/api/grounds/{ground['id']}/availability?date={starts.date().isoformat()}"
    availability = get(player['client'], url)
    assert availability.status_code == 200
    slot = next(slot for slot in availability.json['slots'] if datetime.fromisoformat(slot['startsAt']) == starts)
    assert slot['available'] and datetime.fromisoformat(slot['endsAt']) - starts == timedelta(hours=1)
    assert post(player['client'], '/api/bookings',
                {'groundId': ground['id'], 'startsAt': starts.isoformat(), 'userId': other['userId']}).status_code == 400
    booked = post(player['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': starts.isoformat()})
    assert booked.status_code == 201
    assert booked.json['booking']['playerId'] == player['userId']
    booking_id = booked.json['booking']['id']
    assert not next(slot for slot in get(other['client'], url).json['slots']
                    if datetime.fromisoformat(slot['startsAt']) == starts)['available']
    mine = get(player['client'], '/api/bookings').json['bookings']
    assert [booking['id'] for booking in mine] == [booking_id]
    assert get(other['client'], '/api/bookings').json['bookings'] == []
    assert booking_id not in get(other['client'], '/api/grounds').get_data(as_text=True)
    assert post(other['client'], f'/api/bookings/{booking_id}/cancel').status_code == 403
    assert post(owner['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': starts.isoformat()}).status_code == 403
    assert post(player['client'], f'/api/bookings/{booking_id}/cancel').status_code == 200
    assert post(player['client'], f'/api/bookings/{booking_id}/cancel').status_code == 409
    assert post(other['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': starts.isoformat()}).status_code == 201
    for public_path in ('/api/organisations', '/api/grounds', '/api/tournaments'):
        serialized = get(other['client'], public_path).get_data(as_text=True)
        assert all(actor['email'] not in serialized for actor in (owner, player, other))
        assert PASSWORD not in serialized and 'password_hash' not in serialized
    replay = app.test_client()
    replay.set_cookie(COOKIE, player['client'].get_cookie(COOKIE).value)
    assert any(booking['id'] == booking_id for booking in get(replay, '/api/bookings').json['bookings'])


def test_booking_validation_and_simultaneous_claims(accounts, service_clock):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)
    for invalid in (starts.replace(minute=30).isoformat(), starts.replace(hour=6).isoformat(),
                    starts.replace(hour=22).isoformat(), starts.replace(tzinfo=None).isoformat(),
                    service_clock['value'].isoformat(), 'not-a-date'):
        assert post(first['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': invalid}).status_code == 400
    assert get(first['client'], f"/api/grounds/{ground['id']}/availability?date=invalid").status_code == 400
    assert post(first['client'], '/api/bookings', {'groundId': 'missing', 'startsAt': starts.isoformat()}).status_code == 404

    def reserve(actor):
        return post(actor['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': starts.isoformat()}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, (first, second)))
    assert sorted(results) == [201, 409]
    assert sum(len(get(actor['client'], '/api/bookings').json['bookings']) for actor in (first, second)) == 1


def test_physical_tournament_publish_reserves_all_hours_and_conflicts_roll_back(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)
    booked = post(player['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': (starts + timedelta(hours=1)).isoformat()})
    assert booked.status_code == 201
    event = create_event(owner, service_clock, ground)
    assert event['status'] == 'draft'
    assert event['id'] not in get(player['client'], '/api/tournaments').get_data(as_text=True)
    assert post(owner['client'], f"/api/tournaments/{event['id']}/publish").status_code == 409
    # Failed publication must not reserve the first hour of the full interval.
    url = f"/api/grounds/{ground['id']}/availability?date={starts.date().isoformat()}"
    slots = get(player['client'], url).json['slots']
    assert next(slot for slot in slots if datetime.fromisoformat(slot['startsAt']) == starts)['available']
    assert post(player['client'], f"/api/bookings/{booked.json['booking']['id']}/cancel").status_code == 200
    published = post(owner['client'], f"/api/tournaments/{event['id']}/publish")
    assert published.status_code == 200 and published.json['tournament']['status'] == 'open'
    assert post(player['client'], f"/api/tournaments/{event['id']}/registrations", {'teamName': 'Cup Team'}).status_code == 201
    for hour in (0, 1):
        assert post(player['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': (starts + timedelta(hours=hour)).isoformat()}).status_code == 409
    assert post(owner['client'], f"/api/tournaments/{event['id']}/cancel").status_code == 200
    roster = get(owner['client'], f"/api/tournaments/{event['id']}/registrations").json['registrations']
    assert roster[0]['status'] == 'cancelled'
    assert post(player['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': starts.isoformat()}).status_code == 201


def test_create_and_publish_is_visible_to_player_accounts_and_persisted(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    response = post(owner['client'], '/api/tournaments', event_payload(service_clock, publish=True))
    assert response.status_code == 201
    event = response.json['tournament']
    assert event['status'] == 'open' and event['publishedAt'] == service_clock['value'].isoformat()
    visible = get(player['client'], '/api/tournaments').json['tournaments']
    assert [item['id'] for item in visible] == [event['id']]
    assert visible[0]['myRegistration'] is None
    with raw_state() as data:
        saved = next(item for item in data['organisationService']['tournaments'] if item['id'] == event['id'])
        assert saved['status'] == 'open' and saved['publishedAt'] == event['publishedAt']
        assert saved['createdAt'] == service_clock['value'].isoformat()
    assert post(player['client'], f"/api/tournaments/{event['id']}/registrations", {'teamName': 'Player Team'}).status_code == 201


@pytest.mark.parametrize('publish', [True, False])
def test_create_visibility_requires_organisation_role(accounts, service_clock, publish):
    player = accounts()
    assert post(player['client'], '/api/tournaments', event_payload(service_clock, publish=publish)).status_code == 403
    with raw_state() as data:
        assert data.get('organisationService', {}).get('tournaments', []) == []


@pytest.mark.parametrize('publish', ['true', 1, None, []])
def test_create_visibility_requires_boolean(accounts, service_clock, publish):
    owner = accounts('organisation')
    assert post(owner['client'], '/api/tournaments', event_payload(service_clock, publish=publish)).status_code == 400


def test_create_and_publish_venue_conflict_rolls_back_event_and_reservations(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)
    booked = post(player['client'], '/api/bookings', {
        'groundId': ground['id'], 'startsAt': (starts + timedelta(hours=1)).isoformat()
    }).json['booking']
    with raw_state() as data:
        before = deepcopy(data['organisationService'])
    response = post(owner['client'], '/api/tournaments', event_payload(service_clock, ground, publish=True))
    assert response.status_code == 409
    with raw_state() as data:
        assert data['organisationService'] == before
    assert get(owner['client'], '/api/organisations/me').json['tournaments'] == []
    assert get(player['client'], '/api/tournaments').json['tournaments'] == []
    assert post(player['client'], f"/api/bookings/{booked['id']}/cancel").status_code == 200
    published = post(owner['client'], '/api/tournaments', event_payload(service_clock, ground, publish=True))
    assert published.status_code == 201 and published.json['tournament']['status'] == 'open'
    slots = get(player['client'], f"/api/grounds/{ground['id']}/availability?date={starts.date()}").json['slots']
    for offset in (0, 1):
        assert not next(slot for slot in slots if datetime.fromisoformat(slot['startsAt']) == starts + timedelta(hours=offset))['available']


def test_tournament_registration_capacity_privacy_and_lifecycle(accounts, service_clock):
    owner, other_owner = accounts('organisation'), accounts('organisation')
    first, second, third = accounts(), accounts(), accounts()
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(first['client'], event_url + '/publish').status_code == 403
    assert post(other_owner['client'], event_url + '/publish').status_code == 403
    assert post(owner['client'], event_url + '/start').status_code == 409
    assert post(first['client'], event_url + '/registrations', {'teamName': 'First Team'}).status_code == 404
    assert post(owner['client'], event_url + '/publish').status_code == 200
    assert post(owner['client'], event_url + '/publish').status_code == 409
    assert post(owner['client'], event_url + '/registrations', {'teamName': 'Owner Team'}).status_code == 403
    assert post(first['client'], event_url + '/registrations',
                {'teamName': 'First Team', 'userId': third['userId']}).status_code == 400
    result = post(first['client'], event_url + '/registrations', {'teamName': 'First Team'})
    assert result.status_code == 201
    assert result.json['registration']['playerId'] == first['userId']
    assert post(first['client'], event_url + '/registrations', {'teamName': 'Different Team'}).status_code == 409
    assert post(second['client'], event_url + '/registrations', {'teamName': 'FIRST TEAM'}).status_code == 409
    assert get(first['client'], event_url + '/registrations').status_code == 403
    assert get(other_owner['client'], event_url + '/registrations').status_code == 403
    assert len(get(owner['client'], event_url + '/registrations').json['registrations']) == 1
    assert post(second['client'], event_url + '/registrations', {'teamName': 'Second Team'}).status_code == 201
    assert post(third['client'], event_url + '/registrations', {'teamName': 'Third Team'}).status_code == 409
    assert post(owner['client'], event_url + '/start').status_code == 409
    assert post(second['client'], event_url + '/registrations/me/cancel').status_code == 200
    assert post(third['client'], event_url + '/registrations', {'teamName': 'Third Team'}).status_code == 201
    service_clock['value'] = datetime.fromisoformat(event['startsAt'])
    assert post(second['client'], event_url + '/registrations', {'teamName': 'Late Team'}).status_code == 409
    assert post(first['client'], event_url + '/registrations/me/cancel').status_code == 409
    assert post(first['client'], event_url + '/start').status_code == 403
    started = post(owner['client'], event_url + '/start')
    assert started.status_code == 200 and started.json['tournament']['status'] == 'live'
    assert post(owner['client'], event_url + '/cancel').status_code == 409
    assert post(owner['client'], event_url + '/complete').json['tournament']['status'] == 'completed'
    assert post(owner['client'], event_url + '/complete').status_code == 409


def test_registration_edit_preserves_owned_place_and_persists_for_roster(accounts, service_clock):
    owner, first, second, other = accounts('organisation'), accounts(), accounts(), accounts()
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(owner['client'], event_url + '/publish').status_code == 200
    registered = post(first['client'], event_url + '/registrations', {'teamName': 'First Team'}).json['registration']
    assert post(second['client'], event_url + '/registrations', {'teamName': 'Second Team'}).status_code == 201
    edit_url = event_url + '/registrations/me'
    assert patch(app.test_client(), edit_url, {'teamName': 'Anonymous Team'}).status_code == 401
    assert patch(owner['client'], edit_url, {'teamName': 'Owner Team'}).status_code == 403
    assert patch(other['client'], edit_url, {'teamName': 'Other Team'}).status_code == 404
    assert first['client'].patch(edit_url, json={'teamName': 'Missing CSRF'}, base_url=BASE_URL).status_code == 403
    assert patch(first['client'], edit_url, {'teamName': 'Forged Team', 'playerId': second['userId']}).status_code == 400
    assert patch(first['client'], edit_url, {'teamName': '  SECOND TEAM  '}).status_code == 409
    changed = patch(first['client'], edit_url, {'teamName': '  Updated First Team  '})
    assert changed.status_code == 200
    assert changed.json['registration'] == {**registered, 'teamName': 'Updated First Team'}
    mine = get(first['client'], '/api/tournaments').json['tournaments'][0]
    assert mine['myRegistration']['teamName'] == 'Updated First Team'
    assert mine['registrationCount'] == 2 and mine['spotsLeft'] == 0
    others = get(other['client'], '/api/tournaments').json['tournaments'][0]
    assert others['myRegistration'] is None
    assert first['userId'] not in str(others) and 'Updated First Team' not in str(others)
    roster = get(owner['client'], event_url + '/registrations').json['registrations']
    assert [item['teamName'] for item in roster] == ['Updated First Team', 'Second Team']
    with raw_state() as data:
        saved = data['organisationService']['registrations']
        assert len(saved) == 2
        assert saved[0]['id'] == registered['id'] and saved[0]['playerId'] == first['userId']
        assert saved[0]['teamName'] == 'Updated First Team'


@pytest.mark.parametrize('team_name', ['', '   ', 'x' * 61, True, None])
def test_registration_edit_rejects_invalid_team_name(accounts, service_clock, team_name):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(owner['client'], event_url + '/publish').status_code == 200
    assert post(player['client'], event_url + '/registrations', {'teamName': 'Original Team'}).status_code == 201
    assert patch(player['client'], event_url + '/registrations/me', {'teamName': team_name}).status_code == 400
    assert get(player['client'], '/api/tournaments').json['tournaments'][0]['myRegistration']['teamName'] == 'Original Team'


def test_registration_edit_closes_at_deadline_and_rejects_withdrawn_registration(accounts, service_clock):
    owner, player, withdrawn = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(owner['client'], event_url + '/publish').status_code == 200
    for account, name in ((player, 'Original Team'), (withdrawn, 'Withdrawn Team')):
        assert post(account['client'], event_url + '/registrations', {'teamName': name}).status_code == 201
    assert post(withdrawn['client'], event_url + '/registrations/me/cancel').status_code == 200
    assert patch(withdrawn['client'], event_url + '/registrations/me', {'teamName': 'Come Back Team'}).status_code == 404
    service_clock['value'] = datetime.fromisoformat(event['registrationClosesAt'])
    result = patch(player['client'], event_url + '/registrations/me', {'teamName': 'Late Update'})
    assert result.status_code == 409
    assert get(player['client'], '/api/tournaments').json['tournaments'][0]['myRegistration']['teamName'] == 'Original Team'


def test_simultaneous_team_edits_cannot_claim_the_same_name(accounts, service_clock):
    owner, first, second = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(owner['client'], event_url + '/publish').status_code == 200
    for account, name in ((first, 'First Team'), (second, 'Second Team')):
        assert post(account['client'], event_url + '/registrations', {'teamName': name}).status_code == 201

    def rename(account):
        return patch(account['client'], event_url + '/registrations/me', {'teamName': 'Shared Team Name'}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rename, (first, second)))
    assert sorted(results) == [200, 409]
    roster = get(owner['client'], event_url + '/registrations').json['registrations']
    assert sum(item['teamName'] == 'Shared Team Name' for item in roster) == 1


@pytest.mark.parametrize('change', [
    {'capacity': True}, {'capacity': 1}, {'capacity': 129},
    {'durationHours': 0}, {'durationHours': 13}, {'durationHours': 1.5},
    {'eventType': 'unknown'}, {'timezone': 'Invalid/Timezone'},
    {'startsAt': '2035-01-02T10:00:00'}, {'registrationClosesAt': '2035-01-03T10:00:00+05:30'},
])
def test_tournament_validation(accounts, service_clock, change):
    owner = accounts('organisation')
    assert post(owner['client'], '/api/tournaments', event_payload(service_clock, **change)).status_code == 400


def test_lazy_service_migration_preserves_existing_account_and_social_state(accounts, service_clock):
    player = accounts(None)
    assert post(player['client'], '/api/social/posts', {'text': 'Keep this player highlight', 'sport': 'Football'}).status_code == 201
    with raw_state() as data:
        data.pop('organisationService', None)
        account = data['accounts'][player['email']]
        account.pop('account_type', None)
        account.pop('organisation_id', None)
        preserved = deepcopy({key: data[key] for key in ('posts', 'arena', 'accounts', 'userPreferences')})
    assert get(player['client'], '/api/grounds').status_code == 200
    identity = get(player['client'], '/api/auth/me').json
    assert identity['accountType'] == 'player' and identity['organisationId'] is None
    with raw_state() as data:
        assert 'organisationService' in data
        assert {key: data[key] for key in preserved} == preserved


def test_organisation_password_change_preserves_ownership_and_revokes_old_sessions(accounts, service_clock):
    owner = accounts('organisation')
    ground = create_ground(owner)
    old_session = owner['client'].get_cookie(COOKIE).value
    replay = app.test_client()
    replay.set_cookie(COOKIE, old_session)
    replacement = 'replacement-synthetic-password-42'
    changed = post(owner['client'], '/api/auth/change-password',
                   {'currentPassword': PASSWORD, 'password': replacement})
    assert changed.status_code == 200
    assert changed.json['accountType'] == 'organisation'
    assert changed.json['organisationId'] == owner['organisationId']
    assert get(replay, '/api/organisations/me').status_code == 401
    assert post(owner['client'], '/api/auth/logout').status_code == 200
    logged_in = post(owner['client'], '/api/auth/login', {'email': owner['email'], 'password': replacement})
    assert logged_in.status_code == 200 and logged_in.json['organisationId'] == owner['organisationId']
    assert get(owner['client'], '/api/organisations/me').json['grounds'][0]['id'] == ground['id']


@pytest.mark.parametrize('day,expected_count', [('2026-03-08', 3), ('2026-11-01', 5)])
def test_availability_handles_dst_gaps_and_repeated_hours_without_duplicate_instants(
        accounts, service_clock, day, expected_count):
    service_clock['value'] = datetime.fromisoformat(day + 'T00:00:00+00:00') - timedelta(days=1)
    owner, first, second = accounts('organisation'), accounts(), accounts()
    ground = create_ground(owner, timezone='America/New_York', opensAt='00:00', closesAt='04:00')
    availability = get(first['client'], f"/api/grounds/{ground['id']}/availability?date={day}")
    assert availability.status_code == 200
    slots = availability.json['slots']
    assert len(slots) == expected_count
    starts = [datetime.fromisoformat(slot['startsAt']) for slot in slots]
    assert starts == sorted(set(starts))
    assert all(datetime.fromisoformat(slot['endsAt']) - datetime.fromisoformat(slot['startsAt']) == timedelta(hours=1)
               for slot in slots)
    local_hours = [start.astimezone(ZoneInfo('America/New_York')).hour for start in starts]
    if expected_count == 3:
        assert local_hours == [0, 1, 3]
    else:
        assert local_hours == [0, 1, 1, 2, 3]
        repeated = [start for start in starts if start.astimezone(ZoneInfo('America/New_York')).hour == 1]
        for actor, start in zip((first, second), repeated):
            assert post(actor['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': start.isoformat()}).status_code == 201


def test_past_booking_is_unavailable_and_cannot_be_cancelled(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)
    booked = post(player['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': starts.isoformat()})
    assert booked.status_code == 201
    service_clock['value'] = starts
    assert post(player['client'], f"/api/bookings/{booked.json['booking']['id']}/cancel").status_code == 409
    availability = get(player['client'], f"/api/grounds/{ground['id']}/availability?date={starts.date().isoformat()}")
    assert not next(slot for slot in availability.json['slots']
                    if datetime.fromisoformat(slot['startsAt']) == starts)['available']
    assert post(player['client'], '/api/bookings', {'groundId': ground['id'], 'startsAt': starts.isoformat()}).status_code == 400


def test_cancelled_unpublished_draft_stays_private(accounts, service_clock):
    owner, player, other_owner = accounts('organisation'), accounts(), accounts('organisation')
    event = create_event(owner, service_clock)
    assert post(owner['client'], f"/api/tournaments/{event['id']}/cancel").status_code == 200
    assert event['id'] in get(owner['client'], '/api/tournaments').get_data(as_text=True)
    for visitor in (player, other_owner):
        assert event['id'] not in get(visitor['client'], '/api/tournaments').get_data(as_text=True)
    assert post(player['client'], f"/api/tournaments/{event['id']}/registrations", {'teamName': 'Unknown event team'}).status_code == 404


def test_tournament_deadline_minimum_participants_and_missed_start_window(accounts, service_clock):
    owner, player, late_player = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(owner['client'], event_url + '/publish').status_code == 200
    assert post(player['client'], event_url + '/registrations', {'teamName': 'One Team'}).status_code == 201
    service_clock['value'] = datetime.fromisoformat(event['registrationClosesAt'])
    assert post(late_player['client'], event_url + '/registrations', {'teamName': 'After deadline'}).status_code == 409
    service_clock['value'] = datetime.fromisoformat(event['startsAt'])
    assert post(owner['client'], event_url + '/start').status_code == 409
    service_clock['value'] = datetime.fromisoformat(event['endsAt'])
    assert post(owner['client'], event_url + '/start').status_code == 409


def test_simultaneous_registrations_cannot_overfill_last_place(accounts, service_clock):
    owner, first, second, third = accounts('organisation'), accounts(), accounts(), accounts()
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(owner['client'], event_url + '/publish').status_code == 200
    assert post(first['client'], event_url + '/registrations', {'teamName': 'First Team'}).status_code == 201

    def register(actor):
        return post(actor['client'], event_url + '/registrations', {'teamName': actor['name']}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, (second, third)))
    assert sorted(results) == [201, 409]
    assert len(get(owner['client'], event_url + '/registrations').json['registrations']) == 2


@pytest.mark.parametrize('path', ['/api/grounds', '/api/bookings', '/api/tournaments'])
def test_array_payload_is_a_validation_error_instead_of_server_error(accounts, service_clock, path):
    owner = accounts('organisation')
    assert post(owner['client'], path, []).status_code == 400


def test_management_updates_require_owner_sessions_and_csrf(accounts, service_clock):
    owner, other_owner, player = accounts('organisation'), accounts('organisation'), accounts()
    ground = create_ground(owner)
    tournament = create_event(owner, service_clock, ground)
    changes = (('/api/organisations/me', {'description': 'Club profile'}),
               (f"/api/grounds/{ground['id']}", {'name': 'New ground name'}),
               (f"/api/tournaments/{tournament['id']}", {'name': 'New event name'}))
    anonymous = app.test_client()
    for path, value in changes:
        assert patch(anonymous, path, value).status_code == 401
        assert patch(player['client'], path, value).status_code == 403
        assert owner['client'].patch(path, json=value, base_url=BASE_URL).status_code == 403
        assert owner['client'].patch(path, json=value, base_url=BASE_URL,
                                     headers={**HEADERS, 'Origin': 'https://attacker.example.invalid'}).status_code == 403
        for invalid in ({}, [], {'ownerId': other_owner['userId']}, {'id': 'replace-id'}):
            assert patch(owner['client'], path, invalid).status_code == 400
    for path, value in changes[1:]:
        assert patch(other_owner['client'], path, value).status_code == 403
    assert patch(owner['client'], '/api/grounds/missing', {'name': 'Absent ground'}).status_code == 404
    assert patch(owner['client'], '/api/tournaments/missing', {'name': 'Absent event'}).status_code == 404


def test_organisation_partial_update_refreshes_owned_names_only(accounts, service_clock):
    owner, other, player = accounts('organisation'), accounts('organisation'), accounts()
    ground, other_ground = create_ground(owner), create_ground(other)
    event = create_event(owner, service_clock, ground)
    other_event = create_event(other, service_clock)
    assert post(owner['client'], f"/api/tournaments/{event['id']}/publish").status_code == 200
    player_booking = post(player['client'], '/api/bookings',
                          {'groundId': ground['id'], 'startsAt': slot_start(service_clock, hour=14).isoformat()}).json['booking']
    before = get(owner['client'], '/api/organisations/me').json['organisation']
    updated = patch(owner['client'], '/api/organisations/me',
                    {'name': '  South City Sports  ', 'description': '  Open to every team.  '})
    assert updated.status_code == 200
    organisation = updated.json['organisation']
    assert organisation == {**before, 'name': 'South City Sports', 'description': 'Open to every team.'}
    dashboard = get(owner['client'], '/api/organisations/me').json
    assert dashboard['grounds'][0]['organisationName'] == 'South City Sports'
    assert dashboard['tournaments'][0]['organisationName'] == 'South City Sports'
    tournament_booking = next(booking for booking in dashboard['bookings'] if booking['purpose'] == 'tournament')
    assert tournament_booking['playerName'] == 'South City Sports'
    assert get(player['client'], '/api/bookings').json['bookings'] == [player_booking]
    other_dashboard = get(other['client'], '/api/organisations/me').json
    assert other_dashboard['grounds'][0] == other_ground
    assert other_dashboard['tournaments'][0] == other_event
    assert patch(owner['client'], '/api/organisations/me', {'description': ''}).json['organisation']['description'] == ''


@pytest.mark.parametrize('change', [
    {'name': ''}, {'name': 'x' * 101}, {'city': 'x' * 81}, {'state': ''},
    {'country': None}, {'sport': 'Unknown'}, {'description': 'x' * 1001}, {'description': False},
])
def test_organisation_validation_rolls_back_the_entire_patch(accounts, service_clock, change):
    owner = accounts('organisation')
    ground = create_ground(owner)
    create_event(owner, service_clock, ground)
    with raw_state() as data:
        before = deepcopy(data['organisationService'])
    response = patch(owner['client'], '/api/organisations/me', {'name': 'Changed club', **change})
    assert response.status_code == 400
    with raw_state() as data:
        assert data['organisationService'] == before


def test_ground_partial_update_keeps_existing_booking_snapshots(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    event = create_event(owner, service_clock, ground)
    starts = slot_start(service_clock, hour=14)
    booking = post(player['client'], '/api/bookings',
                   {'groundId': ground['id'], 'startsAt': starts.isoformat()}).json['booking']
    changed = patch(owner['client'], f"/api/grounds/{ground['id']}",
                    {'name': '  South City Field  ', 'pricePerHour': 1200, 'address': 'New venue address'})
    assert changed.status_code == 200
    assert changed.json['ground']['quoteToken'] != ground['quoteToken']
    assert changed.json['ground'] == {**ground, 'name': 'South City Field', 'pricePerHour': 1200,
                                     'address': 'New venue address',
                                     'quoteToken': changed.json['ground']['quoteToken']}
    assert get(player['client'], '/api/bookings').json['bookings'] == [booking]
    dashboard = get(owner['client'], '/api/organisations/me').json
    assert dashboard['tournaments'][0]['groundName'] == 'South City Field'
    assert dashboard['tournaments'][0]['id'] == event['id']
    later = post(player['client'], '/api/bookings',
                 {'groundId': ground['id'], 'startsAt': (starts + timedelta(hours=1)).isoformat()})
    assert later.status_code == 201
    assert later.json['booking']['groundName'] == 'South City Field'
    assert later.json['booking']['price'] == 1200


@pytest.mark.parametrize('change', [
    {'opensAt': '11:00'}, {'closesAt': '10:00'}, {'timezone': 'UTC'}, {'sport': 'Tennis'},
])
def test_ground_updates_cannot_invalidate_future_confirmed_reservations(accounts, service_clock, change):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)
    assert post(player['client'], '/api/bookings',
                {'groundId': ground['id'], 'startsAt': starts.isoformat()}).status_code == 201
    with raw_state() as data:
        before = deepcopy(data['organisationService'])
    response = patch(owner['client'], f"/api/grounds/{ground['id']}", {'name': 'Must not be saved', **change})
    assert response.status_code == 409
    with raw_state() as data:
        assert data['organisationService'] == before


def test_simultaneous_ground_update_and_booking_keep_the_reservation_valid(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)

    def update_hours():
        return patch(owner['client'], f"/api/grounds/{ground['id']}", {'opensAt': '11:00'}).status_code

    def reserve_slot():
        return post(player['client'], '/api/bookings',
                    {'groundId': ground['id'], 'startsAt': starts.isoformat()}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        updating = pool.submit(update_hours)
        reserving = pool.submit(reserve_slot)
        results = updating.result(), reserving.result()
    assert results in ((200, 400), (409, 201))
    dashboard = get(owner['client'], '/api/organisations/me').json
    if dashboard['bookings']:
        assert dashboard['grounds'][0]['opensAt'] == '07:00'
    else:
        assert dashboard['grounds'][0]['opensAt'] == '11:00'


def test_ground_updates_preserve_upcoming_draft_and_published_events(accounts, service_clock):
    owner = accounts('organisation')
    ground = create_ground(owner)
    event = create_event(owner, service_clock, ground)
    ground_url = f"/api/grounds/{ground['id']}"
    for change in ({'sport': 'Tennis'}, {'closesAt': '11:00'}, {'timezone': 'UTC'}):
        assert patch(owner['client'], ground_url, change).status_code == 409
    # Widening opening hours leaves the event's absolute interval valid.
    assert patch(owner['client'], ground_url, {'opensAt': '06:00', 'closesAt': '24:00'}).status_code == 200
    assert post(owner['client'], f"/api/tournaments/{event['id']}/publish").status_code == 200
    assert patch(owner['client'], ground_url, {'opensAt': '11:00'}).status_code == 409
    assert post(owner['client'], f"/api/tournaments/{event['id']}/cancel").status_code == 200
    # A cancelled event and its released reservation no longer block maintenance.
    assert patch(owner['client'], ground_url, {'sport': 'Tennis', 'opensAt': '11:00'}).status_code == 200


def test_ground_patch_revalidates_merged_fields_and_timezone_slots(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner, timezone='UTC', opensAt='07:00', closesAt='22:00')
    ground_url = f"/api/grounds/{ground['id']}"
    for change in ({'pricePerHour': True}, {'pricePerHour': -1}, {'name': ' '},
                   {'address': ''}, {'timezone': 'Not/AZone'}, {'opensAt': '23:00'}, {'closesAt': '06:00'}):
        assert patch(owner['client'], ground_url, change).status_code == 400
        assert get(owner['client'], '/api/organisations/me').json['grounds'][0] == ground
    starts = slot_start(service_clock, hour=10, zone='UTC')
    booking = post(player['client'], '/api/bookings',
                   {'groundId': ground['id'], 'startsAt': starts.isoformat()}).json['booking']
    # UTC 10:00 remains an offered 11:00 slot in the new timezone.
    changed = patch(owner['client'], ground_url, {'timezone': 'Europe/Berlin'})
    assert changed.status_code == 200
    assert get(player['client'], '/api/bookings').json['bookings'] == [booking]


def test_draft_tournament_partial_updates_and_event_type_conversion(accounts, service_clock):
    owner, other = accounts('organisation'), accounts('organisation')
    ground, foreign_ground = create_ground(owner), create_ground(other)
    event = create_event(owner, service_clock, ground)
    event_url = f"/api/tournaments/{event['id']}"
    renamed = patch(owner['client'], event_url, {'name': '  Revised Community Cup  ', 'capacity': 8})
    assert renamed.status_code == 200
    assert renamed.json['tournament'] == {**event, 'name': 'Revised Community Cup', 'capacity': 8, 'spotsLeft': 8}
    shortened = patch(owner['client'], event_url, {'durationHours': 1})
    assert shortened.status_code == 200
    assert datetime.fromisoformat(shortened.json['tournament']['endsAt']) == datetime.fromisoformat(event['startsAt']) + timedelta(hours=1)
    online = patch(owner['client'], event_url, {'eventType': 'online', 'sport': 'Esports'})
    assert online.status_code == 200
    assert online.json['tournament']['groundId'] is None and online.json['tournament']['groundName'] is None
    assert patch(owner['client'], event_url, {'groundId': None}).status_code == 200
    assert patch(owner['client'], event_url, {'groundId': ground['id']}).status_code == 400
    assert patch(owner['client'], event_url,
                 {'eventType': 'physical', 'sport': 'Football', 'groundId': foreign_ground['id']}).status_code == 403
    assert patch(owner['client'], event_url,
                 {'eventType': 'physical', 'sport': 'Football', 'groundId': 'missing'}).status_code == 404
    assert patch(owner['client'], event_url,
                 {'eventType': 'physical', 'sport': 'Esports', 'groundId': ground['id']}).status_code == 400
    physical = patch(owner['client'], event_url,
                     {'eventType': 'physical', 'sport': 'Football', 'groundId': ground['id']})
    assert physical.status_code == 200 and physical.json['tournament']['groundId'] == ground['id']


def test_tournament_setup_edits_are_draft_only_and_failed_validation_is_atomic(accounts, service_clock):
    owner = accounts('organisation')
    ground = create_ground(owner)
    event = create_event(owner, service_clock, ground)
    event_url = f"/api/tournaments/{event['id']}"
    with raw_state() as data:
        before = deepcopy(data['organisationService'])
    for change in ({'capacity': True}, {'durationHours': 13}, {'timezone': 'Invalid/Zone'},
                   {'registrationClosesAt': service_clock['value'].isoformat()},
                   {'startsAt': slot_start(service_clock, hour=21).isoformat()}, {'groundId': None}):
        assert patch(owner['client'], event_url, {'name': 'Must not be saved', **change}).status_code == 400
        with raw_state() as data:
            assert data['organisationService'] == before
    assert post(owner['client'], event_url + '/publish').status_code == 200
    assert patch(owner['client'], event_url, {'capacity': 8}).status_code == 409
    assert post(owner['client'], event_url + '/cancel').status_code == 200
    assert patch(owner['client'], event_url, {'name': 'Cancelled edit'}).status_code == 409


def test_expired_draft_can_be_rescheduled_after_ground_maintenance(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    event = create_event(owner, service_clock, ground)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(player['client'], '/api/bookings',
                {'groundId': ground['id'], 'startsAt': slot_start(service_clock, hour=14).isoformat()}).status_code == 201
    service_clock['value'] = datetime.fromisoformat(event['endsAt']) + timedelta(days=1)
    assert patch(owner['client'], f"/api/grounds/{ground['id']}",
                 {'sport': 'Tennis', 'opensAt': '12:00', 'closesAt': '20:00'}).status_code == 200
    assert post(owner['client'], event_url + '/publish').status_code == 409
    assert patch(owner['client'], event_url, {'name': 'Still expired'}).status_code == 400
    starts = slot_start(service_clock, hour=15)
    rescheduled = patch(owner['client'], event_url,
                        {'sport': 'Tennis', 'startsAt': starts.isoformat(),
                         'registrationClosesAt': (starts - timedelta(hours=1)).isoformat()})
    assert rescheduled.status_code == 200
    assert rescheduled.json['tournament']['status'] == 'draft'
    assert post(owner['client'], event_url + '/publish').status_code == 200
