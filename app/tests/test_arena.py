import os
import sys
from copy import deepcopy

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from social import state


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'arena.sqlite3'))
    return app.test_client()


def player(response, player_id='athlete-1'):
    return next(p for p in response.get_json()['players'] if p['id'] == player_id)


def test_support_exact_unique_persistent_and_independent_of_awards(client):
    initial = player(client.get('/api/arena'))
    supported = player(client.post('/api/arena/players/athlete-1/support', json={'supporterId': 'fake'}))
    assert supported['communityStars'] == 1 and supported['communityPoints'] == 0.2
    assert supported['starScore'] == 3.2 and supported['awards'] == initial['awards']
    assert player(app.test_client().get('/api/arena'))['supported']
    removed = player(client.post('/api/arena/players/athlete-1/support'))
    assert removed['communityStars'] == 0 and removed['communityPoints'] == 0
    assert client.post('/api/arena/players/demo-user/support').status_code == 400
    assert client.post('/api/arena/players/missing/support').status_code == 404


def test_join_duplicate_owner_and_capacity(client):
    assert client.post('/api/arena/teams/team-pixel/join').status_code == 201
    assert client.post('/api/arena/teams/team-pixel/join').status_code == 409
    assert client.post('/api/arena/teams/team-maya/members', json={'playerId': 'athlete-2'}).status_code == 403
    assert client.post('/api/arena/teams/team-jordan/members', json={'playerId': 'athlete-2'}).status_code == 200
    assert client.post('/api/arena/teams/team-jordan/members', json={'playerId': 'athlete-2'}).status_code == 409
    with state() as data:
        team = next(t for t in data['arena']['teams'] if t['id'] == 'team-jordan')
        team['capacity'] = len(team['members'])
    assert client.post('/api/arena/teams/team-jordan/members', json={'playerId': 'athlete-3'}).status_code == 409


def test_owner_approval_persists_and_rejects_duplicate(client):
    response = client.post('/api/arena/teams/team-jordan/requests/request-rohan', json={'action': 'approve'})
    assert response.status_code == 200
    assert player(response, 'athlete-5')['teamIds'] == ['team-jordan']
    assert client.post('/api/arena/teams/team-jordan/requests/request-rohan', json={'action': 'approve'}).status_code == 409
    assert player(app.test_client().get('/api/arena'), 'athlete-5')['teamId'] == 'team-jordan'


def test_awards_role_results_validation_and_duplicate(client):
    payload = dict(playerId='demo-user', matchId='match-final', tier='Gold', count=3)
    headers = {'X-Demo-Role': 'organizer'}
    assert client.post('/api/arena/awards', json=payload).status_code == 403
    for count in (0, -1, 101, True, 0.2, '2'):
        assert client.post('/api/arena/awards', json={**payload, 'count': count}, headers=headers).status_code == 400
    assert client.post('/api/arena/awards', json={**payload, 'matchId': 'match-live', 'playerId': 'athlete-2'}, headers=headers).status_code == 400
    assert client.post('/api/arena/awards', json={**payload, 'playerId': 'athlete-2'}, headers=headers).status_code == 400
    response = client.post('/api/arena/awards', json=payload, headers=headers)
    assert response.status_code == 201
    assert player(response, 'demo-user')['rank'] == 'Gold'
    assert player(response, 'demo-user')['awards']['Gold'] == 3
    assert client.post('/api/arena/awards', json=payload, headers=headers).status_code == 409


def test_migration_preserves_existing_posts(client):
    post = client.post('/api/social/posts', json={'text': 'Keep this result', 'sport': 'Football'}).get_json()
    with state() as data:
        data.pop('arena', None)
    assert client.get('/api/arena').status_code == 200
    assert any(p['id'] == post['id'] for p in client.get('/api/social/feed').get_json()['posts'])


def test_saved_identity_preserves_name_and_achievements(client):
    client.get('/api/arena')
    with state() as data:
        profile = next(p for p in data['arena']['players'] if p['id'] == 'demo-user')
        profile.update(name='Jordan Lee', initials='JL')
        profile['awards']['Gold'] = 7
    migrated = player(client.get('/api/arena'), 'demo-user')
    assert (migrated['name'], migrated['initials']) == ('Jordan Lee', 'JL')
    assert migrated['awards']['Gold'] == 7
    with state() as data:
        assert next(p for p in data['arena']['players'] if p['id'] == 'demo-user')['name'] == 'Jordan Lee'


def test_communities_seed_and_membership_persistence(client):
    initial = client.get('/api/arena').get_json()
    communities = {community['id']: community for community in initial['communities']}
    assert set(communities) == {'afterhours-fc', 'zero-ping', 'court-culture', 'boundary-club'}
    assert communities['afterhours-fc']['joined']
    assert communities['afterhours-fc']['memberIds'] == ['athlete-1', 'demo-user']
    assert communities['zero-ping']['city'] == 'Online'
    for community in communities.values():
        assert community['image'] and community['description']
        assert community['memberCount'] == len(community['memberIds'])

    for expected in (True, False, True):
        response = client.post('/api/arena/communities/zero-ping/membership', json={'userId': 'fake'})
        assert response.status_code == 200
        assert 'players' in response.get_json()
        persisted = app.test_client().get('/api/arena').get_json()
        community = next(c for c in persisted['communities'] if c['id'] == 'zero-ping')
        assert community['joined'] == expected
        assert community['memberIds'].count('demo-user') == int(expected)
        assert 'fake' not in community['memberIds']
        assert community['memberCount'] == 1 + int(expected)
    assert client.post('/api/arena/communities/missing/membership').status_code == 404


def test_communities_migration_preserves_existing_arena(client):
    client.get('/api/arena')
    client.post('/api/arena/players/athlete-1/support')
    with state() as data:
        del data['arena']['communities']
        data['arena']['players'][0]['awards']['Gold'] = 77
        before = deepcopy(data['arena'])
    response = client.get('/api/arena')
    assert len(response.get_json()['communities']) == 4
    with state() as data:
        assert {key: value for key, value in data['arena'].items() if key != 'communities'} == before
        data['arena']['communities'][0]['name'] = 'Our custom arena'
    persisted = client.get('/api/arena').get_json()
    assert persisted['communities'][0]['name'] == 'Our custom arena'


def test_influence_approval_awards_and_support_recompute_without_inheriting(client):
    before = player(client.get('/api/arena'), 'athlete-5')
    assert before['discoveryBoost'] == 0 and before['influenceSources'] == []
    approved = client.post('/api/arena/teams/team-jordan/requests/request-rohan', json={'action': 'approve'})
    assert player(approved, 'athlete-5')['discoveryBoost'] == 0.2
    awarded = client.post('/api/arena/awards', json=dict(playerId='demo-user', matchId='match-final', tier='Star', count=3), headers={'X-Demo-Role': 'organizer'})
    member = player(awarded, 'athlete-5')
    assert member['discoveryBoost'] == 0.8
    assert member['rank'] == before['rank'] and member['awards'] == before['awards']
    assert member['communityPoints'] == before['communityPoints']
    assert player(awarded, 'demo-user')['discoveryBoost'] == 0
    with state() as data:
        data['arena']['teams'][0]['members'].append('athlete-2')
    supported = client.post('/api/arena/players/athlete-1/support')
    assert player(supported, 'athlete-2')['discoveryBoost'] == 0.84
    removed = client.post('/api/arena/players/athlete-1/support')
    assert player(removed, 'athlete-2')['discoveryBoost'] == 0.8


def test_influence_bounded_no_stacking_or_recursive_inheritance(client):
    client.get('/api/arena')
    with state() as data:
        value = data['arena']
        value['players'][0]['supporters'] = [str(i) for i in range(100)]
        value['teams'][0]['members'].extend(['athlete-2', 'demo-user'])
        value['teams'][1]['members'].append('athlete-2')
    result = client.get('/api/arena')
    member = player(result, 'athlete-2')
    assert member['discoveryBoost'] == 1
    assert sorted(s['boost'] for s in member['influenceSources']) == [0.2, 1]
    assert player(result)['discoveryBoost'] == 0
    teams = {t['id']: t for t in result.get_json()['teams']}
    assert teams['team-maya']['influence']['score'] == 5
    assert teams['team-jordan']['influence']['score'] == 1


def test_influence_breakdown_counts_only_real_accepted_non_owner_members(client):
    client.get('/api/arena')
    with state() as data:
        value = data['arena']
        value['players'][0]['supporters'] = [str(i) for i in range(100)]
        value['teams'][0]['members'].extend(['athlete-2', 'athlete-2', 'missing'])
        value['teams'][0]['requests'].append(dict(id='waiting', playerId='athlete-3', status='pending'))
    result = client.get('/api/arena').get_json()
    influence = next(t for t in result['teams'] if t['id'] == 'team-maya')['influence']
    assert influence['tierPoints'] == 4
    assert influence['supportPoints'] == 1
    assert influence['score'] == 5 and influence['memberBoost'] == 1
    assert influence['acceptedMemberCount'] == 1
    assert next(p for p in result['players'] if p['id'] == 'athlete-3')['discoveryBoost'] == 0
    assert result['influenceRules']['feeds'] == ['global', 'country', 'state', 'for-you', 'local']


def test_feed_explains_only_strongest_matching_source_and_excludes_following(client):
    posts = {sport: client.post('/api/social/posts', json={'text': 'Match highlight', 'sport': sport}).get_json()['id']
             for sport in ('Esports', 'Basketball', 'Cricket')}
    assert client.post('/api/arena/teams/team-pixel/join').status_code == 201
    pending = {p['id']: p for p in client.get('/api/social/feed').get_json()['posts']}
    assert pending[posts['Esports']]['discoveryBoost'] == 0
    assert pending[posts['Esports']]['discoverySources'] == []
    with state() as data:
        value = data['arena']
        value['teams'][2]['members'].append('demo-user')
        value['players'][0]['supporters'] = [str(i) for i in range(100)]
        value['teams'].append(dict(id='basketball-squad', name='Court Squad', sport='Basketball', city='Bengaluru',
                                  ownerId='athlete-1', members=['athlete-1', 'demo-user'], requests=[], capacity=5))
        data['preferences']['following'] = ['Jordan Davis']
    for mode in ('for-you', 'local'):
        feed_posts = {p['id']: p for p in client.get('/api/social/feed?mode=' + mode).get_json()['posts']}
        esports = feed_posts[posts['Esports']]
        assert esports['discoveryBoost'] == 0.6
        assert [s['teamId'] for s in esports['discoverySources']] == ['team-pixel']
        assert all(s['boost'] == esports['discoveryBoost'] and s['sport'] == 'Esports' for s in esports['discoverySources'])
        assert feed_posts[posts['Basketball']]['discoveryBoost'] == 1
        assert feed_posts[posts['Cricket']]['discoveryBoost'] == 0
        assert feed_posts[posts['Cricket']]['discoverySources'] == []
    following = client.get('/api/social/feed?mode=following').get_json()['posts']
    assert len(following) == 3
    assert all(p['discoveryBoost'] == 0 and p['discoverySources'] == [] for p in following)


def test_profile_persists_and_feed_uses_current_name(client):
    post = client.post('/api/social/posts', json={'text': 'Training today', 'sport': 'Football'}).get_json()
    response = client.patch('/api/arena/players/demo-user', json={'name': 'Alex Kumar', 'city': 'Delhi', 'sport': 'Tennis'})
    assert response.status_code == 200
    current = player(app.test_client().get('/api/arena'), 'demo-user')
    assert (current['name'], current['city'], current['sport'], current['initials']) == ('Alex Kumar', 'Delhi', 'Tennis', 'AK')
    posts = client.get('/api/social/feed').get_json()['posts']
    assert next(p for p in posts if p['id'] == post['id'])['name'] == 'Alex Kumar'
    # The old hardcoded migration must never overwrite a saved name.
    client.patch('/api/arena/players/demo-user', json={'name': 'Jordan Lee'})
    assert player(client.get('/api/arena'), 'demo-user')['name'] == 'Jordan Lee'


@pytest.mark.parametrize('payload', [{}, {'name': ''}, {'city': 123}, {'sport': 'Invalid'}, {'awards': {'Star': 99}}])
def test_profile_rejects_invalid_fields(client, payload):
    assert client.patch('/api/arena/players/demo-user', json=payload).status_code == 400


def test_profile_cannot_edit_other_players(client):
    assert client.patch('/api/arena/players/athlete-1', json={'name': 'Changed'}).status_code == 403


def test_profile_photo_and_bio_persist_and_remove(client):
    import base64
    from io import BytesIO
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (20, 30), 'blue').save(image, format='PNG')
    avatar = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
    response = client.patch('/api/arena/players/demo-user', json={'avatar': avatar, 'bio': 'Weekend footballer.'})
    assert response.status_code == 200
    saved = player(client.get('/api/arena'), 'demo-user')
    assert saved['bio'] == 'Weekend footballer.'
    assert saved['avatar'].startswith('data:image/jpeg;base64,')
    normalized = Image.open(BytesIO(base64.b64decode(saved['avatar'].split(',')[1])))
    assert normalized.size == (256, 256)
    post = client.post('/api/social/posts', json={'text': 'Ready to play', 'sport': 'Football'}).get_json()
    assert post['avatar'] == saved['avatar']
    assert client.patch('/api/arena/players/demo-user', json={'avatar': '', 'bio': ''}).status_code == 200
    saved = player(client.get('/api/arena'), 'demo-user')
    assert saved['avatar'] == saved['bio'] == ''


@pytest.mark.parametrize('payload', [
    {'avatar': 12}, {'avatar': 'data:image/svg+xml;base64,PHN2Zz4='},
    {'avatar': 'data:image/png;base64,bm90IGFuIGltYWdl'},
    {'avatar': 'x' * 400001}, {'bio': 123}, {'bio': 'x' * 281},
])
def test_invalid_photo_or_bio_does_not_change_profile(client, payload):
    original = player(client.get('/api/arena'), 'demo-user')
    assert client.patch('/api/arena/players/demo-user', json={'name': 'Should not save', **payload}).status_code == 400
    assert player(client.get('/api/arena'), 'demo-user') == original
