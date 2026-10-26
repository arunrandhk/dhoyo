import os
import sys
from io import BytesIO
import base64
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app
from social import raw_state

HEADERS={'X-Dhoyo-Request':'1'}

@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path/'accounts.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    return app.test_client(), app.test_client()


def register(client, email):
    return client.post('/api/auth/register', json=dict(name=email.split('@')[0], email=email, password='my-long-password', sport='Football', city='Delhi', state='Delhi', country='India'), headers=HEADERS)


def test_accounts_posts_and_interactions_are_isolated(clients):
    a,b=clients
    assert a.get('/api/arena').status_code==401
    ra,rb=register(a,'alex@example.com'),register(b,'sam@example.com')
    assert ra.status_code==rb.status_code==201
    aid,bid=ra.json['userId'],rb.json['userId']
    assert aid!=bid
    assert a.get('/api/arena').json['currentUserId']==aid
    assert b.patch('/api/arena/players/'+aid,json={'name':'Imposter'},headers=HEADERS).status_code==403
    assert a.patch('/api/arena/players/'+aid,json={'name':'Alex Updated','photoPrivacy':'public'},headers=HEADERS).status_code==200
    from PIL import Image
    image=BytesIO();Image.new('RGB',(20,10),'green').save(image,format='PNG')
    photo='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()
    post=a.post('/api/social/posts',json={'text':'We played today!', 'sport':'Football','image':photo},headers=HEADERS)
    assert post.status_code==201
    assert post.json['authorId']==aid and post.json['name']=='Alex Updated'
    assert post.json['image'].startswith('data:image/jpeg;base64,')
    pid=post.json['id']
    assert a.post(f'/api/social/posts/{pid}/like',json={},headers=HEADERS).json['liked']
    assert a.post(f'/api/social/posts/{pid}/save',json={},headers=HEADERS).json['saved']
    other=next(p for p in b.get('/api/social/feed').json['posts'] if p['id']==pid)
    assert not other['liked'] and not other['saved'] and other['likes']==1
    mine=next(p for p in a.get('/api/social/feed').json['posts'] if p['id']==pid)
    assert mine['liked'] and mine['saved']
    comment=b.post(f'/api/social/posts/{pid}/comments',json={'text':'Nice game!'},headers=HEADERS).json['comments'][-1]
    assert comment['authorId']==bid and comment['name']=='sam'
    assert b.post('/api/arena/awards',json={},headers={**HEADERS,'X-Demo-Role':'organizer'}).status_code==403
    assert b.get('/users').status_code==403
    with raw_state() as data:
        assert 'my-long-password' not in str(data)
        assert data['accounts']['alex@example.com']['password_hash'].startswith('scrypt:')
    assert a.post('/api/auth/logout',json={},headers=HEADERS).status_code==200
    assert a.get('/api/arena').status_code==401
    assert a.post('/api/auth/login',json={'email':'ALEX@example.com','password':'my-long-password'},headers=HEADERS).status_code==200
    assert a.get('/api/arena').json['currentUserId']==aid


def test_login_errors_csrf_duplicate_and_revocation(clients):
    a,b=clients
    assert register(a,'alex@example.com').status_code==201
    assert register(b,'alex@example.com').status_code==409
    assert b.post('/api/auth/login',json={'email':'alex@example.com','password':'wrong'},headers=HEADERS).status_code==401
    assert a.post('/api/auth/logout',json={}).status_code==403
    assert a.post('/api/auth/logout',json={},headers={**HEADERS,'Origin':'https://evil.example'}).status_code==403
    cookie=a.get_cookie('dhoyo_session').value
    a.post('/api/auth/logout',json={},headers=HEADERS)
    b.set_cookie('dhoyo_session',cookie)
    assert b.get('/api/arena').status_code==401


def test_game_reactions_are_persistent_private_and_do_not_award_rank(clients):
    a,b=clients
    aid=register(a,'game-a@example.com').json['userId']
    register(b,'game-b@example.com')
    post=a.post('/api/social/posts',json={'text':'Great match','sport':'Football'},headers=HEADERS).json
    url='/api/social/posts/'+post['id']+'/reaction'
    assert a.post(url,json={'reaction':'fire'},headers=HEADERS).json['reactionCounts']['fire']==1
    result=b.post(url,json={'reaction':'mvp'},headers=HEADERS).json
    assert result['reactionCounts']=={'fire':1,'mvp':1,'clap':0}
    assert 'reactionsBy' not in result
    result=a.post(url,json={'reaction':'clap'},headers=HEADERS).json
    assert result['reactionCounts']=={'fire':0,'mvp':1,'clap':1}
    assert a.get('/api/arena/players/'+aid).json['player']['awards']==dict(Star=0,Diamond=0,Gold=0,Silver=0)
    result=a.post(url,json={'reaction':'clap'},headers=HEADERS).json
    assert result['myReaction'] is None
    assert a.post(url,json={'reaction':'invalid'},headers=HEADERS).status_code==400
    result=next(p for p in b.get('/api/social/feed').json['posts'] if p['id']==post['id'])
    assert result['myReaction']=='mvp' and result['reactionCounts']['mvp']==1
