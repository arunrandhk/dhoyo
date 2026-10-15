const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = name => readFileSync(path.join(__dirname, '../static/sportspace', name), 'utf8');
const initialPlayer = {
  id: 'player-owner', name: 'Alex', initials: 'A', city: 'Delhi', state: 'Delhi',
  country: 'India', sport: 'Football', bio: '', avatar: '', photoPrivacy: 'friends',
  gamesPlayed: 0, wins: 0, awards: {}, rank: null,
};
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

function attributes(markup) {
  const result = {};
  for (const match of markup.matchAll(/([\w-]+)(?:="([^"]*)")?/g)) result[match[1]] = match[2] ?? '';
  return result;
}

function element(tag, attrs = {}) {
  return {
    tag, attrs, id: attrs.id, name: attrs.name, value: attrs.value || '',
    disabled: 'disabled' in attrs, hidden: 'hidden' in attrs, events: {}, children: [],
    textContent: '', innerHTML: '',
    setAttribute(key, value) { this.attrs[key] = value; },
    addEventListener(name, handler) { this.events[name] = handler; },
    replaceChildren(...children) { this.children = children; },
    focus() { this.focused = true; }, showModal() { this.open = true; }, close() { this.open = false; },
  };
}

function matches(node, selector) {
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  if (selector.startsWith('.')) return (node.attrs.class || '').split(' ').includes(selector.slice(1));
  if (selector.startsWith('[')) return selector.slice(1, -1) in node.attrs;
  return node.tag === selector;
}

// Run the actual editor against parsed form controls. The small DOM fixture
// covers opening, validation, submission, failures and save confirmation.
function editor({request = async () => ({currentUserId: initialPlayer.id, players: [initialPlayer]}), loaded = true} = {}) {
  const dialogs = [], clicks = [], calls = [], notices = [];
  let feedRefreshes = 0;
  const context = vm.createContext({
    arena: {data: loaded ? {currentUserId: initialPlayer.id} : null, request: 0, error: ''},
    arenaPlayer: id => id === initialPlayer.id ? {...initialPlayer} : undefined,
    sports: ['All sports', 'Football', 'Tennis'], escape,
    render() {}, toast: text => notices.push(text),
    refreshFeed: async () => { feedRefreshes++; },
    arenaAPI: async (apiPath, method, payload) => {
      calls.push({path: apiPath, method, payload: JSON.parse(JSON.stringify(payload))});
      return request(payload);
    },
    FormData: class {
      constructor(form) { this.fields = form.nodes.filter(node => node.name && !node.disabled); }
      *[Symbol.iterator]() { for (const node of this.fields) yield [node.name, node.value]; }
    },
    document: {
      addEventListener(type, handler) { if (type === 'click') clicks.push(handler); },
      getElementById(id) { return [...dialogs, ...dialogs.flatMap(dialog => dialog.nodes)].find(node => node.id === id); },
      body: {append(node) { dialogs.push(node); }},
      createElement(tag) {
        const node = element(tag);
        if (tag !== 'dialog') return node;
        node.nodes = [];
        Object.defineProperty(node, 'innerHTML', {
          get() { return this.markup || ''; },
          set(markup) {
            this.markup = markup;
            this.nodes = [...markup.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/g)].map(match => element(match[1], attributes(match[2])));
            for (const field of this.nodes) {
              if (field.tag === 'select') {
                const contents = markup.match(new RegExp(`<select[^>]*id="${field.id}"[^>]*>([\\s\\S]*?)</select>`))[1];
                const options = [...contents.matchAll(/<option\b([^>]*)>([^<]*)<\/option>/g)].map(match => ({attrs: attributes(match[1]), text: match[2]}));
                const selected = options.find(option => 'selected' in option.attrs) || options[0];
                field.value = selected.attrs.value || selected.text;
              }
              if (field.tag === 'textarea') field.value = markup.match(new RegExp(`<textarea[^>]*id="${field.id}"[^>]*>([\\s\\S]*?)</textarea>`))[1];
            }
            const form = this.nodes.find(node => node.tag === 'form');
            form.nodes = this.nodes;
            form.reportValidity = () => form.nodes.every(field => !('required' in field.attrs) || Boolean(field.value.trim()));
            form.querySelectorAll = selector => this.nodes.filter(node => selector.split(',').some(part => matches(node, part)));
          },
        });
        node.querySelector = selector => node.nodes.find(field => matches(field, selector));
        node.querySelectorAll = selector => node.nodes.filter(field => matches(field, selector));
        return node;
      },
    },
  });
  context.window = context;
  vm.runInContext(source('arena.js').slice(source('arena.js').indexOf('function editPlayerProfile(){')), context);
  const open = () => clicks.forEach(handler => handler({target: {closest: () => ({dataset: {editProfile: ''}})}}));
  return {context, calls, notices, dialogs, open, get feedRefreshes() { return feedRefreshes; }};
}

test('regular player opens a complete form and saves their own account', async () => {
  const page = editor();
  page.open();
  const dialog = page.dialogs[0], form = dialog.querySelector('form'), save = dialog.querySelector('.profile-save');
  assert.equal(dialog.open, true);
  assert.equal(save.disabled, true);
  assert.equal(dialog.querySelector('#profile-name').focused, true);
  for (const key of ['name', 'city', 'country', 'state', 'sport', 'bio', 'photoPrivacy']) {
    assert.ok(form.nodes.find(node => node.name === key), `Missing profile field: ${key}`);
  }
  dialog.querySelector('#profile-name').value = ' Alex Kumar ';
  dialog.querySelector('#profile-city').value = 'Toronto';
  dialog.querySelector('#profile-country').value = 'Canada';
  dialog.querySelector('#profile-state').value = 'Ontario';
  dialog.querySelector('#profile-bio').value = 'Weekend doubles player.';
  form.events.input();
  assert.equal(save.disabled, false);
  await form.events.submit({preventDefault() {}});
  assert.equal(page.calls.length, 1);
  assert.equal(page.calls[0].path, '/players/player-owner');
  assert.equal(page.calls[0].method, 'PATCH');
  assert.equal(page.calls[0].payload.name, 'Alex Kumar');
  assert.equal(page.calls[0].payload.state, 'Ontario');
  assert.equal(dialog.open, false);
  assert.equal(page.feedRefreshes, 1);
  assert.deepEqual(page.notices, ['Your profile changes have been saved.']);
});

test('failed saves keep edits visible and allow a retry without a success message', async () => {
  let attempts = 0;
  const page = editor({request: async () => {
    if (++attempts === 1) throw new Error('Connection unavailable');
    return {currentUserId: initialPlayer.id, players: [initialPlayer]};
  }});
  page.open();
  const dialog = page.dialogs[0], form = dialog.querySelector('form');
  dialog.querySelector('#profile-name').value = 'Alex Updated';
  form.events.input();
  await form.events.submit({preventDefault() {}});
  assert.equal(dialog.open, true);
  assert.equal(dialog.querySelector('.profile-error').textContent, 'Connection unavailable');
  assert.equal(dialog.querySelector('#profile-name').value, 'Alex Updated');
  assert.equal(dialog.querySelector('.profile-save').disabled, false);
  assert.equal(page.notices.length, 0);
  await form.events.submit({preventDefault() {}});
  assert.equal(dialog.open, false);
  assert.equal(page.notices.length, 1);
});

test('editor handles a loading account and requires every location field', () => {
  const pending = editor({loaded: false});
  pending.open();
  assert.equal(pending.dialogs.length, 0);
  assert.match(pending.notices[0], /still loading/);
  const page = editor();
  page.open();
  const dialog = page.dialogs[0], form = dialog.querySelector('form');
  dialog.querySelector('#profile-name').value = 'Alex Updated';
  dialog.querySelector('#profile-state').value = '';
  form.events.input();
  assert.equal(dialog.querySelector('.profile-save').disabled, true);
});

test('own profile exposes tournament tools before connections and hides private actions on other profiles', () => {
  const context = vm.createContext({
    arena: {route: 'player/player-owner', data: {currentUserId: initialPlayer.id, teams: []}},
    playerHub: {profiles: new Map(), errors: new Map()},
    arenaPlayer: () => initialPlayer, escape, arenaAvatar: () => '', rankBadge: () => '',
    hubLocation: () => 'Delhi / India', hubPlayerURL: id => '#player/' + id,
    hubProfileConnections: () => '<section id="profile-connections">Connections</section>',
    icon: () => '', supportButton: () => '', social: {preferences: {following: []}},
  });
  const profile = source('player-hub.js');
  vm.runInContext(profile.slice(profile.indexOf('playerPage=function(){'), profile.indexOf('\n};', profile.indexOf('playerPage=function(){')) + 3), context);
  const markup = context.playerPage();
  assert.ok(markup.indexOf('data-edit-profile') < markup.indexOf('id="profile-connections"'));
  assert.match(markup, /class="hub-tournament-link" href="#progress">Tournament achievements & rankings/);
  assert.match(markup, /class="hub-tournament-link" href="#reminders">Tournament reminders/);
  assert.ok(markup.indexOf('href="#progress"') < markup.indexOf('id="profile-connections"'));
  assert.ok(markup.indexOf('href="#reminders"') < markup.indexOf('id="profile-connections"'));
  context.arena.route = 'player/another-player';
  assert.doesNotMatch(context.playerPage(), /data-edit-profile|hub-tournament-link|href="#progress"|href="#reminders"/);
});

test('Home exposes real tournament tools before the feed without needing profile or progress data', () => {
  const context = vm.createContext({
    icon: () => '', social: {online: true}, state: {posts: []}, matches: () => true,
    ringStories: () => '', ringFeed: () => '', sports: [], filter: 'All sports', arena: {data: null},
  });
  const profile = source('player-hub.js'), ring = source('ring.js');
  vm.runInContext(profile.slice(profile.indexOf('function hubHomeConnections(){'), profile.indexOf('// The connections graph')), context);
  vm.runInContext(ring.slice(ring.indexOf('function ringHome() {'), ring.indexOf('function discoverRing() {')), context);
  const markup = context.ringHome();
  assert.match(markup, /<nav class="hub-player-tools" aria-label="Your tournament tools">/);
  assert.match(markup, /href="#progress"/);
  assert.match(markup, /Achievements & rankings/);
  assert.match(markup, /href="#reminders"/);
  assert.match(markup, /Tournament reminders/);
  assert.ok(markup.indexOf('Your tournament tools') < markup.indexOf('Social feed'));
  assert.doesNotMatch(markup, /games played|wins|badges earned|unread reminders/i);
});
