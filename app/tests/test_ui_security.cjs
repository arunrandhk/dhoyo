const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function page(scripts) {
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      innerHTML: '', textContent: '', value: '',
      classList: {add() {}, remove() {}, toggle() {}},
      setAttribute() {}, addEventListener() {}
    });
    return nodes.get(selector);
  };
  const context = vm.createContext({
    structuredClone, Date, setTimeout, clearTimeout,
    location: {hash: '#feed', protocol: 'file:'},
    localStorage: {getItem() { return null; }, setItem() {}},
    document: {querySelector: node, querySelectorAll() { return []; }, addEventListener() {}},
    addEventListener() {}
  });
  context.window = context;
  for (const name of scripts) {
    vm.runInContext(readFileSync(path.join(__dirname, '../static/sportspace', name), 'utf8'), context, {filename: name});
  }
  return context;
}

test('suggested players render malicious profile names and initials as text', () => {
  const context = page(['app.js', 'social.js']);
  context.attacker = {
    id: 'player-test',
    name: '"><img src=x onerror="alert(1)">',
    initials: '<svg onload="alert(2)">',
    sport: '<img src=x onerror="alert(3)">'
  };
  vm.runInContext('state.posts=[attacker]; state.following=[];', context);
  const markup = vm.runInContext('railHTML()', context);
  assert.ok(markup.includes('&lt;svg onload=&quot;alert(2)&quot;&gt;'));
  assert.ok(markup.includes('&lt;img src=x onerror=&quot;alert(3)&quot;&gt;'));
  assert.ok(markup.includes('data-follow="&quot;&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"'));
  assert.doesNotMatch(markup, /<(?:img|svg)\b[^>]*\bon(?:error|load)\s*=/i);
});

test('cached demo post IDs cannot inject markup through action attributes', () => {
  const context = page(['app.js']);
  context.attacker = {
    id: '"><img src=x onerror="alert(1)">',
    name: 'Test Player', initials: 'TP', sport: 'Football', time: 'Just now',
    text: '<script>alert(2)</script>', likes: 0, comments: []
  };
  const markup = vm.runInContext('postHTML(attacker)', context);
  assert.ok(markup.includes('data-like="&quot;&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"'));
  assert.ok(markup.includes('&lt;script&gt;alert(2)&lt;/script&gt;'));
  assert.doesNotMatch(markup, /<(?:img|script)\b/i);
});
