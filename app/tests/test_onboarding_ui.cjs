const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = name => readFileSync(path.join(__dirname, '../static/sportspace', name), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const response = (value, status = 200) => ({status, ok: status < 400, json: async () => value});
const deferred = () => {
  let resolve;
  return {promise: new Promise(done => { resolve = done; }), resolve(value) { resolve(value); }};
};
function attrs(markup) {
  const result = {};
  for (const match of markup.matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
    result[match[1]] = match[2] ?? match[3] ?? match[4] ?? '';
  }
  return result;
}
function matches(node, selector) {
  if (selector.startsWith('.')) return (node.className || '').split(/\s+/).includes(selector.slice(1));
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  const attribute = selector.match(/^\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
  if (attribute) return attribute[2] === undefined ? attribute[1] in node.attrs : node.attrs[attribute[1]] === attribute[2];
  return node.tag === selector;
}
function element(tag = 'div', initial = {}) {
  const node = {tag, attrs: {...initial}, children: [], dataset: {}, isConnected: true,
    hidden: 'hidden' in initial, disabled: 'disabled' in initial, required: 'required' in initial,
    name: initial.name || '', value: initial.value || '', type: initial.type || '', textContent: '',
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return this.attrs[name] ?? null; },
    append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } },
    replaceChildren(...children) { this.children = []; this.append(...children); },
    remove() { this.isConnected = false; }, focus() {},
    closest(selector) { return matches(this, selector) ? this : this.parent?.closest(selector) || null; },
    querySelectorAll(selector) {
      const selectors = selector.split(',').map(value => value.trim());
      const result = [];
      for (const child of this.children) {
        if (selectors.some(value => matches(child, value))) result.push(child);
        result.push(...child.querySelectorAll(selector));
      }
      return result;
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  };
  for (const [name, value] of Object.entries(initial)) {
    if (name.startsWith('data-')) node.dataset[name.slice(5).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] = value;
  }
  Object.defineProperties(node, {
    id: {get() { return this.attrs.id || ''; }, set(value) { this.attrs.id = value; }},
    className: {get() { return this.attrs.class || ''; }, set(value) { this.attrs.class = value; }},
    innerHTML: {
      configurable: true,
      get() { return this.markup || ''; },
      set(markup) {
        for (const child of this.children) child.isConnected = false;
        this.children = []; this.markup = markup;
        for (const match of markup.matchAll(/<(input|select|button|p|div|span|small|label)\b([^>]*)>/g)) {
          const child = element(match[1], attrs(match[2]));
          if (child.tag === 'select') {
            const options = markup.slice(match.index + match[0].length).split('</select>')[0];
            const option = options.match(/<option\b([^>]*)>([^<]*)/);
            child.value = option ? attrs(option[1]).value || option[2] : '';
          }
          if (child.tag === 'button') child.append(element('span'));
          this.append(child);
        }
        this.fields = this.children.filter(child => ['input', 'select'].includes(child.tag));
      }
    }
  });
  node.classList = {
    contains(value) { return node.className.split(/\s+/).includes(value); },
    add(...values) { node.className = [...new Set([...node.className.split(/\s+/).filter(Boolean), ...values])].join(' '); },
    remove(...values) { node.className = node.className.split(/\s+/).filter(value => !values.includes(value)).join(' '); },
    toggle(value, on = !this.contains(value)) { if (on) this.add(value); else this.remove(value); }
  };
  return node;
}

async function page({enabled = false, sdk = true, hash = '', authenticate} = {}) {
  const requests = [], scripts = [], navigations = [], historyChanges = [], envelopes = new Map();
  let overlay, sdkOptions, renderedButtons = 0;
  function section() {
    const value = element('section');
    Object.defineProperty(value, 'innerHTML', {
      get() { return this.markup || ''; },
      set(markup) {
        if (this.form) this.form.isConnected = false;
        this.markup = markup;
        const match = markup.match(/<form\b([^>]*)>([\s\S]*?)<\/form>/);
        this.form = element('form', attrs(match[1])); this.form.innerHTML = match[2];
        this.stickers = element('div', {class: 'account-sticker-strip'});
        this.stickers.parent = element('div', {class: 'account-stickers'});
      }
    });
    value.querySelector = selector => selector === 'form' || selector === '.account-form' ? value.form :
      selector === '.account-sticker-strip' ? value.stickers : value.form.querySelector(selector);
    value.querySelectorAll = selector => value.form.querySelectorAll(selector);
    return value;
  }
  const context = vm.createContext({Date, Promise, URLSearchParams, encodeURIComponent,
    isSecureContext: true, navigator: {}, RingStickers: {ready: Promise.resolve([])},
    matchMedia: () => ({matches: false}),
    document: {
      body: element('body'),
      head: {append(script) { scripts.push(script); setImmediate(() => script.onerror()); }},
      addEventListener() {}, querySelectorAll: () => [], querySelector: () => element(),
      getElementById: id => id === 'account-screen' ? overlay : null,
      createElement(tag) { if (tag === 'section') { overlay = section(); return overlay; } return element(tag); }
    },
    location: {hash, pathname: '/ring', search: '', protocol: 'https:', hostname: 'dhoyo.example',
      replace(url) { navigations.push(url); }, reload() { assert.fail('Unexpected reload'); }},
    history: {replaceState(_state, _title, url) { historyChanges.push(url); context.location.hash = url.includes('#') ? '#' + url.split('#')[1] : ''; }},
    FormData: class {
      constructor(form) { this.values = form.fields.filter(field => field.name && !field.disabled).map(field => [field.name, field.value]); }
      [Symbol.iterator]() { return this.values[Symbol.iterator](); }
    },
    encryptAccountPayload: async (_route, payload) => {
      const ciphertext = 'envelope-' + envelopes.size;
      envelopes.set(ciphertext, JSON.parse(JSON.stringify(payload)));
      return {ciphertext};
    },
    fetch: async (url, options = {}) => {
      const envelope = options.body ? JSON.parse(options.body) : undefined;
      const request = {url, payload: envelope?.ciphertext ? envelopes.get(envelope.ciphertext) : envelope, options};
      requests.push(request);
      if (url === '/api/auth/me') return response({userId: null});
      if (url === '/api/auth/google/config') return response({enabled, clientId: 'synthetic-client.apps.googleusercontent.com'});
      if (url === '/api/auth/google/challenge') return response({challengeId: 'synthetic-challenge', nonce: 'synthetic-nonce', expiresIn: 300});
      return authenticate ? authenticate(request) : response({activationRequired: true, email: 'player@example.invalid', message: 'Check your activation email.'});
    }
  });
  context.window = context;
  if (sdk) context.google = {accounts: {id: {
    initialize(options) { sdkOptions = options; }, renderButton() { renderedButtons++; }
  }}};
  vm.runInContext(source('account-onboarding.js'), context, {filename: 'account-onboarding.js'});
  vm.runInContext(source('auth-ui.js'), context, {filename: 'auth-ui.js'});
  await tick(); await tick();
  return {context, requests, scripts, navigations, historyChanges,
    get form() { return overlay.form; }, get sdkOptions() { return sdkOptions; }, get renderedButtons() { return renderedButtons; },
    run(code) { return vm.runInContext(code, context); },
    field(name) { return overlay.form.querySelector(`[name="${name}"]`); },
    fill(values) { for (const [name, value] of Object.entries(values)) { const field = this.field(name); assert.ok(field, `Missing field ${name}`); field.value = value; } },
    async submit() { const form = overlay.form; return form.onsubmit({target: form, preventDefault() {}}); },
    async google(credential = 'synthetic-google-credential') { assert.ok(sdkOptions); sdkOptions.callback({credential}); await tick(); await tick(); }
  };
}

const details = {name: ' Player Name ', phone: ' +919876543210 ', city: ' Bengaluru ', state: ' Karnataka ', country: ' India ', sport: 'Football', accountType: 'player'};

test('unconfigured Google stays visible with an honest unavailable state and email access', async () => {
  const p = await page({enabled: false, sdk: false});
  assert.equal(p.form.id, 'account-login-form');
  assert.ok(p.field('email')); assert.ok(p.field('password'));
  assert.equal(p.form.querySelector('.account-google').hidden, false);
  const unavailable = p.form.querySelector('.account-google-unavailable');
  assert.equal(unavailable.disabled, true);
  assert.match(unavailable.textContent, /Not available yet/);
  assert.match(p.form.querySelector('.account-google-status').textContent, /being set up/);
  assert.deepEqual(p.scripts, []);
  assert.ok(!p.requests.some(request => request.url.endsWith('/challenge')));
  assert.equal(p.renderedButtons, 0);
});

test('new Google users must complete required profile fields and receive activation before any session', async () => {
  const p = await page({enabled: true, authenticate: request => request.url.endsWith('/google') ?
    response({onboardingRequired: true, email: 'player@example.invalid', name: 'Google Name'}) :
    response({activationRequired: true, email: 'player@example.invalid', message: 'Activate from your email.'})});
  assert.equal(p.sdkOptions.nonce, 'synthetic-nonce');
  await p.google();
  assert.equal(p.form.id, 'account-google-register-form');
  for (const name of ['name', 'phone', 'city', 'state', 'country', 'sport']) assert.equal(p.field(name).required, true, name);
  assert.equal(p.field('phone').attrs.type, 'tel');
  assert.equal(p.field('phone').attrs.autocomplete, 'tel');
  assert.equal(p.field('email'), null);
  p.fill(details);
  p.form.fields.push(element('input', {name: 'email', value: 'attacker@example.invalid'}));
  p.form.fields.push(element('input', {name: 'credential', value: 'unexpected-extra-credential'}));
  await p.submit();
  const registration = p.requests.find(request => request.url.endsWith('/google/register'));
  assert.deepEqual(registration.payload, {name: 'Player Name', phone: '+919876543210', city: 'Bengaluru', state: 'Karnataka', country: 'India', sport: 'Football', accountType: 'player'});
  assert.equal(p.form.id, 'account-activation-pending-form');
  assert.equal(p.run('account.userId'), null);
  assert.deepEqual(p.navigations, []);
  assert.ok(!p.form.innerHTML.includes('synthetic-google-credential'));
  assert.match(registration.options.body, /envelope-/);
  assert.ok(!registration.options.body.includes('9876543210'));
});

test('Google organisation onboarding reveals required organisation name and submits only that account type detail', async () => {
  const p = await page();
  p.run("DhoyoOnboarding.registerGoogle({email:'owner@example.invalid',name:'Owner'})");
  assert.equal(p.field('organisationName').disabled, true);
  assert.equal(p.form.querySelector('.account-onboarding-organisation').hidden, true);
  p.fill({...details, accountType: 'organisation'});
  p.field('accountType').onchange();
  assert.equal(p.field('organisationName').required, true);
  assert.equal(p.field('organisationName').disabled, false);
  assert.equal(p.form.querySelector('.account-onboarding-organisation').hidden, false);
  p.fill({organisationName: ' Community Club '});
  await p.submit();
  assert.deepEqual(p.requests.find(request => request.url.endsWith('/google/register')).payload,
    {name: 'Player Name', phone: '+919876543210', city: 'Bengaluru', state: 'Karnataka', country: 'India', sport: 'Football', accountType: 'organisation', organisationName: 'Community Club'});
  assert.equal(p.run('account.userId'), null);
});

test('activation removes its token from the URL and submits it only after explicit confirmation', async () => {
  const token = 'synthetic-activation-token-that-must-remain-private';
  const waiting = deferred();
  const p = await page({hash: '#activate-token=' + token, authenticate: () => waiting.promise});
  assert.equal(p.form.id, 'account-activation-form');
  assert.deepEqual(p.historyChanges, ['/ring#ring']);
  assert.ok(!p.context.location.hash.includes(token));
  assert.ok(!p.form.innerHTML.includes(token));
  assert.ok(!p.form.fields.some(field => field.value.includes(token)));
  assert.ok(!p.requests.some(request => request.url.endsWith('/activate-account')));
  const first = p.submit(); await tick();
  await p.submit();
  const activation = p.requests.filter(request => request.url.endsWith('/activate-account'));
  assert.equal(activation.length, 1);
  assert.deepEqual(activation[0].payload, {token});
  assert.ok(!activation[0].options.body.includes(token));
  waiting.resolve(response({message: 'Account activated. Sign in now.'})); await first;
  assert.equal(p.form.id, 'account-login-form');
  assert.equal(p.run('account.userId'), null);
  assert.deepEqual(p.navigations, []);
});

test('Google activation-required HTTP errors open the pending activation flow', async () => {
  const p = await page({enabled: true, authenticate: () => response({error: 'Activate your account first.', activationRequired: true, email: 'pending@example.invalid'}, 403)});
  await p.google();
  assert.equal(p.form.id, 'account-activation-pending-form');
  assert.equal(p.field('email').value, 'pending@example.invalid');
  assert.match(p.form.innerHTML, /Activate your account first/);
  assert.equal(p.run('account.userId'), null);
  assert.deepEqual(p.navigations, []);
});

test('a Google SDK load failure preserves functional email and password login', async () => {
  const p = await page({enabled: true, sdk: false, authenticate: () => response({userId: 'player-email', accountType: 'player'})});
  assert.equal(p.scripts.length, 1);
  assert.match(p.form.querySelector('.account-error').textContent, /Google sign-in could not load/);
  assert.equal(p.form.id, 'account-login-form');
  p.fill({email: 'player@example.invalid', password: 'synthetic-password'});
  await p.submit();
  assert.deepEqual(p.requests.find(request => request.url.endsWith('/login')).payload, {email: 'player@example.invalid', password: 'synthetic-password'});
  assert.deepEqual(p.navigations, ['/ring#ring']);
});

test('a delayed Google callback cannot replace a newer account form or establish a session', async () => {
  const waiting = deferred();
  const p = await page({enabled: true, authenticate: () => waiting.promise});
  p.sdkOptions.callback({credential: 'synthetic-old-credential'});
  await tick();
  p.run("showAccountForm('forgot')");
  const current = p.form;
  waiting.resolve(response({onboardingRequired: true, email: 'old@example.invalid', name: 'Old Form'}));
  await tick(); await tick();
  assert.equal(p.form, current);
  assert.equal(p.form.id, 'account-forgot-form');
  assert.equal(p.run('account.userId'), null);
  assert.deepEqual(p.navigations, []);
});

test('email registration also requires phone details and stays signed out while activation is pending', async () => {
  const p = await page();
  p.run("showAccountForm('register')");
  assert.equal(p.field('phone').required, true);
  assert.equal(p.field('phone').attrs.autocomplete, 'tel');
  p.fill({...details, email: 'player@example.invalid', password: 'synthetic-password'});
  await p.submit();
  assert.equal(p.form.id, 'account-activation-pending-form');
  assert.equal(p.requests.find(request => request.url.endsWith('/register')).payload.phone, ' +919876543210 ');
  assert.equal(p.run('account.userId'), null);
  assert.deepEqual(p.navigations, []);
});

test('Google sign-in preserves the requested achievements or reminders page', async () => {
  for (const route of ['progress', 'reminders']) {
    const p = await page({hash: '#' + route, enabled: true, authenticate: () => response({userId: 'google-player', accountType: 'player'})});
    await p.google();
    assert.deepEqual(p.navigations, ['/ring#' + route]);
  }
});
