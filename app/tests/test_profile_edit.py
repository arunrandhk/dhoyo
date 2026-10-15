"""Profile self-service with authenticated accounts and persisted SQLite state."""
import json
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app


HEADERS = {'X-Dhoyo-Request': '1'}


@pytest.fixture
def profile_accounts(tmp_path, monkeypatch):
    database = tmp_path / 'profiles.sqlite3'
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(database))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    clients = [app.test_client(), app.test_client()]
    identities = []
    for client, name in zip(clients, ('Alex', 'Sam')):
        response = client.post('/api/auth/register', headers=HEADERS, json={
            'name': name, 'email': name.lower() + '@example.com',
            'password': 'test-long-password', 'sport': 'Football',
            'city': 'Delhi', 'state': 'Delhi', 'country': 'India',
        })
        assert response.status_code == 201
        identities.append(response.json['userId'])
    return clients, identities, database


def test_regular_account_edits_are_committed_and_survive_sign_in(profile_accounts):
    clients, identities, database = profile_accounts
    owner, viewer = clients
    owner_id, viewer_id = identities
    original_viewer = viewer.get('/api/arena/players/' + viewer_id).json['player']
    fields = dict(name='Alex Kumar', city='Toronto', state='Ontario', country='Canada',
                  sport='Tennis', bio='Weekend doubles player.', photoPrivacy='public')
    response = owner.patch('/api/arena/players/' + owner_id, json=fields, headers=HEADERS)
    assert response.status_code == 200
    assert response.json['currentUserId'] == owner_id

    # Read the committed database with an independent connection, rather than
    # trusting the PATCH response or another route's in-memory representation.
    with sqlite3.connect(database) as connection:
        stored = json.loads(connection.execute(
            'SELECT payload FROM demo_state WHERE id = 1').fetchone()[0])
    saved = next(profile for profile in stored['arena']['players'] if profile['id'] == owner_id)
    assert {key: saved[key] for key in fields} == fields
    assert saved['initials'] == 'AK'
    assert stored['accounts']['alex@example.com']['player_id'] == owner_id
    assert stored['userPreferences'][owner_id]['city'] == 'Toronto'
    assert stored['userPreferences'][owner_id]['state'] == 'Ontario'
    assert stored['userPreferences'][owner_id]['country'] == 'Canada'

    fresh_session = app.test_client()
    assert fresh_session.post('/api/auth/login', headers=HEADERS, json={
        'email': 'alex@example.com', 'password': 'test-long-password',
    }).status_code == 200
    profile = fresh_session.get('/api/arena/players/' + owner_id).json['player']
    assert {key: profile[key] for key in fields} == fields
    assert fresh_session.get('/api/auth/me').json['name'] == fields['name']
    assert viewer.get('/api/arena/players/' + viewer_id).json['player'] == original_viewer


def test_regular_account_cannot_edit_another_profile_or_identity(profile_accounts):
    clients, identities, database = profile_accounts
    owner, visitor = clients
    owner_id, visitor_id = identities
    with sqlite3.connect(database) as connection:
        original = connection.execute('SELECT payload FROM demo_state WHERE id = 1').fetchone()[0]
    assert visitor.patch('/api/arena/players/' + owner_id, headers=HEADERS,
                         json={'name': 'Imposter'}).status_code == 403
    assert owner.patch('/api/arena/players/' + owner_id, headers=HEADERS,
                       json={'name': 'Alex', 'id': visitor_id}).status_code == 400
    assert app.test_client().patch('/api/arena/players/' + owner_id, headers=HEADERS,
                                  json={'name': 'Anonymous'}).status_code == 401
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT payload FROM demo_state WHERE id = 1').fetchone()[0] == original
