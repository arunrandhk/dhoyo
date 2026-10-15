"""Tournament configuration and private application details survive real SQL writes."""
from copy import deepcopy
from datetime import datetime
import json
import os
import sqlite3

from test_organisations import (accounts, service_clock, create_event, create_ground,
                                event_payload, get, patch, post)
from app import app
from organisations import tournament_option_defaults
from social import raw_state


def database_service():
    """Read committed state independently of the application's context manager."""
    with sqlite3.connect(os.environ['SPORTSPACE_SOCIAL_DB']) as connection:
        payload = connection.execute('SELECT payload FROM demo_state WHERE id = 1').fetchone()[0]
    return json.loads(payload)['organisationService']


def options():
    return dict(description='A neighbourhood cup for new and experienced teams.',
                format='groups_knockout', formatDetails='Two pools followed by semi-finals.',
                teamSize=7, entryFee=250, prize='Winner: trophy and sports equipment',
                eligibility='Players aged 18 or older', rules='No metal studs. Arrive 30 minutes early.',
                contact='Contact the club reception', onlinePlatform='Club gaming lobby',
                customDetails=[{'label': 'Equipment', 'value': 'Bring your own kit'},
                               {'label': 'Refreshments', 'value': 'Drinking water provided'}],
                registrationQuestions=[
                    {'id': 'captain', 'label': 'Captain name', 'type': 'text', 'required': True},
                    {'id': 'division', 'label': 'Preferred division', 'type': 'select',
                     'required': True, 'options': ['Beginner', 'Experienced']},
                    {'id': 'arrival', 'label': 'Arrival preference', 'type': 'text', 'required': False}])


def test_options_publish_persist_and_legacy_defaults_do_not_rewrite_records(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    configured = create_event(owner, service_clock, **options(), publish=True)
    assert configured['status'] == 'open'
    assert {key: configured[key] for key in options()} == options()
    legacy = create_event(owner, service_clock, name='Legacy cup', publish=True)
    with raw_state() as data:
        stored = next(item for item in data['organisationService']['tournaments'] if item['id'] == legacy['id'])
        for key in tournament_option_defaults():
            stored.pop(key)
    original = database_service()
    visible = get(player['client'], '/api/tournaments').json['tournaments']
    old_view = next(item for item in visible if item['id'] == legacy['id'])
    assert {key: old_view[key] for key in tournament_option_defaults()} == tournament_option_defaults()
    assert database_service() == original
    committed = next(item for item in database_service()['tournaments'] if item['id'] == configured['id'])
    assert {key: committed[key] for key in options()} == options()


def test_custom_draft_patch_preserves_options_and_publication_visibility(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    configured = create_event(owner, service_clock, **options())
    event_url = f"/api/tournaments/{configured['id']}"
    assert get(player['client'], '/api/tournaments').json['tournaments'] == []
    changed = patch(owner['client'], event_url, {'description': 'Updated draft', 'teamSize': 9})
    assert changed.status_code == 200
    assert changed.json['tournament']['description'] == 'Updated draft'
    assert changed.json['tournament']['teamSize'] == 9
    assert changed.json['tournament']['registrationQuestions'] == configured['registrationQuestions']
    assert changed.json['tournament']['customDetails'] == configured['customDetails']
    cleared = patch(owner['client'], event_url, {'customDetails': [], 'registrationQuestions': []})
    assert cleared.status_code == 200
    assert cleared.json['tournament']['customDetails'] == cleared.json['tournament']['registrationQuestions'] == []
    assert post(owner['client'], event_url + '/publish').status_code == 200
    assert get(player['client'], '/api/tournaments').json['tournaments'][0]['teamSize'] == 9


def test_invalid_options_roll_back_creation_and_patch(accounts, service_clock):
    owner = accounts('organisation')
    event = create_event(owner, service_clock)
    event_url = f"/api/tournaments/{event['id']}"
    original = database_service()
    question = options()['registrationQuestions'][0]
    invalid = [
        {'description': None}, {'description': 'x' * 2001}, {'format': 'double_elimination'},
        {'format': []}, {'teamSize': True}, {'teamSize': 0}, {'teamSize': 51},
        {'entryFee': -1}, {'entryFee': 0.5}, {'entryFee': True}, {'entryFee': 100001},
        {'rules': 'x' * 3001}, {'customDetails': None}, {'customDetails': [{'label': 'Empty', 'value': ' '}]},
        {'customDetails': [{'label': 'Extra', 'value': 'Value', 'hidden': 'forged'}]},
        {'customDetails': [{'label': 'Detail', 'value': 'Value'}] * 13},
        {'registrationQuestions': {}}, {'registrationQuestions': [question] * 9},
        {'registrationQuestions': [question, question]},
        {'registrationQuestions': [{**question, 'id': 'invalid id'}]},
        {'registrationQuestions': [{**question, 'required': 'yes'}]},
        {'registrationQuestions': [{**question, 'type': 'file'}]},
        {'registrationQuestions': [{**question, 'options': ['Unwanted choice']}]},
        {'registrationQuestions': [{**question, 'type': 'select', 'options': []}]},
        {'registrationQuestions': [{**question, 'type': 'select', 'options': ['Same', ' Same ']}]},
        {'registrationQuestions': [{**question, 'type': 'select', 'options': [True]}]},
    ]
    for change in invalid:
        created = post(owner['client'], '/api/tournaments', event_payload(service_clock, **change))
        assert created.status_code == 400, (change, created.get_data(as_text=True))
        changed = patch(owner['client'], event_url, {'name': 'Must not save', **change})
        assert changed.status_code == 400, (change, changed.get_data(as_text=True))
        assert database_service() == original


def test_upcoming_open_info_edits_preserve_reservation_and_freeze_setup(accounts, service_clock):
    owner, other_owner, player = accounts('organisation'), accounts('organisation'), accounts()
    ground = create_ground(owner)
    event = create_event(owner, service_clock, ground, **options(), publish=True)
    event_url = f"/api/tournaments/{event['id']}"
    original = database_service()
    for account, status in ((app.test_client(), 401), (other_owner['client'], 403), (player['client'], 403)):
        assert patch(account, event_url, {'description': 'Forged information'}).status_code == status
    assert patch(owner['client'], event_url, {'name': 'Must not save', 'rules': False}).status_code == 400
    for frozen in ({'teamSize': 8}, {'registrationQuestions': []}, {'format': 'custom'},
                   {'capacity': 16}, {'timezone': 'UTC'}, {'eventType': 'online'},
                   {'startsAt': event['startsAt']}, {'sport': 'Tennis'}, {'groundId': None},
                   {'registrationClosesAt': event['registrationClosesAt']}, {'durationHours': 3}):
        assert patch(owner['client'], event_url, {'description': 'Must not save', **frozen}).status_code == 409
        assert database_service() == original
    service_clock['value'] = datetime.fromisoformat(event['registrationClosesAt'])
    changed = patch(owner['client'], event_url,
                    {'name': 'Updated cup', 'rules': 'Updated arrival instructions',
                     'customDetails': [{'label': 'Parking', 'value': 'East gate'}]})
    assert changed.status_code == 200
    committed = database_service()
    assert committed['bookings'] == original['bookings']
    assert len(committed['bookings']) == 1
    visible = get(player['client'], '/api/tournaments').json['tournaments'][0]
    assert visible['name'] == 'Updated cup' and visible['customDetails'][0]['label'] == 'Parking'
    assert visible['registrationQuestions'] == event['registrationQuestions']
    service_clock['value'] = datetime.fromisoformat(event['startsAt'])
    before = deepcopy(committed)
    assert patch(owner['client'], event_url, {'description': 'Too late'}).status_code == 409
    assert database_service() == before
    assert post(owner['client'], event_url + '/cancel').status_code == 200
    assert patch(owner['client'], event_url, {'description': 'Cancelled'}).status_code == 409


def test_registration_answers_and_notes_validate_persist_and_remain_private(accounts, service_clock):
    owner, other_owner, first, second = accounts('organisation'), accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, **options(), publish=True)
    event_url = f"/api/tournaments/{event['id']}"
    answers = {'captain': 'Synthetic Captain', 'division': 'Beginner', 'arrival': '  Early  '}
    saved = post(first['client'], event_url + '/registrations',
                 {'teamName': 'First team', 'answers': answers, 'notes': '  Private equipment request  '})
    assert saved.status_code == 201
    registration = saved.json['registration']
    assert registration['answers'] == {**answers, 'arrival': 'Early'}
    assert registration['notes'] == 'Private equipment request'
    committed = database_service()['registrations'][0]
    assert committed['answers'] == registration['answers'] and committed['notes'] == registration['notes']
    for account in (second, other_owner):
        visible = get(account['client'], '/api/tournaments').json['tournaments'][0]
        assert visible['myRegistration'] is None
        assert 'Synthetic Captain' not in str(visible) and 'Private equipment request' not in str(visible)
        assert get(account['client'], event_url + '/registrations').status_code == 403
    mine = get(first['client'], '/api/tournaments').json['tournaments'][0]['myRegistration']
    assert mine == registration
    roster = get(owner['client'], event_url + '/registrations').json['registrations']
    assert roster == [registration]
    renamed = patch(first['client'], event_url + '/registrations/me', {'teamName': 'New team name'})
    assert renamed.status_code == 200
    assert renamed.json['registration']['answers'] == registration['answers']
    assert renamed.json['registration']['notes'] == registration['notes']
    changed_answers = {'captain': 'Updated private captain', 'division': 'Experienced'}
    edited = patch(first['client'], event_url + '/registrations/me',
                   {'teamName': 'New team name', 'answers': changed_answers, 'notes': ''})
    assert edited.status_code == 200 and edited.json['registration']['notes'] == ''
    assert database_service()['registrations'][0]['answers'] == changed_answers
    assert database_service()['registrations'][0]['notes'] == ''
    assert patch(second['client'], event_url + '/registrations/me',
                 {'teamName': 'Intruder', 'answers': changed_answers, 'notes': 'Forged'}).status_code == 404
    assert patch(owner['client'], event_url + '/registrations/me',
                 {'teamName': 'Intruder', 'answers': changed_answers}).status_code == 403


def test_invalid_answers_or_notes_roll_back_team_changes_and_registration(accounts, service_clock):
    owner, player, other = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, **options(), publish=True)
    event_url = f"/api/tournaments/{event['id']}"
    answers = {'captain': 'Original captain', 'division': 'Beginner'}
    assert post(player['client'], event_url + '/registrations',
                {'teamName': 'Original team', 'answers': answers, 'notes': 'Original notes'}).status_code == 201
    original = database_service()
    invalid = [
        {'answers': {}}, {'answers': []}, {'answers': {**answers, 'forged': 'Unknown question'}},
        {'answers': {**answers, 'captain': True}}, {'answers': {**answers, 'captain': ' '}},
        {'answers': {**answers, 'captain': 'x' * 501}},
        {'answers': {**answers, 'division': 'Unknown choice'}},
        {'notes': None}, {'notes': 'x' * 1001},
    ]
    for change in invalid:
        attempted = {'teamName': 'Must not save', 'answers': answers, **change}
        assert patch(player['client'], event_url + '/registrations/me', attempted).status_code == 400
        assert post(other['client'], event_url + '/registrations', attempted).status_code == 400
        assert database_service() == original
    service_clock['value'] = datetime.fromisoformat(event['registrationClosesAt'])
    assert patch(player['client'], event_url + '/registrations/me',
                 {'teamName': 'Late edit', 'answers': answers, 'notes': 'Late notes'}).status_code == 409
    assert database_service() == original


def test_legacy_registrations_get_empty_private_defaults_without_rewriting(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, publish=True)
    event_url = f"/api/tournaments/{event['id']}"
    assert post(player['client'], event_url + '/registrations', {'teamName': 'Legacy team'}).status_code == 201
    with raw_state() as data:
        registration = data['organisationService']['registrations'][0]
        registration.pop('answers')
        registration.pop('notes')
    original = database_service()
    mine = get(player['client'], '/api/tournaments').json['tournaments'][0]['myRegistration']
    assert mine['answers'] == {} and mine['notes'] == ''
    assert get(owner['client'], event_url + '/registrations').json['registrations'][0] == mine
    assert database_service() == original
    assert post(player['client'], event_url + '/registrations/me/cancel').status_code == 200
    assert patch(player['client'], event_url + '/registrations/me',
                 {'teamName': 'Withdrawn', 'notes': 'Cannot update'}).status_code == 404
