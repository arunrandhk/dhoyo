// Browse the pack without starting a conversation, then choose how to share it.
(() => {
  const state = {dialog: null, trigger: null, selectedId: null, file: null, revision: 0, busy: false, loading: false, preparing: false};
  const files = new Map();
  const selected = () => window.RingStickers.image(state.selectedId);
  const assetURL = item => new URL(item.image, location.href).href;
  const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${{
    sticker: '<path d="M20 13V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h8Z"/><path d="M13 20v-5a2 2 0 0 1 2-2h5M7 8h.01M13 8h.01M7 12c2 2 4 2 6 0"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>'
  }[name]}</svg>`;

  function status(message) {
    state.dialog.querySelector('[data-sticker-status]').textContent = message;
  }

  function updateActions() {
    const item = selected();
    state.dialog.querySelectorAll('[data-sticker-action]').forEach(button => {
      button.disabled = !item || state.busy || state.loading;
    });
    // Prepare the file before the click so native sharing retains user activation.
    state.dialog.querySelector('[data-sticker-share]').disabled = !item || state.busy || state.loading || state.preparing;
    state.dialog.querySelector('[data-sticker-download]').disabled = !item || state.busy || state.loading || state.preparing;
    state.dialog.querySelectorAll('[data-sticker-select]').forEach(button => { button.disabled = state.busy || state.loading; });
  }

  function prepareFile(item) {
    const key = `${item.id}:${item.image}`;
    if (files.has(key)) return files.get(key);
    const promise = new Promise((resolve, reject) => {
      const image = new Image();
      const timeout = setTimeout(() => {
        image.onload = image.onerror = null;
        reject(new Error('Loading this sticker image timed out.'));
      }, 10000);
      image.onload = () => {
        clearTimeout(timeout);
        try {
          const canvas = document.createElement('canvas');
          canvas.width = canvas.height = 512;
          const context = canvas.getContext('2d');
          if (!context) throw new Error('Image conversion unavailable.');
          context.drawImage(image, 0, 0, 512, 512);
          canvas.toBlob(blob => blob ? resolve(new File([blob], `dhoyo-${item.id}.png`, {type: 'image/png'})) : reject(new Error('Image conversion unavailable.')), 'image/png');
        } catch (error) { reject(error); }
      };
      image.onerror = () => { clearTimeout(timeout); reject(new Error('Could not load this sticker image.')); };
      image.src = assetURL(item);
    });
    files.set(key, promise);
    promise.catch(() => files.delete(key));
    return promise;
  }

  async function select(id) {
    const item = window.RingStickers.image(id);
    if (!item || state.busy || state.loading) return;
    state.selectedId = id;
    state.file = null;
    state.preparing = true;
    const revision = ++state.revision;
    state.dialog.querySelectorAll('[data-sticker-select]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.stickerSelect === id)));
    const preview = state.dialog.querySelector('[data-sticker-preview]');
    preview.src = item.image;
    preview.alt = `${item.name} sticker`;
    state.dialog.querySelector('[data-sticker-name]').textContent = item.name;
    state.dialog.querySelector('[data-sticker-link]').value = assetURL(item);
    state.dialog.querySelector('[data-sticker-fallback]').hidden = true;
    status('');
    updateActions();
    try {
      const file = await prepareFile(item);
      if (revision === state.revision) state.file = file;
    } catch {
      if (revision === state.revision) status('The image could not load. Try another sticker, or share its link.');
    } finally {
      if (revision === state.revision) { state.preparing = false; updateActions(); }
    }
  }

  async function loadPack() {
    const grid = state.dialog.querySelector('[data-sticker-grid]');
    const retry = state.dialog.querySelector('[data-sticker-retry]');
    retry.hidden = true;
    state.loading = true;
    updateActions();
    status('Loading stickers…');
    const loaded = window.RingStickers.items.length ? window.RingStickers.items : await window.RingStickers.load();
    const items = loaded.length ? loaded : window.RingStickers.items;
    state.loading = false;
    grid.replaceChildren();
    if (!items.length) {
      state.selectedId = null;
      state.file = null;
      state.revision++;
      state.dialog.querySelector('[data-sticker-detail]').hidden = true;
      status(window.RingStickers.error || 'Stickers could not load. Please try again.');
      retry.hidden = false;
      updateActions();
      return;
    }
    for (const item of items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'sticker-choice';
      button.dataset.stickerSelect = item.id;
      button.setAttribute('aria-label', `Choose ${item.name} sticker`);
      button.setAttribute('aria-pressed', 'false');
      const image = document.createElement('img');
      image.src = item.image; image.alt = ''; image.width = image.height = 96;
      const label = document.createElement('span'); label.textContent = item.name;
      button.append(image, label);
      grid.append(button);
    }
    state.dialog.querySelector('[data-sticker-detail]').hidden = false;
    await select(window.RingStickers.image(state.selectedId)?.id || items[0].id);
  }

  function showFallback(message) {
    state.dialog.querySelector('[data-sticker-fallback]').hidden = false;
    status(message);
  }

  async function share() {
    const item = selected();
    if (!item || state.busy) return;
    if (!navigator.share) {
      showFallback('Copy the sticker link or download the image to share it in another app.');
      return;
    }
    state.busy = true;
    updateActions();
    try {
      const payload = state.file && navigator.canShare?.({files: [state.file]})
        ? {title: item.name, files: [state.file]}
        : {title: item.name, text: `${item.name} — dhoyo`, url: assetURL(item)};
      await navigator.share(payload);
      status('Sticker shared.');
    } catch (error) {
      if (error.name !== 'AbortError') showFallback('Sharing could not open. Copy the link or download the sticker below.');
      else status('');
    } finally {
      state.busy = false;
      updateActions();
      if (state.dialog.open) state.dialog.querySelector('[data-sticker-share]').focus({preventScroll: true});
    }
  }

  async function copy() {
    const item = selected();
    if (!item || state.busy) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable.');
      await navigator.clipboard.writeText(assetURL(item));
      status('Sticker link copied.');
    } catch {
      showFallback('Select and copy the sticker link below.');
      const input = state.dialog.querySelector('[data-sticker-link]');
      input.focus(); input.select();
    }
  }

  function download() {
    const item = selected();
    if (!item || state.busy) return;
    const url = state.file ? URL.createObjectURL(state.file) : assetURL(item);
    const link = document.createElement('a');
    link.href = url; link.download = `dhoyo-${item.id}.${state.file ? 'png' : 'svg'}`;
    document.body.append(link); link.click(); link.remove();
    if (state.file) setTimeout(() => URL.revokeObjectURL(url), 60000);
    status('Sticker download started.');
  }

  function createDialog() {
    const dialog = document.createElement('dialog');
    dialog.id = 'stickers-dialog'; dialog.className = 'stickers-dialog';
    dialog.setAttribute('aria-labelledby', 'stickers-title');
    dialog.innerHTML = `<header class="stickers-heading"><div><span>BIG PLAYS. BIGGER REACTIONS.</span><h2 id="stickers-title">Share a little game spirit.</h2></div><button type="button" data-sticker-close aria-label="Close stickers">${icon('close')}</button></header><div class="stickers-body"><p class="stickers-intro">Choose a sticker. Send it to a player or share it with your people.</p><p class="stickers-status" data-sticker-status role="status" aria-live="polite"></p><button type="button" class="stickers-retry" data-sticker-retry hidden>Try again</button><div class="stickers-grid" data-sticker-grid role="group" aria-label="Sticker pack"></div><section class="sticker-detail" data-sticker-detail hidden><img data-sticker-preview width="144" height="144" alt=""><div class="sticker-detail-copy"><h3 data-sticker-name></h3><div class="sticker-actions"><button type="button" class="primary" data-sticker-action data-sticker-share>Share sticker</button><button type="button" data-sticker-action data-sticker-send>Send to player</button></div><div class="sticker-secondary-actions"><button type="button" data-sticker-action data-sticker-copy>Copy link</button><button type="button" data-sticker-action data-sticker-download>Download</button></div><label class="sticker-fallback" data-sticker-fallback hidden>Sticker link<input data-sticker-link readonly aria-label="Sticker link"></label></div></section></div>`;
    document.body.append(dialog); state.dialog = dialog;
    dialog.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
      if (button.hasAttribute('data-sticker-close')) dialog.close();
      else if (button.dataset.stickerSelect) select(button.dataset.stickerSelect);
      else if (button.hasAttribute('data-sticker-retry')) loadPack();
      else if (button.hasAttribute('data-sticker-share')) share();
      else if (button.hasAttribute('data-sticker-copy')) copy();
      else if (button.hasAttribute('data-sticker-download')) download();
      else if (button.hasAttribute('data-sticker-send')) {
        dialog.close(); window.RingMessages.open(undefined, state.selectedId);
      }
    });
    dialog.addEventListener('close', () => {
      state.trigger.setAttribute('aria-expanded', 'false');
      state.trigger.focus({preventScroll: true});
    });
  }

  async function open(id) {
    await accountReady;
    if (!state.dialog) createDialog();
    if (!state.dialog.open) state.dialog.showModal();
    state.trigger.setAttribute('aria-expanded', 'true');
    if (state.busy) return;
    if (id) state.selectedId = id;
    await loadPack();
  }

  window.RingStickerPack = {open};
  accountReady.then(() => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'stickers-trigger';
    button.setAttribute('aria-label', 'Share stickers');
    button.setAttribute('aria-controls', 'stickers-dialog');
    button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-expanded', 'false');
    button.innerHTML = icon('sticker') + '<span>Stickers</span>';
    button.addEventListener('click', () => open());
    const topbar = document.querySelector('.topbar');
    topbar.insertBefore(button, topbar.querySelector('.messages-trigger') || topbar.querySelector('.account-logout'));
    state.trigger = button;
  });
})();
