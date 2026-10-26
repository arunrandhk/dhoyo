"""Sports demo. The shared demo role header is not production authentication."""
from uuid import uuid4

from flask import Blueprint, jsonify, request

from social import body, state
from privacy import public_photos, redact_photo_aliases, visible_photo_item

arena = Blueprint('arena', __name__, url_prefix='/api/arena')
from auth import current_user_id
AWARD_ORDER = ['Star', 'Diamond', 'Gold', 'Silver']
INFLUENCE_TIER_POINTS = {'Star': 4, 'Diamond': 3, 'Gold': 2, 'Silver': 1}
INFLUENCE_SUPPORT_CAP = 1.0
INFLUENCE_MEMBER_FACTOR = 0.2
INFLUENCE_MEMBER_CAP = 1.0


def ensure_communities(value):
    if 'communities' in value:
        return
    entries = [
        ('afterhours-fc', 'Afterhours FC', 'Football', 'Bengaluru', 'Floodlit pitches, late kickoffs, and the people who stay for one more game.'),
        ('zero-ping', 'Zero Ping', 'Esports', 'Online', 'Ranked nights, clutch clips, and your next squad.'),
        ('court-culture', 'Court Culture', 'Basketball', 'Mumbai', 'Pickup runs, street courts, and a community built around the next shot.'),
        ('boundary-club', 'Boundary Club', 'Cricket', 'Bengaluru', 'Weekend nets, big innings, and stories from beyond the boundary.'),
    ]
    value['communities'] = []
    for community_id, name, sport, city, description in entries:
        players = [player for player in value['players'] if player['sport'] == sport]
        image = next((player['image'] for player in players if player['image']), '')
        value['communities'].append(dict(id=community_id, name=name, sport=sport, city=city,
                                         description=description, image=image,
                                         memberIds=[player['id'] for player in players]))


def ensure_arena(data):
    if 'arena' in data:
        ensure_communities(data['arena'])
        from geography import migrate_geography
        migrate_geography(data)
        return data['arena']
    from social import seed
    award_counts = [(3, 20, 30, 40), (0, 4, 8, 12), (0, 0, 5, 8), (0, 2, 4, 6), (0, 0, 0, 3), (1, 3, 6, 8), (0, 0, 2, 5)]
    players = []
    for index, post in enumerate(seed()['posts']):
        players.append(dict(id=post['authorId'], name=post['name'], initials=post['initials'], sport=post['sport'], city=post['city'], image=post['image'], awards=dict(zip(AWARD_ORDER, award_counts[index])), gamesPlayed=120 - index * 12, wins=85 - index * 9, supporters=[], teamId=None))
    players.append(dict(id='demo-user', name='Jordan Davis', initials='JD', sport='Football', city='Bengaluru', image='', awards=dict(zip(AWARD_ORDER, [0, 0, 0, 2])), gamesPlayed=12, wins=7, supporters=[], teamId='team-jordan'))
    teams = [dict(id='team-maya', name='Bengaluru Strikers', sport='Football', city='Bengaluru', ownerId='athlete-1', members=['athlete-1'], requests=[], capacity=11), dict(id='team-jordan', name='Weekend United', sport='Football', city='Bengaluru', ownerId='demo-user', members=['demo-user'], requests=[], capacity=11)]
    players[0]['teamId'] = 'team-maya'
    matches = [dict(id='match-final', sport='Football', home='Bengaluru Strikers', away='City Rovers', homeScore=3, awayScore=1, status='final', clock='FT', venue='Bengaluru Arena', participantIds=['athlete-1', 'demo-user'], organizer='City Sports League'), dict(id='match-live', sport='Cricket', home='Royal XI', away='Metro XI', homeScore='148/3', awayScore='142/8', status='live', clock='18.2 overs', venue='Central Cricket Ground', participantIds=['athlete-2'], organizer='Weekend Cricket League'), dict(id='match-upcoming', sport='Esports', home='Pixel United', away='Neon Five', homeScore=None, awayScore=None, status='upcoming', clock='Tonight 19:00', venue='Online', participantIds=['athlete-4'], organizer='Community Esports Cup')]
    teams.append(dict(id='team-pixel', name='Pixel United', sport='Esports', city='Bengaluru', ownerId='athlete-4', members=['athlete-4'], requests=[], capacity=5))
    players[3]['teamId'] = 'team-pixel'
    teams[1]['requests'].append(dict(id='request-rohan', playerId='athlete-5', status='pending'))
    data['arena'] = dict(players=players, teams=teams, matches=matches, awards=[])
    ensure_communities(data['arena'])
    from geography import migrate_geography
    migrate_geography(data)
    return data['arena']


def player_rank(player):
    return next((tier for tier in AWARD_ORDER if player['awards'].get(tier, 0) > 0), None)


def discovery_influence(value):
    """Captain tier (4/3/2/1) + capped support gives direct members 20%, max 1.

    Only accepted non-owner members benefit; sources never inherit other sources.
    Consumers use the strongest sport-relevant boost, never a sum. Awards stay intact.
    """
    players = {player['id']: player for player in value['players']}
    teams, sources = {}, {player_id: [] for player_id in players}
    for team in value['teams']:
        owner = players.get(team['ownerId'])
        tier = player_rank(owner) if owner else None
        tier_points = INFLUENCE_TIER_POINTS.get(tier, 0)
        support_points = min(len(owner['supporters']) / 5, INFLUENCE_SUPPORT_CAP) if owner else 0
        score = round(tier_points + support_points, 2)
        boost = round(min(INFLUENCE_MEMBER_CAP, score * INFLUENCE_MEMBER_FACTOR), 2)
        accepted_members = set(team['members']) - {team['ownerId']}
        teams[team['id']] = dict(sourcePlayerId=team['ownerId'], sourceRank=tier,
                                tierPoints=tier_points, supportPoints=round(support_points, 2),
                                score=score, memberBoost=boost,
                                acceptedMemberCount=sum(member_id in players for member_id in accepted_members))
        for member_id in set(team['members']):
            if member_id != team['ownerId'] and member_id in sources:
                sources[member_id].append(dict(teamId=team['id'], sourcePlayerId=team['ownerId'], sourceRank=tier, sport=team['sport'], boost=boost))
    return teams, sources


def public_arena(data):
    from auth import pending_account_ids
    value = ensure_arena(data)
    pending_ids = pending_account_ids(data)
    team_influence, player_sources = discovery_influence(value)
    players = []
    for player in value['players']:
        if player['id'] in pending_ids:
            continue
        supporters = player['supporters']
        points = round(len(supporters) / 5, 1)
        players.append({**{key: val for key, val in public_photos(player, data).items() if key != 'supporters'}, 'teamIds': [t['id'] for t in value['teams'] if player['id'] in t['members']], 'rank': player_rank(player), 'communityStars': len(supporters), 'communityPoints': points, 'starScore': round(player['awards']['Star'] + points, 1), 'supported': current_user_id() in supporters})
        players[-1].update(influenceSources=player_sources[player['id']], discoveryBoost=max((source['boost'] for source in player_sources[player['id']]), default=0))
    communities = [{**community, 'joined': current_user_id() in community['memberIds'],
                    'memberCount': len(community['memberIds'])} for community in value['communities']]
    teams = [{**team, 'influence': team_influence[team['id']]} for team in value['teams']]
    rules = dict(tierPoints=INFLUENCE_TIER_POINTS, supportCap=INFLUENCE_SUPPORT_CAP,
                 memberFactor=INFLUENCE_MEMBER_FACTOR, memberCap=INFLUENCE_MEMBER_CAP,
                 supportersPerPoint=5, feeds=['global', 'country', 'state', 'for-you', 'local'])
    return redact_photo_aliases(dict(players=players, teams=teams, communities=communities,
                                    matches=value['matches'], awards=value['awards'],
                                    currentUserId=current_user_id(), awardOrder=AWARD_ORDER,
                                    influenceRules=rules, demo=True), data)


def find(items, item_id):
    return next((item for item in items if item['id'] == item_id), None)


@arena.get('')
def overview():
    with state() as data:
        return jsonify(public_arena(data))


@arena.get('/players/<player_id>')
def player_details(player_id):
    """A profile's activity is independent of the visitor's feed scope."""
    from social import active_stories, public
    with state() as data:
        overview = public_arena(data)
        player = find(overview['players'], player_id)
        if not player:
            return jsonify(error='Player not found'), 404
        teams = [t for t in overview['teams'] if player_id in t['members']]
        matches = [m for m in overview['matches'] if player_id in m['participantIds']]
        connections = {}
        for team in teams:
            for member_id in team['members']:
                if member_id != player_id:
                    connections.setdefault(member_id, dict(playerId=member_id, teamIds=[], matchIds=[]))['teamIds'].append(team['id'])
        for match in matches:
            for member_id in match['participantIds']:
                if member_id != player_id:
                    connections.setdefault(member_id, dict(playerId=member_id, teamIds=[], matchIds=[]))['matchIds'].append(match['id'])
        from friends import relationships
        from messages import registered_players
        players_by_id = registered_players(data)
        if player_id in players_by_id:
            for friendship, peer in relationships(data, player_id, players_by_id):
                if friendship['status'] == 'accepted':
                    connections.setdefault(peer['id'], dict(playerId=peer['id'], teamIds=[], matchIds=[]))['friend'] = True
        posts = sorted((p for p in data['posts'] if p.get('authorId') == player_id and visible_photo_item(p, data)), key=lambda p: p['createdAt'], reverse=True)
        return jsonify(player=player, registeredPlayer=player_id in players_by_id,
                       teams=teams, matches=matches,
                       connections=[{**c, 'player': find(overview['players'], c['playerId'])} for c in connections.values() if find(overview['players'], c['playerId'])],
                       awards=[a for a in overview['awards'] if a['playerId'] == player_id],
                       posts=[public(p, data) for p in posts],
                       stories=[s for s in active_stories(data) if s.get('authorId') == player_id],
                       recordedMatchCount=len(matches), historicalGamesPlayed=player['gamesPlayed'], demo=True)


@arena.post('/location/resolve')
def resolve_location():
    """Called only after the visitor chooses browser location access."""
    import hashlib
    import math
    import time
    from geography import reverse_location
    payload = body()
    latitude, longitude = payload.get('latitude'), payload.get('longitude')
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        return jsonify(error='Provide valid location coordinates'), 400
    fingerprint = hashlib.sha256(f'{round(latitude, 2)},{round(longitude, 2)}'.encode()).hexdigest()
    timestamp = time.time()
    with state() as data:
        cache = data.get('locationLookup', {})
        if cache.get('fingerprint') == fingerprint and timestamp - cache.get('resolvedAt', 0) < 86400 and cache.get('location'):
            return jsonify(location=cache['location'])
        if timestamp - cache.get('attemptedAt', 0) < 2:
            return jsonify(error='Please wait a moment before trying location again'), 429
        data['locationLookup'] = {**cache, 'attemptedAt': timestamp}
    try:
        location = reverse_location(latitude, longitude)
    except Exception:
        return jsonify(error='Could not detect your region. Keep your saved location or enter it manually.'), 502
    with state() as data:
        data['locationLookup'] = dict(fingerprint=fingerprint, location=location,
                                      resolvedAt=timestamp, attemptedAt=timestamp)
    return jsonify(location=location)


@arena.post('/communities/<community_id>/membership')
def community_membership(community_id):
    with state() as data:
        community = find(ensure_arena(data)['communities'], community_id)
        if not community:
            return jsonify(error='Arena not found'), 404
        members = community['memberIds']
        members.remove(current_user_id()) if current_user_id() in members else members.append(current_user_id())
        return jsonify(public_arena(data))


@arena.post('/players/<player_id>/support')
def support(player_id):
    from auth import pending_account_ids
    with state() as data:
        player = find(ensure_arena(data)['players'], player_id)
        if not player or player_id in pending_account_ids(data):
            return jsonify(error='Player not found'), 404
        if player_id == current_user_id():
            return jsonify(error='You cannot support yourself'), 400
        supporters = player['supporters']
        supporters.remove(current_user_id()) if current_user_id() in supporters else supporters.append(current_user_id())
        return jsonify(public_arena(data))


def add_member(value, team, player_id):
    player = find(value['players'], player_id)
    if not player:
        return 'Player not found'
    if any(player_id in other['members'] and other['sport'] == team['sport'] for other in value['teams']):
        return 'Player already belongs to a team for this sport'
    if len(team['members']) >= team['capacity']:
        return 'Team is full'
    team['members'].append(player_id)
    player['teamId'] = team['id']
    for other in value['teams']:
        for application in other['requests']:
            if application['playerId'] == player_id and application['status'] == 'pending' and other['sport'] == team['sport']:
                application['status'] = 'approved' if other['id'] == team['id'] else 'withdrawn'
    return None


@arena.post('/teams/<team_id>/join')
def join(team_id):
    with state() as data:
        value = ensure_arena(data)
        team = find(value['teams'], team_id)
        if not team:
            return jsonify(error='Team not found'), 404
        if any(current_user_id() in other['members'] and other['sport'] == team['sport'] for other in value['teams']):
            return jsonify(error='You already belong to a team for this sport'), 409
        if len(team['members']) >= team['capacity']:
            return jsonify(error='Team is full'), 409
        if any(r['playerId'] == current_user_id() and r['status'] == 'pending' for r in team['requests']):
            return jsonify(error='Request already pending'), 409
        team['requests'].append(dict(id=uuid4().hex, playerId=current_user_id(), status='pending'))
        return jsonify(public_arena(data)), 201


@arena.post('/teams/<team_id>/members')
@arena.post('/teams/<team_id>/requests/<request_id>')
def manage_members(team_id, request_id=None):
    from auth import pending_account_ids
    payload = body()
    with state() as data:
        value = ensure_arena(data)
        team = find(value['teams'], team_id)
        if not team:
            return jsonify(error='Team not found'), 404
        if team['ownerId'] != current_user_id():
            return jsonify(error='Only the team owner can manage members'), 403
        application = None
        if request_id:
            application = find(team['requests'], request_id)
            if not application:
                return jsonify(error='Request not found'), 404
            if application['status'] != 'pending':
                return jsonify(error='Request already resolved'), 409
            if payload.get('action') not in ('approve', 'reject'):
                return jsonify(error='Choose approve or reject'), 400
            if payload['action'] == 'reject':
                application['status'] = 'rejected'
                return jsonify(public_arena(data))
        player_id = application['playerId'] if application else payload.get('playerId')
        if isinstance(player_id, str) and player_id in pending_account_ids(data):
            return jsonify(error='Player not found'), 404
        error = add_member(value, team, player_id)
        if error:
            return jsonify(error=error), 409
        return jsonify(public_arena(data))


@arena.post('/awards')
def award():
    from auth import test_demo_enabled
    if not test_demo_enabled() or request.headers.get('X-Demo-Role') != 'organizer':
        return jsonify(error='Demo organizer role required'), 403
    payload = body()
    tier, count = payload.get('tier'), payload.get('count')
    if tier not in AWARD_ORDER or type(count) is not int or not 1 <= count <= 100:
        return jsonify(error='Choose a valid tier and an integer count from 1 to 100'), 400
    with state() as data:
        value = ensure_arena(data)
        player = find(value['players'], payload.get('playerId'))
        match = find(value['matches'], payload.get('matchId'))
        if not player or not match:
            return jsonify(error='Player or match not found'), 404
        if match['status'] != 'final' or player['id'] not in match['participantIds']:
            return jsonify(error='Awards require a participant in a finalized match'), 400
        if any(a['playerId'] == player['id'] and a['matchId'] == match['id'] and a['tier'] == tier for a in value['awards']):
            return jsonify(error='This match award was already issued'), 409
        player['awards'][tier] += count
        value['awards'].append(dict(id=uuid4().hex, playerId=player['id'], matchId=match['id'], tier=tier, count=count, organizer=match['organizer']))
        return jsonify(public_arena(data)), 201


@arena.patch('/players/<player_id>')
def update_player(player_id):
    from social import string, valid_sport
    if player_id != current_user_id():
        return jsonify(error='You can only edit your own profile'), 403
    payload = body()
    if not payload or set(payload) - {'name', 'city', 'country', 'state', 'sport', 'bio', 'avatar', 'cover', 'photoPrivacy'}:
        return jsonify(error='Provide profile fields only'), 400
    for key, maximum in (('name', 100), ('city', 80), ('country', 80), ('state', 80)):
        if key in payload and not string(payload[key], maximum):
            return jsonify(error=f'{key} must contain 1-{maximum} characters'), 400
    if 'sport' in payload and not valid_sport(payload['sport']):
        return jsonify(error='Choose a valid sport'), 400
    if 'bio' in payload and (not isinstance(payload['bio'], str) or len(payload['bio']) > 280):
        return jsonify(error='Keep your bio under 280 characters'), 400
    if 'photoPrivacy' in payload and payload['photoPrivacy'] not in ('public', 'friends'):
        return jsonify(error='Choose public or friends for photo privacy'), 400
    if 'avatar' in payload:
        try:
            payload['avatar'] = validate_avatar(payload['avatar'])
        except ValueError as error:
            return jsonify(error=str(error)), 400
    if 'cover' in payload:
        try:
            payload['cover'] = validate_avatar(payload['cover'], full_photo=True)
        except ValueError as error:
            return jsonify(error=str(error)), 400
    with state() as data:
        player = find(ensure_arena(data)['players'], player_id)
        if player is None:
            return jsonify(error='Player not found'), 404
        old_name = player['name']
        player.update({key: value.strip() for key, value in payload.items()})
        player['initials'] = ''.join(part[0] for part in player['name'].split())[:2].upper()
        for post in data['posts']:
            if post.get('authorId') == player_id:
                post.update(name=player['name'], initials=player['initials'])
        for story in data['stories']:
            if story.get('authorId') == player_id or (player_id == 'demo-user' and story['name'] == 'You'):
                story.update(authorId=player_id, name=player['name'], initials=player['initials'])
        data['preferences']['following'] = [player['name'] if name == old_name else name for name in data['preferences']['following']]
        if 'city' in payload:
            data['preferences']['city'] = player['city']
        for key in ('country', 'state'):
            if key in payload:
                data['preferences'][key] = player[key]
        return jsonify(public_arena(data))


def validate_avatar(value, full_photo=False):
    """Decode and re-encode raster uploads; never persist arbitrary file content."""
    import base64
    import binascii
    import warnings
    from io import BytesIO
    from PIL import Image, ImageOps, UnidentifiedImageError
    if value == '':
        return ''
    if not isinstance(value, str) or len(value) > 400_000:
        raise ValueError('Please choose a smaller photo')
    try:
        header, encoded = value.split(',', 1)
        if header not in ('data:image/jpeg;base64', 'data:image/png;base64', 'data:image/webp;base64'):
            raise ValueError('Choose a JPG, PNG, or WebP photo')
        raw = base64.b64decode(encoded, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as picture:
                if picture.format not in ('JPEG', 'PNG', 'WEBP') or picture.width * picture.height > 4_000_000:
                    raise ValueError('Please choose a smaller JPG, PNG, or WebP photo')
                picture = ImageOps.exif_transpose(picture).convert('RGB')
                if full_photo:
                    picture.thumbnail((1200, 1200))
                else:
                    picture = ImageOps.fit(picture, (256, 256))
                output = BytesIO()
                picture.save(output, format='JPEG', quality=85)
        return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
    except (ValueError, OSError, binascii.Error, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('That photo could not be read. Try a JPG, PNG, or WebP image.')
