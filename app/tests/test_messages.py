import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'messages.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    return app.test_client(), app.test_client(), app.test_client()


def register(client, name):
    response = client.post('/api/auth/register', json=dict(
        name=name, email=name.lower() + '@example.com', password='my-long-password',
        sport='Football', city='Delhi', state='Delhi', country='India'), headers=HEADERS)
    assert response.status_code == 201
    return response.json['userId']


def send(client, recipient, sticker='gg', **extra):
    return client.post('/api/messages/conversations/' + recipient,
                       json={'stickerId': sticker, **extra}, headers=HEADERS)


def test_registered_player_directory_excludes_demo_and_private_account_data(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    result = a.get('/api/messages/players').json
    assert result['currentUserId'] == aid
    assert [player['id'] for player in result['players']] == [bid, cid]
    assert all(set(player) == {'id', 'name', 'initials', 'avatar', 'sport'} for player in result['players'])
    assert a.get('/api/messages/players?q=SAM').json['players'][0]['id'] == bid
    assert a.get('/api/messages/players?q=unknown').json['players'] == []


def test_stickers_are_private_bidirectional_and_sender_is_session_identity(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    first = send(a, bid)
    assert first.status_code == 201
    message = first.json['message']
    assert set(message) == {'id', 'senderId', 'recipientId', 'stickerId', 'createdAt'}
    assert message['senderId'] == aid and message['recipientId'] == bid and message['stickerId'] == 'gg'
    reply = send(b, aid, 'fire').json['message']
    assert a.get('/api/messages/conversations/' + bid).json['messages'] == [message, reply]
    assert b.get('/api/messages/conversations/' + aid).json['messages'] == [message, reply]
    assert c.get('/api/messages/conversations').json == {'conversations': [], 'unreadCount': 0}
    # Looking up either participant yields only the visitor's own conversation.
    assert c.get('/api/messages/conversations/' + bid).json['messages'] == []
    assert c.get('/api/messages/conversations/' + aid).json['messages'] == []
    assert send(a, bid, senderId=cid).status_code == 400
    assert len(b.get('/api/messages/conversations/' + aid).json['messages']) == 2


def test_unread_counts_mark_only_the_opened_incoming_conversation(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    send(a, bid)
    send(a, bid, 'heart')
    send(c, bid, 'wave')
    assert a.get('/api/messages/conversations').json['unreadCount'] == 0
    result = b.get('/api/messages/conversations').json
    assert result['unreadCount'] == 3
    assert {item['player']['id']: item['unreadCount'] for item in result['conversations']} == {aid: 2, cid: 1}
    assert result['conversations'][0]['player']['id'] == cid
    a.get('/api/messages/conversations/' + bid)
    assert b.get('/api/messages/conversations').json['unreadCount'] == 3
    b.get('/api/messages/conversations/' + aid)
    result = b.get('/api/messages/conversations').json
    assert result['unreadCount'] == 1
    assert {item['player']['id']: item['unreadCount'] for item in result['conversations']} == {aid: 0, cid: 1}
    latest = send(a, bid, 'trophy').json['message']
    result = b.get('/api/messages/conversations').json
    assert result['unreadCount'] == 2
    assert result['conversations'][0]['lastMessage'] == latest


def test_message_history_and_read_state_survive_logout_and_login(clients):
    a, b, _ = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    message = send(a, bid, 'football').json['message']
    b.get('/api/messages/conversations/' + aid)
    assert a.post('/api/auth/logout', json={}, headers=HEADERS).status_code == 200
    assert b.post('/api/auth/logout', json={}, headers=HEADERS).status_code == 200
    for client, email in ((a, 'alex@example.com'), (b, 'sam@example.com')):
        assert client.post('/api/auth/login', json={'email': email, 'password': 'my-long-password'},
                           headers=HEADERS).status_code == 200
    assert a.get('/api/messages/conversations/' + bid).json['messages'] == [message]
    assert b.get('/api/messages/conversations').json['unreadCount'] == 0
    with raw_state() as data:
        assert data['stickerMessages'][0]['id'] == message['id']
        assert data['stickerMessages'][0]['readAt']


def test_invalid_stickers_targets_and_payloads_do_not_create_messages(clients):
    a, b, _ = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    assert send(a, aid).status_code == 400
    assert send(a, 'unknown-player').status_code == 404
    assert send(a, 'athlete-1').status_code == 404
    assert a.get('/api/messages/conversations/' + aid).status_code == 400
    assert a.get('/api/messages/conversations/athlete-1').status_code == 404
    for sticker in ('unknown', '', '../gg', None, 12, [], {}):
        assert send(a, bid, sticker).status_code == 400
    url = '/api/messages/conversations/' + bid
    for payload in ({}, [], {'stickerId': 'gg', 'recipientId': aid}):
        assert a.post(url, json=payload, headers=HEADERS).status_code == 400
    for raw_json in ('null', '{broken', '"gg"'):
        assert a.post(url, data=raw_json, content_type='application/json', headers=HEADERS).status_code == 400
    assert a.get('/api/messages/conversations').json['conversations'] == []


def test_authentication_and_existing_csrf_controls_apply_to_messages(clients):
    a, b, c = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    for path in ('/api/messages/players', '/api/messages/conversations', '/api/messages/conversations/' + aid):
        assert c.get(path).status_code == 401
    assert send(c, bid).status_code == 401
    url = '/api/messages/conversations/' + bid
    assert a.post(url, json={'stickerId': 'gg'}).status_code == 403
    assert a.post(url, json={'stickerId': 'gg'}, headers={**HEADERS, 'Origin': 'https://evil.example'}).status_code == 403
    assert a.post(url, json={'stickerId': 'gg'}, headers={**HEADERS, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert b.get('/api/messages/conversations').json['unreadCount'] == 0


def test_send_uses_catalog_whitelist(clients, tmp_path, monkeypatch):
    a, b, _ = clients
    register(a, 'Alex')
    bid = register(b, 'Sam')
    static = tmp_path / 'static'
    catalog_dir = static / 'sportspace'
    catalog_dir.mkdir(parents=True)
    (catalog_dir / 'stickers.json').write_text('{"stickers":[{"id":"custom-sticker"}]}')
    monkeypatch.setattr(app, 'static_folder', str(static))
    assert send(a, bid, 'gg').status_code == 400
    assert send(a, bid, 'custom-sticker').status_code == 201
