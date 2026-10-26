import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from social import now, rank, state


def test_member_discovery_sport_following_and_freshness(client):
    from datetime import timedelta
    client.get('/api/arena')
    with state() as data:
        data['preferences'].update(sports=[], following=[])
        prototype = data['posts'][0]
        data['posts'] = [{**prototype, 'id': str(i), 'authorId': author, 'name': author, 'sport': 'Football', 'likes': 0, 'liked': False, 'saved': False, 'comments': [], 'createdAt': now().isoformat()} for i, author in enumerate(['athlete-2', 'athlete-3'])]
        for p in data['arena']['players']:
            if p['id'] in ('athlete-2', 'athlete-3'):
                p['awards'] = dict(Star=0, Diamond=0, Gold=0, Silver=1)
        data['arena']['teams'][0]['members'].append('athlete-3')
    for mode in ('for-you', 'local'):
        posts = client.get('/api/social/feed?mode=' + mode).get_json()['posts']
        assert posts[0]['authorId'] == 'athlete-3' and posts[0]['discoveryBoost'] == 0.8
    assert client.get('/api/social/feed?mode=following').get_json()['posts'] == []
    with state() as data:
        data['preferences']['following'] = ['athlete-3']
    followed = client.get('/api/social/feed?mode=following').get_json()['posts']
    assert len(followed) == 1 and followed[0]['discoveryBoost'] == 0
    with state() as data:
        data['preferences']['following'] = []
        data['posts'][1]['createdAt'] = (now() - timedelta(days=10)).isoformat()
    assert client.get('/api/social/feed').get_json()['posts'][0]['authorId'] == 'athlete-2'
    with state() as data:
        data['posts'][1]['sport'] = 'Cricket'
    posts = client.get('/api/social/feed').get_json()['posts']
    assert all(p['discoveryBoost'] == 0 for p in posts)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'social.sqlite3'))
    return app.test_client()


def test_mutations_persist_and_toggle(client):
    post = client.post('/api/social/posts', json={'text': 'Match day!', 'sport': 'Cricket'}).get_json()
    url = '/api/social/posts/' + post['id']
    assert client.post(url + '/like').get_json()['likes'] == 1
    assert client.post(url + '/like').get_json()['likes'] == 0
    assert client.post(url + '/save').get_json()['saved']
    assert client.post(url + '/comments', json={'text': 'Great game'}).get_json()['comments'] == [{'authorId': 'demo-user', 'name': 'Jordan Davis', 'text': 'Great game'}]
    retrieved = client.get('/api/social/feed?q=Match%20day!').get_json()['posts']
    assert retrieved[0]['saved']


def test_following_and_local_filters(client):
    preferences = client.post('/api/social/follow', json={'name': 'Maya Rao'}).get_json()
    assert 'Maya Rao' not in preferences['following']
    assert {p['name'] for p in client.get('/api/social/feed?mode=following').get_json()['posts']} == {'Pixel United'}
    client.patch('/api/social/preferences', json={'city': 'Mumbai'})
    posts = client.get('/api/social/feed?mode=local').get_json()['posts']
    assert posts and all(p['city'] == 'Mumbai' for p in posts)
    assert client.get('/api/social/feed?mode=local&city=Unknown').get_json()['posts'] == []


def test_preferences_and_engagement_personalize_feed(client):
    client.get('/api/social/feed')
    with state() as data:
        data['preferences'].update(sports=[], following=[], city='Other')
        for post in data['posts']:
            post.update(createdAt=now().isoformat(), likes=0, baseSaves=0)
    client.patch('/api/social/preferences', json={'sports': ['Tennis']})
    assert client.get('/api/social/feed').get_json()['posts'][0]['sport'] == 'Tennis'
    client.patch('/api/social/preferences', json={'sports': []})
    client.post('/api/social/posts/4/save')
    assert client.get('/api/social/feed').get_json()['posts'][0]['sport'] == 'Esports'


def test_stories_expire_and_validate(client):
    payload = {'image': 'https://example.com/court.jpg', 'text': 'Today', 'sport': 'Tennis'}
    response = client.post('/api/social/stories', json=payload)
    assert response.status_code == 201
    story_id = response.get_json()['id']
    with state() as data:
        next(s for s in data['stories'] if s['id'] == story_id)['expiresAt'] = (now() - timedelta(seconds=1)).isoformat()
    assert story_id not in {s['id'] for s in client.get('/api/social/stories').get_json()['stories']}
    assert story_id not in {s['id'] for s in client.get('/api/social/feed').get_json()['stories']}
    for image in ['javascript:alert(1)', 'file:///etc/passwd', 'https://', 'http://[invalid']:
        assert client.post('/api/social/stories', json={**payload, 'image': image}).status_code == 400


def test_ranks_and_invalid_requests(client):
    post = dict(likes=0, comments=[], baseSaves=0, saved=False)
    assert all(rank({**post, 'likes': score}) is None for score in [0, 50, 150, 400, 1000])
    assert client.post('/api/social/posts', json={'text': 'Hi', 'sport': []}).status_code == 400
    assert client.patch('/api/social/preferences', json={'sports': [5]}).status_code == 400
    assert client.post('/api/social/posts/missing/like').status_code == 404
    assert client.post('/api/social/posts/1/comments', json={'text': ' '}).status_code == 400
    assert client.get('/api/social/feed?mode=invalid').status_code == 400
    assert client.get('/sportspace').location == '/static/sportspace/index.html'


def test_repeated_comments_cannot_farm_rank(client):
    client.get('/api/social/feed')
    with state() as data:
        data['posts'][0].update(likes=42, baseSaves=0)
    for index in range(12):
        post = client.post('/api/social/posts/1/comments', json={'text': 'Comment ' + str(index)}).get_json()
        assert post['rank'] == 'Star'
    assert len(post['comments']) == 12
    assert client.post('/api/social/posts/1/like').get_json()['rank'] == 'Star'
    assert client.post('/api/social/posts/1/save').get_json()['rank'] == 'Star'
    assert client.post('/api/social/posts/1/save').get_json()['rank'] == 'Star'


def test_persistence_across_clients(client):
    client.patch('/api/social/preferences', json={'city': 'Delhi', 'sports': ['Tennis']})
    post = client.post('/api/social/posts', json={'text': 'Persistent rally', 'sport': 'Tennis'}).get_json()
    client.post('/api/social/posts/' + post['id'] + '/save')
    with app.test_client() as fresh_client:
        preferences = fresh_client.get('/api/social/preferences').get_json()
        assert preferences['city'] == 'Delhi'
        assert preferences['sports'] == ['Tennis']
        posts = fresh_client.get('/api/social/feed?q=Persistent%20rally').get_json()['posts']
        assert len(posts) == 1 and posts[0]['id'] == post['id']
        assert posts[0]['saved'] and posts[0]['city'] == 'Delhi'


def test_local_rank_boost_and_freshness(client):
    client.get('/api/social/feed')
    with state() as data:
        data['preferences'].update(sports=[], following=[], city='Bengaluru')
        data['posts'] = data['posts'][:2]
        for post in data['posts']:
            post.update(likes=0, baseSaves=0, createdAt=now().isoformat())
        data['arena']['players'][0]['awards'] = dict(Star=0, Diamond=0, Gold=0, Silver=1)
        data['arena']['players'][1]['awards']['Star'] = 1
    posts = client.get('/api/social/feed?mode=local').get_json()['posts']
    assert [post['id'] for post in posts] == ['2', '1']
    assert posts[0]['rank'] == 'Star'
    with state() as data:
        data['posts'][1]['createdAt'] = (now() - timedelta(days=100)).isoformat()
    assert client.get('/api/social/feed?mode=local').get_json()['posts'][0]['id'] == '1'


@pytest.mark.parametrize('community_id,sport,city', [
    ('zero-ping', 'Esports', 'Online'),
    ('court-culture', 'Basketball', 'Mumbai'),
])
def test_community_posts_persist_context_without_membership(client, community_id, sport, city):
    response = client.post('/api/social/posts', json={
        'text': 'A new Arena highlight', 'sport': sport, 'communityId': community_id,
    })
    assert response.status_code == 201
    post = response.get_json()
    assert post['communityId'] == community_id and post['city'] == city
    persisted = app.test_client().get('/api/social/feed').get_json()['posts']
    stored = next(item for item in persisted if item['id'] == post['id'])
    assert stored['communityId'] == community_id and stored['city'] == city
    assert stored['sport'] == sport


def test_community_post_validation_preserves_posts(client):
    before = client.get('/api/social/feed').get_json()['posts']
    payload = {'text': 'Invalid Arena highlight', 'sport': 'Football'}
    for community_id in ('missing', '', None, [], 3):
        response = client.post('/api/social/posts', json={**payload, 'communityId': community_id})
        assert response.status_code == 404
    assert client.post('/api/social/posts', json={**payload, 'communityId': 'zero-ping'}).status_code == 400
    assert {post['id'] for post in client.get('/api/social/feed').get_json()['posts']} == {post['id'] for post in before}
    response = client.post('/api/social/posts', json=payload)
    assert response.status_code == 201
    assert 'communityId' not in response.get_json()
    assert response.get_json()['city'] == 'Bengaluru'
