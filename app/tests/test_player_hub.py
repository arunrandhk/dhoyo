import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from social import now, state


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'hub.sqlite3'))
    return app.test_client()


def test_geographic_scopes_and_state_first_global_order(client):
    client.get('/api/arena')
    locations = [('home', 'India', 'Karnataka', 0), ('nation', 'India', 'Maharashtra', 1000),
                 ('international', 'Canada', 'Ontario', 1000000),
                 ('same-state-different-country', 'Canada', 'Karnataka', 1000000)]
    with state() as data:
        prototype = data['posts'][0]
        data['posts'] = [{**prototype, 'id': pid, 'country': country, 'state': region, 'likes': likes,
                          'createdAt': now().isoformat()} for pid, country, region, likes in locations]
        data['stories'] = [dict(id=pid, authorId='athlete-1', name='Maya Rao', initials='MR', image='https://example.com/a.jpg',
                                sport='Football', country=country, state=region, expiresAt=(now()+timedelta(hours=1)).isoformat())
                           for pid, country, region, _ in locations]
    local = client.get('/api/social/feed?mode=state').get_json()
    assert [p['id'] for p in local['posts']] == ['home']
    assert [s['id'] for s in local['stories']] == ['home']
    country = client.get('/api/social/feed?mode=country').get_json()
    assert [p['id'] for p in country['posts']] == ['home', 'nation']
    assert {s['id'] for s in country['stories']} == {'home', 'nation'}
    global_feed = client.get('/api/social/feed?mode=global').get_json()
    assert [p['id'] for p in global_feed['posts']][:2] == ['home', 'nation']
    assert len(global_feed['posts']) == 4
    assert global_feed['scope'] == dict(mode='global', country='India', state='Karnataka')


def test_location_persists_and_new_content_keeps_publication_location(client):
    response = client.patch('/api/social/preferences', json={'country': 'Canada', 'state': 'Ontario', 'city': 'Toronto'})
    assert response.status_code == 200
    post = client.post('/api/social/posts', json={'text': 'Toronto game', 'sport': 'Football'}).get_json()
    story = client.post('/api/social/stories', json={'image': 'https://example.com/a.jpg', 'sport': 'Football'}).get_json()
    assert post['country'] == story['country'] == 'Canada'
    assert post['state'] == story['state'] == 'Ontario'
    moved = client.patch('/api/arena/players/demo-user', json={'country': 'India', 'state': 'Karnataka', 'city': 'Bengaluru'})
    assert moved.status_code == 200
    preferences = app.test_client().get('/api/social/preferences').get_json()
    assert preferences['state'] == 'Karnataka' and preferences['country'] == 'India'
    assert post['id'] not in {p['id'] for p in client.get('/api/social/feed?mode=state').get_json()['posts']}
    profile = client.get('/api/arena/players/demo-user').get_json()
    assert profile['posts'][0]['country'] == 'Canada'
    assert profile['stories'][0]['state'] == 'Ontario'


def test_profile_includes_accepted_connections_matches_and_only_own_stories(client):
    client.get('/api/arena')
    profile = client.get('/api/arena/players/demo-user').get_json()
    assert {c['playerId'] for c in profile['connections']} == {'athlete-1'}
    assert 'athlete-5' not in {c['playerId'] for c in profile['connections']}
    assert profile['recordedMatchCount'] == 1 and profile['historicalGamesPlayed'] == 12
    assert client.post('/api/arena/teams/team-jordan/requests/request-rohan', json={'action': 'approve'}).status_code == 200
    client.post('/api/social/stories', json={'image': 'https://example.com/a.jpg', 'sport': 'Football'})
    profile = client.get('/api/arena/players/demo-user').get_json()
    assert {c['playerId'] for c in profile['connections']} == {'athlete-1', 'athlete-5'}
    teammate = next(c for c in profile['connections'] if c['playerId'] == 'athlete-5')
    assert teammate['teamIds'] == ['team-jordan']
    assert teammate['player']['gamesPlayed'] == 72 and teammate['player']['rank'] == 'Silver'
    assert all(s['authorId'] == 'demo-user' for s in profile['stories'])
    maya = client.get('/api/arena/players/athlete-1').get_json()
    assert maya['stories'] and all(s['authorId'] == 'athlete-1' for s in maya['stories'])
    assert client.get('/api/arena/players/missing').status_code == 404


def test_migration_and_scope_validation(client):
    client.get('/api/arena')
    with state() as data:
        data['preferences'].pop('country', None)
        data['preferences'].pop('state', None)
        for p in data['posts']:
            p.pop('country', None)
            p.pop('state', None)
        data['posts'][0].update(country='Canada', state='Ontario')
    feed = client.get('/api/social/feed?mode=global').get_json()
    assert feed['preferences']['state'] == 'Karnataka'
    assert next(p for p in feed['posts'] if p['id'] == '1')['country'] == 'Canada'
    assert client.get('/api/social/feed?mode=unknown').status_code == 400
    for payload in ({'state': ''}, {'state': []}, {'country': False}, {'country': 'x'*81}):
        assert client.patch('/api/social/preferences', json=payload).status_code == 400
        assert client.patch('/api/arena/players/demo-user', json=payload).status_code == 400


def test_full_photo_preserves_aspect_ratio_and_rejects_non_image(client):
    import base64
    from io import BytesIO
    from PIL import Image
    image = Image.new('RGB', (700, 400), 'green')
    output = BytesIO()
    image.save(output, format='PNG')
    photo = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
    response = client.patch('/api/arena/players/demo-user', json={'cover': photo})
    assert response.status_code == 200
    saved = client.get('/api/arena/players/demo-user').get_json()['player']['cover']
    with Image.open(BytesIO(base64.b64decode(saved.split(',')[1]))) as decoded:
        assert decoded.size == (700, 400)
    assert client.patch('/api/arena/players/demo-user', json={'cover': 'javascript:alert(1)'}).status_code == 400
    assert client.patch('/api/arena/players/athlete-1', json={'cover': photo}).status_code == 403
    post = client.post('/api/social/posts', json={'sport': 'Football', 'text': 'Uploaded highlight', 'image': photo})
    story = client.post('/api/social/stories', json={'sport': 'Football', 'image': photo})
    assert post.status_code == story.status_code == 201
    assert post.get_json()['image'].startswith('data:image/jpeg;base64,')
    assert story.get_json()['image'].startswith('data:image/jpeg;base64,')
    assert client.post('/api/social/posts', json={'sport': 'Football', 'text': 'Bad upload', 'image': 'data:image/svg+xml;base64,PHN2Zz4='}).status_code == 400


def test_can_follow_player_without_posts_and_cannot_follow_self(client):
    client.get('/api/arena')
    with state() as data:
        data['posts'] = [p for p in data['posts'] if p['authorId'] != 'athlete-5']
    response = client.post('/api/social/follow', json={'name': 'Rohan Das'})
    assert response.status_code == 200 and 'Rohan Das' in response.get_json()['following']
    assert client.post('/api/social/follow', json={'name': 'Jordan Davis'}).status_code == 400


def test_feed_country_and_state_follow_profile_not_separate_preferences(client):
    client.get('/api/arena')
    with state() as data:
        player = next(p for p in data['arena']['players'] if p['id'] == 'demo-user')
        player.update(country='Canada', state='Ontario')
        data['preferences'].update(country='India', state='Karnataka')
        data['posts'][0].update(country='Canada', state='Ontario')
    feed = client.get('/api/social/feed?mode=state').get_json()
    assert feed['posts'] and all(p['country'] == 'Canada' and p['state'] == 'Ontario' for p in feed['posts'])
    assert feed['scope'] == dict(mode='state', country='Canada', state='Ontario')
    assert feed['preferences']['country'] == 'Canada'


def test_device_location_resolves_caches_and_requires_profile_save(client, monkeypatch):
    import geography
    lookups = []
    def resolve(lat, lon):
        lookups.append((lat, lon))
        return dict(city='Toronto', state='Ontario', country='Canada')
    monkeypatch.setattr(geography, 'reverse_location', resolve)
    response = client.post('/api/arena/location/resolve', json={'latitude': 43.651, 'longitude': -79.383})
    assert response.status_code == 200
    assert response.get_json()['location']['country'] == 'Canada'
    assert client.post('/api/arena/location/resolve', json={'latitude': 43.651, 'longitude': -79.383}).status_code == 200
    assert len(lookups) == 1
    assert client.post('/api/arena/location/resolve', json={'latitude': 12, 'longitude': 77}).status_code == 429
    profile = client.get('/api/arena/players/demo-user').get_json()['player']
    assert profile['country'] == 'India'  # Detection alone does not silently move a player.
    with state() as data:
        assert 'latitude' not in data['locationLookup'] and 'longitude' not in data['locationLookup']
    for payload in ({'latitude': True, 'longitude': 0}, {'latitude': 91, 'longitude': 0},
                    {'latitude': 0, 'longitude': -181}, {'latitude': '43', 'longitude': 0}):
        assert client.post('/api/arena/location/resolve', json=payload).status_code == 400


def test_failed_location_lookup_keeps_saved_profile(client, monkeypatch):
    import geography
    def fail(lat, lon):
        raise OSError('Provider unavailable')
    monkeypatch.setattr(geography, 'reverse_location', fail)
    assert client.post('/api/arena/location/resolve', json={'latitude': 12, 'longitude': 77}).status_code == 502
    assert client.get('/api/arena/players/demo-user').get_json()['player']['country'] == 'India'
