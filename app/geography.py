"""Explicit player geography and a conservative migration for existing demo cities."""
CITY_STATES = {'bengaluru': 'Karnataka', 'bangalore': 'Karnataka', 'mumbai': 'Maharashtra',
               'delhi': 'Delhi', 'new delhi': 'Delhi', 'chennai': 'Tamil Nadu',
               'hyderabad': 'Telangana', 'pune': 'Maharashtra', 'kolkata': 'West Bengal'}


def normalize(value):
    return str(value or '').strip().casefold()


def migrate_geography(data):
    """Fill missing fields only; never overwrite an explicitly selected location."""
    preferences = data['preferences']
    preferences.setdefault('country', 'India')
    preferences.setdefault('state', CITY_STATES.get(normalize(preferences.get('city')), ''))
    players = data.get('arena', {}).get('players', [])
    by_id = {p['id']: p for p in players}
    for player in players:
        player.setdefault('country', 'India')
        player.setdefault('state', CITY_STATES.get(normalize(player.get('city')), ''))
    for post in data['posts']:
        post.setdefault('country', 'India')
        post.setdefault('state', CITY_STATES.get(normalize(post.get('city')), ''))
    for story in data['stories']:
        if not story.get('authorId'):
            # Original seed story IDs are derived from their source post.
            post = next((p for p in data['posts'] if story['id'] == 'story-' + p['id']), None)
            player = next((p for p in players if p['name'] == story['name']), None)
            author = post.get('authorId') if post else player['id'] if player else None
            if author:
                story['authorId'] = author
        author = by_id.get(story.get('authorId'), {})
        story.setdefault('country', author.get('country', 'India'))
        story.setdefault('state', author.get('state', ''))


def location_bucket(item, country, region):
    """0 = same state and country, 1 = same country, 2 = elsewhere/unknown."""
    if country and normalize(item.get('country')) == normalize(country):
        if region and normalize(item.get('state')) == normalize(region):
            return 0
        return 1
    return 2


def reverse_location(latitude, longitude):
    """Resolve coarse coordinates; return only the region used by the feed."""
    import json
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    query = urlencode(dict(lat=round(latitude, 2), lon=round(longitude, 2), format='jsonv2', zoom=10,
                           addressdetails=1, **{'accept-language': 'en'}))
    lookup = Request('https://nominatim.openstreetmap.org/reverse?' + query,
                     headers={'User-Agent': 'dhoyo-demo/1.0 (https://github.com/gurpreetrandhk/byte-devops)'})
    with urlopen(lookup, timeout=5) as response:
        address = json.loads(response.read(100_000)).get('address', {})
    country = address.get('country', '')
    region = address.get('state') or address.get('region') or address.get('province') or ''
    city = address.get('city') or address.get('town') or address.get('village') or address.get('municipality') or address.get('county') or region
    if not all(isinstance(value, str) and 0 < len(value.strip()) <= 80 for value in (country, region, city)):
        raise ValueError('Location does not contain a city, state and country')
    return dict(city=city.strip(), state=region.strip(), country=country.strip())
