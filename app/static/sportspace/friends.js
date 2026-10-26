// Friend requests use the signed-in account and persist independently of follows.
(feedState => {
  const state = {
    dialog: null, tab: 'requests', overview: null,
    players: [], knownPlayers: new Map(), relations: new Map(), relationRevision: 0, query: '', loading: false,
    playersLoading: false, error: '', playersError: '', busy: false,
    overviewRevision: 0, playersRevision: 0, lastRefresh: 0, searchTimer: null,
    search: null, searchResults: null, searchOpen: false, selectedPlayer: -1
  };
  const markupCache = new WeakMap();
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${name === 'close' ? '<path d="m6 6 12 12M6 18 18 6"/>' : '<circle cx="9" cy="8" r="4"/><path d="M2 21v-2a7 7 0 0 1 14 0v2M19 8v6m-3-3h6"/>'}</svg>`;
  const avatar = player => `<span class="friends-avatar" aria-hidden="true">${player.avatar ? `<img src="${escapeHTML(player.avatar)}" alt="" loading="lazy">` : escapeHTML(player.initials || player.name?.slice(0, 2) || 'P')}</span>`;
  const empty = (title, copy) => `<div class="friends-empty"><h3>${escapeHTML(title)}</h3><p>${escapeHTML(copy)}</p></div>`;
  const profileLink = id => '#player/' + encodeURIComponent(id) + '/moments';
  const signedIn = () => !!account.userId && !document.body.classList.contains('account-visible');

  // Keep keyboard focus in place when background refreshes update a list.
  function updateRegion(node, markup) {
    if (!node || markupCache.get(node) === markup) return;
    const active = document.activeElement;
    const attributes = ['data-friend-action', 'data-friends-tab', 'data-friends-open', 'data-friends-retry'];
    const attribute = node.contains(active) && attributes.find(name => active.hasAttribute(name));
    const value = attribute ? active.getAttribute(attribute) : null;
    const playerId = active?.getAttribute('data-friend-player');
    const requestId = active?.getAttribute('data-friend-id');
    node.innerHTML = markup;
    markupCache.set(node, markup);
    if (attribute) {
      const replacement = [...node.querySelectorAll(`[${attribute}]`)].find(element =>
        element.getAttribute(attribute) === value &&
        element.getAttribute('data-friend-player') === playerId &&
        element.getAttribute('data-friend-id') === requestId);
      replacement?.focus({preventScroll: true});
    }
  }

  async function request(path, payload) {
    if (!signedIn()) throw new Error('Sign in again to manage friends.');
    const userId = account.userId;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/api/friends' + path, {
        method: payload ? 'POST' : 'GET', signal: controller.signal,
        headers: payload ? {'Content-Type': 'application/json', 'X-Dhoyo-Request': '1'} : {},
        body: payload ? JSON.stringify(payload) : undefined
      });
      const value = await response.json().catch(() => null);
      if (!response.ok) {
        const fallback = response.status === 404 ? 'The friends service could not be found' :
          response.status === 500 ? 'The friends service encountered an error' :
          [502, 503, 504].includes(response.status) ? 'The friends service is temporarily unavailable' :
          'Friends are unavailable right now';
        const error = new Error(value?.error || `${fallback} (HTTP ${response.status}). Please try again.`);
        error.status = response.status;
        throw error;
      }
      if (!signedIn() || account.userId !== userId) throw new Error('Sign in again to manage friends.');
      if (!value || typeof value !== 'object') throw new Error('Could not load friends. Please try again.');
      return value;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The request timed out. Please try again.');
      if (error instanceof TypeError) throw new Error('Could not connect. Check your connection and try again.');
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function remember(players, revision) {
    players.forEach(player => {
      state.knownPlayers.set(player.id, player);
      if (['none', 'friends', 'incoming', 'outgoing'].includes(player.friendship)) {
        rememberRelation(player.id, {status: player.friendship, requestId: player.requestId}, revision);
      }
    });
  }

  function rememberRelation(playerId, relation, revision) {
    if ((state.relations.get(playerId)?.revision || 0) <= revision) state.relations.set(playerId, {...relation, revision});
  }

  function applyOverview(value, revision) {
    if (value.currentUserId !== account.userId) return;
    const previousFriends = new Set((state.overview?.friends || []).map(player => player.id));
    const nextFriends = new Set(value.friends.map(player => player.id));
    const changedFriends = [...new Set([...previousFriends, ...nextFriends])].filter(id => previousFriends.has(id) !== nextFriends.has(id));
    state.overview = value;
    // Directory responses include their own relationship state. An earlier
    // overview must not turn a newer received request into another Add friend.
    for (const playerId of state.relations.keys()) rememberRelation(playerId, {status: 'none', requestId: null}, revision);
    value.friends.forEach(player => rememberRelation(player.id, {status: 'friends', requestId: player.requestId}, revision));
    value.incoming.forEach(item => rememberRelation(item.player.id, {status: 'incoming', requestId: item.id}, revision));
    value.outgoing.forEach(item => rememberRelation(item.player.id, {status: 'outgoing', requestId: item.id}, revision));
    remember(value.friends);
    remember([...value.incoming, ...value.outgoing].map(item => item.player));
    state.error = '';
    if (changedFriends.length) invalidateMedia(changedFriends);
  }

  function invalidateMedia(playerIds) {
    const ids = new Set(playerIds.filter(id => id !== account.userId));
    const scrub = player => {
      if (ids.has(player.id)) Object.assign(player, {avatar: '', cover: '', image: '', canViewPhotos: false, mediaHidden: true});
    };
    state.playersRevision++;
    state.playersLoading = false;
    state.players.forEach(scrub);
    state.knownPlayers.forEach(scrub);
    if (typeof playerHub !== 'undefined') {
      playerHub.revision++;
      playerHub.profiles.clear();
      playerHub.errors.clear();
    }
    if (typeof arena !== 'undefined') {
      arena.request++;
      arena.data?.players.forEach(scrub);
    }
    if (feedState?.posts) feedState.posts.forEach(post => {
      if (ids.has(post.authorId)) Object.assign(post, {image: '', avatar: '', mediaHidden: true});
    });
    if (typeof social !== 'undefined') {
      social.request++;
      social.stories = social.stories.filter(story => !ids.has(story.authorId));
    }
    if (document.querySelector('#story-dialog')?.open) document.querySelector('#story-dialog').close();
    const storyContent = document.querySelector('#story-content');
    if (storyContent) storyContent.innerHTML = '';
    if (document.querySelector('#modal .hub-full-photo')) {
      document.querySelector('#modal')?.close();
      const modalBody = document.querySelector('#modal-body');
      if (modalBody) modalBody.innerHTML = '';
    }
    window.RingMessages?.invalidateMedia?.(playerIds);
    if (typeof render === 'function') render();
    renderUI();
    // Remove cached media before these requests start, so a failed refresh
    // cannot leave a former friend's private photos visible.
    return Promise.allSettled([
      ...(typeof refreshArena === 'function' ? [refreshArena()] : []),
      ...(typeof refreshFeed === 'function' ? [refreshFeed()] : []),
      loadPlayers()
    ]);
  }

  function relationship(playerId) {
    const known = state.relations.get(playerId);
    if (known) return known;
    const overview = state.overview;
    const friend = overview?.friends.find(player => player.id === playerId);
    if (friend) return {status: 'friends', requestId: friend.requestId};
    const incoming = overview?.incoming.find(item => item.player.id === playerId);
    if (incoming) return {status: 'incoming', requestId: incoming.id};
    const outgoing = overview?.outgoing.find(item => item.player.id === playerId);
    if (outgoing) return {status: 'outgoing', requestId: outgoing.id};
    return {status: 'none', requestId: null};
  }

  function actionButton(action, label, playerId, requestId, primary = false) {
    return `<button type="button" class="${primary ? 'friends-primary' : 'friends-secondary'}" data-friend-action="${action}" data-friend-player="${escapeHTML(playerId)}"${requestId ? ` data-friend-id="${escapeHTML(requestId)}"` : ''}${state.busy ? ' disabled' : ''}>${label}</button>`;
  }

  function actions(playerId, allowRemove = false) {
    const relation = relationship(playerId);
    if (relation.status === 'incoming') return actionButton('accept', 'Accept', playerId, relation.requestId, true) + actionButton('decline', 'Decline', playerId, relation.requestId);
    if (relation.status === 'outgoing') return '<small class="friends-row-status">Request sent</small>' + actionButton('cancel', 'Cancel request', playerId, relation.requestId);
    if (relation.status === 'friends') return '<small class="friends-row-status">Friends</small>' + (allowRemove ? actionButton('remove', 'Remove friend', playerId, relation.requestId) : '<button type="button" class="friends-secondary" data-friends-open="friends">View friends</button>');
    return actionButton('send', 'Add friend', playerId, null, true);
  }

  function row(player, allowRemove = false) {
    return `<article class="friends-row">${avatar(player)}<a class="friends-player-copy" href="${profileLink(player.id)}" data-friends-profile><strong>${escapeHTML(player.name)}</strong><small>${escapeHTML(player.sport)} · View profile ↗</small></a><div class="friends-actions">${actions(player.id, allowRemove)}</div></article>`;
  }

  function errorMarkup(message, source) {
    return message ? `<div class="friends-error" role="alert"><span>${escapeHTML(message)}</span><button type="button" data-friends-retry="${source}">Try again</button></div>` : '';
  }

  function renderDialog() {
    if (!state.dialog) return;
    const incomingCount = state.overview?.incoming.length || 0;
    state.dialog.querySelectorAll('[data-friends-tab]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.friendsTab === state.tab));
      const count = button.querySelector('.friends-tab-count');
      if (count) { count.hidden = !incomingCount; count.textContent = String(incomingCount); }
    });
    let content = errorMarkup(state.error, 'overview');
    if (!state.overview) {
      content += '<p class="friends-note" role="status">' + (state.loading ? 'Loading your friends and requests…' : 'Your friends will appear when the connection is restored.') + '</p>';
    } else if (state.tab === 'requests') {
      content += `<section class="friends-section"><h3>Received requests · ${incomingCount}</h3>${state.overview.incoming.map(item => row(item.player)).join('') || empty('No new requests', 'Requests from other players will appear here.')}</section>`;
      content += `<section class="friends-section"><h3>Sent requests · ${state.overview.outgoing.length}</h3>${state.overview.outgoing.map(item => row(item.player)).join('') || '<p class="friends-note">You have no pending sent requests.</p>'}</section>`;
    } else if (state.tab === 'friends') {
      content += `<section class="friends-section"><h3>Your friends · ${state.overview.friends.length}</h3>${state.overview.friends.map(player => row(player, true)).join('') || empty('Your circle starts here', 'Use the search at the top to open a player’s profile and send a friend request.')}</section>`;
    }
    updateRegion(state.dialog.querySelector('[data-friends-content]'), content);
  }

  function addProfileAction() {
    if (!signedIn() || typeof arena === 'undefined' || typeof view === 'undefined' || view !== 'player') return;
    let playerId;
    try { playerId = decodeURIComponent(arena.route.split('/')[1] || ''); } catch { return; }
    const container = document.querySelector('.hub-profile-actions');
    if (!container) return;
    const own = playerId === account.userId;
    const registered = state.knownPlayers.has(playerId) || (typeof playerHub !== 'undefined' && playerHub.profiles.get(playerId)?.registeredPlayer);
    if (!own && !registered) return;
    let region = container.querySelector('.friends-profile-actions');
    if (!region) { region = document.createElement('div'); region.className = 'friends-profile-actions'; container.prepend(region); }
    const incomingCount = state.overview?.incoming.length || 0;
    updateRegion(region, (own ? `<button type="button" class="friends-primary" data-friends-open="${incomingCount ? 'requests' : 'friends'}" aria-controls="friends-dialog" aria-haspopup="dialog" aria-expanded="${!!state.dialog?.open}">Manage friends${incomingCount ? ` · ${incomingCount} request${incomingCount === 1 ? '' : 's'}` : ''}</button>` : actions(playerId, true)) + errorMarkup(state.error, 'overview'));
  }

  function renderSearch() {
    if (!state.search || !state.searchResults) return;
    const expanded = state.searchOpen && !!state.query && signedIn();
    state.searchResults.hidden = !expanded;
    state.search.setAttribute('aria-expanded', String(expanded));
    state.search.removeAttribute('aria-activedescendant');
    if (!expanded) return;
    let content = '<strong class="player-search-heading">Players</strong>';
    if (state.playersError) content += errorMarkup(state.playersError, 'players');
    else if (state.playersLoading) content += '<p class="player-search-note" role="status">Searching players…</p>';
    else if (!state.players.length) content += '<p class="player-search-note" role="status">No players found. Try another name or sport.</p>';
    const selected = state.selectedPlayer;
    content += `<div id="player-search-list" role="listbox" aria-label="Players">${state.players.map((player, index) => `<a id="player-search-option-${index}" class="player-search-option" href="${profileLink(player.id)}" role="option" aria-selected="${index === selected}" data-player-search-id="${escapeHTML(player.id)}" data-friends-profile>${avatar(player)}<span><strong>${escapeHTML(player.name)}</strong><small>${escapeHTML(player.sport)} · View profile</small></span></a>`).join('')}</div>`;
    updateRegion(state.searchResults, content);
    if (selected >= 0 && state.players[selected]) state.search.setAttribute('aria-activedescendant', 'player-search-option-' + selected);
  }

  function closeSearch() {
    state.searchOpen = false;
    state.selectedPlayer = -1;
    renderSearch();
  }

  function selectPlayer(playerId) {
    closeSearch();
    const route = profileLink(playerId);
    if (location.hash === route && typeof navigate === 'function') navigate(route.slice(1));
    else location.hash = route;
  }

  function createSearch() {
    const search = document.querySelector('#search');
    if (!search) return;
    state.search = search;
    search.setAttribute('role', 'combobox');
    search.setAttribute('aria-autocomplete', 'list');
    search.setAttribute('aria-controls', 'player-search-list');
    search.setAttribute('aria-expanded', 'false');
    search.setAttribute('autocomplete', 'off');
    const results = document.createElement('div');
    results.id = 'player-search-results';
    results.className = 'player-search-results';
    results.hidden = true;
    search.closest('.search').append(results);
    state.searchResults = results;
    search.addEventListener('input', () => {
      state.query = search.value.trim().slice(0, 100);
      state.playersRevision++;
      state.players = [];
      state.playersError = '';
      state.playersLoading = !!state.query;
      state.searchOpen = !!state.query;
      state.selectedPlayer = -1;
      clearTimeout(state.searchTimer);
      renderSearch();
      if (state.query) state.searchTimer = setTimeout(loadPlayers, 250);
    });
    search.addEventListener('focus', () => {
      if (search.value.trim() !== state.query) {
        state.query = search.value.trim().slice(0, 100);
        state.players = [];
        state.playersError = '';
        state.selectedPlayer = -1;
        if (state.query) loadPlayers();
      }
      state.searchOpen = !!state.query;
      renderSearch();
    });
    search.addEventListener('keydown', event => {
      if (event.key === 'Escape') { if (state.searchOpen) { event.preventDefault(); closeSearch(); } return; }
      if (!state.query || !state.players.length) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        state.searchOpen = true;
        const count = state.players.length;
        state.selectedPlayer = event.key === 'ArrowDown' ? (state.selectedPlayer + 1) % count : (state.selectedPlayer < 0 ? count - 1 : (state.selectedPlayer - 1 + count) % count);
        renderSearch();
      } else if (event.key === 'Enter' && state.searchOpen) {
        event.preventDefault();
        selectPlayer(state.players[Math.max(0, state.selectedPlayer)].id);
      }
    });
  }

  function renderUI() { renderDialog(); addProfileAction(); renderSearch(); }

  async function loadOverview() {
    if (!signedIn() || state.busy || state.loading) return;
    const revision = ++state.overviewRevision;
    const relationRevision = ++state.relationRevision;
    state.loading = true;
    state.lastRefresh = Date.now();
    renderDialog();
    try { const value = await request(''); if (revision === state.overviewRevision) applyOverview(value, relationRevision); }
    catch (error) { if (revision === state.overviewRevision && signedIn()) state.error = error.message; }
    finally { if (revision === state.overviewRevision) { state.loading = false; renderUI(); } }
  }

  async function loadPlayers() {
    if (!signedIn() || !state.query) return;
    const revision = ++state.playersRevision;
    const relationRevision = ++state.relationRevision;
    state.playersLoading = true;
    state.playersError = '';
    renderSearch();
    try {
      const value = await request('/players?q=' + encodeURIComponent(state.query));
      if (revision === state.playersRevision && value.currentUserId === account.userId) { state.players = value.players; remember(value.players, relationRevision); }
    } catch (error) { if (revision === state.playersRevision && signedIn()) state.playersError = error.message; }
    finally { if (revision === state.playersRevision) { state.playersLoading = false; renderUI(); } }
  }

  async function mutate(button) {
    if (state.busy || !signedIn()) return;
    const {friendAction: action, friendPlayer: playerId, friendId: requestId} = button.dataset;
    if (action !== 'send' && !requestId) return;
    state.busy = true;
    state.error = '';
    state.overviewRevision++;
    state.playersRevision++;
    state.loading = false;
    state.playersLoading = false;
    let refreshRelationship = false;
    renderUI();
    try {
      const value = await request(action === 'send' ? '/requests' : '/requests/' + encodeURIComponent(requestId), action === 'send' ? {playerId} : {action});
      state.playersRevision++;
      state.playersLoading = false;
      applyOverview(value, ++state.relationRevision);
      if (typeof toast === 'function') toast({send: 'Friend request sent.', accept: 'Friend request accepted.', decline: 'Friend request declined.', cancel: 'Friend request cancelled.', remove: 'Friend removed.'}[action]);
    } catch (error) {
      if (signedIn()) {
        state.error = error.message;
        refreshRelationship = error.status === 409 || error.status === 404;
        if (!state.dialog.open) { state.tab = 'requests'; state.dialog.showModal(); }
      }
    } finally {
      state.busy = false;
      renderUI();
      if (state.dialog.open && (!document.activeElement || document.activeElement === document.body)) state.dialog.querySelector(`[data-friends-tab="${state.tab}"]`)?.focus();
      if (refreshRelationship) await Promise.all([loadOverview(), loadPlayers()]);
    }
  }

  async function open(tab) {
    await accountReady;
    if (!signedIn()) return;
    state.tab = ['requests', 'friends'].includes(tab) ? tab : 'requests';
    closeSearch();
    renderDialog();
    if (!state.dialog.open) { state.dialog.showModal(); addProfileAction(); }
    await loadOverview();
  }

  function createDialog() {
    const dialog = document.createElement('dialog');
    dialog.id = 'friends-dialog'; dialog.className = 'friends-dialog';
    dialog.setAttribute('aria-labelledby', 'friends-title');
    dialog.innerHTML = `<header class="friends-heading"><div><span class="friends-kicker">YOUR PEOPLE. YOUR GAME.</span><h2 id="friends-title">Your circle</h2><p class="friends-description">Manage your requests and friends. Search for players at the top of the page.</p></div><button type="button" class="friends-close" data-friends-close aria-label="Close friends">${icon('close')}</button></header><nav class="friends-tabs" aria-label="Friends sections"><button type="button" data-friends-tab="requests" aria-pressed="true">Requests <span class="friends-tab-count" hidden></span></button><button type="button" data-friends-tab="friends" aria-pressed="false">Friends</button></nav><div class="friends-body" data-friends-content></div>`;
    document.body.append(dialog);
    state.dialog = dialog;
    dialog.addEventListener('close', addProfileAction);
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button?.hasAttribute('data-friend-action')) { event.preventDefault(); mutate(button); }
    else if (button?.hasAttribute('data-friends-open')) open(button.dataset.friendsOpen);
    else if (button?.hasAttribute('data-friends-tab')) { state.tab = button.dataset.friendsTab; renderDialog(); }
    else if (button?.hasAttribute('data-friends-close')) state.dialog.close();
    else if (button?.hasAttribute('data-friends-retry')) {
      const source = button.dataset.friendsRetry;
      if (source === 'players') loadPlayers();
      else loadOverview();
    }
    const profile = event.target.closest('[data-friends-profile]');
    if (profile) { state.dialog?.close(); closeSearch(); }
    else if (!event.target.closest('.search')) closeSearch();
  });

  if (typeof render === 'function') {
    const previousRender = render;
    render = function () { previousRender(); addProfileAction(); };
  }
  window.RingFriends = {open, refresh: loadOverview, invalidateMedia};
  accountReady.then(() => {
    createDialog();
    createSearch();
    loadOverview();
    setInterval(() => {
      if (document.visibilityState !== 'hidden' && signedIn() && Date.now() - state.lastRefresh >= (state.dialog.open ? 8000 : 30000)) loadOverview();
    }, 8000);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') loadOverview(); });
  });
  // Expired sessions must not leave a private friends dialog over the login screen.
  new MutationObserver(() => {
    if (signedIn()) return;
    state.overviewRevision++; state.playersRevision++;
    state.overview = null; state.players = []; state.knownPlayers.clear(); state.relations.clear();
    state.query = '';
    if (state.search) state.search.value = '';
    closeSearch();
    state.error = ''; state.playersError = ''; state.loading = false; state.playersLoading = false;
    clearTimeout(state.searchTimer);
    if (state.dialog?.open) state.dialog.close();
    document.querySelectorAll('.friends-profile-actions').forEach(node => node.remove());
    renderUI();
  }).observe(document.body, {attributes: true, attributeFilter: ['class']});
})(typeof state === 'undefined' ? null : state);
