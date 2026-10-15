const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = readFileSync(path.join(__dirname, '../static/sportspace/auth-ui.js'), 'utf8');
const response = (value, status = 200) => ({status, ok: status < 400, json: async () => value});
const tick = () => new Promise(resolve => setImmediate(resolve));

function deferred() {
  let resolve, reject;
  const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
  return {promise, resolve, reject};
}

// These fixtures model only the DOM operations used by account access. Parsing
// rendered tags lets the tests inspect form semantics without matching JS source.
function attributes(tag) {
  const result = {};
  for (const match of tag.matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
    result[match[1]] = match[2] ?? match[3] ?? match[4] ?? '';
  }
  return result;
}

function element(initial = {}) {
  const attrs = {...initial};
  const classes = new Set();
  return {
    attrs, dataset: {}, isConnected: true, disabled: false, textContent: '', innerHTML: '',
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
      toggle(name, force) {
        const present = force ?? !classes.has(name);
        if (present) classes.add(name); else classes.delete(name);
        return present;
      }
    },
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return attrs[name] ?? null; },
    append() {}, focus() {},
    remove() { this.isConnected = false; }
  };
}

function accountOverlay(events) {
  const overlay = element();
  Object.defineProperty(overlay, 'innerHTML', {
    get() { return this.markup; },
    set(markup) {
      if (this.form) this.form.isConnected = false;
      this.markup = markup;
      const form = element(attributes(markup.match(/<form\b([^>]*)>/)[1]));
      form.fields = [...markup.matchAll(/<input\b([^>]*)>/g)].map(match => {
        const field = element(attributes(match[1]));
        field.name = field.attrs.name;
        field.value = field.attrs.value || '';
        field.type = field.attrs.type || 'text';
        return field;
      });
      form.submit = element({type: 'submit'});
      form.submit.label = element();
      form.submit.querySelector = selector => selector === 'span' ? form.submit.label : null;
      form.error = element({role: 'alert'});
      form.notice = markup.includes('class="account-notice"') ? element({role: 'status'}) : null;
      form.switch = markup.includes('class="account-switch"') ? element() : null;
      form.forgot = markup.includes('class="account-forgot"') ? element() : null;
      form.modes = [...markup.matchAll(/<button\b([^>]*data-account-mode=[^>]*)>/g)].map(match => {
        const attrs = attributes(match[1]);
        return {...element(attrs), dataset: {accountMode: attrs['data-account-mode']}};
      });
      form.passwordToggle = markup.includes('class="account-password-toggle"') ? element() : null;
      form.querySelector = selector => {
        if (selector === '[type=submit]' || selector === '.account-submit') return form.submit;
        if (selector === '.account-error') return form.error;
        if (selector === '.account-notice') return form.notice;
        if (selector === '.account-switch') return form.switch;
        if (selector === '.account-forgot') return form.forgot;
        if (selector === '.account-password-toggle') return form.passwordToggle;
        if (selector === 'input') return form.fields[0] || null;
        const name = selector.match(/^\[name=["']?([^"'\]]+)["']?\]$/)?.[1];
        return form.fields.find(field => field.name === name) || null;
      };
      form.querySelectorAll = selector => {
        if (!selector) return [...form.modes, form.switch, form.forgot].filter(Boolean);
        return [
          ...(selector.includes('[data-account-mode]') ? form.modes : []),
          ...(selector.includes('.account-switch') && form.switch ? [form.switch] : []),
          ...(selector.includes('.account-forgot') && form.forgot ? [form.forgot] : [])
        ];
      };
      form.remove = () => { form.isConnected = false; events.push('form removed'); };
      this.form = form;
      this.stickers = element();
      this.stickers.closest = () => element();
    }
  });
  overlay.querySelector = selector => {
    if (selector === 'form' || selector === '.account-form') return overlay.form;
    if (selector === '.account-sticker-strip') return overlay.stickers;
    return overlay.form.querySelector(selector);
  };
  overlay.querySelectorAll = selector => overlay.form.querySelectorAll(selector);
  return overlay;
}

async function accountPage({register = false, authenticate, store, secure = true, credentialAPI = true, constructorError = false, credentialsAPI = true, hash = '', userId = null, protocol = 'https:', hostname = 'dhoyo.example'} = {}) {
  const events = [], requests = [], stored = [], navigations = [], historyChanges = [];
  const encryptedFixtures = new Map();
  let overlay, formDataReads = 0;
  const context = {
    isSecureContext: secure,
    document: {
      querySelectorAll: () => [],
      querySelector: () => element(),
      getElementById: id => id === 'account-screen' ? overlay : null,
      createElement: tag => {
        if (tag !== 'section') return element();
        overlay = accountOverlay(events);
        return overlay;
      },
      body: {...element(), append() {}}
    },
    RingStickers: {ready: Promise.resolve([])},
    // Form behavior tests isolate the encrypted transport. Real crypto and
    // browser/server interoperability are covered separately.
    encryptAccountPayload: async (_path, payload) => {
      const ciphertext = 'fixture-' + encryptedFixtures.size;
      encryptedFixtures.set(ciphertext, JSON.parse(JSON.stringify(payload)));
      return {ciphertext};
    },
    matchMedia: () => ({matches: false}),
    FormData: class {
      constructor(form) {
        formDataReads++;
        this.values = form.fields.map(field => [field.name, field.value]);
      }
      [Symbol.iterator]() { return this.values[Symbol.iterator](); }
    },
    fetch: async (url, options = {}) => {
      if (url === '/api/auth/me') return response({userId});
      const envelope = options.body ? JSON.parse(options.body) : undefined;
      const request = {url, payload: envelope ? encryptedFixtures.get(envelope.ciphertext) : undefined};
      requests.push(request);
      events.push('authentication requested');
      const result = authenticate ? await authenticate(request) : response({userId: 'player-123'});
      events.push('authentication returned');
      return result;
    },
    location: {
      hash, protocol, hostname, pathname: '/ring', search: '', href: protocol + '//' + hostname + '/ring' + hash,
      replace(target) { navigations.push(target); events.push('navigate'); },
      reload() { assert.fail('Account access should perform one clear navigation after success'); }
    },
    history: {
      replaceState(_state, _title, target) {
        historyChanges.push(target);
        context.location.hash = target.includes('#') ? '#' + target.split('#').slice(1).join('#') : '';
        context.location.href = 'https://dhoyo.example' + target;
      }
    },
    URLSearchParams,
    navigator: credentialsAPI ? {credentials: {
      async store(credential) {
        stored.push(credential);
        events.push('password storage requested');
        if (store) await store(credential);
        events.push('password storage returned');
      }
    }} : {}
  };
  if (credentialAPI) context.PasswordCredential = class {
    constructor(data) {
      if (constructorError) throw new Error('Credential API unavailable');
      Object.assign(this, data);
    }
  };
  context.window = context;
  vm.runInNewContext(script, context, {filename: 'auth-ui.js'});
  await tick();
  if (register) overlay.form.modes.find(button => button.dataset.accountMode === 'register').onclick();
  return {
    context, events, requests, stored, navigations, historyChanges,
    get form() { return overlay?.form; },
    get formDataReads() { return formDataReads; },
    fill(values) {
      for (const [name, value] of Object.entries(values)) {
        const field = overlay.form.fields.find(item => item.name === name);
        assert.ok(field, `Missing ${name} field`);
        field.value = value;
      }
    },
    submit() {
      const form = overlay.form;
      let prevented = false;
      const pending = form.onsubmit({target: form, preventDefault() { prevented = true; }});
      assert.equal(prevented, true);
      return pending;
    },
    click(selector) {
      const button = overlay.form.querySelector(selector);
      assert.ok(button, `Missing ${selector} control`);
      button.onclick({currentTarget: button, preventDefault() {}});
    },
    mode(mode) {
      const button = overlay.form.modes.find(item => item.dataset.accountMode === mode);
      assert.ok(button, `Missing ${mode} mode control`);
      button.onclick({currentTarget: button, preventDefault() {}});
    }
  };
}

test('public HTTP login refuses to send credentials before any network request', async () => {
  const page = await accountPage({protocol: 'http:', hostname: 'dhoyo.example', secure: false});
  page.fill({email: 'player@example.com', password: 'long-password-123'});
  await page.submit();
  assert.match(page.form.error.textContent, /HTTPS/);
  assert.deepEqual(page.requests, []);
  assert.equal(page.stored.length, 0);
  assert.deepEqual(page.navigations, []);
});

test('HTTP development on a loopback host remains available', async t => {
  for (const hostname of ['localhost', '127.0.0.1', '[::1]']) {
    await t.test(hostname, async () => {
      const page = await accountPage({protocol: 'http:', hostname, secure: false});
      page.fill({email: 'player@example.com', password: 'long-password-123'});
      await page.submit();
      assert.equal(page.requests[0].url, '/api/auth/login');
      assert.deepEqual(page.navigations, ['/ring#ring']);
    });
  }
});

for (const register of [false, true]) {
  const mode = register ? 'registration' : 'login';
  test(`${mode} identifies its credential fields for browser password managers`, async () => {
    const page = await accountPage({register});
    assert.equal(page.form.getAttribute('id'), register ? 'account-register-form' : 'account-login-form');
    assert.equal(page.form.getAttribute('method'), 'post');
    assert.equal(page.form.getAttribute('action'), '/api/auth/' + (register ? 'register' : 'login'));
    assert.equal(page.form.getAttribute('autocomplete'), 'on');
    assert.equal(page.form.querySelector('[name="email"]').getAttribute('autocomplete'), 'username');
    assert.equal(page.form.querySelector('[name="password"]').getAttribute('autocomplete'), register ? 'new-password' : 'current-password');
  });

  test(`${mode} saves the authenticated submission before navigation`, async () => {
    const auth = deferred(), storage = deferred();
    const page = await accountPage({register, authenticate: () => auth.promise, store: () => storage.promise});
    const values = {email: '  Player@example.com  ', password: '  long-password-123  '};
    if (register) values.name = '  Player Name  ';
    page.fill(values);
    const submitted = page.submit();
    assert.equal(page.form.submit.disabled, true);
    assert.equal(page.form.getAttribute('aria-busy'), 'true');
    assert.equal(page.formDataReads, 1);
    await tick(); // Encryption completes before the authentication fetch starts.
    assert.equal(page.requests[0].url, '/api/auth/' + (register ? 'register' : 'login'));
    assert.equal(page.requests[0].payload.email, values.email.trim());
    assert.equal(page.requests[0].payload.password, values.password);
    assert.equal(page.stored.length, 0, 'Unconfirmed passwords must never reach the browser store');
    assert.deepEqual(page.navigations, []);
    page.fill({email: 'different@example.com', password: 'changed-password-123'});
    auth.resolve(response({userId: 'player-123'}));
    await tick();
    assert.equal(page.stored.length, 1);
    assert.equal(page.stored[0].id, values.email.trim());
    assert.equal(page.stored[0].password, values.password, 'Keep every character of the submitted password');
    assert.equal(page.stored[0].name, register ? values.name.trim() : undefined);
    assert.deepEqual(page.navigations, [], 'Wait for the browser store before leaving the form');
    storage.resolve();
    await submitted;
    assert.deepEqual(page.navigations, ['/ring#ring']);
    assert.equal(page.form.isConnected, false);
    assert.equal(page.form.querySelector('[name="password"]').value, '', 'Clear the password from the outgoing form after browser saving');
    assert.deepEqual(page.events, ['authentication requested', 'authentication returned', 'password storage requested', 'password storage returned', 'form removed', 'navigate']);
    assert.equal(page.formDataReads, 1, 'Credential storage must reuse the authenticated submission');
  });

  test(`${mode} leaves rejected credentials unsaved and allows correction`, async () => {
    const page = await accountPage({register, authenticate: () => response({error: 'Credentials rejected'}, register ? 409 : 401)});
    page.fill({email: 'player@example.com', password: 'incorrect-password-123'});
    await page.submit();
    assert.equal(page.form.error.textContent, 'Credentials rejected');
    assert.equal(page.form.submit.disabled, false);
    assert.equal(page.form.getAttribute('aria-busy'), 'false');
    assert.ok(page.form.querySelectorAll().every(button => !button.disabled));
    assert.equal(page.form.isConnected, true);
    assert.equal(page.stored.length, 0);
    assert.deepEqual(page.navigations, []);
  });
}

test('password manager limitations never undo successful authentication', async t => {
  const cases = [
    ['PasswordCredential is unsupported', {credentialAPI: false}],
    ['credential storage is unsupported', {credentialsAPI: false}],
    ['the page is not a secure context', {secure: false}],
    ['the credential constructor throws', {constructorError: true}],
    ['the browser rejects password storage', {store: () => Promise.reject(new Error('Storage declined'))}]
  ];
  for (const [name, options] of cases) {
    await t.test(name, async () => {
      const page = await accountPage(options);
      page.fill({email: 'player@example.com', password: 'long-password-123'});
      await page.submit();
      assert.deepEqual(page.navigations, ['/ring#ring']);
      assert.equal(page.form.isConnected, false);
      assert.equal(page.form.error.textContent, '');
      if (!options.store) assert.equal(page.stored.length, 0);
    });
  }
});

test('login accepts existing passwords shorter than the new password minimum', async () => {
  const page = await accountPage();
  assert.equal(page.form.querySelector('[name="password"]').getAttribute('minlength'), null);
  assert.equal(page.form.querySelector('[name="password"]').getAttribute('maxlength'), '128');
  page.fill({email: 'player@example.com', password: 'old-pass'});
  await page.submit();
  assert.equal(page.requests[0].payload.password, 'old-pass');
  assert.deepEqual(page.navigations, ['/ring#ring']);
});

test('signup collects a required private international phone number', async () => {
  const page = await accountPage({register: true});
  const phone = page.form.querySelector('[name="phone"]');
  assert.equal(phone.type, 'tel');
  assert.equal(phone.getAttribute('autocomplete'), 'tel');
  assert.notEqual(phone.getAttribute('required'), null);
  page.fill({email: 'player@example.com', password: 'long-password-123', phone: '+91 98765 43210'});
  await page.submit();
  assert.equal(page.requests[0].payload.phone, '+91 98765 43210');
});

test('pending signup requires activation before identity, password saving or navigation', async () => {
  const page = await accountPage({register: true, authenticate: () => response({
    activationRequired: true, email: 'player@example.com', message: 'Check your email and activate your account.'
  }, 201)});
  page.fill({email: 'player@example.com', password: 'long-password-123', phone: '+919876543210'});
  await page.submit();
  assert.equal(page.form.getAttribute('id'), 'account-login-form');
  assert.match(page.form.notice.textContent, /activate your account/);
  assert.equal(page.stored.length, 0);
  assert.deepEqual(page.navigations, []);
  assert.equal(vm.runInContext('account.userId', page.context), null);
});

test('an inactive login opens activation recovery without saving credentials', async () => {
  const calls = [];
  const page = await accountPage({authenticate: () => response({
    activationRequired: true, error: 'Activate your account using your email link.'
  }, 403)});
  page.context.DhoyoOnboarding = {pending: (...values) => calls.push(values)};
  page.fill({email: 'player@example.com', password: 'long-password-123'});
  await page.submit();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'player@example.com');
  assert.match(calls[0][1], /Activate your account/);
  assert.equal(page.form.querySelector('[name="password"]').value, '');
  assert.equal(page.stored.length, 0);
  assert.deepEqual(page.navigations, []);
});

test('forgot password offers an email-only form and preserves the email while switching modes', async () => {
  const page = await accountPage();
  page.fill({email: 'player@example.com', password: 'private-password'});
  page.click('.account-forgot');
  assert.equal(page.form.getAttribute('id'), 'account-forgot-form');
  assert.equal(page.form.getAttribute('method'), 'post');
  assert.equal(page.form.getAttribute('action'), '/api/auth/request-password-code');
  assert.deepEqual(page.form.fields.map(field => field.name), ['email']);
  assert.equal(page.form.querySelector('[name="email"]').value, 'player@example.com');
  page.fill({email: 'corrected@example.com'});
  page.click('.account-switch');
  assert.equal(page.form.getAttribute('id'), 'account-login-form');
  assert.equal(page.form.querySelector('[name="email"]').value, 'corrected@example.com');
  assert.equal(page.form.querySelector('[name="password"]').value, '', 'Do not retain an unverified password across modes');
  page.mode('register');
  assert.equal(page.form.querySelector('[name="email"]').value, 'corrected@example.com');
});

test('forgot password opens the code form without saving credentials or navigating', async () => {
  const notice = 'If an account uses this email, a verification code has been sent.';
  const page = await accountPage({authenticate: () => response({message: notice, challengeId: 'c'.repeat(43)})});
  page.click('.account-forgot');
  page.fill({email: '  player@example.com  '});
  await page.submit();
  assert.deepEqual(page.requests, [{url: '/api/auth/request-password-code', payload: {email: 'player@example.com'}}]);
  assert.equal(page.form.getAttribute('id'), 'account-code-form');
  assert.equal(page.form.notice.getAttribute('role'), 'status');
  assert.equal(page.form.notice.textContent, notice);
  assert.equal(page.form.error.textContent, '');
  assert.equal(page.form.submit.disabled, false);
  assert.equal(page.form.getAttribute('aria-busy'), 'false');
  assert.equal(page.stored.length, 0);
  assert.deepEqual(page.navigations, []);
});

test('direct password recovery opens the email form and removes its hash', async () => {
  const page = await accountPage({hash: '#forgot-password'});
  assert.deepEqual(page.historyChanges, ['/ring#ring']);
  assert.equal(page.form.getAttribute('id'), 'account-forgot-form');
  assert.equal(page.form.getAttribute('action'), '/api/auth/request-password-code');
});

test('verification code uses numeric keyboard and one-time-code autofill', async () => {
  const page = await accountPage({authenticate: () => response({message: 'Check your email.', challengeId: 'c'.repeat(43)})});
  page.click('.account-forgot');
  page.fill({email: 'player@example.com'});
  await page.submit();
  assert.deepEqual(page.form.fields.map(field => field.name), ['code', 'password', 'passwordConfirm']);
  const code = page.form.querySelector('[name="code"]');
  assert.equal(code.getAttribute('inputmode'), 'numeric');
  assert.equal(code.getAttribute('autocomplete'), 'one-time-code');
  assert.equal(code.getAttribute('pattern'), '[0-9]{6}');
  assert.equal(code.getAttribute('maxlength'), '6');
  assert.equal(page.form.getAttribute('action'), '/api/auth/reset-password-code');
  assert.deepEqual(page.historyChanges, []);
});

test('malformed code and mismatching confirmation do not submit a reset', async () => {
  const page = await accountPage({authenticate: () => response({message: 'Check your email.', challengeId: 'c'.repeat(43)})});
  page.click('.account-forgot'); page.fill({email: 'player@example.com'}); await page.submit();
  page.fill({code: '123456', password: 'new-password-123', passwordConfirm: 'different-password-123'});
  await page.submit();
  assert.match(page.form.error.textContent, /match/i);
  page.fill({code: 'abc123', passwordConfirm: 'new-password-123'});
  await page.submit();
  assert.match(page.form.error.textContent, /six-digit/i);
  assert.equal(page.requests.length, 1);
  assert.equal(page.form.submit.disabled, false);
});

test('code reset sends only the challenge, code and exact password and then offers login', async () => {
  const notice = 'Your password has been reset. Sign in with your new password.';
  const challengeId = 'c'.repeat(43);
  const page = await accountPage({authenticate: ({url}) => response(url === '/api/auth/request-password-code' ? {message: 'Check your email.', challengeId} : {message: notice})});
  page.click('.account-forgot'); page.fill({email: 'player@example.com'}); await page.submit();
  page.fill({code: '001234', password: '  new-password-123  ', passwordConfirm: '  new-password-123  '});
  await page.submit();
  assert.deepEqual(page.requests[1], {url: '/api/auth/reset-password-code', payload: {challengeId, code: '001234', password: '  new-password-123  '}});
  assert.equal(page.form.getAttribute('id'), 'account-login-form');
  assert.equal(page.form.notice.textContent, notice);
  assert.equal(page.form.querySelector('[name="email"]').value, 'player@example.com');
  assert.equal(page.form.querySelector('[name="password"]').value, '');
  assert.equal(vm.runInContext('accountRecoveryChallenge', page.context), '');
  assert.equal(page.stored.length, 0);
});

test('invalid code keeps the form usable and resend preserves the recovery email', async () => {
  const page = await accountPage({authenticate: ({url}) => url === '/api/auth/request-password-code' ? response({message: 'Check your email.', challengeId: 'c'.repeat(43)}) : response({error: 'This code is invalid or has expired.'}, 400)});
  page.click('.account-forgot'); page.fill({email: 'player@example.com'}); await page.submit();
  page.fill({code: '123456', password: 'new-password-123', passwordConfirm: 'new-password-123'});
  await page.submit();
  assert.equal(page.form.getAttribute('id'), 'account-code-form');
  assert.match(page.form.error.textContent, /invalid/i);
  assert.equal(page.form.submit.disabled, false);
  page.click('.account-forgot');
  assert.equal(page.form.getAttribute('id'), 'account-forgot-form');
  assert.equal(page.form.querySelector('[name="email"]').value, 'player@example.com');
});

test('an incomplete code request response keeps the request retryable', async () => {
  const page = await accountPage({authenticate: () => response({message: 'Incomplete response'})});
  page.click('.account-forgot'); page.fill({email: 'player@example.com'}); await page.submit();
  assert.equal(page.form.getAttribute('id'), 'account-forgot-form');
  assert.match(page.form.error.textContent, /verification code/i);
  assert.equal(page.form.submit.disabled, false);
});

test('forgot password errors preserve the email and allow retry', async () => {
  const page = await accountPage({authenticate: () => response({error: 'Please wait before requesting another link.'}, 429)});
  page.click('.account-forgot');
  page.fill({email: 'player@example.com'});
  await page.submit();
  assert.equal(page.form.error.textContent, 'Please wait before requesting another link.');
  assert.equal(page.form.querySelector('[name="email"]').value, 'player@example.com');
  assert.equal(page.form.submit.disabled, false);
  assert.ok(page.form.querySelectorAll().every(button => !button.disabled));
  assert.equal(page.stored.length, 0);
});

test('a reset link removes the token from the URL and opens reset even for a signed-in user', async () => {
  const page = await accountPage({hash: '#reset-token=reset%2Bsecret%2Ftoken', userId: 'existing-session'});
  assert.deepEqual(page.historyChanges, ['/ring#ring']);
  assert.equal(page.context.location.hash, '#ring');
  assert.equal(page.form.getAttribute('id'), 'account-reset-form');
  assert.equal(page.form.getAttribute('method'), 'post');
  assert.equal(page.form.getAttribute('action'), '/api/auth/reset-password');
  assert.deepEqual(page.form.fields.map(field => field.name), ['password', 'passwordConfirm']);
  for (const name of ['password', 'passwordConfirm']) {
    const field = page.form.querySelector(`[name="${name}"]`);
    assert.equal(field.getAttribute('type'), 'password');
    assert.equal(field.getAttribute('autocomplete'), 'new-password');
    assert.equal(field.getAttribute('minlength'), '10');
    assert.equal(field.getAttribute('maxlength'), '128');
  }
  page.fill({password: 'new-password-123', passwordConfirm: 'new-password-123'});
  await page.submit();
  assert.equal(page.requests[0].payload.token, 'reset+secret/token');
});

test('reset confirmation must match before making any request', async () => {
  const page = await accountPage({hash: '#reset-token=reset-token'});
  page.fill({password: 'new-password-123', passwordConfirm: 'different-password-123'});
  await page.submit();
  assert.match(page.form.error.textContent, /match/i);
  assert.deepEqual(page.requests, []);
  assert.equal(page.form.submit.disabled, false);
  assert.equal(page.form.getAttribute('aria-busy'), 'false');
  assert.equal(page.form.querySelector('[name="password"]').value, 'new-password-123');
  assert.equal(page.stored.length, 0);
});

test('a successful reset sends only the token and exact new password, then offers login', async () => {
  const notice = 'Your password has been reset. Sign in with your new password.';
  const page = await accountPage({hash: '#reset-token=reset-token', authenticate: () => response({message: notice})});
  page.fill({password: '  new-password-123  ', passwordConfirm: '  new-password-123  '});
  await page.submit();
  assert.deepEqual(page.requests, [{url: '/api/auth/reset-password', payload: {token: 'reset-token', password: '  new-password-123  '}}]);
  assert.equal(page.form.getAttribute('id'), 'account-login-form');
  assert.equal(page.form.notice.textContent, notice);
  assert.equal(page.form.error.textContent, '');
  assert.equal(page.form.querySelector('[name="password"]').value, '');
  assert.equal(page.stored.length, 0, 'Reset does not authenticate or save browser credentials');
  assert.deepEqual(page.navigations, []);
});

test('expired reset links display the server error and let the player request a new link', async () => {
  const page = await accountPage({hash: '#reset-token=expired-token', authenticate: () => response({error: 'This reset link has expired. Request a new one.'}, 400)});
  page.fill({password: 'new-password-123', passwordConfirm: 'new-password-123'});
  await page.submit();
  assert.equal(page.form.getAttribute('id'), 'account-reset-form');
  assert.equal(page.form.error.textContent, 'This reset link has expired. Request a new one.');
  assert.equal(page.form.submit.disabled, false);
  assert.equal(page.stored.length, 0);
  page.click('.account-forgot');
  assert.equal(page.form.getAttribute('id'), 'account-forgot-form');
  assert.equal(page.form.error.textContent, '');
});

test('login after a successful reset saves credentials only after authentication', async () => {
  const page = await accountPage({
    hash: '#reset-token=reset-token',
    authenticate: ({url}) => response(url === '/api/auth/reset-password'
      ? {message: 'Password updated. Sign in now.'}
      : {userId: 'player-123'})
  });
  page.fill({password: 'new-password-123', passwordConfirm: 'new-password-123'});
  await page.submit();
  page.fill({email: 'player@example.com', password: 'new-password-123'});
  await page.submit();
  assert.deepEqual(page.requests.map(request => request.url), ['/api/auth/reset-password', '/api/auth/login']);
  assert.equal(page.stored.length, 1);
  assert.equal(page.stored[0].id, 'player@example.com');
  assert.equal(page.stored[0].password, 'new-password-123');
  assert.deepEqual(page.navigations, ['/ring#ring']);
});

test('authentication transport errors display a useful message and allow correction', async t => {
  const cases = [
    ['network failure', () => Promise.reject(new TypeError('Failed to fetch'))],
    ['non-JSON server failure', () => ({status: 502, ok: false, json: async () => { throw new SyntaxError('Unexpected token <'); }})]
  ];
  for (const [name, authenticate] of cases) {
    await t.test(name, async () => {
      const page = await accountPage({authenticate});
      page.fill({email: 'player@example.com', password: 'correct-password-123'});
      await page.submit();
      assert.match(page.form.error.textContent, /server|connection|connect|try again/i);
      assert.doesNotMatch(page.form.error.textContent, /Unexpected token|Failed to fetch/i);
      assert.equal(page.form.submit.disabled, false);
      assert.equal(page.form.querySelector('[name="email"]').value, 'player@example.com');
      assert.equal(page.form.querySelector('[name="password"]').value, 'correct-password-123');
      assert.equal(page.stored.length, 0);
      assert.deepEqual(page.navigations, []);
    });
  }
});

test('repeated unauthorized responses preserve the current recovery form and draft fields', async () => {
  const page = await accountPage({userId: 'expired-session', authenticate: () => response({error: 'Unauthorized'}, 401)});
  assert.equal(page.form, undefined);
  await page.context.fetch('/api/example');
  assert.equal(page.form.getAttribute('id'), 'account-login-form');
  page.fill({email: 'player@example.com', password: 'draft-password'});
  const loginForm = page.form;
  await page.context.fetch('/api/example');
  assert.equal(page.form, loginForm);
  assert.equal(page.form.querySelector('[name="password"]').value, 'draft-password');
  page.click('.account-forgot');
  page.fill({email: 'corrected@example.com'});
  const forgotForm = page.form;
  await page.context.fetch('/api/example');
  assert.equal(page.form, forgotForm);
  assert.equal(page.form.querySelector('[name="email"]').value, 'corrected@example.com');
});

test('signing in returns players to the requested tournament feature', async () => {
  for (const route of ['progress', 'reminders', 'google-play', 'google-play/connect/' + 'a'.repeat(43)]) {
    const page = await accountPage({hash: '#' + route});
    page.fill({email: 'player@example.com', password: 'correct-password-123'});
    await page.submit();
    assert.deepEqual(page.navigations, ['/ring#' + route]);
  }
});

test('untrusted account destinations fall back to the home feed', async () => {
  const page = await accountPage({hash: '#https://untrusted.example'});
  page.fill({email: 'player@example.com', password: 'correct-password-123'});
  await page.submit();
  assert.deepEqual(page.navigations, ['/ring#ring']);
});

test('the signup link opens the required details form directly', async () => {
  const page = await accountPage({hash: '#signup'});
  assert.equal(page.form.getAttribute('id'), 'account-register-form');
  assert.ok(page.form.fields.find(field => field.name === 'phone'));
});
