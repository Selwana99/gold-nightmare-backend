/* ═════════════════════════════════════════════════════════
   Auth — cookie-based session, no localStorage
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const Auth = {
    _checked: false,
    _isAuthenticated: false,

    async check() {
      try {
        await Api.get('/auth/me');
        this._isAuthenticated = true;
      } catch {
        this._isAuthenticated = false;
      }
      this._checked = true;
      return this._isAuthenticated;
    },

    async login(passcode) {
      await Api.post('/auth/login', { passcode });
      this._isAuthenticated = true;
      window.location.href = '/';
    },

    async logout() {
      try { await Api.post('/auth/logout', {}); } catch {}
      this._isAuthenticated = false;
      window.location.href = '/login';
    },

    isAuthenticated() {
      return this._isAuthenticated;
    },

    async requireAuth() {
      if (!this._checked) await this.check();
      if (!this._isAuthenticated) {
        window.location.href = '/login';
        return false;
      }
      return true;
    },
  };

  window.Auth = Auth;

  // Auto-check on page load (except login page)
  document.addEventListener('DOMContentLoaded', () => {
    const isLoginPage = window.location.pathname === '/login';
    const isSharePage = window.location.pathname.startsWith('/share/');
    if (!isLoginPage && !isSharePage) {
      Auth.check().then(ok => {
        if (!ok && !isLoginPage) {
          window.location.href = '/login';
        }
      });
    }
  });
})();
