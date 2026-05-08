/* ═════════════════════════════════════════════════════════
   Training dashboard — outcomes, few-shot, classifier, backtest
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const Training = {
    async init() {
      if (!Auth.requireAuth()) return;
await this.loadStats();
      this._wireUI();
    },

    async loadStats() {
      try {
        const s = await Api.get('/training/stats');
        const el = document.getElementById('training-stats');
        if (!el) return;

        const wr = s.overall_win_rate != null ? (s.overall_win_rate * 100).toFixed(1) + '%' : '—';
        const avgRR = s.avg_realized_rr != null ? s.avg_realized_rr.toFixed(2) + 'R' : '—';
        const accRating = s.avg_accuracy_rating != null ? s.avg_accuracy_rating.toFixed(1) + '/5' : '—';
        const useRating = s.avg_usefulness_rating != null ? s.avg_usefulness_rating.toFixed(1) + '/5' : '—';

        el.innerHTML = `
          <div class="stat-tile"><p class="label">Outcomes</p>
            <p class="value">${s.total_outcomes}</p>
            <p class="sub">نشط: ${s.outcomes_active} · مغلق: ${s.outcomes_closed}</p></div>
          <div class="stat-tile"><p class="label">Win Rate</p>
            <p class="value">${wr}</p>
            <p class="sub">${s.wins || 0}W / ${s.losses || 0}L</p></div>
          <div class="stat-tile"><p class="label">Avg R:R</p>
            <p class="value">${avgRR}</p>
            <p class="sub">للصفقات المغلقة</p></div>
          <div class="stat-tile"><p class="label">Feedback</p>
            <p class="value">${s.feedback_count}</p>
            <p class="sub">دقة: ${accRating} · فائدة: ${useRating}</p></div>
          <div class="stat-tile"><p class="label">Few-shot</p>
            <p class="value">${s.few_shot_count_active}</p>
            <p class="sub">استُخدمت ${s.few_shot_total_uses} مرة</p></div>
          <div class="stat-tile"><p class="label">ML Classifier</p>
            <p class="value" style="font-size:18px;">${s.classifier_trained ? '✓ مفعّل' : '○ غير مدرّب'}</p>
            <p class="sub">${s.classifier_accuracy != null ? 'دقة: ' + (s.classifier_accuracy * 100).toFixed(1) + '%' : 'يحتاج بيانات'}</p></div>
        `;

        // Outcomes distribution
        const distEl = document.getElementById('outcomes-distribution');
        if (distEl && s.by_status) {
          const total = Object.values(s.by_status).reduce((a, b) => a + b, 0) || 1;
          distEl.innerHTML = Object.entries(s.by_status).map(([k, v]) => {
            const pct = (v / total * 100).toFixed(1);
            const color = k === 'tp_full' ? 'var(--green)' : k === 'sl_hit' ? 'var(--red)' : 'var(--gold)';
            return `
              <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
                <div style="width:120px;font-size:13px;">${k}</div>
                <div style="flex:1;height:24px;background:var(--bg-elevated);border-radius:4px;overflow:hidden;">
                  <div style="width:${pct}%;height:100%;background:${color};"></div>
                </div>
                <div class="mono" style="width:90px;text-align:end;font-size:13px;">${v} (${pct}%)</div>
              </div>`;
          }).join('');
        }
      } catch (e) {
        Api.toast('فشل تحميل الإحصائيات: ' + e.message, 'error');
      }
    },

    async loadFewShot() {
      try {
        const items = await Api.get('/training/few_shot?limit=100');
        const el = document.getElementById('fewshot-table');
        if (!el) return;
        if (!items.length) {
          el.innerHTML = '<div class="p-6 text-center muted">لا توجد أمثلة بعد. النظام بيرقي تلقائياً التحاليل الناجحة.</div>';
          return;
        }
        el.innerHTML = `
          <table class="data">
            <thead><tr>
              <th>Symbol/TF</th><th>Regime</th><th>R:R</th>
              <th>Score</th><th>الاستخدام</th><th>الحالة</th><th>تاريخ</th>
            </tr></thead>
            <tbody>
              ${items.map(i => `
                <tr>
                  <td class="mono">${i.symbol} · ${i.timeframe}</td>
                  <td>${i.market_regime || '—'}</td>
                  <td class="mono tnum">${i.realized_rr ? i.realized_rr.toFixed(2) : '—'}</td>
                  <td><span class="badge badge-gold">${i.quality_score.toFixed(1)}</span></td>
                  <td class="mono tnum">${i.use_count}</td>
                  <td>${i.is_active ? '<span class="badge badge-bullish">نشط</span>' : '<span class="badge badge-secondary">معطّل</span>'}</td>
                  <td class="muted" style="font-size:12px;">${new Date(i.created_at).toLocaleDateString('ar-EG')}</td>
                </tr>`).join('')}
            </tbody>
          </table>`;
      } catch (e) { Api.toast(e.message, 'error'); }
    },

    async loadClassifier() {
      try {
        const info = await Api.get('/training/classifier/info');
        const el = document.getElementById('classifier-info');
        if (!el) return;
        if (!info.trained) {
          el.innerHTML = `<p class="muted">⏳ النموذج لم يُدرَّب بعد. تحتاج 30+ outcome مغلق.</p>`;
          return;
        }
        const imp = info.importances || {};
        const sorted = Object.entries(imp).sort((a, b) => b[1] - a[1]).slice(0, 8);

        el.innerHTML = `
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;">
            <div class="price-tile"><p class="text-muted" style="font-size:11px;">عينات</p>
              <p class="mono tnum gold mt-1" style="font-size:18px;">${info.samples}</p></div>
            <div class="price-tile"><p class="text-muted" style="font-size:11px;">Train Acc</p>
              <p class="mono tnum gold mt-1" style="font-size:18px;">${(info.train_accuracy * 100).toFixed(1)}%</p></div>
            <div class="price-tile"><p class="text-muted" style="font-size:11px;">Test Acc</p>
              <p class="mono tnum gold mt-1" style="font-size:18px;">${(info.test_accuracy * 100).toFixed(1)}%</p></div>
            <div class="price-tile"><p class="text-muted" style="font-size:11px;">AUC</p>
              <p class="mono tnum gold mt-1" style="font-size:18px;">${info.test_auc ? info.test_auc.toFixed(3) : '—'}</p></div>
          </div>
          <h4 class="display-font gold mt-4 mb-2" style="font-size:16px;">أهم الـ Features</h4>
          ${sorted.map(([f, v]) => `
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;">
              <div style="width:140px;font-size:12px;font-family:monospace;">${f}</div>
              <div style="flex:1;height:14px;background:var(--bg-elevated);border-radius:4px;overflow:hidden;">
                <div style="width:${(v * 100).toFixed(1)}%;height:100%;background:var(--gold);"></div>
              </div>
              <div class="mono" style="width:60px;text-align:end;font-size:12px;">${(v * 100).toFixed(1)}%</div>
            </div>
          `).join('')}
          <p class="muted mt-3" style="font-size:11px;">آخر تدريب: ${info.trained_at || '—'}</p>
        `;
      } catch (e) { Api.toast(e.message, 'error'); }
    },

    async loadBacktests() {
      try {
        const items = await Api.get('/training/backtest?limit=20');
        const el = document.getElementById('backtest-table');
        if (!el) return;
        if (!items.length) {
          el.innerHTML = '<div class="p-6 text-center muted">لا توجد backtests بعد.</div>';
          return;
        }
        el.innerHTML = `
          <table class="data">
            <thead><tr>
              <th>الاسم</th><th>Symbol/TF</th><th>الحالة</th>
              <th>Setups</th><th>W/L</th><th>Win Rate</th>
              <th>Avg RR</th><th>تكلفة</th><th>تاريخ</th>
            </tr></thead>
            <tbody>
              ${items.map(b => `
                <tr>
                  <td>${b.name}</td>
                  <td class="mono">${b.symbol} · ${b.timeframe}</td>
                  <td><span class="badge ${b.status === 'completed' ? 'badge-bullish' : b.status === 'failed' ? 'badge-bearish' : 'badge-gold'}">${b.status}</span></td>
                  <td class="mono tnum">${b.total_setups_filled}/${b.total_setups_generated}</td>
                  <td class="mono tnum">${b.wins}/${b.losses}</td>
                  <td class="mono tnum">${b.win_rate != null ? (b.win_rate * 100).toFixed(1) + '%' : '—'}</td>
                  <td class="mono tnum">${b.avg_realized_rr != null ? b.avg_realized_rr.toFixed(2) + 'R' : '—'}</td>
                  <td class="mono tnum">$${(b.total_cost_usd || 0).toFixed(2)}</td>
                  <td class="muted" style="font-size:11px;">${new Date(b.started_at).toLocaleString('ar-EG')}</td>
                </tr>`).join('')}
            </tbody>
          </table>`;
      } catch (e) { Api.toast(e.message, 'error'); }
    },

    _wireUI() {
      // Tab switching
      document.querySelectorAll('[data-tab]').forEach(tab => {
        tab.addEventListener('click', () => {
          const target = tab.dataset.tab;
          document.querySelectorAll('[data-tab]').forEach(t => t.classList.toggle('active', t === tab));
          document.querySelectorAll('[data-tab-content]').forEach(c => {
            c.style.display = c.dataset.tabContent === target ? '' : 'none';
          });
          if (target === 'fewshot') this.loadFewShot();
          if (target === 'classifier') this.loadClassifier();
          if (target === 'backtest') this.loadBacktests();
        });
      });

      // Trigger outcomes manually
      const trigBtn = document.getElementById('trigger-outcomes');
      const trigOut = document.getElementById('outcomes-result');
      if (trigBtn) {
        trigBtn.addEventListener('click', async () => {
          trigBtn.disabled = true;
          trigOut.textContent = 'جاري الفحص...';
          try {
            const r = await Api.post('/training/outcomes/check_now', {});
            trigOut.textContent = `✓ فُحص ${r.checked || 0} · أُغلق ${r.closed || 0} · السعر: ${r.price?.toFixed(2) || '—'}`;
            Api.toast('✓ تم الفحص', 'success');
            this.loadStats();
          } catch (e) {
            trigOut.textContent = '❌ ' + e.message;
          } finally { trigBtn.disabled = false; }
        });
      }

      // Train classifier
      const trainBtn = document.getElementById('train-classifier-btn');
      const trainOut = document.getElementById('train-result');
      if (trainBtn) {
        trainBtn.addEventListener('click', async () => {
          trainBtn.disabled = true;
          trainOut.textContent = '⏳ جاري التدريب...';
          try {
            const r = await Api.post('/training/classifier/train', {});
            if (r.trained) {
              trainOut.innerHTML = `✓ تم التدريب: <strong>${r.samples} عينة</strong>, دقة الاختبار <strong>${(r.test_accuracy * 100).toFixed(1)}%</strong>`;
              Api.toast('✓ تم تدريب النموذج', 'success');
              this.loadClassifier();
            } else {
              trainOut.textContent = `⚠️ ${r.reason}`;
            }
          } catch (e) { trainOut.textContent = '❌ ' + e.message; }
          finally { trainBtn.disabled = false; }
        });
      }

      // Start backtest
      const btBtn = document.getElementById('bt-start-btn');
      if (btBtn) {
        btBtn.addEventListener('click', async () => {
          const start = document.getElementById('bt-start').value;
          const end = document.getElementById('bt-end').value;
          if (!start || !end) {
            Api.toast('اختر تاريخ البدء والانتهاء', 'error'); return;
          }
          btBtn.disabled = true;
          try {
            const r = await Api.post('/training/backtest/run', {
              name: document.getElementById('bt-name').value,
              symbol: document.getElementById('bt-symbol').value,
              timeframe: document.getElementById('bt-tf').value,
              start_date: new Date(start).toISOString(),
              end_date: new Date(end).toISOString(),
              sample_size: parseInt(document.getElementById('bt-samples').value),
            });
            Api.toast('🚀 بدأ الـ Backtest في الخلفية', 'success');
            setTimeout(() => this.loadBacktests(), 1000);
          } catch (e) { Api.toast(e.message, 'error'); }
          finally { btBtn.disabled = false; }
        });
      }

      // Exports
      const eqBtn = document.getElementById('export-quality');
      const etBtn = document.getElementById('export-training');
      const eOut = document.getElementById('export-result');
      const _doExport = async (path, label) => {
        eOut.textContent = '⏳ جاري...';
        try {
          const r = await Api.post(path, {});
          const fname = (r.output_path || '').split('/').pop();
          eOut.innerHTML = `✓ صُدّر <strong>${r.exported_count}</strong> سجل · <a href="/api/v1/training/dataset/download/${fname}" class="gold" download>تحميل ${fname}</a>`;
        } catch (e) { eOut.textContent = '❌ ' + e.message; }
      };
      if (eqBtn) eqBtn.addEventListener('click', () => _doExport('/training/dataset/export_quality', 'quality'));
      if (etBtn) etBtn.addEventListener('click', () => _doExport('/training/dataset/export_training', 'training'));
    },
  };

  window.Training = Training;

  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => Training.init(), 200);
  });
})();
