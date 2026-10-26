// Account password controls are available only on the signed-in player's profile.
(() => {
  let dialog, busy = false;
  const signedIn = () => !!account.userId && !document.body.classList.contains('account-visible');

  function createDialog() {
    dialog = document.createElement('dialog');
    dialog.id = 'account-security-dialog';
    dialog.className = 'account-security-dialog';
    dialog.setAttribute('aria-labelledby', 'account-security-title');
    dialog.innerHTML = `<header class="security-heading"><div><span class="eyebrow">YOUR ACCOUNT</span><h2 id="account-security-title">Password & security</h2></div><button type="button" class="security-close" data-security-close aria-label="Close password settings">×</button></header><form id="account-security-form" method="post" action="/api/auth/change-password"><p class="security-intro">Choose a new password for your account. Your other signed-in devices will be signed out.</p><label for="security-current-password">Current password<input id="security-current-password" name="currentPassword" type="password" autocomplete="current-password" maxlength="128" required></label><label for="security-new-password">New password<input id="security-new-password" name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" aria-describedby="security-password-help" required></label><small id="security-password-help">Use between 10 and 128 characters.</small><label for="security-confirm-password">Confirm new password<input id="security-confirm-password" name="passwordConfirm" type="password" autocomplete="new-password" minlength="10" maxlength="128" required></label><p class="security-error" role="alert"></p><button type="submit" class="primary security-submit">Update password</button><div class="security-recovery"><strong>Forgot your current password?</strong><p>Get a six-digit verification code by email to reset it.</p><button type="button" data-security-recover>Send a reset code</button></div></form>`;
    document.body.append(dialog);
    const form = dialog.querySelector('form');
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || !signedIn()) return;
      const values = Object.fromEntries(new FormData(form));
      const error = form.querySelector('.security-error');
      error.textContent = '';
      if (values.password !== values.passwordConfirm) { error.textContent = 'The new passwords do not match.'; return; }
      if (values.password.length < 10 || values.password.length > 128) { error.textContent = 'Use a password between 10 and 128 characters.'; return; }
      const userId = account.userId, submit = form.querySelector('[type="submit"]');
      busy = true;
      form.setAttribute('aria-busy', 'true');
      submit.textContent = 'Updating password…';
      form.querySelectorAll('input, button').forEach(node => { node.disabled = true; });
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
      try {
        requireAccountSecureTransport();
        const encrypted=await encryptAccountPayload('change-password',{currentPassword:values.currentPassword,password:values.password});
        const response = await fetch('/api/auth/change-password', {
          method: 'POST', signal: controller.signal,
          headers: {'Content-Type': 'application/json', 'X-Dhoyo-Request': '1'},
          body: JSON.stringify(encrypted)
        });
        const result = await response.json().catch(() => null);
        if (response.status === 401) { account.userId = null; showAccountForm('login', 'Your session has expired. Sign in again.'); return; }
        if (!response.ok) throw new Error(result?.error || 'Could not update your password. Please try again.');
        if (!signedIn() || account.userId !== userId) return;
        form.reset();
        dialog.close();
        toast(result.message || 'Your password has been updated.');
      } catch (problem) {
        if (signedIn() && account.userId === userId && dialog.open) error.textContent = problem.name === 'AbortError' ? 'The request timed out. Please try again.' : problem instanceof TypeError ? 'Could not connect. Check your connection and try again.' : problem.message;
      } finally {
        delete values.currentPassword;
        delete values.password;
        delete values.passwordConfirm;
        clearTimeout(timeout);
        busy = false;
        form.setAttribute('aria-busy', 'false');
        submit.textContent = 'Update password';
        form.querySelectorAll('input, button').forEach(node => { node.disabled = false; });
      }
    });
    dialog.addEventListener('click', event => {
      if (event.target.closest('[data-security-close]')) dialog.close();
      if (event.target.closest('[data-security-recover]') && !busy && signedIn()) {
        dialog.close();
        accountRecoveryReturnToProfile = true;
        showAccountForm('forgot');
      }
    });
    dialog.addEventListener('close', () => {
      form.reset();
      form.querySelector('.security-error').textContent = '';
    });
  }

  async function open() {
    await accountReady;
    if (!signedIn()) return;
    if (!dialog) createDialog();
    if (!dialog.open) dialog.showModal();
  }

  function addProfileAction() {
    if (!signedIn() || typeof view === 'undefined' || view !== 'player' || typeof arena === 'undefined') return;
    let playerId;
    try { playerId = decodeURIComponent(arena.route.split('/')[1] || ''); } catch { return; }
    const actions = document.querySelector('.hub-profile-actions');
    if (playerId !== account.userId || !actions || actions.querySelector('[data-account-security]')) return;
    const button = document.createElement('button');
    button.type = 'button'; button.dataset.accountSecurity = '';
    button.textContent = 'Password & security';
    actions.append(button);
  }

  document.addEventListener('click', event => {
    if (event.target.closest('[data-account-security]')) open();
  });
  if (typeof render === 'function') {
    const previousRender = render;
    render = function () { previousRender(); addProfileAction(); };
  }
  window.RingAccountSecurity = {open};
  accountReady.then(addProfileAction);
})();
