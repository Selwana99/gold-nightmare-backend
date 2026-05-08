/* ═════════════════════════════════════════════════════════
   API wrapper — no token storage; uses cookie for auth
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const API_BASE = '/api/v1';

  const Api = {
    async _fetch(path, options = {}) {
      const opts = {
        ...options,
        headers: { ...(options.headers || {}) },
        credentials: 'include',  // send cookie
      };
      if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
        opts.body = JSON.stringify(opts.body);
        opts.headers['Content-Type'] = 'application/json';
      }
      const r = await fetch(API_BASE + path, opts);
      if (r.status === 401) {
        // Redirect to login
        if (!path.includes('/auth/')) {
          window.location.href = '/login';
        }
        throw new Error('غير مصرح');
      }
      const text = await r.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { _raw: text }; }
      if (!r.ok) {
        const msg = data.detail || data.message || `Error ${r.status}`;
        throw new Error(msg);
      }
      return data;
    },

    get(path) { return this._fetch(path); },
    post(path, body) { return this._fetch(path, { method: 'POST', body }); },
    del(path) { return this._fetch(path, { method: 'DELETE' }); },

    async upload(path, formData) {
      // For file uploads — don't set Content-Type
      const r = await fetch(API_BASE + path, {
        method: 'POST', body: formData, credentials: 'include',
      });
      if (r.status === 401) {
        window.location.href = '/login';
        throw new Error('غير مصرح');
      }
      const text = await r.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { _raw: text }; }
      if (!r.ok) throw new Error(data.detail || `Error ${r.status}`);
      return data;
    },

    // ─── Toast helper ───
    toast(message, type = 'info', duration = 3500) {
      let container = document.getElementById('toast-container');
      if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;top:20px;inset-inline-end:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
        document.body.appendChild(container);
      }
      const t = document.createElement('div');
      const colors = {
        success: 'background:rgba(40,180,99,0.95);color:#fff;',
        error: 'background:rgba(220,53,69,0.95);color:#fff;',
        info: 'background:rgba(212,175,55,0.95);color:#000;',
      };
      t.style.cssText = `padding:12px 20px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.4);
        ${colors[type] || colors.info};animation:slideIn 0.25s ease;pointer-events:auto;
        max-width:340px;font-size:14px;line-height:1.5;`;
      t.textContent = message;
      container.appendChild(t);
      setTimeout(() => {
        t.style.animation = 'slideOut 0.25s ease';
        setTimeout(() => t.remove(), 250);
      }, duration);
    },
  };

  // Animations
  if (!document.getElementById('toast-keyframes')) {
    const style = document.createElement('style');
    style.id = 'toast-keyframes';
    style.textContent = `
      @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
      @keyframes slideOut { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
    `;
    document.head.appendChild(style);
  }

  window.Api = Api;
})();
