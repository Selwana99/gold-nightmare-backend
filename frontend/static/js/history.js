/* ═════════════════════════════════════════════════════════
   History page — paginated user analyses
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const History = {
    page: 1,
    pageSize: 20,
    total: 0,

    async init() {
      if (!Auth.requireAuth()) return;
      await this.load(1);
      this._wireUI();
    },

    async load(page) {
      this.page = page;
      const listEl = document.getElementById('history-list');
      if (!listEl) return;
      listEl.innerHTML = '<div style="text-align:center;padding:40px;"><div class="spin"></div></div>';

      try {
        const data = await Api.get(`/analyses/?page=${page}&page_size=${this.pageSize}`);
        this.total = data.total;
        this._renderList(data.items);
        this._renderPagination();
      } catch (e) {
        listEl.innerHTML = `<div class="card p-6"><p class="error-msg">${e.message}</p></div>`;
      }
    },

    _renderList(items) {
      const listEl = document.getElementById('history-list');
      if (!items.length) {
        listEl.innerHTML = `
          <div class="card p-6 text-center">
            <p class="muted">لا توجد تحاليل بعد</p>
            <a href="/" class="btn-gold mt-4" style="display:inline-block;">إنشاء أول تحليل</a>
          </div>`;
        return;
      }

      listEl.innerHTML = items.map(item => `
        <div class="card p-4 mb-3" style="cursor:pointer;" data-id="${item.id}">
          <div class="flex justify-between items-start gap-3 flex-wrap">
            <div>
              <h4 class="display-font" style="font-size:18px;">
                ${item.symbol} <span class="gold">·</span> ${item.timeframe}
                ${item.is_mtf ? '<span class="badge badge-gold">MTF</span>' : ''}
              </h4>
              <div class="flex items-center gap-2 mt-2 flex-wrap">
                ${item.trend_direction ? `<span class="badge ${Render.biasClass(item.trend_direction)}">${Render.biasLabel(item.trend_direction)}</span>` : ''}
                ${item.primary_bias ? `<span class="badge badge-gold">bias: ${item.primary_bias}</span>` : ''}
                <span class="text-muted" style="font-size:12px;">${item.setup_count} setup${item.setup_count !== 1 ? 's' : ''}</span>
              </div>
            </div>
            <div class="text-end">
              ${item.chart_price ? `<p class="mono tnum gold">${item.chart_price.toFixed(2)}</p>` : ''}
              <p class="text-muted" style="font-size:11px;">${this._fmtDate(item.created_at)}</p>
            </div>
          </div>
        </div>
      `).join('');

      // Click handler
      listEl.querySelectorAll('[data-id]').forEach(el => {
        el.addEventListener('click', () => this._showDetails(el.dataset.id));
      });
    },

    _renderPagination() {
      const pgEl = document.getElementById('pagination');
      if (!pgEl) return;
      const totalPages = Math.ceil(this.total / this.pageSize);
      if (totalPages <= 1) { pgEl.innerHTML = ''; return; }
      pgEl.innerHTML = `
        <button class="btn-ghost" ${this.page <= 1 ? 'disabled' : ''} data-page="${this.page - 1}">←</button>
        <span class="muted" style="padding:0 16px;font-size:14px;">صفحة ${this.page} / ${totalPages}</span>
        <button class="btn-ghost" ${this.page >= totalPages ? 'disabled' : ''} data-page="${this.page + 1}">→</button>
      `;
      pgEl.querySelectorAll('[data-page]').forEach(b => {
        if (b.disabled) return;
        b.addEventListener('click', () => this.load(parseInt(b.dataset.page)));
      });
    },

    async _showDetails(id) {
      const modal = document.getElementById('detail-modal');
      const body = document.getElementById('detail-body');
      if (!modal || !body) return;

      modal.hidden = false;
      body.innerHTML = '<div style="text-align:center;padding:40px;"><div class="spin"></div></div>';

      try {
        const a = await Api.get(`/analyses/${id}`);
        let html = Render.analysis(a.result_json || {});
        // ─── Feedback widget ───
        html += `
          <div class="card-elevated p-5 mt-5">
            <h4 class="display-font gold mb-3" style="font-size:16px;">💬 تقييمك للتحليل</h4>
            <div class="flex gap-3 flex-wrap items-center mb-3">
              <label class="muted" style="font-size:13px;">دقة التحليل:</label>
              <div data-rating="accuracy" class="flex gap-1">
                ${[1,2,3,4,5].map(n => `<span class="rating-star" data-val="${n}" style="cursor:pointer;font-size:22px;color:#666;">★</span>`).join('')}
              </div>
            </div>
            <div class="flex gap-3 flex-wrap items-center mb-3">
              <label class="muted" style="font-size:13px;">الفائدة:</label>
              <div data-rating="usefulness" class="flex gap-1">
                ${[1,2,3,4,5].map(n => `<span class="rating-star" data-val="${n}" style="cursor:pointer;font-size:22px;color:#666;">★</span>`).join('')}
              </div>
            </div>
            <div class="flex gap-3 flex-wrap mb-3" style="font-size:13px;">
              <label><input type="checkbox" data-fb="bias_correct"> الـ bias كان صحيح</label>
              <label><input type="checkbox" data-fb="levels_correct"> الـ levels كانت دقيقة</label>
              <label><input type="checkbox" data-fb="setup_followed"> دخلت الصفقة</label>
              <label><input type="checkbox" data-fb="setup_profitable"> الصفقة ربحت</label>
            </div>
            <textarea data-fb="comments" class="input" rows="2" placeholder="ملاحظاتك (اختياري)..." style="resize:vertical;width:100%;"></textarea>
            <button class="btn-gold mt-3" data-submit-feedback="${a.id}">💾 حفظ التقييم</button>
          </div>
          <div id="outcomes-section-${a.id}" class="card p-5 mt-3"></div>
          <div class="flex gap-2 justify-center mt-4 flex-wrap">
            <button class="btn-ghost" data-share="${a.id}">🔗 مشاركة</button>
            <button class="btn-ghost" data-pdf="${a.id}">📄 PDF</button>
            <button class="btn-ghost danger" data-delete="${a.id}">🗑 حذف</button>
          </div>`;
        body.innerHTML = html;

        // Wire copy buttons
        document.querySelectorAll('[data-copy-setup]').forEach(btn => {
          btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.copySetup);
            const setups = (a.result_json || {}).setups || [];
            if (!setups[idx]) return;
            navigator.clipboard.writeText(Render.copySetupText(setups[idx]))
              .then(() => Api.toast('✓ تم النسخ', 'success'));
          });
        });

        // Toolbar
        const shareBtn = body.querySelector(`[data-share="${a.id}"]`);
        const pdfBtn = body.querySelector(`[data-pdf="${a.id}"]`);
        const deleteBtn = body.querySelector(`[data-delete="${a.id}"]`);
        if (shareBtn) shareBtn.addEventListener('click', async () => {
          try {
            const link = await Api.post(`/analyses/${a.id}/share`, {});
            await navigator.clipboard.writeText(link.public_url);
            Api.toast('✓ تم نسخ الرابط', 'success');
          } catch (e) { Api.toast(e.message, 'error'); }
        });
        if (pdfBtn) pdfBtn.addEventListener('click', () => {
          window.open(`/api/v1/analyses/${a.id}/pdf`, '_blank');
        });
        if (deleteBtn) deleteBtn.addEventListener('click', async () => {
          if (!confirm('حذف هذا التحليل نهائياً؟')) return;
          try {
            await Api.del(`/analyses/${a.id}`);
            Api.toast('✓ تم الحذف', 'success');
            modal.hidden = true;
            this.load(this.page);
          } catch (e) { Api.toast(e.message, 'error'); }
        });

        // ─── Feedback widget logic ───
        const fbState = { accuracy_rating: null, usefulness_rating: null };
        body.querySelectorAll('[data-rating]').forEach(group => {
          const dim = group.dataset.rating;
          const stars = group.querySelectorAll('.rating-star');
          stars.forEach(star => {
            star.addEventListener('click', () => {
              const val = parseInt(star.dataset.val);
              fbState[dim === 'accuracy' ? 'accuracy_rating' : 'usefulness_rating'] = val;
              stars.forEach((s, i) => s.style.color = i < val ? 'var(--gold)' : '#666');
            });
          });
        });
        const submitBtn = body.querySelector(`[data-submit-feedback="${a.id}"]`);
        if (submitBtn) submitBtn.addEventListener('click', async () => {
          const payload = { ...fbState };
          body.querySelectorAll('[data-fb]').forEach(el => {
            const k = el.dataset.fb;
            if (el.type === 'checkbox') payload[k] = el.checked || null;
            else if (el.value) payload[k] = el.value;
          });
          submitBtn.disabled = true;
          try {
            await Api.post(`/training/feedback/${a.id}`, payload);
            Api.toast('✓ تم حفظ التقييم — شكراً!', 'success');
          } catch (e) { Api.toast(e.message, 'error'); }
          finally { submitBtn.disabled = false; }
        });

        // ─── Load outcomes ───
        try {
          const outcomes = await Api.get(`/training/outcomes/${a.id}`);
          const outEl = document.getElementById(`outcomes-section-${a.id}`);
          if (outEl) {
            if (!outcomes.length) {
              outEl.innerHTML = '<p class="muted text-center" style="font-size:13px;">لا توجد setups متتبَّعة لهذا التحليل.</p>';
            } else {
              outEl.innerHTML = `
                <h4 class="display-font gold mb-3" style="font-size:16px;">🎯 تتبّع الـ Setups</h4>
                <div style="display:grid;gap:8px;">
                ${outcomes.map(o => {
                  const statusColor = {
                    'tp_full': 'var(--green)', 'tp1_hit': 'var(--gold)', 'tp2_hit': 'var(--gold)',
                    'sl_hit': 'var(--red)', 'expired': '#666', 'pending': '#888', 'active': 'var(--gold)',
                  }[o.status] || '#888';
                  return `
                    <div class="flex justify-between items-center" style="padding:10px;background:var(--bg-elevated);border-radius:8px;">
                      <div>
                        <strong>${o.setup_label || 'Setup ' + (o.setup_index + 1)}</strong>
                        <span class="muted" style="font-size:12px;margin-inline-start:8px;">${o.direction.toUpperCase()} @ ${o.entry_price.toFixed(2)}</span>
                      </div>
                      <div class="flex items-center gap-2">
                        ${o.realized_rr != null ? `<span class="mono tnum">${o.realized_rr >= 0 ? '+' : ''}${o.realized_rr.toFixed(2)}R</span>` : ''}
                        <span class="badge" style="background:${statusColor};color:white;">${o.status}</span>
                      </div>
                    </div>`;
                }).join('')}
                </div>`;
            }
          }
        } catch (e) { /* outcomes endpoint may not exist if no tracking */ }
      } catch (e) {
        body.innerHTML = `<p class="error-msg">${e.message}</p>`;
      }
    },

    _wireUI() {
      const modal = document.getElementById('detail-modal');
      if (!modal) return;
      modal.querySelectorAll('[data-close-modal]').forEach(el => {
        el.addEventListener('click', () => { modal.hidden = true; });
      });
    },

    _fmtDate(iso) {
      try {
        const d = new Date(iso);
        return d.toLocaleString(I18n.lang === 'ar' ? 'ar-EG' : 'en-US', {
          year: 'numeric', month: 'short', day: 'numeric',
          hour: '2-digit', minute: '2-digit',
        });
      } catch { return iso; }
    },
  };

  window.History = History;

  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => History.init(), 200);  // Wait for Auth
  });
})();
