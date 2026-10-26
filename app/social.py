"""Persistent social demo: visitors share one identity, not authenticated accounts."""
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

from flask import Blueprint, jsonify, request, g
from auth import current_user_id
from privacy import can_view_photos, redact_photo_aliases, visible_photo_item

social = Blueprint('social', __name__, url_prefix='/api/social')
SPORTS = {'Football', 'Cricket', 'Basketball', 'Badminton', 'Tennis', 'Running', 'Esports', 'Swimming', 'Volleyball'}


def now():
    return datetime.now(timezone.utc)


def seed():
    entries = [
        ('Maya Rao', 'Football', 'Bengaluru', 'Floodlights on. Phones away. Nothing beats a five-a-side finish with this crew.', 'photo-1574629810360-7efbbe195018', 860, 90),
        ('Arjun Patel', 'Cricket', 'Bengaluru', 'A straight drive and a perfect Sunday. Who is joining nets this weekend?', 'photo-1540747913346-19e32dc3e97e', 360, 35),
        ('Neha Singh', 'Basketball', 'Mumbai', 'One more shot after everyone leaves. Putting in the work for the city league.', 'photo-1546519638-68e109498ffc', 130, 12),
        ('Pixel United', 'Esports', 'Bengaluru', 'From ranked nights to our first tournament final. This team never gives up.', 'photo-1542751371-adc38448a05e', 55, 4),
        ('Rohan Das', 'Tennis', 'Delhi', 'Early court, fresh strings, and a new doubles partner. Match day is here.', 'photo-1554068865-24cecd4e34b8', 16, 1),
        ('Sara Khan', 'Running', 'Bengaluru', 'Six sunrise kilometres around the lake. The best part was the company.', 'photo-1552674605-db6ffd4facb5', 190, 18),
        ('Aditi Shah', 'Badminton', 'Bengaluru', 'A comeback from match point down. Every rally counts.', 'photo-1622279457486-62dcc4a431d6', 75, 5),
    ]
    posts = []
    for index, (name, sport, city, text, asset, likes, saves) in enumerate(entries):
        posts.append(dict(id=str(index + 1), authorId='athlete-' + str(index + 1), name=name,
                          initials=''.join(word[0] for word in name.split()), sport=sport, city=city,
                          text=text, image='https://images.unsplash.com/' + asset + '?auto=format&fit=crop&w=1200&q=85',
                          likes=likes, baseSaves=saves, comments=[], liked=False, saved=False,
                          createdAt=(now() - timedelta(hours=index * 2 + 1)).isoformat()))
    stories = [dict(id='story-' + p['id'], name=p['name'], initials=p['initials'], image=p['image'],
                    sport=p['sport'], text=p['text'], expiresAt=(now() + timedelta(hours=24)).isoformat()) for p in posts[:6]]
    return dict(posts=posts, stories=stories, preferences=dict(sports=['Football', 'Esports'], city='Bengaluru', following=['Maya Rao', 'Pixel United']))


@contextmanager
def raw_state():
    if not os.environ.get("SPORTSPACE_SOCIAL_DB"):
        from db import sportspace_state
        with sportspace_state(seed) as data:
            yield data
        return
    # Explicit SQLite override for isolated tests and offline development.
    connection = sqlite3.connect(os.environ.get('SPORTSPACE_SOCIAL_DB', '/tmp/sportspace-social.sqlite3'), timeout=10)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS demo_state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT payload FROM demo_state WHERE id = 1').fetchone()
        data = json.loads(row[0]) if row else seed()
        yield data
        connection.execute('INSERT OR REPLACE INTO demo_state VALUES (1, ?)', (json.dumps(data),))
        connection.commit()
    finally:
        connection.close()


@contextmanager
def state():
    from auth import current_user_id, test_demo_enabled
    from flask import has_request_context
    user_id = current_user_id()
    with raw_state() as data:
        if not has_request_context() or test_demo_enabled():
            yield data
            return
        original_preferences = data['preferences']
        data['preferences'] = data.setdefault('userPreferences', {}).setdefault(user_id, dict(sports=[], following=[], city='', state='', country=''))
        for post in data['posts']:
            # Preserve legacy aggregate likes but isolate new users' interactions.
            post['liked'] = user_id in post.get('likedBy', [])
            post['saved'] = user_id in post.get('savedBy', [])
        try:
            yield data
            for post in data['posts']:
                for flag, collection in (('liked', 'likedBy'), ('saved', 'savedBy')):
                    members = post.setdefault(collection, [])
                    if post[flag] and user_id not in members:
                        members.append(user_id)
                    elif not post[flag] and user_id in members:
                        members.remove(user_id)
        finally:
            data['preferences'] = original_preferences
            for post in data['posts']:
                post['liked'] = False
                post['saved'] = False


def rank(post, data=None):
    if data is None:
        return None
    from arena import ensure_arena, player_rank
    player = next((p for p in ensure_arena(data)['players'] if p['id'] == post.get('authorId')), None)
    return player_rank(player) if player else None


def public(post, data):
    from arena import ensure_arena
    player = next((p for p in ensure_arena(data)['players'] if p['id'] == post.get('authorId')), None)
    identity = {key: player[key] for key in ('name', 'initials')} if player else {}
    allowed = can_view_photos(data, post.get('authorId'))
    result = {**{key: value for key, value in post.items() if key not in ('baseSaves', 'likedBy', 'savedBy', 'reactionsBy')}, **identity, 'reactionCounts': {key: list(post.get('reactionsBy', {}).values()).count(key) for key in ('fire', 'mvp', 'clap')}, 'myReaction': post.get('reactionsBy', {}).get(current_user_id()), 'avatar': player.get('avatar', '') if player and allowed else '', 'rank': rank(post, data), 'time': post['createdAt']}
    if not allowed:
        for key in ('image', 'avatar', 'cover'):
            if key in result:
                result[key] = ''
    return redact_photo_aliases(result, data)


def active_stories(data):
    return [redact_photo_aliases(story, data) for story in data['stories']
            if datetime.fromisoformat(story['expiresAt']) > now() and visible_photo_item(story, data)]


def body():
    if request.path.startswith('/api/auth/') and hasattr(g, 'auth_payload'):
        return g.auth_payload
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def string(value, maximum):
    return isinstance(value, str) and 0 < len(value.strip()) <= maximum


def valid_sport(value):
    return isinstance(value, str) and value in SPORTS


def media_image(image):
    """Accept raster uploads or HTTP(S) links; reject active content."""
    if isinstance(image, str) and image.startswith('data:'):
        from arena import validate_avatar
        return validate_avatar(image, full_photo=True)
    try:
        url = urlparse(image) if isinstance(image, str) else None
        if url is not None and url.scheme in ('http', 'https') and bool(url.hostname) and not url.username and len(image) <= 2048:
            return image
    except ValueError:
        pass
    raise ValueError('Choose a JPG, PNG or WebP photo, or a valid HTTP(S) image URL')


@social.get('/feed')
def feed():
    mode = request.args.get('mode', 'for-you')
    if mode not in ('global', 'country', 'state', 'for-you', 'following', 'local'):
        return jsonify(error='Unknown feed mode'), 400
    with state() as data:
        preferences = data['preferences']
        city = request.args.get('city', preferences['city']).strip()
        sport = request.args.get('sport', 'All sports')
        query = request.args.get('q', '').casefold().strip()
        scored_at = now()
        from arena import discovery_influence, ensure_arena
        value = ensure_arena(data)
        _, influence_sources = discovery_influence(value)
        from geography import location_bucket
        current_player = next(p for p in value['players'] if p['id'] == current_user_id())
        country, region = current_player['country'], current_player['state']
        preferences = {**preferences, 'country': country, 'state': region}

        def in_scope(item):
            bucket = location_bucket(item, country, region)
            return (mode != 'country' or bucket < 2) and (mode != 'state' or bucket == 0)

        def discovery_sources(post):
            if mode == 'following':
                return []
            return [source for source in influence_sources.get(post['authorId'], [])
                    if source['sport'] == post['sport'] and source['boost'] > 0]

        def discovery_boost(post):
            return max((source['boost'] for source in discovery_sources(post)), default=0)

        affinity = {sport: 6 for sport in preferences['sports']}
        for post in data['posts']:
            affinity[post['sport']] = min(18, affinity.get(post['sport'], 0) + int(post['liked']) * 2 + int(post['saved']) * 3 + min(3, sum(c['name'] == 'You' for c in post['comments'])))

        def score(post):
            hours = max(0, (scored_at - datetime.fromisoformat(post['createdAt'])).total_seconds() / 3600)
            locality = post['city'].casefold() == city.casefold()
            tier = {None: 0, 'Silver': 1, 'Gold': 2, 'Diamond': 3, 'Star': 4}[rank(post, data)]
            return (affinity.get(post['sport'], 0) if mode in ('for-you', 'global', 'country', 'state') else 0) + 5 * (post['name'] in preferences['following']) + 12 / (1 + hours / 12) + locality * (2 + tier * 1.5) + min(4, math.log1p(post['likes']) / 2) + discovery_boost(post)

        posts = [post for post in data['posts'] if visible_photo_item(post, data) and
                 (sport in ('All sports', 'All', '') or post['sport'].casefold() == sport.casefold()) and
                 (not query or query in ' '.join([post['text'], post['name'], post['sport'], post['city']]).casefold()) and
                 (mode != 'following' or post['name'] in preferences['following']) and
                 in_scope(post) and
                 (mode != 'local' or post['city'].casefold() == city.casefold())]
        posts.sort(key=lambda post: ((location_bucket(post, country, region) if mode in ('global', 'country', 'state') else 0), -score(post), post['id']))
        return jsonify(posts=[{**public(post, data), 'discoveryBoost': discovery_boost(post),
                               'discoverySources': [source for source in discovery_sources(post)
                                                    if source['boost'] == discovery_boost(post)]}
                              for post in posts], stories=[s for s in active_stories(data) if in_scope(s)], preferences=preferences,
                       scope=dict(mode=mode, country=country, state=region))


@social.route('/preferences', methods=['GET', 'PATCH'])
def preferences():
    payload = body()
    if request.method == 'PATCH':
        if 'sports' in payload and (not isinstance(payload['sports'], list) or any(not isinstance(sport, str) or sport not in SPORTS for sport in payload['sports']) or len(payload['sports']) > len(SPORTS)):
            return jsonify(error='Choose valid sports'), 400
        if 'city' in payload and not string(payload['city'], 80):
            return jsonify(error='City is required (maximum 80 characters)'), 400
        for key in ('country', 'state'):
            if key in payload and not string(payload[key], 80):
                return jsonify(error=f'{key} is required (maximum 80 characters)'), 400
    with state() as data:
        from arena import ensure_arena
        value = ensure_arena(data)
        if request.method == 'PATCH':
            for key in ('sports', 'city', 'country', 'state'):
                if key in payload:
                    data['preferences'][key] = list(dict.fromkeys(payload[key])) if key == 'sports' else payload[key].strip()
            player = next(p for p in value['players'] if p['id'] == current_user_id())
            for key in ('country', 'state', 'city'):
                if key in payload:
                    player[key] = data['preferences'][key]
        return jsonify(data['preferences'])


@social.post('/posts')
def create_post():
    payload = body()
    if not string(payload.get('text'), 3000) or not valid_sport(payload.get('sport')):
        return jsonify(error='Text (1-3000 characters) and a valid sport are required'), 400
    try:
        image = media_image(payload['image']) if payload.get('image') else ''
    except ValueError as error:
        return jsonify(error=str(error)), 400
    with state() as data:
        from arena import ensure_arena
        ensure_arena(data)
        community = None
        if 'communityId' in payload:
            from arena import ensure_arena
            community_id = payload['communityId']
            if isinstance(community_id, str):
                community = next((item for item in ensure_arena(data)['communities'] if item['id'] == community_id), None)
            if community is None:
                return jsonify(error='Arena not found'), 404
            if payload['sport'] != community['sport']:
                return jsonify(error='Post sport must match the Arena sport'), 400
        post = dict(id=uuid4().hex, authorId=current_user_id(), name=next(p['name'] for p in data['arena']['players'] if p['id'] == current_user_id()), initials=next(p['initials'] for p in data['arena']['players'] if p['id'] == current_user_id()), sport=payload['sport'],
                    text=payload['text'].strip(), image=image, likes=0, baseSaves=0, comments=[], liked=False, saved=False,
                    city=community['city'] if community else data['preferences']['city'], createdAt=now().isoformat())
        # A post keeps the author's location at publication, even after a profile move.
        post.update(country=data['preferences']['country'], state=data['preferences']['state'])
        if community:
            post['communityId'] = community['id']
        data['posts'].append(post)
        return jsonify(public(post, data)), 201


@social.post('/posts/<post_id>/<action>')
def engage(post_id, action):
    if action not in ('like', 'save', 'comments', 'reaction'):
        return jsonify(error='Unknown action'), 404
    payload = body()
    if action == 'reaction' and payload.get('reaction') not in ('fire', 'mvp', 'clap'):
        return jsonify(error='Choose a valid reaction'), 400
    if action == 'comments' and not string(payload.get('text'), 1000):
        return jsonify(error='Comment must contain 1-1000 characters'), 400
    with state() as data:
        post = next((p for p in data['posts'] if p['id'] == post_id), None)
        if post is None or not visible_photo_item(post, data):
            return jsonify(error='Post not found'), 404
        if action == 'like':
            post['liked'] = not post['liked']
            post['likes'] += 1 if post['liked'] else -1
        elif action == 'reaction':
            reactions = post.setdefault('reactionsBy', {})
            if reactions.get(current_user_id()) == payload['reaction']:
                reactions.pop(current_user_id())
            else:
                reactions[current_user_id()] = payload['reaction']
        elif action == 'save':
            post['saved'] = not post['saved']
        else:
            from arena import ensure_arena
            author = next(p for p in ensure_arena(data)['players'] if p['id'] == current_user_id())
            post['comments'].append(dict(authorId=current_user_id(), name=author['name'], text=payload['text'].strip()))
        return jsonify(public(post, data))


@social.post('/follow')
def follow():
    name = body().get('name')
    if not string(name, 100) or name == 'You':
        return jsonify(error='A valid athlete name is required'), 400
    with state() as data:
        from arena import ensure_arena
        players = ensure_arena(data)['players']
        if name == next(p['name'] for p in players if p['id'] == current_user_id()):
            return jsonify(error='You cannot follow yourself'), 400
        if name not in {p['name'] for p in players} | {p['name'] for p in data['posts']}:
            return jsonify(error='Athlete not found'), 404
        following = data['preferences']['following']
        following.remove(name) if name in following else following.append(name)
        return jsonify(data['preferences'])


@social.route('/stories', methods=['GET', 'POST'])
def stories():
    payload = body()
    if request.method == 'POST':
        try:
            image = media_image(payload.get('image'))
        except ValueError:
            return jsonify(error='A valid photo or HTTP(S) image URL is required'), 400
        if not valid_sport(payload.get('sport')) or not isinstance(payload.get('text', ''), str) or len(payload.get('text', '')) > 500:
            return jsonify(error='A valid sport and text up to 500 characters are required'), 400
    with state() as data:
        from arena import ensure_arena
        ensure_arena(data)
        if request.method == 'GET':
            return jsonify(stories=active_stories(data))
        from arena import ensure_arena
        player = next(p for p in ensure_arena(data)['players'] if p['id'] == current_user_id())
        story = dict(id=uuid4().hex, authorId=current_user_id(), name=player['name'], initials=player['initials'], image=image, sport=payload['sport'], country=player['country'], state=player['state'], text=payload.get('text', '').strip(), expiresAt=(now() + timedelta(hours=24)).isoformat())
        data['stories'].append(story)
        return jsonify(story), 201
