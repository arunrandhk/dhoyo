"""Organisation-owned grounds, reservations, and tournament lifecycle.

All service writes run inside social.raw_state's database transaction. Player
and tournament reservations share the same conflict check and inventory.
"""
import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, jsonify, request

from auth import current_user_id
from social import raw_state, string, valid_sport


organisations = Blueprint('organisations', __name__)
HORIZON_DAYS = 180
ORGANISATION_INPUT_FIELDS = ('name', 'description', 'city', 'state', 'country', 'sport')
GROUND_REQUIRED_FIELDS = ('name', 'sport', 'city', 'address', 'timezone',
                          'pricePerHour', 'opensAt', 'closesAt')
PAYMENT_METHODS = ('arrange_with_organiser', 'cash', 'upi', 'bank_transfer')
PAYMENT_INPUT_FIELDS = ('paymentMethod', 'paymentInstructions', 'refundPolicy')
GROUND_TEXT_LIMITS = {'description': 2000, 'surface': 100, 'rules': 3000, 'contact': 200}
GROUND_OPTION_FIELDS = (*GROUND_TEXT_LIMITS, 'amenities', 'capacity', 'customDetails',
                        'bookingQuestions', 'deposit', *PAYMENT_INPUT_FIELDS)
GROUND_INPUT_FIELDS = (*GROUND_REQUIRED_FIELDS, *GROUND_OPTION_FIELDS)
TOURNAMENT_SCHEDULE_FIELDS = ('name', 'sport', 'eventType', 'startsAt', 'timezone',
                              'registrationClosesAt', 'capacity', 'durationHours', 'groundId')
TOURNAMENT_TEXT_LIMITS = {'description': 2000, 'formatDetails': 200, 'prize': 300,
                          'eligibility': 1000, 'rules': 3000, 'contact': 200,
                          'onlinePlatform': 100}
TOURNAMENT_OPTION_FIELDS = (*TOURNAMENT_TEXT_LIMITS, 'format', 'teamSize', 'entryFee',
                            'customDetails', 'registrationQuestions', 'prizePool',
                            'requirePlayerEmailVerification', 'playerEmailConfirmation', *PAYMENT_INPUT_FIELDS)
TOURNAMENT_INPUT_FIELDS = (*TOURNAMENT_SCHEDULE_FIELDS, *TOURNAMENT_OPTION_FIELDS)
TOURNAMENT_FORMATS = ('single_elimination', 'round_robin', 'groups_knockout', 'custom')
TOURNAMENT_OPEN_EDIT_FIELDS = ('name', *TOURNAMENT_TEXT_LIMITS, 'customDetails',
                              'paymentInstructions', 'refundPolicy')
ORG_FIELDS = ('id', 'name', 'city', 'state', 'country', 'sport',
              'description', 'verificationStatus', 'createdAt')
GROUND_FIELDS = ('id', 'organisationId', 'organisationName', 'name', 'sport',
                 'city', 'address', 'timezone', 'pricePerHour', 'currency',
                 'opensAt', 'closesAt')
BOOKING_FIELDS = ('id', 'groundId', 'groundName', 'playerId', 'playerName',
                  'startsAt', 'endsAt', 'timezone', 'price', 'currency',
                  'status', 'purpose', 'tournamentId')
TOURNAMENT_FIELDS = ('id', 'organisationId', 'organisationName', 'name', 'sport',
                     'eventType', 'startsAt', 'endsAt', 'timezone',
                     'registrationClosesAt', 'capacity', 'groundId',
                     'groundName', 'status')
REGISTRATION_FIELDS = ('id', 'tournamentId', 'playerId', 'playerName',
                       'teamName', 'status')


class ServiceError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@organisations.errorhandler(ServiceError)
def service_error(error):
    return jsonify(error=str(error)), error.status


def now():
    return datetime.now(timezone.utc)


def ensure_service(data):
    service = data.setdefault('organisationService', {})
    for collection in ('organisations', 'grounds', 'bookings', 'tournaments', 'registrations'):
        service.setdefault(collection, [])
    service.setdefault('playerEmailChallenges', {})
    service.setdefault('playerEmailRateLimits', {})
    # Freeze legacy application amounts before a tournament can be edited. New
    # registrations already contain a complete snapshot and need no migration.
    tournaments = {item['id']: item for item in service['tournaments']}
    for registration in service['registrations']:
        tournament = tournaments.get(registration['tournamentId'], {})
        fee = registration.get('entryFee', tournament.get('entryFee', 0))
        registration.setdefault('entryFee', fee)
        registration.setdefault('totalAmount', fee)
        registration.setdefault('currency', 'INR')
        registration.setdefault('paymentStatus', payment_state(
            registration['totalAmount'], registration['status'] == 'registered'))
        for key, default in payment_defaults().items():
            registration.setdefault(key, tournament.get(key, default))
    return service


def find(items, item_id):
    return next((item for item in items if item['id'] == item_id), None)


def create_organisation(data, user_id, name, profile):
    """Called by identity registration while its account transaction is held."""
    organisation = dict(id='org-' + uuid4().hex, name=name.strip(), ownerId=user_id,
                        description='', verificationStatus='unverified',
                        createdAt=now().isoformat())
    organisation.update({key: profile[key].strip()
                         for key in ('city', 'state', 'country', 'sport')})
    ensure_service(data)['organisations'].append(organisation)
    return organisation


def organisation_for_user(data, user_id):
    account = next((account for account in data.get('accounts', {}).values()
                    if account.get('player_id') == user_id), None)
    if not account or account.get('account_type') != 'organisation':
        return None
    return next((organisation for organisation in ensure_service(data)['organisations']
                 if organisation['ownerId'] == user_id and
                 (not account.get('organisation_id') or
                  account['organisation_id'] == organisation['id'])), None)


def actor(data, role=None):
    user_id = current_user_id()
    email, account = next(((email, account) for email, account in data.get('accounts', {}).items()
                           if account.get('player_id') == user_id), (None, None)) if user_id else (None, None)
    if not account:
        raise ServiceError('Sign in with a registered account to continue', 401)
    account_type = account.get('account_type', 'player')
    if account_type not in ('player', 'organisation') or (role and account_type != role):
        raise ServiceError('This action requires an ' + role + ' account' if role
                           else 'This account cannot use this service', 403)
    profile = next((player for player in data.get('arena', {}).get('players', [])
                    if player.get('id') == user_id), {})
    organisation = organisation_for_user(data, user_id) if account_type == 'organisation' else None
    if role == 'organisation' and not organisation:
        raise ServiceError('Organisation account not found', 403)
    return dict(id=user_id, name=profile.get('name', 'Player'), email=email,
                accountType=account_type, organisation=organisation)


def payload(allowed=(), required=()):
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ServiceError('Provide the required fields only')
    return value


def patch_payload(allowed):
    value = payload(allowed)
    if not value:
        raise ServiceError('Provide at least one field to update')
    return value


def zone(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ServiceError('Choose a valid IANA timezone')
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ServiceError('Choose a valid IANA timezone') from None


def instant(value, label='Date and time'):
    if (not isinstance(value, str) or len(value) > 80 or
            not re.fullmatch(r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})', value)):
        raise ServiceError(label + ' must include a UTC offset')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ServiceError(label + ' must be a valid date and time with a UTC offset') from None


def hour(value, closing=False):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-4]):00', value):
        raise ServiceError('Ground hours must use HH:00')
    result = int(value[:2])
    if result == 24 and not closing:
        raise ServiceError('Only closing time can be 24:00')
    return result


def schedule_date(value, venue_zone, timestamp):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ServiceError('Choose a date in YYYY-MM-DD format')
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ServiceError('Choose a valid date') from None
    today = timestamp.astimezone(venue_zone).date()
    if result < today or result > today + timedelta(days=HORIZON_DAYS):
        raise ServiceError('Choose today or a date within the next 180 days')
    return result


def local_instants(naive, venue_zone):
    """Both fall-back hours are real; spring-forward wall hours are not."""
    seen = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=venue_zone, fold=fold).astimezone(timezone.utc)
        if (candidate not in seen and
                candidate.astimezone(venue_zone).replace(tzinfo=None) == naive):
            seen.add(candidate)
            yield candidate


def offered_slots(ground, day):
    venue_zone = zone(ground['timezone'])
    opens, closes = hour(ground['opensAt']), hour(ground['closesAt'], closing=True)
    midnight = datetime.combine(day, time())
    close_local = midnight + timedelta(hours=closes)
    slots = []
    for number in range(opens, closes):
        for starts in local_instants(midnight + timedelta(hours=number), venue_zone):
            ends = starts + timedelta(hours=1)
            if ends.astimezone(venue_zone).replace(tzinfo=None) > close_local:
                continue
            start_local, end_local = starts.astimezone(venue_zone), ends.astimezone(venue_zone)
            label = start_local.strftime('%H:%M') + ' – ' + end_local.strftime('%H:%M')
            if start_local.utcoffset() != end_local.utcoffset() or start_local.fold:
                label += ' (' + start_local.strftime('%z') + ')'
            slots.append(dict(startsAt=starts.isoformat(), endsAt=ends.isoformat(), label=label))
    return sorted(slots, key=lambda slot: slot['startsAt'])


def interval_for_ground(ground, starts, duration, timestamp):
    venue_zone = zone(ground['timezone'])
    day = schedule_date(starts.astimezone(venue_zone).date().isoformat(), venue_zone, timestamp)
    if starts <= timestamp:
        raise ServiceError('Choose a future start time')
    slots = offered_slots(ground, day)
    selected = next((index for index, slot in enumerate(slots)
                     if instant(slot['startsAt']) == starts), None)
    if selected is None:
        raise ServiceError('Choose an offered hourly ground slot')
    ends = starts + timedelta(hours=duration)
    interval = slots[selected:selected + duration]
    if (len(interval) != duration or instant(interval[-1]['endsAt']) != ends or
            any(instant(left['endsAt']) != instant(right['startsAt'])
                for left, right in zip(interval, interval[1:]))):
        raise ServiceError('The event must fit within the ground operating hours')
    return ends


def validate_ground(value):
    if (not string(value['name'], 100) or not valid_sport(value['sport']) or
            not string(value['city'], 80) or not string(value['address'], 200)):
        raise ServiceError('Enter a ground name, valid sport, city and address')
    zone(value['timezone'])
    if type(value['pricePerHour']) is not int or not 0 <= value['pricePerHour'] <= 100000:
        raise ServiceError('Hourly price must be an integer from 0 to 100000 INR')
    if hour(value['closesAt'], closing=True) <= hour(value['opensAt']):
        raise ServiceError('Closing time must be after opening time on the same day')
    result = {key: value[key].strip() if isinstance(value[key], str) else value[key]
              for key in GROUND_REQUIRED_FIELDS}
    options = ground_option_defaults()
    options.update({key: value[key] for key in GROUND_OPTION_FIELDS if key in value})
    for key, maximum in GROUND_TEXT_LIMITS.items():
        options[key] = bounded_text(options[key], maximum, key)
    if type(options['capacity']) is not int or not 1 <= options['capacity'] <= 200:
        raise ServiceError('Ground capacity must be an integer from 1 to 200 players')
    if type(options['deposit']) is not int or not 0 <= options['deposit'] <= 100000:
        raise ServiceError('Deposit must be an integer from 0 to 100000 INR')
    if not isinstance(options['amenities'], list) or len(options['amenities']) > 12:
        raise ServiceError('Add at most 12 ground amenities')
    options['amenities'] = [bounded_text(item, 80, 'Amenity', required=True)
                            for item in options['amenities']]
    options['customDetails'] = validate_custom_details(options['customDetails'])
    options['bookingQuestions'] = validate_questions(options['bookingQuestions'], 'Booking')
    options.update(validate_payment_options(options))
    return {**result, **options}


def owned_ground(service, ground_id, owner):
    ground = find(service['grounds'], ground_id)
    if not ground:
        raise ServiceError('Ground not found', 404)
    if ground['organisationId'] != owner['organisation']['id']:
        raise ServiceError('Only the organisation owner can manage this ground', 403)
    return ground


def validate_ground_commitments(service, ground, candidate, timestamp):
    """Keep existing reservations valid before replacing any ground details."""
    for booking in service['bookings']:
        if (booking['groundId'] != ground['id'] or booking['status'] != 'confirmed' or
                instant(booking['startsAt']) <= timestamp):
            continue
        if ground['sport'] != candidate['sport']:
            raise ServiceError('The ground sport cannot change while future bookings are confirmed', 409)
        starts, ends = instant(booking['startsAt']), instant(booking['endsAt'])
        duration = int((ends - starts).total_seconds() // 3600)
        try:
            candidate_end = interval_for_ground(candidate, starts, duration, timestamp)
            if candidate_end != ends:
                raise ServiceError('The reserved interval must stay available')
        except ServiceError:
            raise ServiceError('These ground details would invalidate a confirmed future booking', 409) from None
    for tournament in service['tournaments']:
        if (tournament['eventType'] != 'physical' or tournament['groundId'] != ground['id'] or
                tournament['status'] in ('cancelled', 'completed') or
                instant(tournament['startsAt']) <= timestamp):
            continue
        if tournament['sport'] != candidate['sport']:
            raise ServiceError('The ground sport must still match its scheduled physical tournaments', 409)
        starts, ends = instant(tournament['startsAt']), instant(tournament['endsAt'])
        duration = int((ends - starts).total_seconds() // 3600)
        try:
            candidate_end = interval_for_ground(candidate, starts, duration, timestamp)
            if candidate_end != ends:
                raise ServiceError('The tournament interval must stay available')
        except ServiceError:
            raise ServiceError('These ground details would invalidate a scheduled physical tournament', 409) from None


def validate_tournament(value, service, owner, timestamp):
    if (not string(value['name'], 100) or not valid_sport(value['sport']) or
            not isinstance(value['eventType'], str) or value['eventType'] not in ('physical', 'online')):
        raise ServiceError('Enter an event name, valid sport and physical or online event type')
    event_zone = zone(value['timezone'])
    starts = instant(value['startsAt'], 'Tournament start')
    registration_closes = instant(value['registrationClosesAt'], 'Registration deadline')
    if type(value['capacity']) is not int or not 2 <= value['capacity'] <= 128:
        raise ServiceError('Tournament capacity must be an integer from 2 to 128')
    if type(value['durationHours']) is not int or not 1 <= value['durationHours'] <= 12:
        raise ServiceError('Duration must be an integer from 1 to 12 hours')
    if value['eventType'] == 'physical' and not string(value.get('groundId'), 100):
        raise ServiceError('Choose an organisation-owned ground for a physical tournament')
    if value['eventType'] == 'online' and value.get('groundId') is not None:
        raise ServiceError('Online tournaments do not have a ground')
    if starts <= timestamp or not timestamp < registration_closes <= starts:
        raise ServiceError('Start and registration deadline must be future dates; registration closes by the start')
    ground = None
    if value['eventType'] == 'physical':
        ground = owned_ground(service, value['groundId'], owner)
        if ground['sport'] != value['sport']:
            raise ServiceError('Tournament sport must match the ground sport')
        ends = interval_for_ground(ground, starts, value['durationHours'], timestamp)
    else:
        schedule_date(starts.astimezone(event_zone).date().isoformat(), event_zone, timestamp)
        ends = starts + timedelta(hours=value['durationHours'])
    return dict(name=value['name'].strip(), sport=value['sport'], eventType=value['eventType'],
                startsAt=starts.isoformat(), endsAt=ends.isoformat(), timezone=value['timezone'],
                registrationClosesAt=registration_closes.isoformat(), capacity=value['capacity'],
                groundId=ground['id'] if ground else None, groundName=ground['name'] if ground else None,
                **validate_tournament_options(value))


def tournament_option_defaults():
    """Fresh containers avoid modifying legacy records while rendering them."""
    return dict.fromkeys(TOURNAMENT_TEXT_LIMITS, '') | dict(
        format='single_elimination', teamSize=5, entryFee=0, prizePool=0,
        customDetails=[], registrationQuestions=[], requirePlayerEmailVerification=False, playerEmailConfirmation='code') | payment_defaults()


def payment_defaults():
    return dict(paymentMethod='arrange_with_organiser', paymentInstructions='', refundPolicy='')


def ground_option_defaults():
    return dict.fromkeys(GROUND_TEXT_LIMITS, '') | dict(
        amenities=[], capacity=22, deposit=0, customDetails=[], bookingQuestions=[]) | payment_defaults()


def payment_state(amount, active=True):
    return 'not_required' if not amount else ('unpaid' if active else 'cancelled')


def validate_payment_options(value):
    result = {key: value.get(key, default) for key, default in payment_defaults().items()}
    if not isinstance(result['paymentMethod'], str) or result['paymentMethod'] not in PAYMENT_METHODS:
        raise ServiceError('Choose arrange with organiser, cash, UPI or bank transfer')
    for key in ('paymentInstructions', 'refundPolicy'):
        result[key] = bounded_text(result[key], 1000, key)
    return result


def bounded_text(value, maximum, label, required=False):
    if (not isinstance(value, str) or len(value) > maximum or
            (required and not value.strip())):
        raise ServiceError(f'{label} must contain ' +
                           (f'1 to {maximum}' if required else f'at most {maximum}') + ' characters')
    return value.strip()


def validate_tournament_options(value):
    result = tournament_option_defaults()
    result.update({key: value[key] for key in TOURNAMENT_OPTION_FIELDS if key in value})
    for key, maximum in TOURNAMENT_TEXT_LIMITS.items():
        result[key] = bounded_text(result[key], maximum, key)
    if not isinstance(result['format'], str) or result['format'] not in TOURNAMENT_FORMATS:
        raise ServiceError('Choose single elimination, round robin, groups and knockout, or a custom format')
    if type(result['teamSize']) is not int or not 1 <= result['teamSize'] <= 50:
        raise ServiceError('Team size must be an integer from 1 to 50 players')
    if result['playerEmailConfirmation'] not in ('code', 'activation_link'):
        raise ServiceError('Choose verification codes or activation links')
    if type(result['requirePlayerEmailVerification']) is not bool:
        raise ServiceError('Choose whether every player email must be verified')
    if type(result['entryFee']) is not int or not 0 <= result['entryFee'] <= 100000:
        raise ServiceError('Entry fee must be an integer from 0 to 100000 INR')
    if type(result['prizePool']) is not int or not 0 <= result['prizePool'] <= 10000000:
        raise ServiceError('Prize pool must be an integer from 0 to 10000000 INR')
    result.update(validate_payment_options(result))
    result['customDetails'] = validate_custom_details(result['customDetails'])
    result['registrationQuestions'] = validate_questions(result['registrationQuestions'], 'Registration')
    return result


def validate_custom_details(details):
    if not isinstance(details, list) or len(details) > 12:
        raise ServiceError('Add at most 12 custom details')
    result = []
    for detail in details:
        if not isinstance(detail, dict) or set(detail) != {'label', 'value'}:
            raise ServiceError('Each custom detail needs a label and value only')
        result.append(dict(
            label=bounded_text(detail['label'], 80, 'Custom detail label', required=True),
            value=bounded_text(detail['value'], 500, 'Custom detail value', required=True)))
    return result


def validate_questions(questions, label='Registration'):
    if not isinstance(questions, list) or len(questions) > 8:
        raise ServiceError(f'Add at most 8 {label.lower()} questions')
    result = []
    ids = set()
    for question in questions:
        required_fields = {'id', 'label', 'type', 'required'}
        if (not isinstance(question, dict) or set(question) - (required_fields | {'options'}) or
                required_fields - set(question)):
            raise ServiceError('Each registration question needs an id, label, type and required choice')
        question_id = question['id']
        if (not isinstance(question_id, str) or
                not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', question_id) or question_id in ids):
            raise ServiceError('Registration question ids must be unique and use letters, numbers, - or _')
        ids.add(question_id)
        if (not isinstance(question['type'], str) or question['type'] not in ('text', 'select') or
                type(question['required']) is not bool):
            raise ServiceError('Choose text or select and whether each registration question is required')
        cleaned = dict(id=question_id,
                       label=bounded_text(question['label'], 160, 'Registration question', required=True),
                       type=question['type'], required=question['required'])
        options = question.get('options', [])
        if question['type'] == 'select':
            if not isinstance(options, list) or not 1 <= len(options) <= 20:
                raise ServiceError('Select questions need 1 to 20 choices')
            cleaned['options'] = [bounded_text(option, 80, 'Registration choice', required=True)
                                  for option in options]
            if len(set(cleaned['options'])) != len(cleaned['options']):
                raise ServiceError('Registration choices must be unique')
        elif options != []:
            raise ServiceError('Only select registration questions can have choices')
        result.append(cleaned)
    return result


def validate_registration_answers(tournament, answers):
    return validate_answers(tournament.get('registrationQuestions', []), answers, 'tournament registration')


def validate_answers(questions, answers, label):
    if not isinstance(answers, dict) or set(answers) - {question['id'] for question in questions}:
        raise ServiceError(f'Provide answers for these {label} questions only')
    result = {}
    for question in questions:
        answer = bounded_text(answers.get(question['id'], ''), 500,
                              'Answer for ' + question['label'], required=question['required'])
        if question['type'] == 'select' and answer and answer not in question['options']:
            raise ServiceError('Choose an offered answer for ' + question['label'])
        if question['id'] in answers:
            result[question['id']] = answer
    return result


def conflicting(service, ground_id, starts, ends):
    return any(booking['groundId'] == ground_id and booking['status'] == 'confirmed' and
               instant(booking['startsAt']) < ends and instant(booking['endsAt']) > starts
               for booking in service['bookings'])


def reserve(service, ground, owner, starts, ends, purpose='player', tournament_id=None):
    """Caller holds raw_state lock; conflict and append are one transaction."""
    if conflicting(service, ground['id'], starts, ends):
        raise ServiceError('That ground slot is already reserved. Choose another time.', 409)
    duration = int((ends - starts).total_seconds() // 3600)
    booking = dict(id='booking-' + uuid4().hex, groundId=ground['id'],
                   groundName=ground['name'], playerId=owner['id'],
                   playerName=owner['name'], startsAt=starts.isoformat(),
                   endsAt=ends.isoformat(), timezone=ground['timezone'],
                   price=ground['pricePerHour'] * duration, currency='INR',
                   status='confirmed', purpose=purpose)
    booking['deposit'] = ground.get('deposit', 0) if purpose == 'player' else 0
    booking['totalAmount'] = booking['price'] + booking['deposit'] if purpose == 'player' else 0
    booking['paymentStatus'] = payment_state(booking['totalAmount'])
    booking.update({key: ground.get(key, default) for key, default in payment_defaults().items()})
    if tournament_id:
        booking['tournamentId'] = tournament_id
    service['bookings'].append(booking)
    return booking


def public_organisation(organisation):
    return {key: organisation[key] for key in ORG_FIELDS}


def public_ground(ground):
    return {**{key: ground[key] for key in GROUND_FIELDS},
            **{key: ground.get(key, default) for key, default in ground_option_defaults().items()},
            'quoteToken': ground_quote_token(ground)}


def ground_quote_token(ground):
    """Bind a displayed quote to server-owned prices and application terms."""
    defaults = ground_option_defaults()
    fields = ('pricePerHour', 'deposit', *PAYMENT_INPUT_FIELDS, 'bookingQuestions')
    quote = {key: ground.get(key, defaults.get(key, 0)) for key in fields}
    encoded = json.dumps(quote, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def public_booking(booking):
    total = booking.get('totalAmount', booking['price'] if booking.get('purpose', 'player') == 'player' else 0)
    return {**{key: booking[key] for key in BOOKING_FIELDS if key in booking},
            'purpose': booking.get('purpose', 'player'),
            'deposit': booking.get('deposit', 0), 'totalAmount': total,
            'paymentStatus': booking.get('paymentStatus', payment_state(total, booking['status'] == 'confirmed')),
            **{key: booking.get(key, default) for key, default in payment_defaults().items()},
            'paymentReference': booking.get('paymentReference', ''),
            'depositRefunded': booking.get('depositRefunded', False),
            'depositRefundedAt': booking.get('depositRefundedAt'),
            'depositRefundReference': booking.get('depositRefundReference', ''),
            'bookingQuestions': booking.get('bookingQuestions', []),
            'answers': booking.get('answers', {}), 'notes': booking.get('notes', '')}


def public_registration(registration):
    return {**{key: registration[key] for key in REGISTRATION_FIELDS},
            'entryFee': registration.get('entryFee', 0),
            'totalAmount': registration.get('totalAmount', registration.get('entryFee', 0)),
            'currency': registration.get('currency', 'INR'),
            'paymentStatus': registration.get('paymentStatus', 'not_required'),
            **{key: registration.get(key, default) for key, default in payment_defaults().items()},
            'paymentReference': registration.get('paymentReference', ''),
            'answers': registration.get('answers', {}), 'notes': registration.get('notes', ''),
            'playerEmails': [{key: deepcopy(value) for key, value in player.items() if key != 'rosterId'} for player in registration.get('playerEmails', [])]}


def active_registrations(service, tournament_id):
    return [registration for registration in service['registrations']
            if registration['tournamentId'] == tournament_id and registration['status'] == 'registered']


def registration_emails(registration, captain_email=None):
    emails = {player['email'].strip().casefold() for player in registration.get('playerEmails', [])}
    if captain_email:
        emails.add(captain_email.strip().casefold())
    return emails


def is_participant(registrations, user_id, email=None):
    email = email.strip().casefold() if email else None
    return any(registration['playerId'] == user_id or email in registration_emails(registration)
               for registration in registrations)


def validate_registration_membership(data, service, tournament, visitor, roster, existing=None):
    """Reserve captains and roster emails together, including pending invitations.

    Called after roster proof validation and before any proofs or places are
    consumed, inside the registration transaction.
    """
    accounts = {account['player_id']: email for email, account in data.get('accounts', {}).items()}
    occupied = set()
    for registration in active_registrations(service, tournament['id']):
        if not existing or registration['id'] != existing['id']:
            occupied.update(registration_emails(registration, accounts.get(registration['playerId'])))
    if registration_emails({'playerEmails': roster}, visitor['email']) & occupied:
        raise ServiceError('A player email is already registered in another team', 409)


def public_tournament(service, tournament, user_id, user_email=None):
    registrations = active_registrations(service, tournament['id'])
    mine = next((registration for registration in registrations if registration['playerId'] == user_id), None)
    history = [item for item in service['registrations'] if item['tournamentId'] == tournament['id']]
    organisation = find(service['organisations'], tournament['organisationId'])
    own = bool(organisation and organisation['ownerId'] == user_id)
    result = {**{key: tournament[key] for key in TOURNAMENT_FIELDS},
            **{key: tournament.get(key, default)
               for key, default in tournament_option_defaults().items()},
            'publishedAt': tournament.get('publishedAt'),
            'registrationCount': len(registrations),
            'spotsLeft': max(0, tournament['capacity'] - len(registrations)),
            'isParticipant': is_participant(registrations, user_id, user_email),
            'myRegistration': public_registration(mine) if mine else None,
            'myRegistrationHistory': [public_registration(item) for item in history
                                      if item['playerId'] == user_id and item['status'] == 'cancelled']}
    if own:
        result['registrations'] = [public_registration(item) for item in history]
    return result


def financial_summary(bookings, registrations):
    result = dict(groundCollected=0, groundOutstanding=0, tournamentCollected=0,
                  tournamentOutstanding=0, refundDue=0, depositReturnDue=0, currency='INR')
    timestamp = now()
    for records, label, active_status in ((bookings, 'ground', 'confirmed'),
                                          (registrations, 'tournament', 'registered')):
        for record in records:
            if label == 'ground' and record.get('purpose', 'player') != 'player':
                continue
            view = public_booking(record) if label == 'ground' else public_registration(record)
            amount, status = view['totalAmount'], view['paymentStatus']
            if status == 'paid':
                result[label + 'Collected'] += amount - (
                    view['deposit'] if label == 'ground' and view['depositRefunded'] else 0)
                if (label == 'ground' and record['status'] == 'confirmed' and
                        not view['depositRefunded'] and instant(record['endsAt']) <= timestamp):
                    result['depositReturnDue'] += view['deposit']
            elif status == 'unpaid' and record['status'] == active_status:
                result[label + 'Outstanding'] += amount
            elif status == 'refund_due':
                result['refundDue'] += amount
    return result


def cancel_payment(record):
    status = record.get('paymentStatus')
    if status == 'paid':
        record['paymentStatus'] = 'refund_due'
    elif status == 'unpaid':
        record['paymentStatus'] = 'cancelled'


def update_payment(record, value, active_status):
    requested = value['paymentStatus']
    if not isinstance(requested, str) or requested not in ('paid', 'refunded', 'deposit_refunded'):
        raise ServiceError('Choose paid, refunded or deposit_refunded')
    reference_key = 'depositRefundReference' if requested == 'deposit_refunded' else 'paymentReference'
    reference = bounded_text(value.get('paymentReference', record.get(reference_key, '')),
                             200, 'Payment reference')
    if record.get('totalAmount', 0) <= 0:
        raise ServiceError('This reservation does not require payment', 409)
    if requested == 'deposit_refunded':
        if (active_status != 'confirmed' or record['status'] != 'confirmed' or
                record.get('paymentStatus') != 'paid' or record.get('deposit', 0) <= 0 or
                record.get('depositRefunded') or now() < instant(record['endsAt'])):
            raise ServiceError('A deposit can only be returned once after a paid ground booking ends', 409)
        record.update(depositRefunded=True, depositRefundedAt=now().isoformat(),
                      depositRefundReference=reference)
        return
    if requested == 'paid':
        if record['status'] != active_status or record.get('paymentStatus') != 'unpaid':
            raise ServiceError('Only an active unpaid reservation can be marked paid', 409)
    elif record['status'] != 'cancelled' or record.get('paymentStatus') != 'refund_due':
        raise ServiceError('Only a cancelled reservation with a refund due can be marked refunded', 409)
    record['paymentStatus'] = requested
    record['paymentReference'] = reference
    record['paymentUpdatedAt'] = now().isoformat()


def owned_tournament(service, tournament_id, owner):
    tournament = find(service['tournaments'], tournament_id)
    if not tournament:
        raise ServiceError('Tournament not found', 404)
    if tournament['organisationId'] != owner['organisation']['id']:
        raise ServiceError('Only the organisation owner can manage this tournament', 403)
    return tournament


def visible_tournament(service, tournament_id, visitor):
    tournament = find(service['tournaments'], tournament_id)
    own = bool(tournament and visitor['organisation'] and
               visitor['organisation']['id'] == tournament['organisationId'])
    if not tournament or (not tournament.get('publishedAt') and not own):
        raise ServiceError('Tournament not found', 404)
    return tournament


def publish_tournament(service, tournament, owner, timestamp):
    """Publish and reserve a physical venue within the caller's transaction."""
    if tournament['status'] != 'draft':
        raise ServiceError('Only a draft tournament can be published', 409)
    starts, ends = instant(tournament['startsAt']), instant(tournament['endsAt'])
    if starts <= timestamp or instant(tournament['registrationClosesAt']) <= timestamp:
        raise ServiceError('Update the event dates before publishing this tournament', 409)
    if tournament['eventType'] == 'physical':
        ground = find(service['grounds'], tournament['groundId'])
        if not ground:
            raise ServiceError('Ground not found', 404)
        hours = int((ends - starts).total_seconds() // 3600)
        interval_for_ground(ground, starts, hours, timestamp)
        reserve(service, ground, dict(id=owner['id'], name=owner['organisation']['name']),
                starts, ends, purpose='tournament', tournament_id=tournament['id'])
    tournament['status'] = 'open'
    tournament['publishedAt'] = timestamp.isoformat()


@organisations.get('/api/organisations')
def organisation_list():
    with raw_state() as data:
        actor(data)
        return jsonify(organisations=[public_organisation(item)
                                     for item in ensure_service(data)['organisations']])


@organisations.get('/api/organisations/me')
def organisation_dashboard():
    with raw_state() as data:
        visitor = actor(data)
        service = ensure_service(data)
        organisation = visitor['organisation']
        grounds = [ground for ground in service['grounds']
                   if organisation and ground['organisationId'] == organisation['id']]
        ground_ids = {ground['id'] for ground in grounds}
        tournaments = [tournament for tournament in service['tournaments']
                       if organisation and tournament['organisationId'] == organisation['id']]
        tournament_ids = {tournament['id'] for tournament in tournaments}
        bookings = [booking for booking in service['bookings'] if booking['groundId'] in ground_ids]
        registrations = [item for item in service['registrations'] if item['tournamentId'] in tournament_ids]
        return jsonify(organisation=public_organisation(organisation) if organisation else None,
                       grounds=[public_ground(ground) for ground in grounds],
                       bookings=[public_booking(booking) for booking in bookings],
                       payments=financial_summary(bookings, registrations),
                       tournaments=[public_tournament(service, tournament, visitor['id'])
                                    for tournament in tournaments])


@organisations.patch('/api/organisations/me')
def update_organisation():
    value = patch_payload(ORGANISATION_INPUT_FIELDS)
    with raw_state() as data:
        owner = actor(data, 'organisation')
        organisation = owner['organisation']
        candidate = {**organisation, **value}
        if (not string(candidate['name'], 100) or
                any(not string(candidate[key], 80) for key in ('city', 'state', 'country')) or
                not valid_sport(candidate['sport'])):
            raise ServiceError('Enter an organisation name, valid sport, city, state and country')
        if not isinstance(candidate['description'], str) or len(candidate['description'].strip()) > 1000:
            raise ServiceError('Organisation description must be at most 1000 characters')
        service = ensure_service(data)
        organisation.update({key: candidate[key].strip() for key in ORGANISATION_INPUT_FIELDS})
        for ground in service['grounds']:
            if ground['organisationId'] == organisation['id']:
                ground['organisationName'] = organisation['name']
        tournament_ids = set()
        for tournament in service['tournaments']:
            if tournament['organisationId'] == organisation['id']:
                tournament['organisationName'] = organisation['name']
                tournament_ids.add(tournament['id'])
        for booking in service['bookings']:
            if booking.get('purpose', 'player') == 'tournament' and booking.get('tournamentId') in tournament_ids:
                booking['playerName'] = organisation['name']
        return jsonify(organisation=public_organisation(organisation))


@organisations.get('/api/grounds')
def ground_list():
    with raw_state() as data:
        actor(data)
        return jsonify(grounds=[public_ground(ground) for ground in ensure_service(data)['grounds']])


@organisations.post('/api/grounds')
def create_ground():
    value = validate_ground(payload(GROUND_INPUT_FIELDS, GROUND_REQUIRED_FIELDS))
    with raw_state() as data:
        owner = actor(data, 'organisation')
        organisation = owner['organisation']
        ground = dict(id='ground-' + uuid4().hex, organisationId=organisation['id'],
                      organisationName=organisation['name'], currency='INR',
                      **value)
        ensure_service(data)['grounds'].append(ground)
        return jsonify(ground=public_ground(ground)), 201


@organisations.patch('/api/grounds/<ground_id>')
def update_ground(ground_id):
    value = patch_payload(GROUND_INPUT_FIELDS)
    with raw_state() as data:
        owner = actor(data, 'organisation')
        service = ensure_service(data)
        ground = owned_ground(service, ground_id, owner)
        candidate = {**ground, **validate_ground({**ground, **value})}
        validate_ground_commitments(service, ground, candidate, now())
        ground.update({key: candidate[key] for key in GROUND_INPUT_FIELDS})
        for tournament in service['tournaments']:
            if tournament['groundId'] == ground_id:
                tournament['groundName'] = ground['name']
        return jsonify(ground=public_ground(ground))


@organisations.get('/api/grounds/<ground_id>/availability')
def ground_availability(ground_id):
    with raw_state() as data:
        actor(data)
        service = ensure_service(data)
        ground = find(service['grounds'], ground_id)
        if not ground:
            raise ServiceError('Ground not found', 404)
        timestamp = now()
        day = schedule_date(request.args.get('date'), zone(ground['timezone']), timestamp)
        slots = offered_slots(ground, day)
        for slot in slots:
            starts, ends = instant(slot['startsAt']), instant(slot['endsAt'])
            slot['available'] = starts > timestamp and not conflicting(service, ground_id, starts, ends)
        return jsonify(groundId=ground_id, date=day.isoformat(), timezone=ground['timezone'], slots=slots,
                       ground=public_ground(ground), quoteToken=ground_quote_token(ground))


@organisations.get('/api/bookings')
def booking_list():
    with raw_state() as data:
        visitor = actor(data)
        return jsonify(bookings=[public_booking(booking) for booking in ensure_service(data)['bookings']
                                 if booking['playerId'] == visitor['id']])


@organisations.post('/api/bookings')
def create_booking():
    value = payload(('groundId', 'startsAt', 'answers', 'notes', 'quoteToken'), ('groundId', 'startsAt'))
    if not string(value['groundId'], 100):
        raise ServiceError('Choose a ground')
    starts = instant(value['startsAt'], 'Booking start')
    with raw_state() as data:
        visitor = actor(data, 'player')
        service = ensure_service(data)
        ground = find(service['grounds'], value['groundId'])
        if not ground:
            raise ServiceError('Ground not found', 404)
        if 'quoteToken' in value:
            token = value['quoteToken']
            if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{64}', token):
                raise ServiceError('Provide a valid ground quote token')
            if token != ground_quote_token(ground):
                raise ServiceError('Ground prices or booking terms have changed. Review the updated details and choose your slot again.', 409)
        answers = validate_answers(ground.get('bookingQuestions', []), value.get('answers', {}), 'booking')
        notes = bounded_text(value.get('notes', ''), 1000, 'Booking notes')
        ends = interval_for_ground(ground, starts, 1, now())
        booking = reserve(service, ground, visitor, starts, ends)
        booking.update(answers=answers, notes=notes,
                       bookingQuestions=deepcopy(ground.get('bookingQuestions', [])))
        return jsonify(booking=public_booking(booking)), 201


@organisations.post('/api/bookings/<booking_id>/cancel')
def cancel_booking(booking_id):
    payload()
    with raw_state() as data:
        visitor = actor(data)
        booking = find(ensure_service(data)['bookings'], booking_id)
        if not booking:
            raise ServiceError('Booking not found', 404)
        if booking['playerId'] != visitor['id']:
            raise ServiceError('Only the booking owner can cancel it', 403)
        if booking.get('purpose', 'player') != 'player':
            raise ServiceError('Cancel the tournament to release its ground reservation', 409)
        if booking['status'] != 'confirmed':
            raise ServiceError('This booking is already cancelled', 409)
        if instant(booking['startsAt']) <= now():
            raise ServiceError('Only future bookings can be cancelled', 409)
        booking['status'] = 'cancelled'
        cancel_payment(booking)
        return jsonify(booking=public_booking(booking))


@organisations.patch('/api/bookings/<booking_id>/payment')
def booking_payment(booking_id):
    value = payload(('paymentStatus', 'paymentReference'), ('paymentStatus',))
    with raw_state() as data:
        owner = actor(data, 'organisation')
        service = ensure_service(data)
        booking = find(service['bookings'], booking_id)
        if not booking:
            raise ServiceError('Booking not found', 404)
        owned_ground(service, booking['groundId'], owner)
        if booking.get('purpose', 'player') != 'player':
            raise ServiceError('Internal tournament ground reservations do not require payment', 409)
        defaults = public_booking(booking)
        for key in ('deposit', 'totalAmount', 'paymentStatus', *PAYMENT_INPUT_FIELDS):
            booking.setdefault(key, defaults[key])
        update_payment(booking, value, 'confirmed')
        return jsonify(booking=public_booking(booking))


@organisations.get('/api/tournaments')
def tournament_list():
    with raw_state() as data:
        visitor = actor(data)
        service = ensure_service(data)
        own_id = visitor['organisation']['id'] if visitor['organisation'] else None
        return jsonify(tournaments=[public_tournament(service, tournament, visitor['id'], visitor['email'])
                                    for tournament in service['tournaments']
                                    if tournament.get('publishedAt') or tournament['organisationId'] == own_id])


@organisations.post('/api/tournaments')
def create_tournament():
    value = payload((*TOURNAMENT_INPUT_FIELDS, 'publish'),
                    tuple(key for key in TOURNAMENT_SCHEDULE_FIELDS if key != 'groundId'))
    if 'publish' in value and type(value['publish']) is not bool:
        raise ServiceError('Choose whether to publish this tournament')
    with raw_state() as data:
        owner = actor(data, 'organisation')
        service = ensure_service(data)
        timestamp = now()
        tournament = dict(id='tournament-' + uuid4().hex, organisationId=owner['organisation']['id'],
                          organisationName=owner['organisation']['name'], status='draft',
                          createdAt=timestamp.isoformat(),
                          **validate_tournament(value, service, owner, timestamp))
        service['tournaments'].append(tournament)
        if value.get('publish'):
            publish_tournament(service, tournament, owner, timestamp)
        return jsonify(tournament=public_tournament(service, tournament, owner['id'])), 201


@organisations.patch('/api/tournaments/<tournament_id>')
def update_tournament(tournament_id):
    value = patch_payload(TOURNAMENT_INPUT_FIELDS)
    with raw_state() as data:
        owner = actor(data, 'organisation')
        service = ensure_service(data)
        tournament = owned_tournament(service, tournament_id, owner)
        if tournament['status'] == 'open':
            if set(value) - set(TOURNAMENT_OPEN_EDIT_FIELDS):
                raise ServiceError('Only tournament information can change after publishing; event setup is locked', 409)
            if instant(tournament['startsAt']) <= now():
                raise ServiceError('Tournament details can only change before the event starts', 409)
            cleaned = validate_tournament_options({**tournament, **value})
            cleaned['name'] = bounded_text(value.get('name', tournament['name']), 100,
                                           'Tournament name', required=True)
            tournament.update({key: cleaned[key] for key in value})
            return jsonify(tournament=public_tournament(service, tournament, owner['id']))
        if tournament['status'] != 'draft':
            raise ServiceError('Only a draft or upcoming open tournament can be edited', 409)
        candidate = {key: tournament[key] for key in TOURNAMENT_SCHEDULE_FIELDS
                     if key != 'durationHours'}
        candidate.update({key: tournament[key] for key in TOURNAMENT_OPTION_FIELDS if key in tournament})
        candidate['durationHours'] = int((instant(tournament['endsAt']) -
                                          instant(tournament['startsAt'])).total_seconds() // 3600)
        candidate.update(value)
        if value.get('eventType') == 'online' and 'groundId' not in value:
            candidate['groundId'] = None
        tournament.update(validate_tournament(candidate, service, owner, now()))
        return jsonify(tournament=public_tournament(service, tournament, owner['id']))


@organisations.post('/api/tournaments/<tournament_id>/<action>')
def tournament_action(tournament_id, action):
    if action not in ('publish', 'start', 'complete', 'cancel'):
        raise ServiceError('Unknown tournament action', 404)
    payload()
    with raw_state() as data:
        owner = actor(data, 'organisation')
        service = ensure_service(data)
        tournament = owned_tournament(service, tournament_id, owner)
        timestamp = now()
        starts, ends = instant(tournament['startsAt']), instant(tournament['endsAt'])
        if action == 'publish':
            publish_tournament(service, tournament, owner, timestamp)
        elif action == 'start':
            if tournament['status'] != 'open':
                raise ServiceError('Only an open tournament can be started', 409)
            if not starts <= timestamp < ends:
                raise ServiceError('Start the tournament during its scheduled time', 409)
            if len(active_registrations(service, tournament_id)) < 2:
                raise ServiceError('At least two registered teams are needed to start', 409)
            tournament['status'] = 'live'
        elif action == 'complete':
            if tournament['status'] != 'live':
                raise ServiceError('Only a live tournament can be completed', 409)
            tournament['status'] = 'completed'
        else:
            if tournament['status'] not in ('draft', 'open'):
                raise ServiceError('Only a draft or open tournament can be cancelled', 409)
            for booking in service['bookings']:
                if booking.get('tournamentId') == tournament_id and booking.get('purpose', 'player') == 'tournament' and booking['status'] == 'confirmed':
                    booking['status'] = 'cancelled'
            for registration in active_registrations(service, tournament_id):
                registration['status'] = 'cancelled'
                cancel_payment(registration)
            tournament['status'] = 'cancelled'
        return jsonify(tournament=public_tournament(service, tournament, owner['id']))


@organisations.post('/api/tournaments/<tournament_id>/player-emails/request-code')
def request_player_email_code(tournament_id):
    from tournament_verification import request_code
    return request_code(tournament_id)


@organisations.post('/api/tournaments/<tournament_id>/player-emails/verify-code')
def verify_player_email_code(tournament_id):
    from tournament_verification import verify_code
    return verify_code(tournament_id)


@organisations.post('/api/tournaments/<tournament_id>/registrations')
def register_team(tournament_id):
    from tournament_verification import registration_roster, consume_roster_proofs
    value = payload(('teamName', 'answers', 'notes', 'playerEmails'), ('teamName',))
    if not string(value['teamName'], 60):
        raise ServiceError('Enter a team name with 1 to 60 characters')
    with raw_state() as data:
        visitor = actor(data, 'player')
        service = ensure_service(data)
        tournament = visible_tournament(service, tournament_id, visitor)
        if tournament['status'] != 'open' or now() >= instant(tournament['registrationClosesAt']):
            raise ServiceError('Registration is closed for this tournament', 409)
        answers = validate_registration_answers(tournament, value.get('answers', {}))
        notes = bounded_text(value.get('notes', ''), 1000, 'Registration notes')
        registrations = active_registrations(service, tournament_id)
        if is_participant(registrations, visitor['id'], visitor['email']):
            raise ServiceError('You have already registered for this tournament', 409)
        team_name = value['teamName'].strip()
        if any(registration['teamName'].casefold() == team_name.casefold() for registration in registrations):
            raise ServiceError('That team name is already registered', 409)
        if len(registrations) >= tournament['capacity']:
            raise ServiceError('This tournament is full', 409)
        roster, proofs = registration_roster(service, tournament, visitor, value)
        validate_registration_membership(data, service, tournament, visitor, roster)
        registration = dict(id='registration-' + uuid4().hex, tournamentId=tournament_id,
                            playerId=visitor['id'], playerName=visitor['name'],
                            teamName=team_name, status='registered', answers=answers, notes=notes,
                            entryFee=tournament.get('entryFee', 0),
                            totalAmount=tournament.get('entryFee', 0), currency='INR',
                            paymentStatus=payment_state(tournament.get('entryFee', 0)),
                            **{key: tournament.get(key, default)
                               for key, default in payment_defaults().items()})
        registration['playerEmails'] = roster
        consume_roster_proofs(proofs, registration['id'])
        service['registrations'].append(registration)
        return jsonify(registration=public_registration(registration)), 201


@organisations.patch('/api/tournaments/<tournament_id>/registrations/me')
def update_registration(tournament_id):
    from tournament_verification import registration_roster, consume_roster_proofs
    value = payload(('teamName', 'answers', 'notes', 'playerEmails'), ('teamName',))
    if not string(value['teamName'], 60):
        raise ServiceError('Enter a team name with 1 to 60 characters')
    with raw_state() as data:
        visitor = actor(data, 'player')
        service = ensure_service(data)
        tournament = visible_tournament(service, tournament_id, visitor)
        registrations = active_registrations(service, tournament_id)
        registration = next((item for item in registrations if item['playerId'] == visitor['id']), None)
        if not registration:
            raise ServiceError('Active tournament registration not found', 404)
        if tournament['status'] != 'open' or now() >= instant(tournament['registrationClosesAt']):
            raise ServiceError('Team details can only be updated before registration closes', 409)
        answers = validate_registration_answers(tournament, value.get('answers', registration.get('answers', {})))
        notes = bounded_text(value.get('notes', registration.get('notes', '')), 1000, 'Registration notes')
        team_name = value['teamName'].strip()
        if any(item['id'] != registration['id'] and item['teamName'].casefold() == team_name.casefold()
               for item in registrations):
            raise ServiceError('That team name is already registered', 409)
        roster, proofs = registration_roster(service, tournament, visitor, value, registration)
        validate_registration_membership(data, service, tournament, visitor, roster, registration)
        consume_roster_proofs(proofs, registration['id'])
        registration['teamName'] = team_name
        registration['answers'] = answers
        registration['notes'] = notes
        registration['playerEmails'] = roster
        return jsonify(registration=public_registration(registration))


@organisations.post('/api/tournaments/<tournament_id>/registrations/me/cancel')
def cancel_registration(tournament_id):
    payload()
    with raw_state() as data:
        visitor = actor(data, 'player')
        service = ensure_service(data)
        tournament = visible_tournament(service, tournament_id, visitor)
        registration = next((registration for registration in active_registrations(service, tournament_id)
                             if registration['playerId'] == visitor['id']), None)
        if not registration:
            raise ServiceError('Active tournament registration not found', 404)
        if tournament['status'] != 'open' or now() >= instant(tournament['startsAt']):
            raise ServiceError('Registration can only be cancelled before the open event starts', 409)
        registration['status'] = 'cancelled'
        cancel_payment(registration)
        return jsonify(registration=public_registration(registration))


@organisations.patch('/api/tournaments/<tournament_id>/registrations/<registration_id>/payment')
def registration_payment(tournament_id, registration_id):
    value = payload(('paymentStatus', 'paymentReference'), ('paymentStatus',))
    with raw_state() as data:
        owner = actor(data, 'organisation')
        service = ensure_service(data)
        owned_tournament(service, tournament_id, owner)
        registration = find(service['registrations'], registration_id)
        if not registration or registration['tournamentId'] != tournament_id:
            raise ServiceError('Tournament registration not found', 404)
        update_payment(registration, value, 'registered')
        return jsonify(registration=public_registration(registration))


@organisations.get('/api/tournaments/<tournament_id>/registrations')
def tournament_registrations(tournament_id):
    with raw_state() as data:
        owner = actor(data, 'organisation')
        service = ensure_service(data)
        owned_tournament(service, tournament_id, owner)
        return jsonify(registrations=[public_registration(registration) for registration in service['registrations']
                                     if registration['tournamentId'] == tournament_id])


@organisations.post('/api/tournaments/<tournament_id>/player-emails/send-activation')
def send_player_activation(tournament_id):
    from tournament_activation import send_activation
    return send_activation(tournament_id)


@organisations.post('/api/auth/tournament-acknowledgement')
def acknowledge_player_activation():
    from tournament_activation import acknowledge
    return acknowledge()


@organisations.get('/tournament-acknowledgement')
def player_activation_page():
    from flask import send_from_directory, current_app
    from auth import secure_transport
    if not secure_transport():
        return jsonify(error='Use HTTPS to acknowledge participation'), 403
    return send_from_directory(current_app.static_folder, 'sportspace/tournament-acknowledgement.html')
