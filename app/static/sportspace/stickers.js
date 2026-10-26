// One retryable catalog powers the login preview, messages, and sticker sharing.
(() => {
  const catalogURL = new URL('stickers.json', document.currentScript.src);
  const unavailable = 'Stickers could not load. Please try again.';
  let activeRequest = null;

  function validateCatalog(value) {
    if (!value || !Array.isArray(value.stickers) || !value.stickers.length) throw new Error(unavailable);
    const ids = new Set();
    return value.stickers.map(item => {
      if (!item || ['id', 'name', 'image'].some(key => typeof item[key] !== 'string' || !item[key].trim()) || ids.has(item.id)) {
        throw new Error(unavailable);
      }
      const imageURL = new URL(item.image, catalogURL);
      if (!['http:', 'https:'].includes(imageURL.protocol)) throw new Error(unavailable);
      ids.add(item.id);
      return {...item, image: imageURL.href};
    });
  }

  const catalog = window.RingStickers = {
    items: [], error: '', loading: false,
    image(id) { return catalog.items.find(item => item.id === id); },
    load() {
      if (activeRequest) return activeRequest;
      catalog.loading = true;
      catalog.error = '';
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      activeRequest = Promise.resolve().then(() => fetch(catalogURL.href, {
        cache: 'no-cache', signal: controller.signal
      })).then(response => {
        if (!response.ok) throw new Error(unavailable);
        return response.json();
      }).then(validateCatalog).then(items => {
        catalog.items = items;
        return items;
      }).catch(error => {
        catalog.error = error.name === 'AbortError'
          ? 'Loading stickers timed out. Please try again.' : unavailable;
        return [];
      }).finally(() => {
        clearTimeout(timeout);
        catalog.loading = false;
        activeRequest = null;
      });
      catalog.ready = activeRequest;
      return activeRequest;
    }
  };
  catalog.ready = catalog.load();
})();
