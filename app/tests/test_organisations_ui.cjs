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

test('API registered status shows the team and withdrawal action without another join', () => {
  const {context} = page();
  context.fixture = event({myRegistration: {status: 'registered', teamName: 'North Stars'}});
  const card = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(card, /Your team: North Stars/);
  assert.match(card, /data-org-withdraw="event-one"/);
  assert.match(card, /data-org-edit-registration="event-one"/);
  assert.doesNotMatch(card, /data-org-register=/);
  vm.runInContext('orgService.tournaments=[fixture];', context);
  const activity = vm.runInContext('orgActivity()', context);
  assert.match(activity, /Community Cup/);
  assert.match(activity, /North Stars/);
  assert.doesNotMatch(activity, /Your next competition is waiting/);
});

test('roster members see their participation in tournaments and activity without captain controls', () => {
  const {context, node} = page();
  context.fixture = event({isParticipant: true});
  const card = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(card, /Already registered as a team member/);
  assert.doesNotMatch(card, /data-org-(?:register|edit-registration|withdraw)=/);
  assert.doesNotMatch(card, /Your team:|Your entry:|players Acknowledged/);
  assert.match(card, /data-org-event-details="event-one"/);
  vm.runInContext('orgService.tournaments=[fixture]', context);
  const activity = vm.runInContext('orgActivity()', context);
  assert.match(activity, /Community Cup/);
  assert.match(activity, /Already registered as a team member/);
  assert.doesNotMatch(activity, /Your next competition is waiting|data-org-(?:register|edit-registration|withdraw)=/);
  vm.runInContext("orgEditRegistration('event-one')", context);
  assert.equal(node('#modal').open, false);
});

test('direct registration stops existing captains and roster members before opening a form', () => {
  for (const registration of [
    {isParticipant: true},
    {myRegistration: {status: 'registered', teamName: 'North Stars'}},
    {isParticipant: true, myRegistration: {status: 'registered', teamName: 'North Stars'}}
  ]) {
    const {context, node} = page();
    context.fixture = event(registration);
    captureRequests(context, {});
    vm.runInContext("orgService.tournaments=[fixture]; orgRegister('event-one')", context);
    assert.equal(context.location.hash, 'activity');
    assert.equal(node('#modal').open, false);
    assert.equal(context.requests.length, 0);
  }
});

test('players without an active registration can still open registration', () => {
  for (const registration of [
    {isParticipant: false},
    {isParticipant: false, myRegistration: {status: 'cancelled', teamName: 'Previous team'}}
  ]) {
    const {context, node} = page();
    context.fixture = event(registration);
    const card = vm.runInContext('orgTournamentCard(fixture)', context);
    assert.match(card, /data-org-register="event-one"/);
    assert.doesNotMatch(card, /Already registered as a team member/);
    vm.runInContext("orgService.tournaments=[fixture]; orgRegister('event-one')", context);
    assert.equal(node('#modal').open, true);
    assert.match(node('#modal-body').innerHTML, /name="teamName"/);
  }
});

test('owner cards explain private drafts and published player visibility', () => {
  const {context} = organisationPage();
  context.fixture = event({status: 'draft', publishedAt: null});
  const draft = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(draft, /Private draft/);
  assert.match(draft, /Publish event to make it visible in player accounts/);
  context.fixture = event({publishedAt: '2027-01-01T00:00:00Z'});
  const published = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(published, /Published · Visible in player accounts/);
  assert.doesNotMatch(published, /Private draft/);
});

test('registered team edit prefills escaped name and saves only the owning registration', async () => {
  const {context, node, click} = page();
  context.fixture = event({myRegistration: {status: 'registered', teamName: '\"><img src=x>'}});
  vm.runInContext('orgService.tournaments = [fixture]', context);
  captureRequests(context, {registration: {id: 'registration-one', status: 'registered'}});
  click({orgEditRegistration: 'event-one'});
  assert.match(node('#modal-body').innerHTML, /name="teamName" value="&quot;&gt;&lt;img/);
  assert.doesNotMatch(node('#modal-body').innerHTML, /<img\b/);
  assert.equal(context.modalAction(new Map([['teamName', ' Updated Team ']])), false);
  await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(context.requests)), [{
    path: 'tournaments/event-one/registrations/me', method: 'PATCH', body: {teamName: 'Updated Team'}
  }]);
  assert.equal(node('#modal').open, false);
});

test('team edit stops at registration deadline while withdrawal remains available before start', () => {
  const {context, node} = page({now: '2027-01-02T09:00:00Z'});
  context.fixture = event({startsAt: '2027-01-02T10:00:00Z', registrationClosesAt: '2027-01-02T09:00:00Z',
    myRegistration: {status: 'registered', teamName: 'Original Team'}});
  vm.runInContext('orgService.tournaments = [fixture]', context);
  const card = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.doesNotMatch(card, /data-org-edit-registration=/);
  assert.match(card, /data-org-withdraw="event-one"/);
  vm.runInContext("orgEditRegistration('event-one')", context);
  assert.equal(node('#modal').open, false);
  context.fixture = event({myRegistration: {status: 'cancelled', teamName: 'Original Team'}});
  vm.runInContext("orgService.tournaments = [fixture]; orgEditRegistration('event-one')", context);
  assert.equal(node('#modal').open, false);
});

test('failed team update retains the form and reports the server conflict', async () => {
  const {context, node} = page();
  context.fixture = event({myRegistration: {status: 'registered', teamName: 'Original Team'}});
  vm.runInContext("orgService.tournaments = [fixture]; orgRequest = async () => {throw new Error('That team name is already registered');}; orgEditRegistration('event-one')", context);
  assert.equal(context.modalAction(new Map([['teamName', 'Taken Team']])), false);
  await new Promise(setImmediate);
  assert.equal(node('#modal').open, true);
  assert.equal(node('#modal .org-form-error').textContent, 'That team name is already registered');
  assert.equal(node('#submit-modal').textContent, 'Save team');
  assert.equal(node('#submit-modal').disabled, false);
});

test('organisation controls apply only to its own events and never offer player registration', () => {
  const {context} = page();
  context.account = {userId: 'owner', accountType: 'organisation', organisationId: 'org-one'};
  context.fixture = event({status: 'draft'});
  const own = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(own, /data-org-edit-event="event-one"/);
  assert.match(own, /data-org-event-action="publish"/);
  assert.match(own, /data-org-event-action="cancel"/);
  context.fixture = event({organisationId: 'org-other'});
  const other = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.doesNotMatch(other, /data-org-edit-event=|data-org-event-action=|data-org-roster=|data-org-register=/);
});

test('service cards encode names, descriptions and identifiers from server responses', () => {
  const {context} = page();
  const attack = '\"><img src=x onerror="alert(1)">';
  context.fixture = event({id: attack, name: attack, organisationName: attack, groundName: attack,
    myRegistration: {status: 'registered', teamName: attack}});
  const card = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(card, /data-org-withdraw="&quot;&gt;&lt;img/);
  assert.doesNotMatch(card, /<img\b|<script\b/i);
  context.ground = {
    id: attack, organisationId: 'org-one', organisationName: attack,
    name: attack, sport: 'Football', city: attack, address: attack,
    timezone: 'UTC', pricePerHour: 50, currency: 'INR', opensAt: '07:00', closesAt: '22:00'
  };
  const ground = vm.runInContext('orgGroundCard(ground)', context);
  assert.match(ground, /data-org-book="&quot;&gt;&lt;img/);
  assert.doesNotMatch(ground, /<img\b|<script\b/i);
});

test('failed async forms retain the dialog, report the error and allow retry', async () => {
  const {context, node} = page();
  vm.runInContext("orgOpenForm('Reserve', '', 'Confirm', async () => {throw new Error('Slot already taken');});", context);
  const action = context.modalAction;
  assert.equal(action(new Map()), false);
  assert.equal(node('#submit-modal').disabled, true);
  await new Promise(setImmediate);
  assert.equal(node('#modal').open, true);
  assert.equal(node('#modal').closeCount || 0, 0);
  assert.equal(node('#modal .org-form-error').textContent, 'Slot already taken');
  assert.equal(node('#submit-modal').disabled, false);
  assert.equal(node('#submit-modal').textContent, 'Confirm');
});

test('a late failure from a replaced form cannot change the new dialog', async () => {
  const {context, node} = page();
  let reject;
  context.pending = new Promise((resolve, rejectPending) => { reject = rejectPending; });
  vm.runInContext("orgOpenForm('Old form', '', 'Save old', () => pending);", context);
  assert.equal(context.modalAction(new Map()), false);
  node('#modal').close();
  vm.runInContext("orgOpenForm('New form', '', 'Save new', async () => {});", context);
  reject(new Error('Old service failure'));
  await new Promise(setImmediate);
  assert.equal(node('#modal').open, true);
  assert.equal(node('#modal .org-form-error').textContent, '');
  assert.equal(node('#submit-modal').textContent, 'Save new');
});

test('submitting a pending form twice sends one request and closes after confirmation', async () => {
  const {context, node} = page();
  let confirm;
  context.pending = new Promise(resolve => { confirm = resolve; });
  context.requests = 0;
  vm.runInContext("orgOpenForm('Save', '', 'Confirm', () => {requests++; return pending;});", context);
  const action = context.modalAction;
  assert.equal(action(new Map()), false);
  assert.equal(action(new Map()), false);
  assert.equal(context.requests, 1);
  assert.equal(node('#modal').open, true);
  confirm();
  await new Promise(setImmediate);
  assert.equal(node('#modal').open, false);
  assert.equal(node('#modal').closeCount, 1);
});

test('a late directory response cannot replace the page selected after navigation', async () => {
  const {context, node} = page();
  let finishGrounds;
  context.pendingGrounds = new Promise(resolve => { finishGrounds = resolve; });
  context.accountReady = Promise.resolve();
  context.fixture = event();
  vm.runInContext(`orgRequest = path => path === 'grounds'
    ? pendingGrounds : Promise.resolve({tournaments: [fixture]}); view = 'grounds';`, context);
  const earlier = vm.runInContext("orgLoad('grounds')", context);
  await Promise.resolve();
  await vm.runInContext("view = 'tournaments'; orgLoad('tournaments')", context);
  finishGrounds({grounds: [{id: 'stale-ground', name: 'Outdated result'}]});
  await earlier;
  assert.equal(vm.runInContext('orgService.route', context), 'tournaments');
  assert.equal(vm.runInContext('orgService.loading', context), false);
  assert.equal(vm.runInContext('orgService.grounds.length', context), 0);
  assert.match(node('#content').innerHTML, /Community Cup/);
  assert.doesNotMatch(node('#content').innerHTML, /Outdated result/);
});

test('ground editing is available only to the owning organisation and event editing only for drafts', () => {
  const {context} = organisationPage();
  context.fixtureGround = ground();
  assert.match(vm.runInContext('orgGroundCard(fixtureGround)', context), /data-org-edit-ground="ground-one"/);
  context.fixtureGround = ground({organisationId: 'org-other'});
  assert.doesNotMatch(vm.runInContext('orgGroundCard(fixtureGround)', context), /data-org-edit-ground=|data-org-book=/);
  for (const status of ['open', 'live', 'completed', 'cancelled']) {
    context.fixture = event({status});
    assert.doesNotMatch(vm.runInContext('orgTournamentCard(fixture)', context), /data-org-edit-event=/);
  }
  context.account = {userId: 'player-one', accountType: 'player', organisationId: null};
  context.fixtureGround = ground();
  assert.doesNotMatch(vm.runInContext('orgGroundCard(fixtureGround)', context), /data-org-edit-ground=/);
});

test('dashboard shows current totals and orders the next event and reservations by start time', () => {
  const {context} = organisationPage({now: '2027-01-01T12:00:00Z'});
  context.fixtures = {
    grounds: [ground()],
    tournaments: [
      event({id: 'later', name: 'Later competition', startsAt: '2027-01-03T10:00:00Z', endsAt: '2027-01-03T12:00:00Z', registrationCount: 3}),
      event({id: 'expired', name: 'Expired competition', startsAt: '2026-12-31T10:00:00Z', endsAt: '2026-12-31T12:00:00Z', registrationCount: 99}),
      event({id: 'nearest', name: 'Nearest competition', startsAt: '2027-01-02T10:00:00Z', endsAt: '2027-01-02T12:00:00Z', registrationCount: 2}),
      event({id: 'finished', name: 'Finished competition', status: 'completed', registrationCount: 99}),
      event({id: 'cancelled', name: 'Cancelled competition', status: 'cancelled', registrationCount: 99})
    ],
    bookings: [
      booking({id: 'later', groundName: 'Later reservation', startsAt: '2027-01-03T10:00:00Z', endsAt: '2027-01-03T11:00:00Z'}),
      booking({id: 'past', groundName: 'Past reservation', startsAt: '2026-12-31T10:00:00Z', endsAt: '2026-12-31T11:00:00Z'}),
      booking({id: 'near', groundName: 'Nearest reservation'}),
      booking({id: 'cancelled', groundName: 'Cancelled reservation', status: 'cancelled'})
    ]
  };
  vm.runInContext('Object.assign(orgService, fixtures)', context);
  const dashboard = vm.runInContext('orgDashboard()', context);
  assert.match(dashboard, /aria-label="Bookable grounds: 1\./);
  assert.match(dashboard, /aria-label="Active tournaments: 2\./);
  assert.match(dashboard, /aria-label="Upcoming reservations: 2\./);
  assert.match(dashboard, /aria-label="Registered teams: 5\./);
  assert.match(dashboard, /Nearest competition/);
  assert.ok(dashboard.indexOf('Nearest reservation') < dashboard.indexOf('Later reservation'));
  assert.doesNotMatch(dashboard, /Past reservation|Cancelled reservation|Expired competition|Finished competition|Cancelled competition/);
});

test('dashboard tabs combine tournament status, sport and search filters without mixing reservations', () => {
  const {context} = organisationPage({now: '2027-01-01T12:00:00Z'});
  context.fixtures = [
    event({name: 'North football draft', status: 'draft'}),
    event({id: 'south', name: 'South football draft', status: 'draft'}),
    event({id: 'open', name: 'North football open'}),
    event({id: 'cricket', name: 'North cricket draft', sport: 'Cricket', status: 'draft'})
  ];
  vm.runInContext("orgService.tournaments = fixtures; orgService.tab = 'tournaments'; orgService.status = 'draft'; filter = 'Football'; query = 'north';", context);
  const dashboard = vm.runInContext('orgDashboard()', context);
  assert.match(dashboard, /North football draft/);
  assert.doesNotMatch(dashboard, /South football draft|North football open|North cricket draft/);
  assert.match(dashboard, /data-org-status="draft"[^>]+aria-pressed="true"/);
  assert.match(dashboard, /data-org-tab="tournaments"[^>]+aria-current="page"/);
});

test('reservation filters retain accessible history while excluding it from upcoming results', () => {
  const {context} = organisationPage({now: '2027-01-01T12:00:00Z'});
  context.fixtures = [
    booking({id: 'future', groundName: 'Future reservation'}),
    booking({id: 'past', groundName: 'Past reservation', startsAt: '2026-12-31T10:00:00Z', endsAt: '2026-12-31T11:00:00Z'}),
    booking({id: 'cancelled', groundName: 'Cancelled reservation', status: 'cancelled'})
  ];
  vm.runInContext("orgService.bookings = fixtures; orgService.tab = 'bookings';", context);
  const expected = {upcoming: 'Future reservation', past: 'Past reservation', cancelled: 'Cancelled reservation'};
  for (const [status, name] of Object.entries(expected)) {
    context.status = status;
    vm.runInContext('orgService.status = status', context);
    const dashboard = vm.runInContext('orgDashboard()', context);
    assert.match(dashboard, new RegExp('<h3>' + name + '</h3>'));
    for (const other of Object.values(expected).filter(value => value !== name)) {
      assert.doesNotMatch(dashboard, new RegExp('<h3>' + other + '</h3>'));
    }
  }
  vm.runInContext("orgService.status = 'all'; query = 'alex';", context);
  const searched = vm.runInContext('orgDashboard()', context);
  for (const name of Object.values(expected)) assert.match(searched, new RegExp('<h3>' + name + '</h3>'));
  vm.runInContext("query = 'missing player';", context);
  assert.match(vm.runInContext('orgDashboard()', context), /No reservations in this view/);
});

test('organisation profile content is escaped in the dashboard', () => {
  const {context} = organisationPage();
  const attack = '\"><img src=x onerror="alert(1)">';
  Object.assign(context.organisation, {name: attack, description: attack, city: attack, sport: attack, verificationStatus: attack});
  const dashboard = vm.runInContext('orgDashboard()', context);
  assert.match(dashboard, /&quot;&gt;&lt;img/);
  assert.doesNotMatch(dashboard, /<img\b|<script\b/i);
});

test('event times use their selected timezone independently of the device timezone', () => {
  const previousZone = process.env.TZ;
  try {
    for (const deviceZone of ['UTC', 'Pacific/Honolulu']) {
      process.env.TZ = deviceZone;
      const {context} = page();
      assert.equal(vm.runInContext('orgDeviceTimezone()', context), deviceZone);
      for (const [timezone, expected] of [
        ['Asia/Kolkata', '2027-01-02T03:30:00.000Z'],
        ['Asia/Kathmandu', '2027-01-02T03:15:00.000Z'],
        ['Pacific/Kiritimati', '2027-01-01T19:00:00.000Z'],
        ['America/New_York', '2027-01-02T14:00:00.000Z']
      ]) {
        context.timezone = timezone;
        const instant = vm.runInContext("orgLocalInstant('2027-01-02T09:00', timezone)", context);
        assert.equal(instant, expected);
        context.instant = instant;
        assert.equal(vm.runInContext('orgLocalInput(instant, timezone)', context), '2027-01-02T09:00');
      }
    }
  } finally {
    if (previousZone === undefined) delete process.env.TZ; else process.env.TZ = previousZone;
  }
});

test('event times reject clock-change gaps, ambiguous hours and invalid dates', () => {
  const {context} = page();
  assert.throws(() => vm.runInContext("orgLocalInstant('2027-03-14T02:30', 'America/New_York')", context), /does not exist/);
  assert.throws(() => vm.runInContext("orgLocalInstant('2027-11-07T01:30', 'America/New_York')", context), /occurs twice/);
  assert.equal(vm.runInContext("orgLocalInstant('2027-03-14T03:30', 'America/New_York')", context), '2027-03-14T07:30:00.000Z');
  assert.equal(vm.runInContext("orgLocalInstant('2027-11-07T02:30', 'America/New_York')", context), '2027-11-07T07:30:00.000Z');
  assert.throws(() => vm.runInContext("orgLocalInstant('2027-02-30T09:00', 'Asia/Kolkata')", context), /valid date and time/);
  assert.throws(() => vm.runInContext("orgLocalInstant('2027-01-02T09:00', 'Invalid/Zone')", context), /valid IANA timezone/);
});

test('switching dashboard tabs uses local data and resets filters for the selected section', () => {
  const {context, node, click} = organisationPage({now: '2027-01-01T12:00:00Z'});
  context.loads = 0;
  vm.runInContext("orgLoad = async () => {loads++;}; query = 'old search'; orgService.status = 'draft';", context);
  click({orgTab: 'bookings'});
  assert.equal(context.location.hash, 'organisation/bookings');
  vm.runInContext("navigate('organisation/bookings')", context);
  assert.equal(context.loads, 0);
  assert.equal(vm.runInContext('orgService.tab', context), 'bookings');
  assert.equal(vm.runInContext('orgService.status', context), 'upcoming');
  assert.equal(context.query, '');
  assert.equal(node('#search').disabled, false);
  assert.equal(node('#search').getAttribute('aria-label'), 'Search your reservations');
  click({orgStatus: 'cancelled'});
  assert.equal(vm.runInContext('orgService.status', context), 'cancelled');
  vm.runInContext("navigate('organisation/tournaments')", context);
  assert.equal(vm.runInContext('orgService.status', context), 'all');
  assert.equal(context.loads, 0);
  vm.runInContext("navigate('organisation/overview')", context);
  assert.equal(node('#search').disabled, true);
  click({orgTab: 'unknown'});
  assert.equal(context.location.hash, 'organisation/bookings');
});

test('editing the profile encodes existing values and saves trimmed fields through PATCH', async () => {
  const {context, node} = organisationPage();
  Object.assign(context.organisation, {name: '\"><img src=x>', description: '</textarea><script>alert(1)</script>'});
  captureRequests(context, {organisation: {id: 'org-one'}});
  vm.runInContext('orgEditProfile()', context);
  assert.doesNotMatch(node('#modal-body').innerHTML, /<img\b|<script\b/i);
  assert.match(node('#modal-body').innerHTML, /&lt;\/textarea&gt;&lt;script&gt;/);
  assert.equal(context.modalAction(new Map([
    ['name', ' Updated Club '], ['description', ' Everyone is welcome. '],
    ['sport', 'Football'], ['city', ' Pune '], ['state', ' Maharashtra '], ['country', ' India ']
  ])), false);
  await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(context.requests)), [{
    path: 'organisations/me', method: 'PATCH', body: {
      name: 'Updated Club', description: 'Everyone is welcome.', sport: 'Football',
      city: 'Pune', state: 'Maharashtra', country: 'India'
    }
  }]);
  assert.equal(node('#modal').open, false);
});

test('ground edits save the owned venue with numeric pricing and reject reversed hours before sending', async () => {
  const {context, node} = organisationPage();
  context.fixtureGround = ground();
  vm.runInContext('orgService.grounds = [fixtureGround]', context);
  captureRequests(context, {ground: {id: 'ground-one'}});
  vm.runInContext("orgCreateGround('ground-one')", context);
  assert.match(node('#modal-body').innerHTML, /name="name" value="Northside Ground"/);
  assert.match(node('#modal-body').innerHTML, /option value="24:00"/);
  const data = new Map(Object.entries({name: ' Northside Ground ', sport: 'Football', city: ' Pune ',
    address: ' North Road ', timezone: ' Asia/Kolkata ', pricePerHour: '600', opensAt: '22:00', closesAt: '07:00'}));
  assert.equal(context.modalAction(data), false);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 0);
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal .org-form-error').textContent, /Closing time must be after opening time/);
  data.set('opensAt', '07:00');
  data.set('closesAt', '24:00');
  assert.equal(context.modalAction(data), false);
  await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(context.requests)), [{
    path: 'grounds/ground-one', method: 'PATCH', body: {
      name: 'Northside Ground', sport: 'Football', city: 'Pune', address: 'North Road',
      timezone: 'Asia/Kolkata', pricePerHour: 600, opensAt: '07:00', closesAt: '24:00'
    }
  }]);
});

test('draft editing prefills local event times and sends offset-aware PATCH data', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  context.fixture = event({status: 'draft', timezone: 'Asia/Kolkata', startsAt: '2027-01-02T03:30:00Z',
    endsAt: '2027-01-02T05:30:00Z', registrationClosesAt: '2027-01-01T12:30:00Z'});
  vm.runInContext('orgService.tournaments = [fixture]', context);
  captureRequests(context, {tournament: {id: 'event-one', status: 'draft'}});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext("orgCreateEvent('event-one')", context);
  assert.match(node('#modal-body').innerHTML, /name="startsAt" value="2027-01-02T09:00"/);
  assert.match(node('#modal-body').innerHTML, /name="registrationClosesAt" value="2027-01-01T18:00"/);
  assert.equal(context.modalAction(eventForm({groundId: 'unused-ground'})), false);
  await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(context.requests)), [{
    path: 'tournaments/event-one', method: 'PATCH', body: {
      name: 'Community Cup', sport: 'Football', eventType: 'online', timezone: 'Asia/Kolkata',
      startsAt: '2027-01-02T03:30:00.000Z', registrationClosesAt: '2027-01-01T12:30:00.000Z',
      capacity: 8, durationHours: 2
    }
  }]);
});

test('new tournament defaults to explicit publication and can select a private draft', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  captureRequests(context, {tournament: {id: 'created-event', status: 'open'}});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext('orgCreateEvent()', context);
  assert.match(node('#modal-body').innerHTML, /option value="publish" selected/);
  assert.match(node('#modal-body').innerHTML, /Save private draft — only your organisation can see it/);
  assert.equal(node('#submit-modal').textContent, 'Create & publish');
  const visibility = node('#modal [name="publication"]');
  visibility.value = 'draft';
  visibility.dispatch('change');
  assert.equal(node('#submit-modal').textContent, 'Save draft');
  visibility.value = 'publish';
  visibility.dispatch('change');
  assert.equal(node('#submit-modal').textContent, 'Create & publish');
  assert.equal(context.modalAction(eventForm({publication: 'publish'})), false);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 1);
  assert.equal(context.requests[0].path, 'tournaments');
  assert.equal(context.requests[0].method, 'POST');
  assert.equal(context.requests[0].body.publish, true);
  assert.equal('publication' in context.requests[0].body, false);
  assert.equal(context.location.hash, 'organisation/tournaments/created-event');
  assert.equal(node('#modal').open, false);
});

test('private draft creation sends a single nonpublishing request and reveals the saved event', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  captureRequests(context, {tournament: {id: 'created-draft', status: 'draft'}});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext('orgCreateEvent()', context);
  assert.equal(context.modalAction(eventForm({publication: 'draft'})), false);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 1);
  assert.equal(context.requests[0].body.publish, false);
  assert.equal(context.location.hash, 'organisation/tournaments/created-draft');
  assert.equal(node('#modal').open, false);
});

test('failed creation and publication keeps the chosen action ready for retry', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext("orgRequest = async () => {throw new Error('That ground slot is already reserved. Choose another time.');}; orgCreateEvent()", context);
  node('#modal [name="publication"]').value = 'publish';
  assert.equal(context.modalAction(eventForm({publication: 'publish'})), false);
  await new Promise(setImmediate);
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal .org-form-error').textContent, /already reserved/);
  assert.equal(node('#submit-modal').textContent, 'Create & publish');
  assert.equal(node('#submit-modal').disabled, false);
});

test('physical event forms use the selected ground timezone and sport and preserve the online timezone', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  context.fixtureGround = ground({sport: 'Cricket', timezone: 'Asia/Kathmandu'});
  vm.runInContext('orgService.grounds = [fixtureGround]', context);
  captureRequests(context, {tournament: {id: 'created-event', status: 'draft'}});
  const type = node('#modal [name="eventType"]');
  const zone = node('#modal [name="timezone"]');
  const venue = node('#modal [name="groundId"]');
  const sport = node('#modal [name="sport"]');
  type.value = 'online';
  vm.runInContext('orgCreateEvent()', context);
  zone.value = 'Europe/London';
  zone.dispatch('input');
  venue.value = 'ground-one';
  type.value = 'physical';
  type.dispatch('change');
  assert.equal(zone.value, 'Asia/Kathmandu');
  assert.equal(zone.readOnly, true);
  assert.equal(venue.disabled, false);
  assert.equal(venue.required, true);
  assert.equal(sport.value, 'Cricket');
  type.value = 'online';
  type.dispatch('change');
  assert.equal(zone.value, 'Europe/London');
  assert.equal(zone.readOnly, false);
  assert.equal(venue.disabled, true);
  assert.equal(context.modalAction(eventForm({eventType: 'physical', groundId: 'ground-one', timezone: 'UTC', sport: 'Football'})), false);
  await new Promise(setImmediate);
  assert.equal(context.requests[0].method, 'POST');
  assert.equal(context.requests[0].body.timezone, 'Asia/Kathmandu');
  assert.equal(context.requests[0].body.sport, 'Cricket');
  assert.equal(context.requests[0].body.startsAt, '2027-01-02T03:15:00.000Z');
  assert.equal(context.requests[0].body.groundId, 'ground-one');
});

test('invalid event local time stays in the form and can be corrected before any request', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  captureRequests(context, {tournament: {id: 'created-event', status: 'draft'}});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext('orgCreateEvent()', context);
  const data = eventForm({timezone: 'America/New_York', startsAt: '2027-03-14T02:30', registrationClosesAt: '2027-03-13T09:00'});
  assert.equal(context.modalAction(data), false);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 0);
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal .org-form-error').textContent, /does not exist/);
  assert.equal(node('#submit-modal').disabled, false);
  data.set('startsAt', '2027-03-14T03:30');
  assert.equal(context.modalAction(data), false);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 1);
  assert.equal(context.requests[0].body.startsAt, '2027-03-14T07:30:00.000Z');
  assert.equal(node('#modal').open, false);
});

test('direct edit actions ignore another organisation, published events and player accounts', () => {
  const {context, node} = organisationPage();
  context.fixtureGround = ground({organisationId: 'org-other'});
  context.fixture = event({status: 'draft', organisationId: 'org-other'});
  vm.runInContext('orgService.grounds = [fixtureGround]; orgService.tournaments = [fixture];', context);
  vm.runInContext("orgCreateGround('ground-one'); orgCreateEvent('event-one');", context);
  assert.equal(node('#modal').open, false);
  context.fixture = event();
  vm.runInContext("orgService.tournaments = [fixture]; orgCreateEvent('event-one');", context);
  assert.equal(node('#modal').open, false);
  context.account = {userId: 'player-one', accountType: 'player', organisationId: null};
  vm.runInContext('orgEditProfile(); orgCreateGround(); orgCreateEvent();', context);
  assert.equal(node('#modal').open, false);
});

test('tournament cards summarize format, teams and rewards while details expose escaped organiser information', () => {
  const {context, node, click} = page();
  const attack = '</textarea><img src=x onerror="alert(1)">';
  context.fixture = event({description: 'A welcoming community tournament.', format: 'groups_knockout',
    formatDetails: attack, teamSize: 7, entryFee: 400, prize: 'Champions trophy',
    eligibility: 'Under 21', rules: attack, contact: 'captain@example.com', onlinePlatform: 'Discord',
    customDetails: [{label: 'What to bring', value: attack}],
    registrationQuestions: [{id: 'captain', label: 'Captain contact', type: 'text', required: true}]});
  vm.runInContext('orgService.tournaments = [fixture]', context);
  const card = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(card, /Groups \+ knockout/);
  assert.match(card, /7 players \/ team/);
  assert.match(card, /₹400 entry \/ team/);
  assert.match(card, /data-org-event-details="event-one"/);
  assert.doesNotMatch(card, /Tournament rules|What to bring/);
  click({orgEventDetails: 'event-one'});
  const details = node('#modal-body').innerHTML;
  assert.match(details, /Who can take part/);
  assert.match(details, /Under 21/);
  assert.match(details, /What to bring/);
  assert.match(details, /Captain contact <strong>\(required\)<\/strong>/);
  assert.match(details, /&lt;img/);
  assert.doesNotMatch(details, /<img\b/);
});

test('new tournament builder adds accessible details and questions and sends only structured fields', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  captureRequests(context, {tournament: {id: 'custom-event', status: 'draft'}});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext('orgCreateEvent()', context);
  const form = node('#modal');
  assert.equal(form.getAttribute('aria-labelledby'), 'modal-title');
  form.dispatch('click', {closest: () => ({dataset: {orgAddDetail: ''}})});
  form.dispatch('click', {closest: () => ({dataset: {orgAddQuestion: ''}})});
  assert.match(node('#modal .org-builder-detail-list').innerHTML, /name="detail_d0_label"/);
  assert.match(node('#modal .org-builder-detail-list').innerHTML, /type="button"[^>]+aria-label="Remove custom detail"/);
  assert.equal(node('#modal [name="detail_d0_label"]').focused, true);
  assert.equal(node('#modal [name="question_q1_label"]').focused, true);
  form.dispatch('change', {dataset: {orgQuestionType: 'q1'}, value: 'select'});
  assert.equal(node('#modal [data-org-question-options="q1"]').hidden, false);
  assert.equal(node('#modal [name="question_q1_options"]').required, true);
  const data = eventForm({publication: 'draft', tournamentOptions: '1', description: ' A friendly cup ',
    format: 'groups_knockout', formatDetails: ' Two groups ', teamSize: '7', entryFee: '500',
    prize: ' Trophy ', eligibility: ' Open to all ', rules: ' Respect the referee ',
    contact: ' captain@example.com ', onlinePlatform: ' Discord ',
    detail_d0_label: ' Parking ', detail_d0_value: ' Use the east gate ',
    question_q1_label: ' Skill level ', question_q1_type: 'select',
    question_q1_required: '1', question_q1_options: ' Beginner \n Intermediate\n Advanced ',
    unexpectedField: 'do not submit'});
  context.modalAction(data);
  await new Promise(setImmediate);
  const payload = JSON.parse(JSON.stringify(context.requests[0].body));
  assert.equal(payload.description, 'A friendly cup');
  assert.equal(payload.teamSize, 7);
  assert.equal(payload.entryFee, 500);
  assert.equal(payload.format, 'groups_knockout');
  assert.equal(payload.contact, 'captain@example.com');
  assert.deepEqual(payload.customDetails, [{label: 'Parking', value: 'Use the east gate'}]);
  assert.match(payload.registrationQuestions[0].id, /^[a-zA-Z0-9_-]{1,64}$/);
  assert.deepEqual({...payload.registrationQuestions[0], id: 'stable-id'}, {
    id: 'stable-id', label: 'Skill level', type: 'select', required: true,
    options: ['Beginner', 'Intermediate', 'Advanced']
  });
  assert.equal('detail_d0_label' in payload, false);
  assert.equal('question_q1_options' in payload, false);
  assert.equal('tournamentOptions' in payload, false);
  assert.equal('unexpectedField' in payload, false);
});

test('custom builder limits rows, removes rows and prevents changes during save', () => {
  const {context, node} = organisationPage();
  vm.runInContext('const builder=orgTournamentBuilder({}); builder.bind({isCurrent:()=>true})', context);
  const form = node('#modal');
  const dispatch = dataset => form.dispatch('click', {closest: () => ({dataset})});
  for (let i = 0; i < 14; i++) dispatch({orgAddDetail: ''});
  for (let i = 0; i < 10; i++) dispatch({orgAddQuestion: ''});
  assert.equal(node('#modal .org-detail-count').textContent, '12 / 12 details');
  assert.equal(node('#modal .org-question-count').textContent, '8 / 8 questions');
  assert.equal(node('#modal [data-org-add-detail]').disabled, true);
  assert.equal(node('#modal [data-org-add-question]').disabled, true);
  dispatch({orgRemoveDetail: 'd0'});
  dispatch({orgRemoveQuestion: 'q12'});
  assert.equal(node('#modal [data-org-detail-row="d0"]').removed, true);
  assert.equal(node('#modal [data-org-question-row="q12"]').removed, true);
  assert.equal(node('#modal .org-detail-count').textContent, '11 / 12 details');
  assert.equal(node('#modal .org-question-count').textContent, '7 / 8 questions');
  node('#submit-modal').disabled = true;
  dispatch({orgAddDetail: ''});
  assert.equal(node('#modal .org-detail-count').textContent, '11 / 12 details');
});

test('draft option prefill encodes content and keeps question identifiers when saving', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  const attack = '</textarea><script>alert(1)</script>';
  context.fixture = event({status: 'draft', timezone: 'Asia/Kolkata', startsAt: '2027-01-02T03:30:00Z',
    endsAt: '2027-01-02T05:30:00Z', registrationClosesAt: '2027-01-01T12:30:00Z',
    description: attack, customDetails: [{label: 'Kit', value: attack}],
    registrationQuestions: [{id: 'skill-stable', label: attack, type: 'select', required: true, options: ['New', 'Experienced']}]});
  vm.runInContext('orgService.tournaments=[fixture]', context);
  captureRequests(context, {tournament: {id: 'event-one', status: 'draft'}});
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext("orgCreateEvent('event-one')", context);
  assert.match(node('#modal-body').innerHTML, /name="question_q1_required"[^>]+checked/);
  assert.match(node('#modal-body').innerHTML, /New\nExperienced/);
  assert.doesNotMatch(node('#modal-body').innerHTML, /<script\b/);
  context.modalAction(eventForm({tournamentOptions: '1', description: attack, detail_d0_label: 'Kit',
    detail_d0_value: 'Bring boots', question_q1_label: 'Skill', question_q1_type: 'select',
    question_q1_required: '1', question_q1_options: 'New\nExperienced'}));
  await new Promise(setImmediate);
  assert.equal(context.requests[0].body.registrationQuestions[0].id, 'skill-stable');
});

test('choice validation and server failure preserve dynamic rows and question IDs for retry', async () => {
  const {context, node} = organisationPage({now: '2027-01-01T00:00:00Z'});
  context.requests = [];
  vm.runInContext("view='ring'; orgRequest=async(path,method,body)=>{requests.push({path,method,body}); if(requests.length===1)throw new Error('Venue is busy'); return {tournament:{id:'event-one',status:'draft'}};};", context);
  node('#modal [name="eventType"]').value = 'online';
  vm.runInContext('orgCreateEvent()', context);
  node('#modal').dispatch('click', {closest: () => ({dataset: {orgAddQuestion: ''}})});
  const data = eventForm({publication: 'draft', tournamentOptions: '1', question_q0_label: 'Level',
    question_q0_type: 'select', question_q0_options: 'Beginner\nBeginner'});
  context.modalAction(data);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 0);
  assert.match(node('#modal .org-form-error').textContent, /different choices/);
  data.set('question_q0_options', 'Beginner\nAdvanced');
  context.modalAction(data);
  await new Promise(setImmediate);
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal .org-form-error').textContent, /Venue is busy/);
  assert.match(node('#modal .org-builder-question-list').innerHTML, /question_q0_label/);
  context.modalAction(data);
  await new Promise(setImmediate);
  assert.equal(context.requests[0].body.registrationQuestions[0].id, context.requests[1].body.registrationQuestions[0].id);
  assert.equal(node('#modal').open, false);
});

test('published details can be updated before start and never submit locked tournament settings', async () => {
  const {context, node, click} = organisationPage({now: '2027-01-01T00:00:00Z'});
  context.fixture = event({startsAt: '2027-01-02T10:00:00Z', customDetails: []});
  vm.runInContext('orgService.tournaments=[fixture]', context);
  captureRequests(context, {tournament: {id: 'event-one', status: 'open'}});
  const card = vm.runInContext('orgTournamentCard(fixture)', context);
  assert.match(card, /data-org-edit-details="event-one"/);
  click({orgEditDetails: 'event-one'});
  const form = node('#modal-body').innerHTML;
  assert.match(form, /fixed after publication/);
  assert.doesNotMatch(form, /name="startsAt"|name="teamSize"|data-org-add-question/);
  context.modalAction(new Map(Object.entries({name: ' Updated Cup ', description: ' New description ',
    rules: ' New rules ', prize: ' Trophy ', tournamentOptions: '1',
    startsAt: 'changed', capacity: '99', entryFee: '900', teamSize: '11', format: 'custom'})));
  await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(context.requests[0])), {
    path: 'tournaments/event-one', method: 'PATCH', body: {name: 'Updated Cup',
      description: 'New description', rules: 'New rules', prize: 'Trophy', customDetails: []}
  });
  context.fixture = event({startsAt: '2026-12-31T10:00:00Z'});
  vm.runInContext("orgService.tournaments=[fixture]; orgEditEventDetails('event-one')", context);
  assert.equal(node('#modal').open, false);
});

test('player registration validates organiser questions and allows a personal note', async () => {
  const {context, node, click} = page();
  context.fixture = event({registrationQuestions: [
    {id: 'captain', label: 'Captain contact', type: 'text', required: true},
    {id: 'level', label: 'Skill level', type: 'select', required: false, options: ['Beginner', 'Advanced']}
  ]});
  vm.runInContext('orgService.tournaments=[fixture]', context);
  captureRequests(context, {registration: {id: 'registration-one', status: 'registered'}});
  click({orgRegister: 'event-one'});
  assert.match(node('#modal-body').innerHTML, /name="answer_captain"[^>]+required/);
  assert.match(node('#modal-body').innerHTML, /name="notes"/);
  const data = new Map([['teamName', ' Tigers '], ['notes', ' We need accessible seating. ']]);
  context.modalAction(data);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 0);
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal .org-form-error').textContent, /Captain contact/);
  data.set('answer_captain', ' captain@example.com ');
  data.set('answer_level', 'Invalid choice');
  context.modalAction(data);
  await new Promise(setImmediate);
  assert.equal(context.requests.length, 0);
  data.set('answer_level', 'Advanced');
  context.modalAction(data);
  await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(context.requests[0].body)), {
    teamName: 'Tigers', answers: {captain: 'captain@example.com', level: 'Advanced'}, notes: 'We need accessible seating.'
  });
});

test('registration edit prefills escaped saved answers and personal notes and can clear optional values', async () => {
  const {context, node} = page();
  const attack = '</textarea><img src=x>';
  context.fixture = event({registrationQuestions: [
    {id: 'captain', label: 'Captain contact', type: 'text', required: true},
    {id: 'level', label: 'Skill level', type: 'select', required: false, options: ['Beginner', 'Advanced']}
  ], myRegistration: {id: 'registration-one', status: 'registered', teamName: 'Tigers',
    answers: {captain: attack, level: 'Advanced'}, notes: attack}});
  vm.runInContext('orgService.tournaments=[fixture]', context);
  captureRequests(context, {registration: {id: 'registration-one', status: 'registered'}});
  vm.runInContext("orgEditRegistration('event-one')", context);
  const form = node('#modal-body').innerHTML;
  assert.match(form, /option value="Advanced" selected/);
  assert.match(form, /&lt;\/textarea&gt;&lt;img/);
  assert.doesNotMatch(form, /<img\b/);
  context.modalAction(new Map([['teamName', 'Tigers'], ['answer_captain', 'new@example.com'], ['answer_level', ''], ['notes', '']]));
  await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(context.requests[0].body)), {
    teamName: 'Tigers', answers: {captain: 'new@example.com'}, notes: ''
  });
});

test('roster shows safe saved answers and notes only for organiser-defined question IDs', async () => {
  const {context, node} = organisationPage();
  const attack = '<img src=x onerror="alert(1)">';
  context.fixture = event({registrationQuestions: [{id: 'captain', label: 'Captain contact', type: 'text', required: true}]});
  vm.runInContext('orgService.tournaments=[fixture]', context);
  captureRequests(context, {registrations: [{teamName: 'Tigers', playerName: 'Alex', status: 'registered',
    answers: {captain: attack, unknown: 'Do not show arbitrary keys'}, notes: attack}]});
  await vm.runInContext("orgRoster('event-one')", context);
  const roster = node('#modal .org-roster-content').innerHTML;
  assert.match(roster, /Captain contact/);
  assert.match(roster, /Note from the team/);
  assert.match(roster, /&lt;img/);
  assert.doesNotMatch(roster, /<img\b|Do not show arbitrary keys/);
});

test('registration handles all valid question identifiers without using object prototypes as answers', () => {
  const {context} = page();
  context.fixture = event({registrationQuestions: [{id: '__proto__', label: 'Captain contact', type: 'text', required: true}]});
  context.data = new Map([['teamName', 'Tigers'], ['answer___proto__', 'captain@example.com']]);
  const payload = JSON.parse(JSON.stringify(vm.runInContext('orgRegistrationPayload(fixture,data)', context)));
  assert.equal(Object.hasOwn(payload.answers, '__proto__'), true);
  assert.equal(payload.answers.__proto__, 'captain@example.com');
  context.registration = {answers: {}};
  assert.doesNotMatch(vm.runInContext('orgRegistrationFields(fixture,registration)', context), /\[object Object\]/);
});
