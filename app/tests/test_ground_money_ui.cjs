const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function page({now} = {}) {
  const nodes = new Map();
  const listeners = new Map();
  const node = selector => {
    if (!nodes.has(selector)) {
      const classes = new Set();
      const attributes = new Map();
      const events = new Map();
      nodes.set(selector, {
        innerHTML: '', textContent: '', value: '', hidden: false, disabled: false,
        open: false, isConnected: true, dataset: {},
        classList: {
          add(...values) { values.forEach(value => classes.add(value)); },
          remove(...values) { values.forEach(value => classes.delete(value)); },
          contains(value) { return classes.has(value); },
          toggle(value, force = !classes.has(value)) {
            if (force) classes.add(value); else classes.delete(value);
            return force;
          }
        },
        setAttribute(name, value) { attributes.set(name, String(value)); },
        getAttribute(name) { return attributes.get(name) ?? null; },
        removeAttribute(name) { attributes.delete(name); },
        addEventListener(type, listener) {
          if (!events.has(type)) events.set(type, []);
          events.get(type).push(listener);
        },
        dispatch(type, target = this) {
          for (const listener of events.get(type) || []) listener({target, preventDefault() {}});
        },
        insertAdjacentHTML(position, html) { assert.equal(position, 'beforeend'); this.innerHTML += html; },
        remove() { this.removed = true; this.isConnected = false; },
        querySelector(child) { return node(selector + ' ' + child); },
        querySelectorAll() { return []; },
        focus() { this.focused = true; },
        close() { this.open = false; this.closeCount = (this.closeCount || 0) + 1; }
      });
    }
    return nodes.get(selector);
  };
  const clock = now ? class extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return new Date(now).getTime(); }
  } : Date;
  const context = vm.createContext({
    Date: clock, Intl, Set, Map, Promise, AbortSignal,
    account: {userId: 'player-one', accountType: 'player', organisationId: null},
    accountReady: new Promise(() => {}),
    location: {hash: '#ring'},
    document: {
      body: node('body'), querySelector: node, querySelectorAll() { return []; },
      addEventListener(type, listener) {
        if (!listeners.has(type)) listeners.set(type, []);
        listeners.get(type).push(listener);
      }
    },
    view: 'ring', filter: 'All sports', query: '',
    state: {posts: [], saved: []}, social: {online: true},
    render() {}, navigate() {}, icon() { return ''; }, postHTML() { return ''; },
    toast() {}, modalAction: null,
    escape(value) {
      return String(value).replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[char]));
    },
    $(selector) { return node(selector); }
  });
  context.window = context;
  context.openModal = (title, body, label, action) => {
    context.modalAction = action;
    node('#modal').open = true;
    node('#modal-body').innerHTML = body;
    node('#submit-modal').textContent = label;
  };
  vm.runInContext(readFileSync(path.join(__dirname, '../static/sportspace/organisations.js'), 'utf8'), context);
  const click = dataset => {
    const button = {dataset, disabled: false};
    for (const listener of listeners.get('click') || []) {
      listener({target: {closest: () => button}, preventDefault() {}});
    }
    return button;
  };
  return {context, node, click};
}

function event(overrides = {}) {
  return {
    id: 'event-one', name: 'Community Cup', organisationId: 'org-one',
    organisationName: 'Local Club', sport: 'Football', eventType: 'online',
    status: 'open', startsAt: '2099-01-02T10:00:00+00:00', endsAt: '2099-01-02T12:00:00+00:00',
    registrationClosesAt: '2099-01-02T09:00:00+00:00', timezone: 'UTC',
    registrationCount: 1, capacity: 8, spotsLeft: 7, myRegistration: null,
    ...overrides
  };
}

function ground(overrides = {}) {
  return {
    id: 'ground-one', organisationId: 'org-one', organisationName: 'Local Club',
    name: 'Northside Ground', sport: 'Football', city: 'Pune', address: 'North Road',
    timezone: 'Asia/Kolkata', pricePerHour: 500, currency: 'INR',
    opensAt: '07:00', closesAt: '22:00', ...overrides
  };
}

function booking(overrides = {}) {
  return {
    id: 'booking-one', groundName: 'Northside Ground', playerName: 'Alex',
    startsAt: '2027-01-02T10:00:00Z', endsAt: '2027-01-02T11:00:00Z',
    timezone: 'Asia/Kolkata', price: 500, currency: 'INR',
    status: 'confirmed', purpose: 'player', ...overrides
  };
}

function organisationPage(options) {
  const result = page(options);
  result.context.account = {userId: 'owner', accountType: 'organisation', organisationId: 'org-one'};
  result.context.organisation = {
    id: 'org-one', name: 'Local Club', description: 'Sport for the whole community.',
    sport: 'Football', city: 'Pune', state: 'Maharashtra', country: 'India',
    verificationStatus: 'unverified'
  };
  vm.runInContext("orgService.organisation = organisation; orgService.route = 'organisation'; view = 'organisation';", result.context);
  return result;
}

function captureRequests(context, response) {
  context.requests = [];
  context.response = response;
  // Keep form submission separate from the following dashboard reload.
  vm.runInContext("orgRequest = async (path, method, body) => {requests.push({path, method, body}); return response;}; view = 'ring';", context);
}

function eventForm(overrides = {}) {
  return new Map(Object.entries({
    name: ' Community Cup ', sport: 'Football', eventType: 'online',
    timezone: ' Asia/Kolkata ', startsAt: '2027-01-02T09:00',
    registrationClosesAt: '2027-01-01T18:00', capacity: '8', durationHours: '2',
    ...overrides
  }));
}

function groundForm(overrides = {}) {
  return new Map(Object.entries({
    name: ' Community ground ', sport: 'Football', city: ' Pune ',
    address: ' North Road ', timezone: ' Asia/Kolkata ', pricePerHour: '500',
    opensAt: '07:00', closesAt: '22:00', ...overrides
  }));
}

const settled = () => new Promise(setImmediate);
const plain = value => JSON.parse(JSON.stringify(value));

test('ground cards and full details expose rich venue and money information safely', () => {
  const {context, node} = page();
  const attack = '\"><img src=x onerror="alert(1)">';
  context.fixtureGround = ground({description: attack, surface: 'Natural grass', capacity: 22,
    amenities: ['Floodlights', attack], rules: attack, contact: attack, deposit: 150,
    paymentMethod: 'upi', paymentInstructions: attack, refundPolicy: attack,
    customDetails: [{label: attack, value: attack}],
    bookingQuestions: [{id: 'kit', label: attack, type: 'text', required: true}]});
  vm.runInContext('orgService.grounds = [fixtureGround]', context);
  const card = vm.runInContext('orgGroundCard(fixtureGround)', context);
  assert.match(card, /Natural grass/);
  assert.match(card, /₹150/);
  assert.match(card, /data-org-ground-details="ground-one"/);
  assert.doesNotMatch(card, /<img\b/i);
  vm.runInContext("orgGroundDetails('ground-one')", context);
  const details = node('#modal-body').innerHTML;
  assert.match(details, /Floodlights/);
  assert.match(details, /Natural grass/);
  assert.match(details, /UPI/);
  assert.match(details, /₹650/);
  assert.match(details, /&quot;&gt;&lt;img/);
  assert.doesNotMatch(details, /<img\b/i);
});

test('ground form uses sections and serializes custom details, booking questions and money', async () => {
  const {context, node} = organisationPage();
  captureRequests(context, {ground: {id: 'custom-ground'}});
  vm.runInContext('orgCreateGround()', context);
  const markup = node('#modal-body').innerHTML;
  assert.match(markup, /org-form-section/);
  for (const field of ['description', 'surface', 'capacity', 'amenities', 'rules', 'contact',
    'deposit', 'paymentMethod', 'paymentInstructions', 'refundPolicy']) {
    assert.match(markup, new RegExp('name="' + field + '"'));
  }
  const form = node('#modal');
  form.dispatch('click', {closest: () => ({dataset: {orgAddDetail: ''}})});
  form.dispatch('click', {closest: () => ({dataset: {orgAddQuestion: ''}})});
  context.modalAction(groundForm({tournamentOptions: '1', description: ' Community sport ',
    surface: ' Natural grass ', capacity: '22', amenities: ' Floodlights\n Parking ',
    rules: ' Bring boots ', contact: ' captain@example.com ', deposit: '150',
    paymentMethod: 'upi', paymentInstructions: ' Ask for club UPI ', refundPolicy: ' Refund before 24 hours ',
    detail_d0_label: ' Parking ', detail_d0_value: ' East gate ',
    question_q1_label: ' Kit needed? ', question_q1_type: 'select', question_q1_required: '1',
    question_q1_options: ' Yes\n No ', spoofedPrice: '-99'}));
  await settled();
  assert.equal(context.requests.length, 1);
  assert.equal(context.requests[0].path, 'grounds');
  const payload = plain(context.requests[0].body);
  assert.equal(payload.description, 'Community sport');
  assert.equal(payload.capacity, 22);
  assert.equal(payload.deposit, 150);
  assert.equal(payload.paymentInstructions, 'Ask for club UPI');
  assert.deepEqual(payload.amenities, ['Floodlights', 'Parking']);
  assert.deepEqual(payload.customDetails, [{label: 'Parking', value: 'East gate'}]);
  assert.match(payload.bookingQuestions[0].id, /^[a-zA-Z0-9_-]{1,64}$/);
  assert.deepEqual({...payload.bookingQuestions[0], id: 'stable'}, {
    id: 'stable', label: 'Kit needed?', type: 'select', required: true, options: ['Yes', 'No']
  });
  for (const key of ['registrationQuestions', 'tournamentOptions', 'detail_d0_label', 'spoofedPrice']) {
    assert.equal(key in payload, false);
  }
});

test('ground builder preserves question identifiers and rejects duplicate choices', () => {
  const {context} = page();
  context.fixtureGround = ground({customDetails: [{label: 'Gate', value: 'East'}],
    bookingQuestions: [{id: 'kit-stable', label: 'Kit', type: 'select', required: true, options: ['Yes', 'No']}]});
  vm.runInContext("builder = orgTournamentBuilder(fixtureGround, true, 5, 'ground')", context);
  context.data = new Map(Object.entries({tournamentOptions: '1', detail_d0_label: ' Gate ', detail_d0_value: ' East ',
    question_q1_label: ' Kit ', question_q1_type: 'select', question_q1_required: '1', question_q1_options: 'Yes\nNo'}));
  assert.equal(plain(vm.runInContext('builder.values(data)', context)).bookingQuestions[0].id, 'kit-stable');
  context.data.set('question_q1_options', 'Yes\nYes');
  assert.throws(() => vm.runInContext('builder.values(data)', context), /different choices/);
});

test('money validation rejects invalid integer amounts and unsupported methods before submission', () => {
  const {context} = page();
  for (const [kind, field, bad] of [
    ['ground', 'pricePerHour', '1.5'], ['ground', 'deposit', '-1'], ['ground', 'deposit', 'Infinity'],
    ['ground', 'deposit', '100001'], ['tournament', 'entryFee', '2.5'],
    ['tournament', 'prizePool', '-5'], ['tournament', 'prizePool', 'oops']
  ]) {
    context.data = new Map([[field, bad]]);
    context.kind = kind;
    assert.throws(() => vm.runInContext('orgMoneyInformation(data,kind)', context), /./);
  }
  context.data = new Map([['paymentMethod', 'made_up_method']]);
  assert.throws(() => vm.runInContext("orgMoneyInformation(data,'ground')", context), /./);
  context.data = new Map([['deposit', '150'], ['paymentMethod', 'upi'], ['paymentInstructions', ' Ask club ']]);
  assert.deepEqual(plain(vm.runInContext("orgMoneyInformation(data,'ground')", context)), {
    deposit: 150, paymentMethod: 'upi', paymentInstructions: 'Ask club'
  });
});

test('booking displays an itemized total and posts only validated answers and notes', async () => {
  const {context, node} = page({now: '2027-01-01T00:00:00Z'});
  context.fixtureGround = ground({deposit: 150, paymentMethod: 'cash', paymentInstructions: 'Pay at reception',
    bookingQuestions: [{id: 'kit', label: 'Kit needed?', type: 'select', required: true, options: ['Yes', 'No']}]});
  context.requests = [];
  vm.runInContext(`orgService.grounds = [fixtureGround]; view = 'ring';
    orgRequest = async (path,method,body) => {
      requests.push({path,method,body});
      if(path.includes('/availability'))return {slots:[{startsAt:'2027-01-02T04:30:00Z',label:'10:00',available:true}]};
      return {booking:{id:'booked',status:'confirmed'}};
    }; orgBook('ground-one');`, context);
  await settled();
  const markup = node('#modal-body').innerHTML;
  for (const amount of ['₹500', '₹150', '₹650']) assert.match(markup, new RegExp(amount));
  assert.match(markup, /Pay at reception/);
  assert.match(markup, /name="answer_kit"/);
  const data = new Map([['startsAt', '2027-01-02T04:30:00Z'], ['notes', ' Boots for six players ']]);
  context.modalAction(data);
  await settled();
  assert.equal(context.requests.filter(item => item.method === 'POST').length, 0);
  assert.match(node('#modal .org-form-error').textContent, /required question/);
  data.set('answer_kit', 'Unlisted');
  context.modalAction(data);
  await settled();
  assert.equal(context.requests.filter(item => item.method === 'POST').length, 0);
  data.set('answer_kit', ' Yes ');
  data.set('totalAmount', '-100');
  data.set('paymentStatus', 'paid');
  context.modalAction(data);
  await settled();
  const request = context.requests.find(item => item.method === 'POST');
  assert.deepEqual(plain(request), {path: 'bookings', method: 'POST', body: {
    groundId: 'ground-one', startsAt: '2027-01-02T04:30:00Z', answers: {kit: 'Yes'}, notes: 'Boots for six players'
  }});
  assert.equal(node('#modal').open, false);
});

test('tournament creation includes prize pool and shared payment terms', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  captureRequests(context, {tournament: {id: 'event-money', status: 'draft'}});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext('orgCreateEvent()', context);
  const markup = node('#modal-body').innerHTML;
  for (const field of ['prizePool', 'paymentMethod', 'paymentInstructions', 'refundPolicy']) {
    assert.match(markup, new RegExp('name="' + field + '"'));
  }
  context.modalAction(eventForm({publication: 'draft', entryFee: '500', prizePool: '8000',
    paymentMethod: 'bank_transfer', paymentInstructions: ' Contact for bank details ', refundPolicy: ' Before deadline '}));
  await settled();
  const payload = plain(context.requests[0].body);
  assert.equal(payload.entryFee, 500);
  assert.equal(payload.prizePool, 8000);
  assert.equal(payload.paymentMethod, 'bank_transfer');
  assert.equal(payload.paymentInstructions, 'Contact for bank details');
  assert.equal(payload.refundPolicy, 'Before deadline');
});

test('registration shows tournament money terms while player cannot mark their own fees paid', () => {
  const {context, node} = page();
  context.fixture = event({entryFee: 500, prizePool: 8000, paymentMethod: 'upi',
    paymentInstructions: 'Contact organiser for UPI', refundPolicy: 'Until deadline'});
  vm.runInContext('orgService.tournaments = [fixture]', context);
  vm.runInContext("orgRegister('event-one')", context);
  const markup = node('#modal-body').innerHTML;
  assert.match(markup, /₹500/);
  assert.match(markup, /₹8,000/);
  assert.match(markup, /Contact organiser for UPI/);
  assert.doesNotMatch(markup, /data-org-payment=/);
  context.fixture.myRegistration = {id: 'registration-one', status: 'registered', teamName: 'North Stars',
    totalAmount: 500, entryFee: 500, paymentStatus: 'unpaid', currency: 'INR'};
  assert.doesNotMatch(vm.runInContext('orgTournamentCard(fixture)', context), /data-org-payment=/);
});

test('booking row shows agreed amount, escaped answers and payment reference', () => {
  const {context} = organisationPage();
  const attack = '\"><img src=x onerror="alert(1)">';
  context.fixtureGround = ground({pricePerHour: 999});
  context.fixtureBooking = booking({groundId: 'ground-one', deposit: 150, totalAmount: 650,
    paymentStatus: 'paid', paymentReference: attack, notes: attack,
    bookingQuestions: [{id: 'kit', label: attack, type: 'text', required: true}], answers: {kit: attack}});
  vm.runInContext('orgService.grounds=[fixtureGround]; orgService.bookings=[fixtureBooking]', context);
  const row = vm.runInContext('orgBookingRow(fixtureBooking)', context);
  assert.match(row, /₹650/);
  assert.doesNotMatch(row, /₹999/);
  assert.match(row, /&quot;&gt;&lt;img/);
  assert.doesNotMatch(row, /<img\b/);
});

test('payment form is limited to owner and submits a trimmed reference with PATCH', async () => {
  const {context, node} = organisationPage();
  context.fixtureGround = ground();
  context.fixtureBooking = booking({groundId: 'ground-one', paymentStatus: 'unpaid', deposit: 150, totalAmount: 650});
  vm.runInContext('orgService.grounds=[fixtureGround];orgService.bookings=[fixtureBooking]', context);
  captureRequests(context, {booking: {...context.fixtureBooking, paymentStatus: 'paid'}});
  vm.runInContext("orgRecordPayment('booking-one','booking','','paid')", context);
  assert.equal(node('#modal').open, true);
  context.modalAction(new Map([['paymentReference', ' UPI-123 ']]));
  await settled();
  assert.deepEqual(plain(context.requests), [{path: 'bookings/booking-one/payment', method: 'PATCH',
    body: {paymentStatus: 'paid', paymentReference: 'UPI-123'}}]);
  assert.equal(node('#modal').open, false);
  context.account = {userId: 'player-one', accountType: 'player', organisationId: null};
  vm.runInContext("orgRecordPayment('booking-one','booking','','paid')", context);
  assert.equal(node('#modal').open, false);
  context.account = {userId: 'another-owner', accountType: 'organisation', organisationId: 'org-other'};
  vm.runInContext("orgRecordPayment('booking-one','booking','','paid')", context);
  assert.equal(node('#modal').open, false);
});

test('owner payment buttons are state-specific and player views omit them', () => {
  const {context} = organisationPage();
  context.fixtureGround = ground();
  context.fixtureBooking = booking({groundId: 'ground-one', paymentStatus: 'unpaid', totalAmount: 500});
  vm.runInContext('orgService.grounds=[fixtureGround];orgService.bookings=[fixtureBooking]', context);
  assert.match(vm.runInContext('orgBookingRow(fixtureBooking)', context), /data-org-payment-status="paid"/);
  context.fixtureBooking.paymentStatus = 'refund_due';
  context.fixtureBooking.status = 'cancelled';
  assert.match(vm.runInContext('orgBookingRow(fixtureBooking)', context), /data-org-payment-status="refunded"/);
  context.fixtureBooking.paymentStatus = 'refunded';
  assert.doesNotMatch(vm.runInContext('orgBookingRow(fixtureBooking)', context), /data-org-payment=/);
  context.account = {userId: 'player-one', accountType: 'player', organisationId: null};
  context.fixtureBooking.paymentStatus = 'unpaid';
  assert.doesNotMatch(vm.runInContext('orgBookingRow(fixtureBooking)', context), /data-org-payment=/);
});

test('financial dashboard renders server totals for each service and pending refunds', () => {
  const {context} = organisationPage();
  context.summary = {groundCollected: 650, groundOutstanding: 1200, tournamentCollected: 2000,
    tournamentOutstanding: 3500, refundDue: 800, depositReturnDue: 350, currency: 'INR'};
  vm.runInContext('orgService.payments=summary', context);
  const markup = vm.runInContext('orgFinanceSummary()', context);
  for (const amount of ['₹650', '₹1,200', '₹2,000', '₹3,500', '₹800', '₹350']) assert.match(markup, new RegExp(amount));
  assert.match(markup, /refund/i);
  assert.match(markup, /Deposits awaiting return/);
});

test('owner records tournament registration payments through its event-specific PATCH endpoint', async () => {
  const {context, node} = organisationPage();
  context.fixtureRegistration = {id: 'registration-one', status: 'registered', teamName: 'North Stars',
    entryFee: 400, totalAmount: 400, paymentStatus: 'unpaid', currency: 'INR'};
  context.fixture = event({registrations: [context.fixtureRegistration]});
  vm.runInContext('orgService.tournaments=[fixture]', context);
  captureRequests(context, {registration: {...context.fixtureRegistration, paymentStatus: 'paid'}});
  vm.runInContext("orgRecordPayment('registration-one','registration','event-one','paid')", context);
  assert.equal(node('#modal').open, true);
  context.modalAction(new Map([['paymentReference', ' UPI-TEAM-42 ']]));
  await settled();
  assert.deepEqual(plain(context.requests), [{
    path: 'tournaments/event-one/registrations/registration-one/payment', method: 'PATCH',
    body: {paymentStatus: 'paid', paymentReference: 'UPI-TEAM-42'}
  }]);
  assert.equal(node('#modal').open, false);
  context.account.organisationId = 'org-other';
  vm.runInContext("orgRecordPayment('registration-one','registration','event-one','paid')", context);
  assert.equal(node('#modal').open, false);
});

test('deposit refund is available only for an ended paid player booking and records deposit amount', async () => {
  const {context, node} = organisationPage({now: '2027-01-03T00:00:00Z'});
  context.fixtureGround = ground();
  context.fixtureBooking = booking({groundId: 'ground-one', paymentStatus: 'paid',
    totalAmount: 650, deposit: 150, depositRefunded: false});
  vm.runInContext('orgService.grounds=[fixtureGround];orgService.bookings=[fixtureBooking]', context);
  captureRequests(context, {booking: {...context.fixtureBooking, depositRefunded: true,
    depositRefundReference: 'CASH-DEPOSIT-42'}});
  const row = vm.runInContext('orgBookingRow(fixtureBooking)', context);
  assert.match(row, /data-org-payment-status="deposit_refunded"/);
  vm.runInContext("orgRecordPayment('booking-one','booking','','deposit_refunded')", context);
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal-body').innerHTML, /₹150/);
  assert.doesNotMatch(node('#modal-body').innerHTML, /₹650/);
  context.modalAction(new Map([['paymentReference', ' CASH-DEPOSIT-42 ']]));
  await settled();
  assert.deepEqual(plain(context.requests), [{path: 'bookings/booking-one/payment', method: 'PATCH',
    body: {paymentStatus: 'deposit_refunded', paymentReference: 'CASH-DEPOSIT-42'}}]);
  assert.equal(node('#modal').open, false);
  for (const overrides of [
    {depositRefunded: true}, {deposit: 0}, {paymentStatus: 'unpaid'}, {status: 'cancelled'},
    {purpose: 'tournament'}, {endsAt: '2027-01-04T00:00:00Z'}
  ]) {
    Object.assign(context.fixtureBooking, {groundId: 'ground-one', paymentStatus: 'paid',
      status: 'confirmed', purpose: 'player', deposit: 150, depositRefunded: false,
      endsAt: '2027-01-02T11:00:00Z'}, overrides);
    assert.doesNotMatch(vm.runInContext('orgBookingRow(fixtureBooking)', context), /data-org-payment-status="deposit_refunded"/);
    vm.runInContext("orgRecordPayment('booking-one','booking','','deposit_refunded')", context);
    assert.equal(node('#modal').open, false);
  }
});

test('booking uses current availability money and questions and submits the displayed quote token', async () => {
  const {context, node} = page({now: '2027-01-01T00:00:00Z'});
  context.cachedGround = ground({deposit: 150});
  context.currentGround = ground({pricePerHour: 700, deposit: 200, paymentInstructions: 'Pay updated rate',
    bookingQuestions: [{id: 'players', label: 'Confirm player count', type: 'text', required: true}]});
  context.requests = [];
  vm.runInContext(`orgService.grounds=[cachedGround];view='ring';
    orgRequest=async(path,method,body)=>{
      requests.push({path,method,body});
      if(path.includes('/availability'))return {ground:currentGround,quoteToken:'current-quote-token',
        slots:[{startsAt:'2027-01-02T04:30:00Z',label:'10:00',available:true}]};
      return {booking:{id:'booked-current',status:'confirmed'}};
    };orgBook('ground-one');`, context);
  await settled();
  const money = node('#modal .org-booking-money').innerHTML;
  for (const amount of ['₹700', '₹200', '₹900']) assert.match(money, new RegExp(amount));
  assert.doesNotMatch(money, /₹500|₹650/);
  assert.match(node('#modal .org-booking-information').innerHTML, /Confirm player count/);
  assert.match(node('#modal .org-slot-status').textContent, /Venue details changed/);
  context.modalAction(new Map([['startsAt', '2027-01-02T04:30:00Z'], ['answer_players', ' 6 '],
    ['notes', ' Bring extra kit '], ['quoteToken', 'spoofed-hidden-value']]));
  await settled();
  const posted = context.requests.find(request => request.method === 'POST');
  assert.deepEqual(plain(posted.body), {groundId: 'ground-one', startsAt: '2027-01-02T04:30:00Z',
    answers: {players: '6'}, notes: 'Bring extra kit', quoteToken: 'current-quote-token'});
  assert.equal(node('#modal').open, false);
});

test('stale quote conflict keeps booking dialog open and refreshes money and token before retry', async () => {
  const {context, node} = page({now: '2027-01-01T00:00:00Z'});
  context.cachedGround = ground({deposit: 150});
  context.latestGround = ground({pricePerHour: 800, deposit: 300, paymentInstructions: 'Review latest price'});
  context.requests = [];
  context.messages = [];
  vm.runInContext(`orgService.grounds=[cachedGround];view='ring';let availabilityCalls=0,bookingCalls=0;
    toast=message=>messages.push(message);
    orgRequest=async(path,method,body)=>{
      requests.push({path,method,body});
      if(path.includes('/availability')){
        availabilityCalls++;
        return {ground:availabilityCalls===1?cachedGround:latestGround,
          quoteToken:availabilityCalls===1?'old-token':'refreshed-token',
          slots:[{startsAt:'2027-01-02T04:30:00Z',label:'10:00',available:true}]};
      }
      bookingCalls++;
      if(bookingCalls===1)throw new Error('Ground price or booking terms changed. Review the new details and choose a slot again.');
      return {booking:{id:'confirmed-after-review',status:'confirmed'}};
    };orgBook('ground-one');`, context);
  await settled();
  const data = new Map([['startsAt', '2027-01-02T04:30:00Z'], ['notes', 'Keep this note']]);
  context.modalAction(data);
  await settled();
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal .org-form-error').textContent, /terms changed/);
  assert.match(node('#modal .org-booking-money').innerHTML, /₹1,100/);
  assert.match(node('#modal [name="startsAt"]').innerHTML, /^<option value="">Choose a start time/);
  assert.equal(context.messages.length, 0);
  assert.equal(context.requests.filter(item => item.method === 'POST')[0].body.quoteToken, 'old-token');
  context.modalAction(data);
  await settled();
  assert.equal(context.requests.filter(item => item.method === 'POST')[1].body.quoteToken, 'refreshed-token');
  assert.equal(node('#modal').open, false);
  assert.equal(context.messages.length, 1);
});

