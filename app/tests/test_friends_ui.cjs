const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = readFileSync(path.join(__dirname, '../static/sportspace/friends.js'), 'utf8');
const html = readFileSync(path.join(__dirname, '../static/sportspace/index.html'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const response = (value, status = 200) => ({status, ok: status < 400, json: async () => value});
const htmlFailure = status => ({status, ok: false, json: async () => { throw new SyntaxError('Unexpected HTML response'); }});
const player = {id: 'peer', name: 'Another Player', sport: 'Football', initials: 'AP', avatar: ''};
const overview = (values = {}) => ({currentUserId: 'owner', friends: [], incoming: [], outgoing: [], ...values});
const directory = (friendship = 'none', requestId = null) => ({currentUserId: 'owner', players: [{...player, friendship, requestId}]});
const pending = {id: 'request-1', player, senderId: 'owner', recipientId: 'peer', status: 'pending'};
const incoming = {...pending, senderId: 'peer', recipientId: 'owner'};

function deferred() {
  let resolve;
  const promise = new Promise(accept => { resolve = accept; });
  return {promise, resolve};
}

// A small DOM fixture runs the whole module and parses its rendered controls.
// These tests exercise API failures and ordering without needing Chromium.
function element(tag = 'div', initial = {}) {
  const attrs = {...initial}, classes = new Set(), events = {};
  const node = {
    tag, attrs, events, dataset: {}, children: [], controls: [], hidden: false, disabled: 'disabled' in attrs,
    classList: {contains: name => classes.has(name), add: name => classes.add(name), remove: name => classes.delete(name)},
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return attrs[name] ?? null; },
    hasAttribute(name) { return name in attrs; },
    removeAttribute(name) { delete attrs[name]; },
    addEventListener(name, handler) { events[name] = handler; },
    append(child) { child.parent = this; this.children.push(child); },
    prepend(child) { child.parent = this; this.children.unshift(child); },
    contains(active) { return active === this || [...this.children, ...this.controls].some(child => child.contains(active)); },
    focus() {}, remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); },
    closest(selector) { return matches(this, selector) ? this : this.parent?.closest(selector) || null; },
    showModal() { this.open = true; },
    close() { this.open = false; events.close?.(); }
  };
  for (const [key, value] of Object.entries(attrs)) if (key.startsWith('data-')) node.dataset[key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = value;
  function matches(item, selector) {
    if (selector.startsWith('.')) return (item.className || item.attrs.class || '').split(/\s+/).includes(selector.slice(1));
    if (selector.startsWith('#')) return (item.id || item.attrs.id) === selector.slice(1);
    const attr = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
    if (attr) return item.hasAttribute(attr[1]) && (attr[2] === undefined || item.getAttribute(attr[1]) === attr[2]);
    return item.tag === selector;
  }
  Object.defineProperty(node, 'innerHTML', {
    get() { return this.markup || ''; },
    set(markup) {
      this.markup = markup;
      this.controls = [...markup.matchAll(/<(button|a)\b([^>]*)>([\s\S]*?)<\/\1>/g)].map(match => {
        const attributes = {};
        for (const attr of match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attributes[attr[1]] = attr[2] || '';
        const button = element(match[1], attributes);
        button.parent = node;
        button.textContent = match[3].replace(/<[^>]+>/g, '');
        return button;
      });
    }
  });
  node.querySelectorAll = selector => {
    const found = [node, ...node.controls, ...node.children.flatMap(child => child.querySelectorAll('*'))];
    return selector === '*' ? found : found.filter(item => matches(item, selector));
  };
  node.querySelector = selector => {
    if (selector === '.friends-tab-count') return node.count ||= element();
    return node.querySelectorAll(selector)[0] || null;
  };
  return node;
}

async function friendsPage({getOverview, getPlayers, post, profile = true, globals = {}} = {}) {
  const calls = [], clicks = [], notifications = [], body = element('body'), topbar = element('header'), profileActions = element(), content = element();
  const dialog = element('dialog'), dialogContent = element(), searchLabel = element('label', {class: 'search'}), search = element('input', {id: 'search'});
  let observer, profileVisible = profile;
  search.value = '';
  searchLabel.append(search);
  topbar.append(searchLabel);
  const queryDialog = dialog.querySelector;
  dialog.querySelector = selector => {
    if (selector === '[data-friends-content]') return dialogContent;
    return queryDialog(selector) || dialogContent.querySelector(selector);
  };
  dialog.append(dialogContent);
  topbar.insertBefore = button => { topbar.append(button); };
  const context = {
    console, AbortController, clearTimeout, setInterval() {},
    // Keep request timeouts intact; advance only the search debounce in tests.
    setTimeout(callback, delay) { return setTimeout(callback, delay === 250 ? 0 : delay); },
    account: {userId: 'owner'}, accountReady: Promise.resolve(),
    location: {hash: profile ? '#player/peer/moments' : '#ring'},
    view: profile ? 'player' : 'ring', arena: {route: 'player/peer/moments', data: {currentUserId: 'owner', players: []}, request: 0},
    playerHub: {profiles: new Map([['peer', {registeredPlayer: true}]]), errors: new Map(), revision: 0},
    render() {}, toast: message => notifications.push(message),
    MutationObserver: class {constructor(callback) { observer = callback; } observe() {}},
    document: {
      body, activeElement: body, visibilityState: 'visible',
      createElement: tag => tag === 'dialog' ? dialog : element(tag),
      addEventListener(name, handler) { if (name === 'click') clicks.push(handler); },
      querySelector(selector) {
        if (selector === '.topbar') return topbar;
        if (selector === '#search') return search;
        if (selector === '.hub-profile-actions') return profileVisible ? profileActions : null;
        if (selector === '#content') return content;
        return null;
      },
      querySelectorAll() { return [profileActions.querySelector('.friends-profile-actions')].filter(Boolean); }
    },
    fetch(url, options) {
      calls.push({url, options, payload: options.body ? JSON.parse(options.body) : null});
      if (options.method === 'POST') return Promise.resolve(post ? post(url, JSON.parse(options.body)) : response(overview({outgoing: [pending]}), 201));
      if (url.includes('/players?')) return Promise.resolve(getPlayers ? getPlayers(url) : response(directory()));
      return Promise.resolve(getOverview ? getOverview() : response(overview()));
    },
    ...globals
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(script, context);
  await tick();
  return {
    context, calls, dialog, dialogContent, profileActions, notifications, content, topbar, search,
    get searchResults() { return searchLabel.querySelector('#player-search-results'); },
    get profile() { return profileActions.querySelector('.friends-profile-actions'); },
    async open(tab = 'requests') { await context.RingFriends.open(tab); await tick(); },
    button(action, region = this.profile) { return region?.querySelector(`[data-friend-action="${action}"]`) || null; },
    async dispatch(control) {
      let prevented = false;
      assert.ok(control, 'Missing UI control');
      clicks.forEach(handler => handler({target: control, preventDefault() { prevented = true; }}));
      if (control.tag === 'a' && !prevented) context.location.hash = control.getAttribute('href');
      await tick();
    },
    async click(action, region = this.profile) {
      const button = this.button(action, region);
      assert.ok(button, `Missing ${action} control in ${region.innerHTML}`);
      assert.equal(button.disabled, false);
      await this.dispatch(button);
    },
    async searchFor(query = 'Another') {
      search.value = query;
      search.events.input();
      await new Promise(resolve => setTimeout(resolve, 5));
      await tick();
    },
    async key(key) {
      let prevented = false;
      search.events.keydown({key, preventDefault() { prevented = true; }});
      await tick();
      return prevented;
    },
    visitSelectedPlayer() {
      profileVisible = true;
      context.view = 'player';
      context.arena.route = context.location.hash.slice(1);
      context.render();
    },
    async retry(source) {
      const region = source === 'players' ? this.searchResults : dialogContent;
      const button = region.querySelector(`[data-friends-retry="${source}"]`);
      assert.ok(button, `Missing ${source} retry control in ${region.innerHTML}`);
      await this.dispatch(button);
    },
    expire() { context.account.userId = null; body.classList.add('account-visible'); observer(); }
  };
}

const outage = () => response({error: 'Friends overview temporarily unavailable'}, 503);

test('public views have no global Friends button or friends banner', async () => {
  assert.doesNotMatch(html, /data-friends-open/);
  const page = await friendsPage({profile: false});
  assert.equal(page.topbar.querySelector('.friends-trigger'), null);
  assert.equal(page.content.querySelector('.friends-summary'), null);
  assert.deepEqual(page.calls.map(call => call.url), ['/api/friends']);
  for (const view of ['connections', 'player']) {
    page.context.view = view;
    page.context.arena.route = 'player/owner/moments';
    page.context.render();
    assert.equal(page.content.querySelector('.friends-summary'), null);
  }
  await page.open();
  assert.equal(page.dialog.querySelector('[data-friends-tab="people"]'), null);
});

test('your profile shows incoming requests and opens request management', async () => {
  const page = await friendsPage({getOverview: () => response(overview({incoming: [incoming]}))});
  page.context.arena.route = 'player/owner/moments';
  page.context.render();
  const manage = page.profile.querySelector('[data-friends-open="requests"]');
  assert.ok(manage);
  assert.equal(manage.textContent, 'Manage friends · 1 request');
  assert.equal(manage.getAttribute('aria-expanded'), 'false');
  await page.dispatch(manage);
  assert.equal(page.dialog.open, true);
  assert.equal(page.profile.querySelector('[data-friends-open="requests"]').getAttribute('aria-expanded'), 'true');
  assert.ok(page.button('accept', page.dialogContent));
  assert.equal(page.button('send', page.dialogContent), null);
  page.dialog.close();
  assert.equal(page.profile.querySelector('[data-friends-open="requests"]').getAttribute('aria-expanded'), 'false');
});

test('search results open public profiles where a friend request can be sent', async () => {
  const page = await friendsPage({profile: false});
  await page.searchFor();
  assert.equal(page.searchResults.hidden, false);
  assert.equal(page.search.getAttribute('aria-expanded'), 'true');
  assert.equal(page.calls.at(-1).url, '/api/friends/players?q=Another');
  const result = page.searchResults.querySelector('[data-player-search-id="peer"]');
  assert.ok(result);
  assert.equal(page.button('send', page.searchResults), null);
  await page.dispatch(result);
  assert.equal(page.context.location.hash, '#player/peer/moments');
  assert.equal(page.searchResults.hidden, true);
  page.visitSelectedPlayer();
  assert.equal(page.button('send').textContent, 'Add friend');
  await page.click('send');
  assert.deepEqual(page.calls.find(call => call.options.method === 'POST').payload, {playerId: 'peer'});
  assert.ok(page.button('cancel'));
  assert.deepEqual(page.notifications, ['Friend request sent.']);
});

test('keyboard search selects a player and Escape closes results', async () => {
  const second = {...player, id: 'peer/second', name: 'Second Player'};
  const page = await friendsPage({profile: false, getPlayers: () => response({currentUserId: 'owner', players: [player, second]})});
  await page.searchFor('Player');
  assert.equal(await page.key('ArrowUp'), true);
  assert.equal(page.search.getAttribute('aria-activedescendant'), 'player-search-option-1');
  assert.equal(await page.key('Enter'), true);
  assert.equal(page.context.location.hash, '#player/peer%2Fsecond/moments');
  assert.equal(page.searchResults.hidden, true);
  page.visitSelectedPlayer();
  assert.equal(page.button('send').getAttribute('data-friend-player'), 'peer/second');
  page.search.events.focus();
  assert.equal(page.searchResults.hidden, false);
  assert.equal(await page.key('Escape'), true);
  assert.equal(page.search.getAttribute('aria-expanded'), 'false');
  assert.equal(page.search.getAttribute('aria-activedescendant'), null);
});

test('sample profiles cannot receive requests and your own profile manages friends', async () => {
  const page = await friendsPage({globals: {playerHub: {profiles: new Map(), errors: new Map(), revision: 0}}});
  assert.equal(page.profile, null);
  page.context.arena.route = 'player/owner/moments';
  page.context.render();
  assert.equal(page.button('send'), null);
  const manage = page.profile.querySelector('[data-friends-open="friends"]');
  assert.equal(manage.textContent, 'Manage friends');
  await page.dispatch(manage);
  assert.match(page.dialogContent.innerHTML, /Your friends/);
});

test('profile Add friend stays enabled when the overview fails and blocks double sends', async () => {
  const mutation = deferred();
  const page = await friendsPage({getOverview: outage, post: () => mutation.promise});
  await page.open();
  assert.match(page.dialogContent.innerHTML, /role="alert"/);
  assert.match(page.dialogContent.innerHTML, /data-friends-retry="overview"/);
  const profile = page.profileActions.querySelector('.friends-profile-actions');
  assert.equal(page.button('send', profile).disabled, false);
  await page.click('send', profile);
  assert.equal(page.button('send').disabled, true, 'Block double clicks while sending');
  await page.dispatch(page.button('send'));
  const calls = page.calls.filter(call => call.options.method === 'POST');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/friends/requests');
  assert.deepEqual(calls[0].payload, {playerId: 'peer'});
  assert.equal(calls[0].options.headers['X-Dhoyo-Request'], '1');
  mutation.resolve(response(overview({outgoing: [pending]}), 201));
  await tick();
  assert.ok(page.button('cancel'));
  assert.ok(page.button('cancel', profile));
  assert.deepEqual(page.notifications, ['Friend request sent.']);
});

test('overview and player-search HTML failures have independent alerts and retries', async () => {
  let restored = false;
  const page = await friendsPage({profile: false,
    getOverview: () => restored ? response(overview()) : htmlFailure(500),
    getPlayers: () => restored ? response(directory()) : htmlFailure(500)
  });
  await page.searchFor();
  await page.open();
  for (const region of [page.dialogContent, page.searchResults]) {
    assert.equal((region.innerHTML.match(/role="alert"/g) || []).length, 1);
    assert.match(region.innerHTML, /The friends service encountered an error \(HTTP 500\)/);
    assert.equal(region.querySelector('[data-friends-retry="all"]'), null);
  }
  assert.equal(page.searchResults.querySelector('[data-player-search-id]'), null);
  const beforeOverview = page.calls.filter(call => call.url === '/api/friends').length;
  const beforePlayers = page.calls.filter(call => call.url.startsWith('/api/friends/players?')).length;
  restored = true;
  await page.retry('overview');
  assert.equal(page.calls.filter(call => call.url === '/api/friends').length, beforeOverview + 1);
  assert.equal(page.calls.filter(call => call.url.startsWith('/api/friends/players?')).length, beforePlayers);
  page.dialog.close();
  page.search.events.focus();
  await page.retry('players');
  assert.equal(page.calls.filter(call => call.url === '/api/friends').length, beforeOverview + 1);
  assert.equal(page.calls.filter(call => call.url.startsWith('/api/friends/players?')).length, beforePlayers + 1);
  assert.doesNotMatch(page.dialogContent.innerHTML, /role="alert"/);
  assert.doesNotMatch(page.searchResults.innerHTML, /role="alert"/);
  assert.ok(page.searchResults.querySelector('[data-player-search-id="peer"]'));
});

test('different overview and search errors stay on their corresponding surfaces', async () => {
  const page = await friendsPage({profile: false, getOverview: outage,
    getPlayers: () => response({error: 'Player search is temporarily unavailable'}, 503)
  });
  await page.searchFor();
  assert.match(page.dialogContent.innerHTML, /Friends overview temporarily unavailable/);
  assert.doesNotMatch(page.dialogContent.innerHTML, /Player search is temporarily unavailable/);
  assert.match(page.searchResults.innerHTML, /Player search is temporarily unavailable/);
  assert.doesNotMatch(page.searchResults.innerHTML, /Friends overview temporarily unavailable/);
  assert.ok(page.dialogContent.querySelector('[data-friends-retry="overview"]'));
  assert.ok(page.searchResults.querySelector('[data-friends-retry="players"]'));
  assert.equal(page.dialogContent.querySelector('[data-friends-retry="all"]'), null);
  const beforeOverview = page.calls.filter(call => call.url === '/api/friends').length;
  const beforePlayers = page.calls.filter(call => call.url.startsWith('/api/friends/players?')).length;
  await page.retry('players');
  assert.equal(page.calls.filter(call => call.url === '/api/friends').length, beforeOverview);
  assert.equal(page.calls.filter(call => call.url.startsWith('/api/friends/players?')).length, beforePlayers + 1);
});

test('non-JSON HTTP failures identify their status without exposing the response body', async t => {
  for (const status of [404, 502, 503, 504, 429]) {
    await t.test(String(status), async () => {
      const page = await friendsPage({getOverview: () => htmlFailure(status)});
      await page.open();
      assert.match(page.dialogContent.innerHTML, new RegExp(`HTTP ${status}`));
      assert.doesNotMatch(page.dialogContent.innerHTML, /Unexpected HTML response/);
      assert.equal(page.button('send').disabled, false, 'An overview failure must not disable available players');
    });
  }
});

test('search relationship state exposes Accept on a profile during an overview outage', async () => {
  let accepted = false;
  const page = await friendsPage({getOverview: outage, getPlayers: () => response(directory(accepted ? 'friends' : 'incoming', 'request-1')), post: (url, payload) => {
    assert.equal(url, '/api/friends/requests/request-1');
    assert.deepEqual(payload, {action: 'accept'});
    accepted = true;
    return response(overview({friends: [{...player, requestId: 'request-1'}]}));
  }});
  await page.searchFor();
  assert.equal(page.button('send'), null);
  assert.equal(page.button('accept').disabled, false);
  await page.click('accept');
  assert.match(page.profile.innerHTML, /Friends/);
  assert.equal(page.button('accept'), null);
  assert.ok(page.button('remove'));
});

test('an older overview cannot overwrite a newer search relationship', async () => {
  const older = deferred();
  const page = await friendsPage({getOverview: () => older.promise, getPlayers: () => response(directory('incoming', 'request-1'))});
  await page.searchFor();
  assert.ok(page.button('accept'));
  older.resolve(response(overview()));
  await tick();
  assert.ok(page.button('accept'));
  assert.equal(page.button('send'), null);
});

test('a delayed search response cannot undo a completed send', async () => {
  const older = deferred();
  const page = await friendsPage({getPlayers: () => older.promise});
  await page.searchFor();
  const profile = page.profileActions.querySelector('.friends-profile-actions');
  await page.click('send', profile);
  assert.ok(page.button('cancel', profile));
  older.resolve(response(directory('none')));
  await tick();
  assert.ok(page.button('cancel', profile));
  assert.equal(page.button('send', profile), null);
});

test('search ignores a delayed response for an earlier query', async () => {
  const older = deferred();
  const page = await friendsPage({profile: false, getPlayers: url => url.endsWith('Earlier') ? older.promise : response(directory())});
  await page.searchFor('Earlier');
  await page.searchFor('Another');
  older.resolve(response({currentUserId: 'owner', players: [{...player, id: 'old', name: 'Earlier Result'}]}));
  await tick();
  assert.ok(page.searchResults.querySelector('[data-player-search-id="peer"]'));
  assert.equal(page.searchResults.querySelector('[data-player-search-id="old"]'), null);
});

test('a changed request refreshes its relationship after a conflict', async () => {
  let changed = false;
  const incoming = {...pending, senderId: 'peer', recipientId: 'owner'};
  const page = await friendsPage({
    getOverview: () => response(overview(changed ? {incoming: [incoming]} : {})),
    getPlayers: () => response(directory(changed ? 'incoming' : 'none', changed ? 'request-1' : null)),
    post: () => { changed = true; return response({error: 'A friend request is already pending'}, 409); }
  });
  await page.searchFor();
  await page.click('send');
  await tick();
  assert.ok(page.button('accept'));
  assert.ok(page.button('accept', page.dialogContent));
  assert.equal(page.button('send'), null);
  assert.equal(page.notifications.length, 0, 'Do not announce failed sends as successful');
});

test('session expiry rejects delayed sends and removes private relationship controls', async () => {
  const mutation = deferred();
  const page = await friendsPage({post: () => mutation.promise});
  await page.searchFor();
  await page.open();
  await page.click('send');
  page.expire();
  mutation.resolve(response(overview({outgoing: [pending]}), 201));
  await tick();
  assert.equal(page.dialog.open, false);
  assert.equal(page.profile, null);
  assert.equal(page.searchResults.hidden, true);
  assert.equal(page.search.value, '');
  assert.equal(page.button('cancel', page.dialogContent), null);
  assert.equal(page.notifications.length, 0);
});

test('media invalidation immediately purges peers while preserving owner access', async () => {
  const secret = 'data:image/png;base64,PRIVATE';
  const own = {id: 'owner', avatar: secret, cover: secret, image: secret, canViewPhotos: true};
  const peer = {...player, avatar: secret, cover: secret, image: secret, canViewPhotos: true};
  const feed = {posts: [{authorId: 'peer', image: secret, avatar: secret}, {authorId: 'owner', image: secret}]};
  const arena = {route: 'player/peer/moments', request: 0, data: {currentUserId: 'owner', players: [own, peer]}};
  const social = {request: 0, stories: [{authorId: 'peer', image: secret}, {authorId: 'owner', image: secret}]};
  const page = await friendsPage({globals: {state: feed, arena, social}});
  const oldRevision = page.context.playerHub.revision;
  const refreshed = page.context.RingFriends.invalidateMedia(['peer', 'owner']);
  assert.equal(peer.avatar, '');
  assert.equal(peer.cover, '');
  assert.equal(peer.image, '');
  assert.equal(peer.canViewPhotos, false);
  assert.equal(feed.posts[0].image, '');
  assert.equal(feed.posts[0].avatar, '');
  assert.deepEqual(social.stories.map(story => story.authorId), ['owner']);
  assert.equal(own.avatar, secret);
  assert.equal(own.canViewPhotos, true);
  assert.equal(feed.posts[1].image, secret);
  assert.ok(page.context.playerHub.revision > oldRevision);
  assert.equal(page.context.playerHub.profiles.size, 0);
  assert.equal(arena.request, 1);
  assert.equal(social.request, 1);
  await refreshed;
});
