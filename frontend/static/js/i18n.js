/* ═════════════════════════════════════════════════════════
   i18n — language management with localStorage persistence
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const STORAGE_KEY = 'gn_lang';
  const FALLBACK = { ar: {}, en: {} };

  const I18n = {
    lang: 'ar',
    translations: FALLBACK,

    async init() {
      this.lang = localStorage.getItem(STORAGE_KEY) || 'ar';
      await this.loadAll();
      this.applyDirection();
      this.applyTranslations();
      this._wireToggle();
    },

    async loadAll() {
      const langs = ['ar', 'en'];
      await Promise.all(langs.map(async (lang) => {
        try {
          const res = await fetch(`/static/locales/${lang}.json`);
          if (res.ok) {
            this.translations[lang] = await res.json();
          }
        } catch (e) {
          console.warn(`Failed to load ${lang} locale`, e);
        }
      }));
    },

    t(key, fallback = '') {
      const parts = key.split('.');
      let val = this.translations[this.lang];
      for (const p of parts) {
        if (val && typeof val === 'object') val = val[p];
        else { val = null; break; }
      }
      return val || fallback || key;
    },

    setLang(lang) {
      if (!['ar', 'en'].includes(lang)) return;
      this.lang = lang;
      localStorage.setItem(STORAGE_KEY, lang);
      this.applyDirection();
      this.applyTranslations();
      const labelEl = document.getElementById('lang-label');
      if (labelEl) labelEl.textContent = lang.toUpperCase();
      window.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
    },

    applyDirection() {
      document.documentElement.lang = this.lang;
      document.documentElement.dir = this.lang === 'ar' ? 'rtl' : 'ltr';
    },

    applyTranslations() {
      document.querySelectorAll('[data-i18n]').forEach((el) => {
        const key = el.getAttribute('data-i18n');
        const txt = this.t(key);
        if (txt && txt !== key) el.textContent = txt;
      });
      document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
        const key = el.getAttribute('data-i18n-placeholder');
        const txt = this.t(key);
        if (txt && txt !== key) el.placeholder = txt;
      });
    },

    _wireToggle() {
      const btn = document.getElementById('lang-toggle');
      if (!btn) return;
      const labelEl = document.getElementById('lang-label');
      if (labelEl) labelEl.textContent = this.lang.toUpperCase();
      btn.addEventListener('click', () => {
        this.setLang(this.lang === 'ar' ? 'en' : 'ar');
      });
    },
  };

  window.I18n = I18n;

  // Theme toggle (lives here for convenience)
  function initTheme() {
    const KEY = 'gn_theme';
    const saved = localStorage.getItem(KEY) || 'dark';
    document.documentElement.dataset.theme = saved;
    document.body.classList.add(`theme-${saved}`);
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const cur = document.documentElement.dataset.theme || 'dark';
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      document.body.classList.remove(`theme-${cur}`);
      document.body.classList.add(`theme-${next}`);
      localStorage.setItem(KEY, next);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    I18n.init();
    initTheme();
  });
})();
