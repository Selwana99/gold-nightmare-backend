/* ═════════════════════════════════════════════════════════
   Analyzer — upload chart + render result
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const Analyzer = {
    files: [],

    async init() {
      if (!await Auth.requireAuth()) return;
      this._wireUI();
    },

    _wireUI() {
      const dropArea = document.getElementById('drop-area');
      const fileInput = document.getElementById('file-input');
      const submitBtn = document.getElementById('analyze-btn');
      const resultEl = document.getElementById('result');
      if (!dropArea || !fileInput) return;

      const renderFiles = () => {
        const list = document.getElementById('file-list');
        if (!list) return;
        list.innerHTML = this.files.map((f, i) => `
          <div class="file-chip">
            <span>📊 ${f.name}</span>
            <button data-rm="${i}" class="btn-ghost" style="padding:2px 8px;font-size:14px;">×</button>
          </div>
        `).join('');
        list.querySelectorAll('[data-rm]').forEach(b => {
          b.addEventListener('click', () => {
            this.files.splice(parseInt(b.dataset.rm), 1);
            renderFiles();
          });
        });
      };

      const addFiles = (files) => {
        for (const f of files) {
          if (this.files.length >= 4) {
            Api.toast('الحد الأقصى 4 صور', 'error'); break;
          }
          if (!f.type.startsWith('image/')) continue;
          this.files.push(f);
        }
        renderFiles();
      };

      dropArea.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', e => addFiles(e.target.files));
      ['dragenter', 'dragover'].forEach(e => dropArea.addEventListener(e, ev => {
        ev.preventDefault(); dropArea.classList.add('drag');
      }));
      ['dragleave', 'drop'].forEach(e => dropArea.addEventListener(e, ev => {
        ev.preventDefault(); dropArea.classList.remove('drag');
      }));
      dropArea.addEventListener('drop', e => addFiles(e.dataTransfer.files));

      // Paste support
      document.addEventListener('paste', e => {
        const items = e.clipboardData?.items || [];
        const files = [];
        for (const item of items) {
          if (item.type.startsWith('image/')) {
            const f = item.getAsFile();
            if (f) files.push(f);
          }
        }
        if (files.length) addFiles(files);
      });

      if (submitBtn) submitBtn.addEventListener('click', async () => {
        if (!this.files.length) {
          Api.toast('ارفع صورة واحدة على الأقل', 'error'); return;
        }
        const ctx = (document.getElementById('extra-context') || {}).value || '';
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spin"></span> جاري التحليل...';
        if (resultEl) {
          resultEl.innerHTML = '<div class="text-center" style="padding:60px;"><div class="spin"></div><p class="muted mt-4">Claude يحلل الشارت...</p></div>';
        }
        try {
          const fd = new FormData();
          this.files.forEach(f => fd.append('images', f));
          if (ctx) fd.append('extra_context', ctx);

          const a = await Api.upload('/analyses', fd);
          if (resultEl) {
            resultEl.innerHTML = Render.analysis(a.result_json || {});
            resultEl.innerHTML += `
              <div class="flex gap-2 justify-center mt-4 flex-wrap">
                <button class="btn-ghost" data-share="${a.id}">🔗 رابط مشاركة</button>
                <button class="btn-ghost" data-pdf="${a.id}">📄 PDF</button>
                <a href="/history" class="btn-ghost">📋 السجل</a>
              </div>`;
            this._wireResultButtons(a, resultEl);
            resultEl.scrollIntoView({ behavior: 'smooth' });
          }
          Api.toast('✓ التحليل جاهز', 'success');
          this.files = [];
          renderFiles();
        } catch (e) {
          if (resultEl) resultEl.innerHTML = `<p class="error-msg">${e.message}</p>`;
          Api.toast(e.message, 'error');
        } finally {
          submitBtn.disabled = false;
          submitBtn.innerHTML = '🚀 تحليل الشارت';
        }
      });
    },

    _wireResultButtons(analysis, container) {
      // copy setup buttons
      container.querySelectorAll('[data-copy-setup]').forEach(btn => {
        btn.addEventListener('click', () => {
          const idx = parseInt(btn.dataset.copySetup);
          const setups = (analysis.result_json || {}).setups || [];
          if (!setups[idx]) return;
          navigator.clipboard.writeText(Render.copySetupText(setups[idx]))
            .then(() => Api.toast('✓ تم النسخ', 'success'));
        });
      });
      const shareBtn = container.querySelector(`[data-share="${analysis.id}"]`);
      if (shareBtn) shareBtn.addEventListener('click', async () => {
        try {
          const link = await Api.post(`/analyses/${analysis.id}/share`, {});
          await navigator.clipboard.writeText(link.public_url);
          Api.toast('✓ تم نسخ الرابط', 'success');
        } catch (e) { Api.toast(e.message, 'error'); }
      });
      const pdfBtn = container.querySelector(`[data-pdf="${analysis.id}"]`);
      if (pdfBtn) pdfBtn.addEventListener('click', () => {
        window.open(`/api/v1/analyses/${analysis.id}/pdf`, '_blank');
      });
    },
  };

  window.Analyzer = Analyzer;
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => Analyzer.init(), 200);
  });
})();
