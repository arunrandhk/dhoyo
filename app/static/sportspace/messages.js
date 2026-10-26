// Private sticker conversations belong to the signed-in player account.
(() => {
  const state = {
    dialog: null, trigger: null, selectedId: null, player: null,
    conversations: [], players: [], registeredPlayers: new Map(), threads: new Map(),
    pending: [], unread: 0, search: '', listLoading: false, playersLoading: false,
    threadLoading: false, listError: '', playersError: '', threadError: '',
    listRevision: 0, playersRevision: 0, selectionRevision: 0, refresh: null,
    searchTimer: null, lastRefresh: 0, logSignature: '', stickersError: '', shareStickerId: null
  };
  const regionMarkup = new WeakMap();
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${{
    message: '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a8.5 8.5 0 1 1 19 0Z"/><path d="M7 9h8m-8 5h5"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    back: '<path d="m14 6-6 6 6 6"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>'
  }[name] || ''}</svg>`;
  const sticker = id => window.RingStickers?.image(id);
  const stickerName = id => sticker(id)?.name || 'Sticker';
  const timeLabel = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
  };
  const fullTime = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'});
  };
  const avatar = player => `<span class="messages-avatar" aria-hidden="true">${player.avatar ? `<img src="${escapeHTML(player.avatar)}" alt="" loading="lazy">` : escapeHTML(player.initials || player.name?.slice(0, 2) || 'P')}</span>`;
  const empty = (title, copy) => `<div class="messages-empty"><span class="messages-empty-icon">${icon('message')}</span><strong>${escapeHTML(title)}</strong><p>${escapeHTML(copy)}</p></div>`;
  const errorHTML = (message, action) => message ? `<div class="messages-error" role="alert"><span>${escapeHTML(message)}</span><button type="button" data-messages-retry="${action}">Try again</button></div>` : '';

  function updateRegion(node, markup) {
    if (regionMarkup.get(node) === markup) return;
    const focused = document.activeElement;
    const attributes = ['data-messages-player', 'data-messages-sticker', 'data-messages-retry', 'data-messages-resend', 'data-messages-back', 'data-messages-thread-title', 'data-messages-share-send', 'data-messages-clear-sticker'];
    const focusAttribute = node.contains(focused) && attributes.find(name => focused.hasAttribute(name));
    const focusValue = focusAttribute ? focused.getAttribute(focusAttribute) : null;
    node.innerHTML = markup;
    regionMarkup.set(node, markup);
    if (focusAttribute) {
      const replacement = [...node.querySelectorAll(`[${focusAttribute}]`)].find(element => element.getAttribute(focusAttribute) === focusValue);
      replacement?.focus({preventScroll: true});
    }
  }

  async function request(path, options = {}) {
    if (document.body.classList.contains('account-visible')) throw new Error('Sign in again to use messages.');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    let response;
    try {
      response = await fetch('/api/messages' + path, {
        ...options,
        signal: controller.signal,
        headers: {...options.headers, ...(options.body ? {'Content-Type': 'application/json'} : {})}
      });
    } catch (error) {
      throw new Error(error.name === 'AbortError' ? 'The request timed out. Please try again.' : 'Could not connect. Check your connection and try again.');
    } finally {
      clearTimeout(timeout);
    }
    let value;
    try { value = await response.json(); }
    catch { throw new Error('Messages are unavailable right now. Please try again.'); }
    if (!response.ok) throw new Error(value.error || 'Could not load your messages. Please try again.');
    return value;
  }

  function remember(players) {
    players.forEach(player => state.registeredPlayers.set(player.id, player));
    addProfileAction();
  }

  function updateBadge() {
    if (!state.trigger) return;
    const badge = state.trigger.querySelector('.messages-unread');
    badge.hidden = !state.unread;
    badge.textContent = state.unread > 99 ? '99+' : String(state.unread);
    state.trigger.setAttribute('aria-label', state.unread ? `Messages, ${state.unread} unread sticker${state.unread === 1 ? '' : 's'}` : 'Messages');
  }

  function renderLists() {
    if (!state.dialog) return;
    const chosen = sticker(state.shareStickerId);
    const intent = state.dialog.querySelector('[data-messages-share-intent]');
    intent.hidden = !chosen;
    updateRegion(intent, chosen ? `<img src="${escapeHTML(chosen.image)}" alt="" width="48" height="48"><span><strong>${escapeHTML(chosen.name)}</strong><small>Choose a player to share this sticker.</small></span><button type="button" data-messages-clear-sticker aria-label="Cancel selected sticker">${icon('close')}</button>` : '');
    const conversations = state.dialog.querySelector('[data-messages-conversations]');
    updateRegion(conversations, errorHTML(state.listError, 'conversations') + (state.listLoading && !state.conversations.length ? '<p class="messages-list-note" role="status">Loading conversations…</p>' : '') + state.conversations.map(item => {
      const player = item.player, selected = state.selectedId === player.id;
      const last = item.lastMessage;
      const preview = last ? `${last.senderId === account.userId ? 'You: ' : ''}${stickerName(last.stickerId)}` : 'Start with a sticker';
      return `<button type="button" class="messages-player ${selected ? 'selected' : ''}" data-messages-player="${escapeHTML(player.id)}" aria-label="Open conversation with ${escapeHTML(player.name)}${item.unreadCount ? `, ${item.unreadCount} unread` : ''}" ${selected ? 'aria-current="true"' : ''}>${avatar(player)}<span class="messages-player-copy"><strong>${escapeHTML(player.name)}</strong><small>${escapeHTML(preview)}</small></span><span class="messages-player-meta">${last ? `<time datetime="${escapeHTML(last.createdAt)}" title="${escapeHTML(fullTime(last.createdAt))}">${escapeHTML(timeLabel(last.createdAt))}</time>` : ''}${item.unreadCount ? `<span class="messages-unread">${item.unreadCount > 99 ? '99+' : item.unreadCount}</span>` : ''}</span></button>`;
    }).join('') + (!state.listLoading && !state.listError && !state.conversations.length ? '<p class="messages-list-note">No conversations yet. Find a player below to say hello.</p>' : ''));
    const players = state.dialog.querySelector('[data-messages-players]');
    updateRegion(players, errorHTML(state.playersError, 'players') + (state.playersLoading && !state.players.length ? '<p class="messages-list-note" role="status">Finding players…</p>' : state.players.map(player => `<button type="button" class="messages-player ${state.selectedId === player.id ? 'selected' : ''}" data-messages-player="${escapeHTML(player.id)}" aria-label="Send a sticker to ${escapeHTML(player.name)}">${avatar(player)}<span class="messages-player-copy"><strong>${escapeHTML(player.name)}</strong><small>${escapeHTML(player.sport || 'Player')}</small></span><span class="messages-player-arrow" aria-hidden="true">↗</span></button>`).join('')) + (!state.playersLoading && !state.playersError && !state.players.length ? `<p class="messages-list-note">${state.search ? 'No players match that name. Try a different search.' : 'Other registered players will appear here when they join.'}</p>` : ''));
    updateBadge();
  }

  function renderPicker() {
    const picker = state.dialog.querySelector('[data-messages-picker]');
    if (!state.selectedId) { picker.hidden = true; return; }
    picker.hidden = false;
    const items = window.RingStickers?.items || [];
    const chosen = sticker(state.shareStickerId);
    const stickersError = items.length ? '' : window.RingStickers?.error || state.stickersError;
    updateRegion(picker, `${chosen ? `<div class="messages-share-confirm"><span>Share <strong>${escapeHTML(chosen.name)}</strong> with ${escapeHTML(state.player?.name || 'this player')}?</span><button type="button" data-messages-share-send="${escapeHTML(chosen.id)}">Send sticker</button></div>` : ''}<div class="messages-picker-heading"><strong>Send a little game spirit.</strong><span>Choose a sticker to send</span></div>${stickersError ? errorHTML(stickersError, 'stickers') : items.length ? `<div class="messages-sticker-grid">${items.map(item => `<button type="button" class="messages-sticker-send" data-messages-sticker="${escapeHTML(item.id)}" aria-label="Send ${escapeHTML(item.name)} sticker to ${escapeHTML(state.player?.name || 'this player')}"><img src="${escapeHTML(item.image)}" alt="" width="72" height="72"><span>${escapeHTML(item.name)}</span></button>`).join('')}</div>` : '<p class="messages-list-note" role="status">Loading stickers…</p>'}`);
  }

  function renderThread(scrollToEnd = false) {
    if (!state.dialog) return;
    state.dialog.classList.toggle('messages-has-thread', !!state.selectedId);
    const heading = state.dialog.querySelector('[data-messages-thread-heading]');
    const log = state.dialog.querySelector('[data-messages-log]');
    const error = state.dialog.querySelector('[data-messages-thread-error]');
    updateRegion(error, errorHTML(state.threadError, 'thread'));
    if (!state.selectedId) {
      updateRegion(heading, '');
      log.removeAttribute('role');
      updateRegion(log, empty('Your next conversation starts here.', 'Find a player and send a sticker. A little good game goes a long way.'));
      state.logSignature = '';
      renderPicker();
      return;
    }
    const player = state.player;
    updateRegion(heading, `<button type="button" class="messages-back" data-messages-back aria-label="Back to all conversations">${icon('back')}</button>${player ? avatar(player) : ''}<div><h3 tabindex="-1" data-messages-thread-title>${escapeHTML(player?.name || 'Player')}</h3><p>Private sticker conversation</p></div>`);
    const messages = state.threads.get(state.selectedId) || [];
    const pending = state.pending.filter(item => item.playerId === state.selectedId);
    const signature = JSON.stringify([state.selectedId, messages, pending, state.threadLoading]);
    if (signature !== state.logSignature) {
      const nearEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
      const oldScroll = log.scrollTop;
      log.setAttribute('role', 'log');
      log.setAttribute('aria-label', `Stickers shared with ${player?.name || 'this player'}`);
      updateRegion(log, messages.map(item => messageHTML(item, false)).join('') + pending.map(item => messageHTML(item, true)).join('') + (!messages.length && !pending.length ? state.threadLoading ? '<p class="messages-list-note" role="status">Loading stickers…</p>' : empty('Say hello with a sticker.', `Send ${player?.name || 'this player'} a wave, a good game, or a little encouragement.`) : ''));
      state.logSignature = signature;
      if (scrollToEnd || nearEnd) log.scrollTop = log.scrollHeight;
      else log.scrollTop = oldScroll;
    }
  }

  function messageHTML(item, pending) {
    const mine = pending || item.senderId === account.userId;
    const asset = sticker(item.stickerId);
    const status = pending ? item.status === 'failed' ? 'Not sent' : 'Sending…' : mine ? 'You' : state.player?.name || 'Player';
    return `<article class="messages-bubble ${mine ? 'sent' : 'received'} ${pending ? 'pending' : ''}"><div class="messages-sticker-bubble">${asset ? `<img src="${escapeHTML(asset.image)}" width="112" height="112" alt="${escapeHTML(asset.name)} sticker">` : '<span class="messages-missing-sticker">Sticker</span>'}</div><div class="messages-bubble-meta"><span>${escapeHTML(status)}</span><time datetime="${escapeHTML(item.createdAt)}" title="${escapeHTML(fullTime(item.createdAt))}">${escapeHTML(timeLabel(item.createdAt))}</time></div>${pending && item.status === 'failed' ? `<div class="messages-send-error" role="alert"><span>${escapeHTML(item.error)}</span><button type="button" data-messages-resend="${escapeHTML(item.id)}" aria-label="Retry sending ${escapeHTML(stickerName(item.stickerId))} sticker">Retry</button></div>` : ''}</article>`;
  }

  async function loadConversations() {
    const revision = ++state.listRevision;
    state.listLoading = true;
    renderLists();
    try {
      const value = await request('/conversations');
      if (revision !== state.listRevision) return;
      state.conversations = value.conversations || [];
      state.unread = value.unreadCount || 0;
      state.listError = '';
      remember(state.conversations.map(item => item.player));
    } catch (error) {
      if (revision === state.listRevision) state.listError = error.message;
    } finally {
      if (revision === state.listRevision) { state.listLoading = false; renderLists(); }
    }
  }

  async function loadPlayers() {
    const revision = ++state.playersRevision;
    state.playersLoading = true;
    renderLists();
    try {
      const value = await request('/players?q=' + encodeURIComponent(state.search));
      if (revision !== state.playersRevision) return;
      state.players = value.players || [];
      state.playersError = '';
      remember(state.players);
    } catch (error) {
      if (revision === state.playersRevision) state.playersError = error.message;
    } finally {
      if (revision === state.playersRevision) { state.playersLoading = false; renderLists(); }
    }
  }

  function mergeMessages(playerId, messages) {
    const merged = new Map((state.threads.get(playerId) || []).map(item => [item.id, item]));
    messages.forEach(item => merged.set(item.id, item));
    state.threads.set(playerId, [...merged.values()].sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt)));
  }

  async function loadThread(playerId, initial = false) {
    const revision = state.selectionRevision;
    state.threadLoading = true;
    renderThread(initial);
    try {
      const value = await request('/conversations/' + encodeURIComponent(playerId));
      if (revision !== state.selectionRevision || playerId !== state.selectedId) return;
      mergeMessages(playerId, value.messages || []);
      state.player = value.player;
      state.threadError = '';
      remember([value.player]);
      state.conversations.forEach(item => { if (item.player.id === playerId) item.unreadCount = 0; });
      state.unread = state.conversations.reduce((total, item) => total + (item.unreadCount || 0), 0);
    } catch (error) {
      if (revision === state.selectionRevision) state.threadError = error.message;
    } finally {
      if (revision === state.selectionRevision) {
        state.threadLoading = false;
        renderThread(initial);
        renderPicker();
        renderLists();
      }
    }
  }

  async function selectPlayer(playerId) {
    if (playerId === account.userId) return;
    state.selectedId = playerId;
    state.player = state.registeredPlayers.get(playerId) || null;
    state.selectionRevision++;
    state.threadError = '';
    state.logSignature = '';
    renderThread(true);
    renderPicker();
    renderLists();
    await loadThread(playerId, true);
    if (state.dialog.open && state.selectedId === playerId) state.dialog.querySelector('[data-messages-thread-title]')?.focus({preventScroll: true});
  }

  async function sendSticker(stickerId, retryId) {
    if (!state.selectedId || !sticker(stickerId)) return;
    let item = retryId ? state.pending.find(message => message.id === retryId) : null;
    if (item?.status === 'sending') return;
    if (!item) {
      item = {id: 'pending-' + (window.crypto?.randomUUID?.() || Date.now() + '-' + Math.random()), playerId: state.selectedId, stickerId, createdAt: new Date().toISOString()};
      state.pending.push(item);
    }
    item.status = 'sending';
    item.error = '';
    const confirming = document.activeElement?.hasAttribute('data-messages-share-send');
    state.shareStickerId = null;
    renderPicker();
    renderLists();
    renderThread(true);
    if (confirming) [...state.dialog.querySelectorAll('[data-messages-sticker]')].find(button => button.dataset.messagesSticker === stickerId)?.focus({preventScroll: true});
    try {
      const value = await request('/conversations/' + encodeURIComponent(item.playerId), {method: 'POST', body: JSON.stringify({stickerId: item.stickerId})});
      mergeMessages(item.playerId, [value.message]);
      state.pending = state.pending.filter(message => message !== item);
      renderThread(true);
      await loadConversations();
    } catch (error) {
      item.status = 'failed';
      item.error = error.message;
      renderThread(true);
    }
  }

  async function refreshInbox() {
    if (document.body.classList.contains('account-visible')) return;
    if (state.refresh) return state.refresh;
    state.lastRefresh = Date.now();
    state.refresh = (async () => {
      const playerId = state.dialog.open && !state.threadLoading ? state.selectedId : null;
      // Read the open thread before counting unread messages so the badge stays accurate.
      if (playerId) await loadThread(playerId);
      await loadConversations();
    })();
    try { await state.refresh; } finally { state.refresh = null; }
  }

  function createDialog() {
    const dialog = document.createElement('dialog');
    dialog.id = 'messages-dialog';
    dialog.className = 'messages-dialog';
    dialog.setAttribute('aria-labelledby', 'messages-title');
    dialog.innerHTML = `<header class="messages-heading"><div><span class="messages-kicker">YOUR PEOPLE. YOUR GAME.</span><h2 id="messages-title">A little sticker. A big hello.</h2></div><button type="button" class="messages-close" data-messages-close aria-label="Close messages">${icon('close')}</button></header><div class="messages-layout"><aside class="messages-sidebar" aria-label="Find a conversation"><div class="messages-share-intent" data-messages-share-intent hidden></div><div class="messages-sidebar-title"><h3>Conversations</h3><span>Just between you</span></div><div data-messages-conversations></div><div class="messages-directory"><label for="messages-player-search">Find a player</label><div class="messages-search">${icon('search')}<input id="messages-player-search" type="search" placeholder="Search player names" autocomplete="off" maxlength="100"></div><div data-messages-players></div></div></aside><section class="messages-thread" aria-label="Private conversation"><header class="messages-thread-heading" data-messages-thread-heading></header><div data-messages-thread-error></div><div class="messages-log" data-messages-log aria-live="polite" aria-relevant="additions"></div><section class="messages-picker" data-messages-picker aria-label="Choose a sticker to send" hidden></section></section></div>`;
    document.body.append(dialog);
    state.dialog = dialog;
    dialog.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.hasAttribute('data-messages-close')) dialog.close();
      else if (button.hasAttribute('data-messages-back')) {
        state.selectedId = null;
        state.player = null;
        state.selectionRevision++;
        state.threadLoading = false;
        renderThread();
        renderLists();
        dialog.querySelector('#messages-player-search').focus();
      } else if (button.dataset.messagesPlayer) selectPlayer(button.dataset.messagesPlayer);
      else if (button.dataset.messagesSticker) sendSticker(button.dataset.messagesSticker);
      else if (button.dataset.messagesShareSend) sendSticker(button.dataset.messagesShareSend);
      else if (button.hasAttribute('data-messages-clear-sticker')) {
        state.shareStickerId = null;
        renderLists(); renderPicker();
        state.dialog.querySelector(state.selectedId ? '[data-messages-thread-title]' : '#messages-player-search')?.focus({preventScroll: true});
      }
      else if (button.dataset.messagesResend) {
        const pending = state.pending.find(item => item.id === button.dataset.messagesResend);
        if (pending) sendSticker(pending.stickerId, pending.id);
      } else if (button.dataset.messagesRetry === 'conversations') loadConversations();
      else if (button.dataset.messagesRetry === 'players') loadPlayers();
      else if (button.dataset.messagesRetry === 'thread' && state.selectedId) loadThread(state.selectedId, true);
      else if (button.dataset.messagesRetry === 'stickers') loadStickers();
    });
    dialog.querySelector('#messages-player-search').addEventListener('input', event => {
      state.search = event.target.value.trim();
      state.playersRevision++;
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(loadPlayers, 250);
    });
    // Native dialog handles Escape, focus containment, and restoring its opener.
    dialog.addEventListener('close', () => {
      state.selectionRevision++;
      state.threadLoading = false;
      state.trigger?.setAttribute('aria-expanded', 'false');
    });
    renderLists();
    renderThread();
  }

  async function open(playerId, stickerId) {
    await accountReady;
    if (!state.dialog) createDialog();
    if (sticker(stickerId)) {
      state.shareStickerId = stickerId;
      // Let the user choose a recipient each time they share from the pack.
      state.selectedId = null;
      state.player = null;
      state.selectionRevision++;
      state.threadLoading = false;
      renderLists(); renderThread();
    }
    if (!state.dialog.open) {
      state.dialog.showModal();
      state.trigger?.setAttribute('aria-expanded', 'true');
    }
    if (playerId) await selectPlayer(playerId);
    else if (state.selectedId) await loadThread(state.selectedId, true);
    await Promise.all([loadConversations(), loadPlayers()]);
  }

  async function loadStickers() {
    const items = await window.RingStickers.load();
    state.stickersError = items.length ? '' : window.RingStickers.error || 'Stickers could not load. Please try again.';
    state.logSignature = '';
    renderPicker(); renderThread(); renderLists();
  }

  function addProfileAction() {
    if (typeof arena === 'undefined' || typeof view === 'undefined' || view !== 'player' || !account.userId) return;
    let playerId;
    try { playerId = decodeURIComponent(arena.route.split('/')[1] || ''); } catch { return; }
    const actions = document.querySelector('.hub-profile-actions');
    if (!actions || playerId === account.userId || !state.registeredPlayers.has(playerId) || actions.querySelector('[data-send-player-sticker]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'messages-profile-send';
    button.dataset.sendPlayerSticker = playerId;
    button.innerHTML = icon('message') + '<span>Send sticker</span>';
    button.setAttribute('aria-label', `Send a sticker to ${state.registeredPlayers.get(playerId).name}`);
    button.addEventListener('click', () => open(playerId));
    actions.prepend(button);
  }

  function invalidateMedia(playerIds) {
    const ids = new Set(playerIds.filter(id => id !== account.userId));
    const scrub = player => {
      if (player && ids.has(player.id)) player.avatar = '';
    };
    state.listRevision++;
    state.playersRevision++;
    state.selectionRevision++;
    state.listLoading = state.playersLoading = state.threadLoading = false;
    state.registeredPlayers.forEach(scrub);
    state.players.forEach(scrub);
    state.conversations.forEach(item => scrub(item.player));
    scrub(state.player);
    renderLists();
    renderThread();
    if (document.body.classList.contains('account-visible')) return;
    return Promise.allSettled([
      loadConversations(), loadPlayers(),
      ...(state.dialog?.open && state.selectedId ? [loadThread(state.selectedId)] : [])
    ]);
  }

  window.RingMessages = {open, invalidateMedia};
  if (typeof render === 'function') {
    const previousRender = render;
    render = function () { previousRender(); addProfileAction(); };
  }
  accountReady.then(() => {
    if (!state.dialog) createDialog();
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'messages-trigger';
    button.setAttribute('aria-controls', 'messages-dialog');
    button.setAttribute('aria-haspopup', 'dialog');
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = icon('message') + '<span>Messages</span><span class="messages-unread" hidden></span>';
    button.addEventListener('click', () => open());
    const topbar = document.querySelector('.topbar');
    topbar.insertBefore(button, topbar.querySelector('.account-logout'));
    state.trigger = button;
    loadConversations();
    loadPlayers();
    loadStickers();
    setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      if (Date.now() - state.lastRefresh >= (state.dialog.open ? 8000 : 30000)) refreshInbox();
    }, 8000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') refreshInbox();
    });
  });
})();
