const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = readFileSync(path.join(__dirname, '../static/sportspace/stickers.js'), 'utf8');
const scriptURL = 'https://dhoyo.example/static/sportspace/stickers.js';
const goodCatalog = {stickers: [{id: 'gg', name: 'Good game!', image: 'assets/stickers/gg.svg'}]};
const response = value => ({ok: true, json: async () => value});

function loadScript(fetch) {
  const context = {
    document: {currentScript: {src: scriptURL}},
    URL, AbortController, setTimeout, clearTimeout, fetch
  };
  context.window = context;
  vm.runInNewContext(script, context, {filename: 'stickers.js'});
  return context.RingStickers;
}

test('loads the catalog and resolves image paths beside the catalog', async () => {
  let requestedURL;
  const catalog = loadScript(async url => { requestedURL = url; return response(goodCatalog); });
  assert.equal(catalog.loading, true);
  const items = await catalog.ready;
  assert.equal(requestedURL, 'https://dhoyo.example/static/sportspace/stickers.json');
  assert.equal(items.length, 1);
  assert.equal(items[0].image, 'https://dhoyo.example/static/sportspace/assets/stickers/gg.svg');
  assert.equal(catalog.image('gg'), items[0]);
  assert.equal(catalog.image('missing'), undefined);
  assert.equal(catalog.loading, false);
  assert.equal(catalog.error, '');
});

test('a failed initial load resolves an empty list and can be retried', async () => {
  let calls = 0;
  const catalog = loadScript(async () => {
    calls++;
    if (calls === 1) throw new TypeError('Failed to fetch');
    return response(goodCatalog);
  });
  assert.equal((await catalog.ready).length, 0);
  assert.equal(catalog.items.length, 0);
  assert.match(catalog.error, /try again/i);
  assert.equal(catalog.loading, false);
  const retry = catalog.load();
  assert.equal(catalog.ready, retry);
  assert.equal(catalog.loading, true);
  assert.equal((await retry)[0].id, 'gg');
  assert.equal(calls, 2);
  assert.equal(catalog.error, '');
});

test('concurrent callers reuse the same pending request', async () => {
  let finish, calls = 0;
  const pending = new Promise(resolve => { finish = resolve; });
  const catalog = loadScript(() => { calls++; return pending; });
  const initial = catalog.ready;
  assert.equal(catalog.load(), initial);
  assert.equal(catalog.load(), initial);
  await Promise.resolve();
  assert.equal(calls, 1);
  finish(response(goodCatalog));
  await initial;
  assert.equal(catalog.loading, false);
});

test('rejects malformed collections without publishing partial sticker data', async () => {
  const invalidCollections = [
    null,
    {},
    {stickers: []},
    {stickers: [{id: 'gg', image: 'gg.svg'}]},
    {stickers: [goodCatalog.stickers[0], goodCatalog.stickers[0]]},
    {stickers: [{id: 'gg', name: 'Good game!', image: 'javascript:alert(1)'}]}
  ];
  for (const value of invalidCollections) {
    const catalog = loadScript(async () => response(value));
    assert.equal((await catalog.ready).length, 0);
    assert.equal(catalog.items.length, 0);
    assert.match(catalog.error, /try again/i);
    assert.equal(catalog.loading, false);
  }
});

test('preserves a working catalog if refreshing fails', async () => {
  let calls = 0;
  const catalog = loadScript(async () => ++calls === 1 ? response(goodCatalog) : {ok: false});
  const original = await catalog.ready;
  assert.equal((await catalog.load()).length, 0);
  assert.equal(catalog.items, original);
  assert.equal(catalog.image('gg'), original[0]);
  assert.match(catalog.error, /try again/i);
});
