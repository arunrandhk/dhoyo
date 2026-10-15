const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// Exercise the actual dialog handlers without sending email or loading an app account.
function page() {
  const nodes = new Map();
  const listeners = new Map();
  const canonical = selector => {
    const input = selector.match(/\[name="(player(?:Email|Code)_\d+)"\]/);
    return input ? '#modal [name="' + input[1] + '"]' : selector;
  };
  const node = selector => {
    selector = canonical(selector);
    if (!nodes.has(selector)) {
      const events = new Map(), classes = new Set(), attributes = new Map();
      const name = selector.match(/\[name="([^"]+)"\]/)?.[1] || '';
      nodes.set(selector, {
        name, innerHTML: '', textContent: '', value: '', hidden: false, disabled: false,
        open: false, isConnected: true,
        dataset: name.startsWith('playerEmail_') ? {orgPlayerEmailIndex: name.split('_')[1]} : {}, checked: false,
        classList: {
          add(...values) { values.forEach(value => classes.add(value)); },
          remove(...values) { values.forEach(value => classes.delete(value)); },
          contains(value) { return classes.has(value); },
          toggle(value, force = !classes.has(value)) {
            if (force) classes.add(value); else classes.delete(value);
            return force;
          }
        },
        setAttribute(key, value) { attributes.set(key, String(value)); },
        getAttribute(key) { return attributes.get(key) ?? null; },
        removeAttribute(key) { attributes.delete(key); },
        addEventListener(type, handler) {
          if (!events.has(type)) events.set(type, []);
          events.get(type).push(handler);
        },
        dispatch(type, target = this) {
          const event = {target, preventDefault() {}};
          return Promise.all((events.get(type) || []).map(handler => handler(event)));
        },
        querySelector(child) { return node(selector + ' ' + child); },
        querySelectorAll(child) {
          return [...nodes.entries()].filter(([key]) => key.startsWith(selector + ' ') && key.includes(child)).map(([,value]) => value);
        },
        matches(query) { return query.includes('name') && query.includes(name); },
        closest() { return this; },
        focus() { this.focused = true; },
        close() { this.open = false; },
        remove() { this.isConnected = false; }
      });
    }
    return nodes.get(selector);
  };
  const context = vm.createContext({
    Date, Intl, Set, Map, Promise, AbortSignal,
    account: {userId: 'captain-one', accountType: 'player', organisationId: null},
    accountReady: new Promise(() => {}), location: {hash: '#ring'},
    document: {
      body: node('body'), querySelector: node, querySelectorAll() { return []; },
      addEventListener(type, handler) {
        if (!listeners.has(type)) listeners.set(type, []);
        listeners.get(type).push(handler);
      }
    },
    view: 'ring', filter: 'All sports', query: '',
    state: {posts: [], saved: []}, social: {online: true},
    render() {}, navigate() {}, icon() { return ''; }, postHTML() { return ''; },
    toast() {}, modalAction: null,
    escape(value) {
      return String(value).replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[character]));
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
  context.requests = [];
  context.respond = request => request.path.endsWith('/request-code')
    ? {email: request.body.email, challengeId: 'challenge-' + request.body.email, expiresIn: 600, message: 'Code sent.'}
    : request.path.endsWith('/verify-code')
      ? {email: request.body.email, challengeId: request.body.challengeId, verified: true, expiresIn: 600}
      : {registration: {id: 'team-one', status: 'registered'}};
  vm.runInContext('orgRequest = async (path,method,body) => {const request={path,method,body}; requests.push(request); return respond(request);};', context);
  const action = dataset => node('#modal').dispatch('click', {closest: () => ({dataset, disabled: false})});
  const fill = async (name, value) => {
    const input = node('#modal [name="' + name + '"]');
    input.value = value;
    await input.dispatch('input');
    await node('#modal').dispatch('input', input);
    await input.dispatch('change');
    await node('#modal').dispatch('change', input);
  };
  const messages = () => [...nodes.values()].map(value => value.textContent).join('\n');
  return {context, node, action, fill, messages};
}

function tournament(overrides = {}) {
  return {
    id: 'event-one', name: 'Community Cup', organisationId: 'org-one',
    organisationName: 'Local Club', sport: 'Football', eventType: 'online',
    status: 'open', startsAt: '2099-01-02T10:00:00Z', endsAt: '2099-01-02T12:00:00Z',
    registrationClosesAt: '2099-01-02T09:00:00Z', timezone: 'UTC',
    registrationCount: 0, capacity: 8, spotsLeft: 8, myRegistration: null,
    teamSize: 2, requirePlayerEmailVerification: true, ...overrides
  };
}

const plain = value => JSON.parse(JSON.stringify(value));
const settled = () => new Promise(setImmediate);

function registrationPage(overrides = {}) {
  const result = page();
  result.context.fixture = tournament(overrides);
  vm.runInContext("orgService.tournaments = [fixture]; orgRegister('event-one');", result.context);
  return result;
}

async function verifyPlayers(result, emails = ['first@example.com', 'second@example.com']) {
  for (let index = 0; index < emails.length; index++) await result.fill('playerEmail_' + index, emails[index]);
  await result.action({orgSendAllPlayerCodes: ''});
  await settled();
  for (let index = 0; index < emails.length; index++) {
    await result.fill('playerCode_' + index, '123456');
    await result.action({orgVerifyPlayerCode: String(index)});
    await settled();
  }
}

test('team registration adds one email/code row per configured player inside the existing dialog', () => {
  const {node} = registrationPage();
  const markup = node('#modal-body').innerHTML;
  assert.match(markup, /org-form-section/);
  assert.match(markup, /name="playerEmailOptions"/);
  assert.equal((markup.match(/name="playerEmail_\d+"/g) || []).length, 2);
  assert.equal((markup.match(/name="playerCode_\d+"/g) || []).length, 2);
  assert.match(markup, /type="email"/);
  assert.match(markup, /data-org-send-all-player-codes/);
  assert.match(markup, /data-org-send-player-code="0"/);
  assert.match(markup, /data-org-verify-player-code="1"/);
  assert.doesNotMatch(markup, /type="checkbox"[^>]+(?:name="verified|checked)/);
});

test('required roster blocks registration until every email is verified by the service', async () => {
  const {context, node, fill} = registrationPage();
  await fill('playerEmail_0', 'first@example.com');
  await fill('playerEmail_1', 'second@example.com');
  context.modalAction(new Map([['teamName', 'North Stars'], ['playerEmailOptions', '1'],
    ['playerEmail_0', 'first@example.com'], ['playerEmail_1', 'second@example.com'],
    ['playerCode_0', '123456'], ['playerCode_1', '123456'], ['verified', 'true']]));
  await settled();
  assert.equal(context.requests.length, 0);
  assert.equal(node('#modal').open, true);
  assert.match(node('#modal .org-form-error').textContent, /verif/i);
});

test('send all rejects invalid or duplicate addresses before sending any email', async () => {
  for (const emails of [['first@example.com', 'bad-address'], [' Same@example.com ', 'same@EXAMPLE.com'], ['first@example.com', '']]) {
    const result = registrationPage();
    await result.fill('playerEmail_0', emails[0]);
    await result.fill('playerEmail_1', emails[1]);
    await result.action({orgSendAllPlayerCodes: ''});
    await settled();
    assert.equal(result.context.requests.length, 0, emails.join(','));
    assert.match(result.messages(), /email|address|different|unique|player/i);
  }
});

test('each player receives a separate request and the final payload uses server-issued proofs', async () => {
  const result = registrationPage();
  await verifyPlayers(result, [' First@Example.com ', 'second@example.com']);
  const requests = plain(result.context.requests);
  const sends = requests.filter(request => request.path.endsWith('/request-code'));
  assert.deepEqual(sends.map(request => request.body), [{email: 'first@example.com'}, {email: 'second@example.com'}]);
  assert.ok(sends.every(request => request.path === 'tournaments/event-one/player-emails/request-code' && request.method === 'POST'));
  const checks = requests.filter(request => request.path.endsWith('/verify-code'));
  assert.equal(checks.length, 2);
  assert.deepEqual(checks[0].body, {email: 'first@example.com', challengeId: 'challenge-first@example.com', code: '123456'});
  result.context.modalAction(new Map([['teamName', ' North Stars '], ['playerEmailOptions', '1'],
    ['playerEmail_0', 'first@example.com'], ['playerEmail_1', 'second@example.com']]));
  await settled();
  const saved = plain(result.context.requests.at(-1));
  assert.equal(saved.path, 'tournaments/event-one/registrations');
  assert.deepEqual(saved.body, {teamName: 'North Stars', playerEmails: [
    {email: 'first@example.com', challengeId: 'challenge-first@example.com'},
    {email: 'second@example.com', challengeId: 'challenge-second@example.com'}
  ]});
  assert.equal(result.node('#modal').open, false);
});

test('changing an email clears its verification and blocks saving with the old proof', async () => {
  const result = registrationPage();
  await verifyPlayers(result);
  await result.fill('playerEmail_0', 'replacement@example.com');
  result.context.modalAction(new Map([['teamName', 'North Stars'], ['playerEmailOptions', '1'],
    ['playerEmail_0', 'replacement@example.com'], ['playerEmail_1', 'second@example.com']]));
  await settled();
  assert.equal(result.context.requests.filter(request => request.path.endsWith('/registrations')).length, 0);
  assert.match(result.node('#modal .org-form-error').textContent, /verif/i);
});

test('delivery failure preserves the form and never presents a successful verification', async () => {
  const result = registrationPage();
  result.context.respond = () => {throw new Error('Email delivery is unavailable.');};
  await result.fill('playerEmail_0', 'first@example.com');
  await result.action({orgSendPlayerCode: '0'});
  await settled();
  assert.equal(result.node('#modal').open, true);
  assert.equal(result.node('#modal [name="playerEmail_0"]').value, 'first@example.com');
  assert.match(result.messages(), /unavailable/);
  assert.doesNotMatch(result.messages(), /Code sent(?:\.| to)|Email verified\./);
});

test('unconfirmed or mismatched server responses do not mark a code as sent or verified', async () => {
  for (const response of [{}, {email: 'other@example.com', challengeId: 'wrong', expiresIn: 600}]) {
    const result = registrationPage();
    result.context.respond = () => response;
    await result.fill('playerEmail_0', 'first@example.com');
    await result.action({orgSendPlayerCode: '0'});
    await settled();
    assert.doesNotMatch(result.messages(), /Code sent(?:\.| to)|Email verified\./);
    assert.equal(result.node('#modal').open, true);
  }
  const result = registrationPage();
  await result.fill('playerEmail_0', 'first@example.com');
  await result.action({orgSendPlayerCode: '0'});
  await settled();
  result.context.respond = request => ({email: request.body.email, challengeId: request.body.challengeId, verified: false});
  await result.fill('playerCode_0', '123456');
  await result.action({orgVerifyPlayerCode: '0'});
  await settled();
  assert.doesNotMatch(result.messages(), /Email verified\./);
});

test('optional roster permits blank legacy registrations while checking any emails entered', async () => {
  const result = registrationPage({requirePlayerEmailVerification: false});
  result.context.modalAction(new Map([['teamName', 'North Stars'], ['playerEmailOptions', '1'],
    ['playerEmail_0', ''], ['playerEmail_1', '']]));
  await settled();
  assert.deepEqual(plain(result.context.requests.at(-1).body), {teamName: 'North Stars'});
  const partial = registrationPage({requirePlayerEmailVerification: false});
  await partial.fill('playerEmail_0', 'first@example.com');
  await partial.action({orgSendAllPlayerCodes: ''});
  await settled();
  assert.equal(partial.context.requests.length, 1);
  assert.equal(partial.context.requests[0].body.email, 'first@example.com');
});

test('editing other team details retains existing verified addresses without resending codes', async () => {
  const result = page();
  result.context.fixture = tournament({myRegistration: {id: 'team-one', status: 'registered', teamName: 'North Stars',
    playerEmails: [{email: 'first@example.com', verified: true, verifiedAt: '2026-01-01T00:00:00Z'},
      {email: 'second@example.com', verified: true, verifiedAt: '2026-01-01T00:00:00Z'}]}});
  vm.runInContext("orgService.tournaments = [fixture]; orgEditRegistration('event-one');", result.context);
  assert.match(result.node('#modal-body').innerHTML, /first@example\.com/);
  result.context.modalAction(new Map([['teamName', 'New Stars'], ['playerEmailOptions', '1'],
    ['playerEmail_0', 'first@example.com'], ['playerEmail_1', 'second@example.com']]));
  await settled();
  assert.deepEqual(plain(result.context.requests), [{path: 'tournaments/event-one/registrations/me', method: 'PATCH', body: {teamName: 'New Stars'}}]);
});

test('owner roster escapes private player email values and other accounts cannot open it', async () => {
  const result = page();
  const attack = '<img src=x onerror="alert(1)">@example.com';
  result.context.account = {userId: 'owner-one', accountType: 'organisation', organisationId: 'org-one'};
  result.context.fixture = tournament();
  result.context.respond = () => ({registrations: [{teamName: 'North Stars', playerName: 'Captain', status: 'registered',
    playerEmails: [{email: attack, verified: true, verifiedAt: '2026-01-01T00:00:00Z'}]}]});
  vm.runInContext('orgService.tournaments = [fixture]', result.context);
  await vm.runInContext("orgRoster('event-one')", result.context);
  const roster = result.node('#modal .org-roster-content').innerHTML;
  assert.match(roster, /&lt;img/);
  assert.doesNotMatch(roster, /<img\b/);
  result.node('#modal').close();
  result.context.requests.length = 0;
  result.context.account = {userId: 'player-other', accountType: 'player', organisationId: null};
  await vm.runInContext("orgRoster('event-one')", result.context);
  assert.equal(result.context.requests.length, 0);
  assert.equal(result.node('#modal').open, false);
  result.context.account = {userId: 'owner-other', accountType: 'organisation', organisationId: 'org-other'};
  await vm.runInContext("orgRoster('event-one')", result.context);
  assert.equal(result.context.requests.length, 0);
});

test('new tournaments enable required player verification and draft settings serialize the checkbox', () => {
  const result = page();
  result.context.account = {userId: 'owner-one', accountType: 'organisation', organisationId: 'org-one'};
  result.context.organisation = {id: 'org-one', name: 'Local Club', sport: 'Football', country: 'India'};
  vm.runInContext('orgService.organisation=organisation; orgCreateEvent()', result.context);
  assert.match(result.node('#modal-body').innerHTML, /name="requirePlayerEmailVerification"[^>]*checked/);
  result.context.data = new Map([['playerEmailVerificationOptions', '1'], ['requirePlayerEmailVerification', '1']]);
  assert.equal(vm.runInContext('orgTournamentInformation(data).requirePlayerEmailVerification', result.context), true);
  result.context.data.delete('requirePlayerEmailVerification');
  assert.equal(vm.runInContext('orgTournamentInformation(data).requirePlayerEmailVerification', result.context), false);
});

test('replacing one saved player sends a fresh proof while preserving the other verified address', async () => {
  const result = page();
  result.context.fixture = tournament({myRegistration: {id: 'team-one', status: 'registered', teamName: 'North Stars',
    playerEmails: [{email: 'first@example.com', verified: true}, {email: 'second@example.com', verified: true}]}});
  vm.runInContext("orgService.tournaments=[fixture]; orgEditRegistration('event-one')", result.context);
  // Real DOM inputs already contain the saved values; represent that prefill in this harness.
  result.node('#modal [name="playerEmail_0"]').value = 'first@example.com';
  result.node('#modal [name="playerEmail_1"]').value = 'second@example.com';
  await result.fill('playerEmail_0', 'replacement@example.com');
  await result.action({orgSendPlayerCode: '0'});
  await settled();
  await result.fill('playerCode_0', '123456');
  await result.action({orgVerifyPlayerCode: '0'});
  await settled();
  result.context.modalAction(new Map([['teamName', 'North Stars'], ['playerEmailOptions', '1'],
    ['playerEmail_0', 'replacement@example.com'], ['playerEmail_1', 'second@example.com']]));
  await settled();
  assert.deepEqual(plain(result.context.requests.at(-1).body.playerEmails), [
    {email: 'replacement@example.com', challengeId: 'challenge-replacement@example.com'},
    {email: 'second@example.com'}
  ]);
});

test('a wrong code keeps the row editable and never permits registration', async () => {
  const result = registrationPage();
  await result.fill('playerEmail_0', 'first@example.com');
  await result.action({orgSendPlayerCode: '0'});
  await settled();
  result.context.respond = () => {throw new Error('This verification code is invalid or has expired.');};
  await result.fill('playerCode_0', '000000');
  await result.action({orgVerifyPlayerCode: '0'});
  await settled();
  assert.match(result.messages(), /invalid or has expired/);
  assert.equal(result.node('#modal [name="playerCode_0"]').value, '000000');
  assert.equal(result.node('#modal [data-org-verify-player-code="0"]').disabled, false);
  assert.equal(result.node('#modal').open, true);
  assert.doesNotMatch(result.messages(), /Email verified\./);
});

test('an email edited while its send is pending ignores the response for the old address', async () => {
  const result = registrationPage();
  let resolveRequest;
  result.context.respond = () => new Promise(resolve => {resolveRequest = resolve;});
  await result.fill('playerEmail_0', 'first@example.com');
  const sending = result.action({orgSendPlayerCode: '0'});
  await settled();
  assert.equal(result.node('#modal [data-org-send-player-code="0"]').disabled, true);
  assert.doesNotMatch(result.messages(), /Code sent(?:\.| to)/);
  await result.fill('playerEmail_0', 'replacement@example.com');
  resolveRequest({email: 'first@example.com', challengeId: 'old-proof', expiresIn: 600});
  await sending;
  await settled();
  assert.doesNotMatch(result.messages(), /Code sent(?:\.| to)|Email verified\./);
  assert.equal(result.node('#modal [name="playerCode_0"]').disabled, true);
  assert.equal(result.node('#modal [data-org-send-player-code="0"]').disabled, false);
});

test('an optional saved roster can be cleared explicitly without retaining its old emails', async () => {
  const result = page();
  result.context.fixture = tournament({requirePlayerEmailVerification: false,
    myRegistration: {id: 'team-one', status: 'registered', teamName: 'North Stars',
      playerEmails: [{email: 'first@example.com', verified: true}, {email: 'second@example.com', verified: true}]}});
  vm.runInContext("orgService.tournaments=[fixture]; orgEditRegistration('event-one')", result.context);
  result.context.modalAction(new Map([['teamName', 'North Stars'], ['playerEmailOptions', '1'],
    ['playerEmail_0', ''], ['playerEmail_1', '']]));
  await settled();
  assert.deepEqual(plain(result.context.requests.at(-1).body), {teamName: 'North Stars', playerEmails: []});
});
