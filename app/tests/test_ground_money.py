"""Ground applications and offline payment tracking use committed server snapshots."""
from copy import deepcopy
from datetime import datetime

from test_organisations import (accounts, service_clock, create_event, create_ground,
                                event_payload, ground_payload, get, patch, post, slot_start)
from test_tournament_options import database_service
from app import app
from organisations import ground_option_defaults, payment_defaults
from social import raw_state


def ground_options():
    return dict(description='A community ground for evening games.', surface='Artificial turf',
                amenities=['Drinking water', 'Changing room'], capacity=14,
                rules='Wear turf shoes.', contact='Ask at the club reception',
                customDetails=[{'label': 'Parking', 'value': 'Use the east gate'}],
                bookingQuestions=[
                    {'id': 'captain', 'label': 'Captain name', 'type': 'text', 'required': True},
                    {'id': 'equipment', 'label': 'Equipment needed', 'type': 'select',
                     'required': True, 'options': ['Ball', 'None']}],
                deposit=300, paymentMethod='upi', paymentInstructions='Pay at the reception.',
                refundPolicy='Contact the organiser for a refund.')


def book(player, ground, clock, **changes):
    value = dict(groundId=ground['id'], startsAt=slot_start(clock).isoformat())
    value.update(changes)
    response = post(player['client'], '/api/bookings', value)
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json['booking']


def register(player, event, name='Community team'):
    response = post(player['client'], f"/api/tournaments/{event['id']}/registrations", {'teamName': name})
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json['registration']


def test_ground_details_persist_and_legacy_read_defaults_are_compatible(accounts, service_clock):
    owner, player, other = accounts('organisation'), accounts(), accounts('organisation')
    ground = create_ground(owner, **ground_options())
    assert {key: ground[key] for key in ground_options()} == ground_options()
    stored = database_service()['grounds'][0]
    assert {key: stored[key] for key in ground_options()} == ground_options()
    url = f"/api/grounds/{ground['id']}"
    assert patch(other['client'], url, {'surface': 'Clay'}).status_code == 403
    changed = patch(owner['client'], url, {'amenities': ['Parking'], 'capacity': 16})
    assert changed.status_code == 200
    assert changed.json['ground']['amenities'] == ['Parking']
    assert changed.json['ground']['bookingQuestions'] == ground['bookingQuestions']
    with raw_state() as data:
        old_ground = data['organisationService']['grounds'][0]
        for field in ground_option_defaults():
            old_ground.pop(field)
    original = database_service()
    legacy = get(player['client'], '/api/grounds').json['grounds'][0]
    assert {key: legacy[key] for key in ground_option_defaults()} == ground_option_defaults()
    assert database_service() == original


def test_invalid_ground_and_financial_configuration_is_atomic(accounts, service_clock):
    owner = accounts('organisation')
    ground = create_ground(owner)
    event = create_event(owner, service_clock)
    original = database_service()
    invalid_ground = [
        {'description': None}, {'description': 'x' * 2001}, {'surface': 'x' * 101},
        {'capacity': True}, {'capacity': 0}, {'capacity': 201},
        {'amenities': {}}, {'amenities': [' ']}, {'amenities': ['x' * 81]},
        {'amenities': ['Water'] * 13}, {'deposit': -1}, {'deposit': True}, {'deposit': 100001},
        {'customDetails': [{'label': 'Empty', 'value': ''}]},
        {'bookingQuestions': [{'id': 'captain', 'label': 'Captain', 'type': [], 'required': True}]},
        {'bookingQuestions': [{'id': 'equipment', 'label': 'Equipment', 'type': 'select',
                               'required': True, 'options': ['Ball', ' Ball ']}]},
    ]
    invalid_payment = [
        {'paymentMethod': 'card'}, {'paymentMethod': []}, {'paymentInstructions': None},
        {'paymentInstructions': 'x' * 1001}, {'refundPolicy': 'x' * 1001},
    ]
    for change in invalid_ground + invalid_payment:
        attempted = {**ground_payload(), **change}
        assert post(owner['client'], '/api/grounds', attempted).status_code == 400
        assert patch(owner['client'], f"/api/grounds/{ground['id']}", change).status_code == 400
        assert database_service() == original
    for change in invalid_payment + [{'prizePool': -1}, {'prizePool': True}, {'prizePool': 10000001}]:
        assert post(owner['client'], '/api/tournaments', event_payload(service_clock, **change)).status_code == 400
        assert patch(owner['client'], f"/api/tournaments/{event['id']}", change).status_code == 400
        assert database_service() == original


def test_booking_answers_are_private_and_financial_and_question_snapshots_survive_edits(accounts, service_clock):
    owner, player, other = accounts('organisation'), accounts(), accounts()
    ground = create_ground(owner, **ground_options())
    url = '/api/bookings'
    value = dict(groundId=ground['id'], startsAt=slot_start(service_clock).isoformat())
    original = database_service()
    for change in ({}, {'answers': []}, {'answers': {'captain': 'Captain', 'equipment': 'Unlisted'}},
                   {'answers': {'captain': 'Captain', 'equipment': 'None', 'forged': 'hidden'}},
                   {'answers': {'captain': 'Captain', 'equipment': 'Ball'}, 'notes': 'x' * 1001}):
        assert post(player['client'], url, {**value, **change}).status_code == 400
        assert database_service() == original
    booking = book(player, ground, service_clock,
                   answers={'captain': '  Private Captain  ', 'equipment': 'Ball'}, notes='  Private request  ')
    assert booking['answers'] == {'captain': 'Private Captain', 'equipment': 'Ball'}
    assert booking['notes'] == 'Private request'
    assert (booking['price'], booking['deposit'], booking['totalAmount'], booking['paymentStatus']) == (800, 300, 1100, 'unpaid')
    changed = patch(owner['client'], f"/api/grounds/{ground['id']}",
                    {'pricePerHour': 1200, 'deposit': 100, 'paymentMethod': 'cash',
                     'paymentInstructions': 'Updated instructions', 'bookingQuestions': []})
    assert changed.status_code == 200
    assert get(player['client'], url).json['bookings'] == [booking]
    assert get(other['client'], url).json['bookings'] == []
    assert 'Private Captain' not in str(get(other['client'], '/api/grounds').json)
    assert booking['bookingQuestions'] == ground['bookingQuestions']
    assert get(owner['client'], '/api/organisations/me').json['bookings'] == [booking]
    second = book(other, ground, service_clock, startsAt=slot_start(service_clock, hour=11).isoformat())
    assert (second['price'], second['deposit'], second['totalAmount'], second['paymentMethod']) == (1200, 100, 1300, 'cash')
    committed = database_service()['bookings'][0]
    assert committed['answers'] == booking['answers'] and committed['bookingQuestions'] == ground['bookingQuestions']


def test_booking_quotes_reject_changed_prices_terms_or_questions_without_reserving(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    starts = slot_start(service_clock)
    availability_url = f"/api/grounds/{ground['id']}/availability?date={starts.date()}"
    ground_url = f"/api/grounds/{ground['id']}"
    changes = [
        {'pricePerHour': 900}, {'deposit': 100}, {'paymentMethod': 'upi'},
        {'paymentInstructions': 'Ask for the UPI address at reception'},
        {'refundPolicy': 'Refunds are arranged by the organiser'},
        {'bookingQuestions': [{'id': 'captain', 'label': 'Captain name', 'type': 'text', 'required': True}]},
    ]
    for change in changes:
        quote = get(player['client'], availability_url).json
        assert quote['ground']['quoteToken'] == quote['quoteToken']
        assert quote['ground']['quoteToken'] == get(player['client'], '/api/grounds').json['grounds'][0]['quoteToken']
        assert patch(owner['client'], ground_url, change).status_code == 200
        committed = database_service()
        stale = post(player['client'], '/api/bookings',
                     {'groundId': ground['id'], 'startsAt': starts.isoformat(), 'quoteToken': quote['quoteToken']})
        assert stale.status_code == 409
        assert stale.json['error'] == 'Ground prices or booking terms have changed. Review the updated details and choose your slot again.'
        assert database_service() == committed and committed['bookings'] == []
    current = get(player['client'], availability_url).json
    stable_token = current['quoteToken']
    assert current['ground']['pricePerHour'] == 900 and current['ground']['deposit'] == 100
    assert patch(owner['client'], ground_url, {'surface': 'Artificial turf'}).status_code == 200
    assert get(player['client'], availability_url).json['quoteToken'] == stable_token
    committed = database_service()
    for token in (None, True, [], {}, '', 'invalid', 'x' * 64):
        invalid = post(player['client'], '/api/bookings',
                       {'groundId': ground['id'], 'startsAt': starts.isoformat(), 'quoteToken': token})
        assert invalid.status_code == 400
        assert database_service() == committed
    forged = post(player['client'], '/api/bookings',
                  {'groundId': ground['id'], 'startsAt': starts.isoformat(), 'quoteToken': '0' * 64})
    assert forged.status_code == 409 and database_service() == committed
    booking = book(player, ground, service_clock, quoteToken=stable_token, answers={'captain': 'Captain'})
    assert (booking['price'], booking['deposit'], booking['totalAmount']) == (900, 100, 1000)


def test_booking_payment_owner_checks_and_paid_cancel_refund_lifecycle(accounts, service_clock):
    owner, player, other_owner = accounts('organisation'), accounts(), accounts('organisation')
    ground = create_ground(owner, deposit=200)
    booking = book(player, ground, service_clock)
    url = f"/api/bookings/{booking['id']}/payment"
    original = database_service()
    for client, status in ((app.test_client(), 401), (player['client'], 403), (other_owner['client'], 403)):
        assert patch(client, url, {'paymentStatus': 'paid'}).status_code == status
    for change in ({'paymentStatus': 'unpaid'}, {'paymentStatus': []},
                   {'paymentStatus': 'paid', 'paymentReference': 'x' * 201},
                   {'paymentStatus': 'paid', 'totalAmount': 1}):
        assert patch(owner['client'], url, change).status_code == 400
    assert patch(owner['client'], url, {'paymentStatus': 'refunded'}).status_code == 409
    assert database_service() == original
    paid = patch(owner['client'], url, {'paymentStatus': 'paid', 'paymentReference': '  Cash receipt 42  '})
    assert paid.status_code == 200
    assert paid.json['booking']['paymentReference'] == 'Cash receipt 42'
    assert patch(owner['client'], url, {'paymentStatus': 'paid'}).status_code == 409
    totals = get(owner['client'], '/api/organisations/me').json['payments']
    assert totals['groundCollected'] == 1000 and totals['groundOutstanding'] == 0
    cancelled = post(player['client'], f"/api/bookings/{booking['id']}/cancel")
    assert cancelled.json['booking']['paymentStatus'] == 'refund_due'
    totals = get(owner['client'], '/api/organisations/me').json['payments']
    assert totals['groundCollected'] == totals['groundOutstanding'] == 0 and totals['refundDue'] == 1000
    assert patch(owner['client'], url, {'paymentStatus': 'paid'}).status_code == 409
    refunded = patch(owner['client'], url, {'paymentStatus': 'refunded', 'paymentReference': 'Refund receipt'})
    assert refunded.status_code == 200 and refunded.json['booking']['paymentStatus'] == 'refunded'
    assert patch(owner['client'], url, {'paymentStatus': 'refunded'}).status_code == 409
    assert get(owner['client'], '/api/organisations/me').json['payments']['refundDue'] == 0
    assert get(player['client'], '/api/bookings').json['bookings'][0] == refunded.json['booking']
    assert database_service()['bookings'][0]['paymentStatus'] == 'refunded'


def test_ground_deposit_returns_once_after_booking_ends_without_changing_original_total(accounts, service_clock):
    owner, player, other = accounts('organisation'), accounts(), accounts('organisation')
    ground = create_ground(owner, deposit=300)
    booking = book(player, ground, service_clock)
    url = f"/api/bookings/{booking['id']}/payment"
    assert patch(owner['client'], url, {'paymentStatus': 'deposit_refunded'}).status_code == 409
    assert patch(owner['client'], url, {'paymentStatus': 'paid', 'paymentReference': 'Receipt 42'}).status_code == 200
    before = database_service()
    assert patch(owner['client'], url, {'paymentStatus': 'deposit_refunded'}).status_code == 409
    assert database_service() == before
    assert get(owner['client'], '/api/organisations/me').json['payments']['depositReturnDue'] == 0
    service_clock['value'] = datetime.fromisoformat(booking['endsAt'])
    due = get(owner['client'], '/api/organisations/me').json['payments']
    assert due['depositReturnDue'] == 300 and due['refundDue'] == 0
    assert patch(other['client'], url, {'paymentStatus': 'deposit_refunded'}).status_code == 403
    returned = patch(owner['client'], url, {'paymentStatus': 'deposit_refunded', 'paymentReference': 'Return 42'})
    assert returned.status_code == 200
    view = returned.json['booking']
    assert view['paymentStatus'] == 'paid' and view['depositRefunded'] is True
    assert view['depositRefundReference'] == 'Return 42'
    assert view['depositRefundedAt'] == service_clock['value'].isoformat()
    assert view['paymentReference'] == 'Receipt 42'
    assert (view['price'], view['deposit'], view['totalAmount']) == (800, 300, 1100)
    totals = get(owner['client'], '/api/organisations/me').json['payments']
    assert totals['groundCollected'] == 800 and totals['refundDue'] == totals['depositReturnDue'] == 0
    assert patch(owner['client'], url, {'paymentStatus': 'deposit_refunded'}).status_code == 409
    assert post(player['client'], f"/api/bookings/{booking['id']}/cancel").status_code == 409
    assert get(player['client'], '/api/bookings').json['bookings'][0] == view
    stored = database_service()['bookings'][0]
    assert stored['depositRefunded'] is True and stored['totalAmount'] == 1100
    assert patch(owner['client'], f"/api/grounds/{ground['id']}", {'deposit': 0}).status_code == 200
    depositless = book(player, ground, service_clock)
    depositless_url = f"/api/bookings/{depositless['id']}/payment"
    assert patch(owner['client'], depositless_url, {'paymentStatus': 'paid'}).status_code == 200
    service_clock['value'] = datetime.fromisoformat(depositless['endsAt'])
    assert patch(owner['client'], depositless_url, {'paymentStatus': 'deposit_refunded'}).status_code == 409


def test_free_unpaid_and_internal_ground_reservations_never_create_false_revenue(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner, pricePerHour=0)
    free = book(player, ground, service_clock)
    assert free['totalAmount'] == 0 and free['paymentStatus'] == 'not_required'
    assert patch(owner['client'], f"/api/bookings/{free['id']}/payment", {'paymentStatus': 'paid'}).status_code == 409
    assert post(player['client'], f"/api/bookings/{free['id']}/cancel").json['booking']['paymentStatus'] == 'not_required'
    assert patch(owner['client'], f"/api/grounds/{ground['id']}", {'pricePerHour': 500, 'deposit': 100}).status_code == 200
    paid_ground = get(player['client'], '/api/grounds').json['grounds'][0]
    unpaid = book(player, paid_ground, service_clock)
    assert post(player['client'], f"/api/bookings/{unpaid['id']}/cancel").json['booking']['paymentStatus'] == 'cancelled'
    event = create_event(owner, service_clock, paid_ground, publish=True)
    dashboard = get(owner['client'], '/api/organisations/me').json
    reservation = next(item for item in dashboard['bookings'] if item.get('tournamentId') == event['id'])
    assert reservation['price'] == 1000
    assert reservation['deposit'] == reservation['totalAmount'] == 0
    assert reservation['paymentStatus'] == 'not_required'
    assert patch(owner['client'], f"/api/bookings/{reservation['id']}/payment", {'paymentStatus': 'paid'}).status_code == 409
    assert dashboard['payments'] == dict(groundCollected=0, groundOutstanding=0, tournamentCollected=0,
                                        tournamentOutstanding=0, refundDue=0, depositReturnDue=0, currency='INR')
    service_clock['value'] = datetime.fromisoformat(reservation['endsAt'])
    assert get(owner['client'], '/api/organisations/me').json['payments']['depositReturnDue'] == 0
    free_event = create_event(owner, service_clock, publish=True)
    application = register(player, free_event)
    assert application['entryFee'] == application['totalAmount'] == 0
    assert application['paymentStatus'] == 'not_required'
    payment_url = f"/api/tournaments/{free_event['id']}/registrations/{application['id']}/payment"
    assert patch(owner['client'], payment_url, {'paymentStatus': 'paid'}).status_code == 409
    assert post(player['client'], f"/api/tournaments/{free_event['id']}/registrations/me/cancel").json['registration']['paymentStatus'] == 'not_required'


def test_tournament_financial_setup_locks_and_private_snapshots_survive_info_updates(accounts, service_clock):
    owner, player, other_owner, other_player = accounts('organisation'), accounts(), accounts('organisation'), accounts()
    event = create_event(owner, service_clock, entryFee=450, prizePool=12000, paymentMethod='bank_transfer',
                         paymentInstructions='Ask the organiser for account details', refundPolicy='Refund on cancellation', publish=True)
    url = f"/api/tournaments/{event['id']}"
    application = register(player, event)
    assert (application['entryFee'], application['totalAmount'], application['currency'], application['paymentStatus']) == (450, 450, 'INR', 'unpaid')
    original = database_service()
    for change in ({'entryFee': 800}, {'prizePool': 15000}, {'paymentMethod': 'cash'}):
        assert patch(owner['client'], url, change).status_code == 409
        assert database_service() == original
    edited = patch(owner['client'], url, {'paymentInstructions': 'New instructions', 'refundPolicy': 'New policy'})
    assert edited.status_code == 200
    visible = get(player['client'], '/api/tournaments').json['tournaments'][0]
    assert visible['myRegistration'] == application and 'registrations' not in visible
    assert visible['paymentInstructions'] == 'New instructions'
    for account in (other_owner, other_player):
        unrelated = get(account['client'], '/api/tournaments').json['tournaments'][0]
        assert unrelated['myRegistration'] is None and unrelated['myRegistrationHistory'] == []
        assert 'registrations' not in unrelated
    owned = get(owner['client'], '/api/organisations/me').json['tournaments'][0]
    assert owned['registrations'] == [application]
    totals = get(owner['client'], '/api/organisations/me').json['payments']
    assert totals['tournamentOutstanding'] == 450 and totals['tournamentCollected'] == 0
    payment_url = url + f"/registrations/{application['id']}/payment"
    for account, status in ((player, 403), (other_owner, 403)):
        assert patch(account['client'], payment_url, {'paymentStatus': 'paid'}).status_code == status
    second_event = create_event(owner, service_clock, publish=True)
    assert patch(owner['client'], f"/api/tournaments/{second_event['id']}/registrations/{application['id']}/payment", {'paymentStatus': 'paid'}).status_code == 404
    assert patch(owner['client'], payment_url, {'paymentStatus': 'paid', 'paymentReference': 'Bank transfer 42'}).status_code == 200
    assert patch(owner['client'], payment_url, {'paymentStatus': 'deposit_refunded'}).status_code == 409
    assert get(owner['client'], '/api/organisations/me').json['payments']['tournamentCollected'] == 450


def test_tournament_cancellation_marks_paid_refunds_and_unpaid_cancelled_and_keeps_player_history(accounts, service_clock):
    owner, paid_player, unpaid_player = accounts('organisation'), accounts(), accounts()
    event = create_event(owner, service_clock, entryFee=300, publish=True)
    url = f"/api/tournaments/{event['id']}"
    paid = register(paid_player, event, 'Paid team')
    unpaid = register(unpaid_player, event, 'Unpaid team')
    payment_url = url + f"/registrations/{paid['id']}/payment"
    assert patch(owner['client'], payment_url, {'paymentStatus': 'paid'}).status_code == 200
    assert post(owner['client'], url + '/cancel').status_code == 200
    roster = get(owner['client'], url + '/registrations').json['registrations']
    assert {item['id']: item['paymentStatus'] for item in roster} == {paid['id']: 'refund_due', unpaid['id']: 'cancelled'}
    assert all(item['status'] == 'cancelled' for item in roster)
    totals = get(owner['client'], '/api/organisations/me').json['payments']
    assert totals['tournamentCollected'] == totals['tournamentOutstanding'] == 0 and totals['refundDue'] == 300
    mine = get(paid_player['client'], '/api/tournaments').json['tournaments'][0]
    assert mine['myRegistration'] is None
    assert mine['myRegistrationHistory'][0]['paymentStatus'] == 'refund_due'
    assert patch(owner['client'], payment_url, {'paymentStatus': 'refunded', 'paymentReference': 'Return 42'}).status_code == 200
    assert get(owner['client'], '/api/organisations/me').json['payments']['refundDue'] == 0
    assert get(paid_player['client'], '/api/tournaments').json['tournaments'][0]['myRegistrationHistory'][0]['paymentStatus'] == 'refunded'
    unpaid_url = url + f"/registrations/{unpaid['id']}/payment"
    assert patch(owner['client'], unpaid_url, {'paymentStatus': 'paid'}).status_code == 409
    assert patch(owner['client'], unpaid_url, {'paymentStatus': 'refunded'}).status_code == 409


def test_player_withdrawal_preserves_payment_history_when_registering_again(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    event = create_event(owner, service_clock, entryFee=250, publish=True)
    url = f"/api/tournaments/{event['id']}"
    first = register(player, event)
    payment_url = url + f"/registrations/{first['id']}/payment"
    assert patch(owner['client'], payment_url, {'paymentStatus': 'paid'}).status_code == 200
    assert post(player['client'], url + '/registrations/me/cancel').json['registration']['paymentStatus'] == 'refund_due'
    second = register(player, event)
    assert second['id'] != first['id'] and second['paymentStatus'] == 'unpaid'
    mine = get(player['client'], '/api/tournaments').json['tournaments'][0]
    assert mine['myRegistration'] == second and mine['myRegistrationHistory'][0]['id'] == first['id']
    totals = get(owner['client'], '/api/organisations/me').json['payments']
    assert totals['refundDue'] == totals['tournamentOutstanding'] == 250


def test_legacy_money_is_backfilled_once_and_cannot_change_past_obligations(accounts, service_clock):
    owner, player = accounts('organisation'), accounts()
    ground = create_ground(owner)
    booking = book(player, ground, service_clock)
    event = create_event(owner, service_clock, entryFee=325, publish=True)
    application = register(player, event)
    with raw_state() as data:
        service = data['organisationService']
        for key in ('deposit', 'totalAmount', 'paymentStatus', *payment_defaults()):
            service['bookings'][0].pop(key)
        service['bookings'][0].pop('purpose')
        for key in ('entryFee', 'totalAmount', 'currency', 'paymentStatus', *payment_defaults()):
            service['registrations'][0].pop(key)
    legacy = get(owner['client'], '/api/organisations/me').json
    assert legacy['bookings'][0]['totalAmount'] == 800 and legacy['bookings'][0]['deposit'] == 0
    assert legacy['tournaments'][0]['registrations'][0]['totalAmount'] == 325
    frozen = deepcopy(database_service()['registrations'][0])
    with raw_state() as data:
        data['organisationService']['tournaments'][0]['entryFee'] = 900
    assert get(player['client'], '/api/tournaments').json['tournaments'][0]['myRegistration']['totalAmount'] == 325
    assert database_service()['registrations'][0] == frozen
    assert patch(owner['client'], f"/api/grounds/{ground['id']}", {'pricePerHour': 1600, 'deposit': 100}).status_code == 200
    assert get(player['client'], '/api/bookings').json['bookings'][0]['totalAmount'] == 800
    assert patch(owner['client'], f"/api/bookings/{booking['id']}/payment", {'paymentStatus': 'paid'}).status_code == 200
    assert patch(owner['client'], f"/api/tournaments/{event['id']}/registrations/{application['id']}/payment", {'paymentStatus': 'paid'}).status_code == 200
