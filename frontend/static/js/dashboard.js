/* ═════════════════════════════════════════════════════════
   Dashboard — owner overview stats
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const Dashboard = {
    async init() {
      if (!await Auth.requireAuth()) return;
      try {
        const stats = await Api.get('/dashboard/stats');
        this._render(stats);
      } catch (e) { Api.toast(e.message, 'error'); }
    },

    _render(s) {
      const el = document.getElementById('dashboard-stats');
      if (!el) return;
      const lastDate = s.last_analysis_at ? new Date(s.last_analysis_at).toLocaleDateString('ar-EG') : '—';

      el.innerHTML = `
        <div class="stat-grid">
          <div class="stat-tile"><p class="label">إجمالي التحاليل</p>
            <p class="value">${s.total_analyses}</p>
            <p class="sub">منذ البداية</p></div>
          <div class="stat-tile"><p class="label">التكلفة الإجمالية</p>
            <p class="value">$${s.total_cost_usd.toFixed(2)}</p>
            <p class="sub">USD</p></div>
          <div class="stat-tile"><p class="label">هذا الشهر</p>
            <p class="value">${s.analyses_this_month}</p>
            <p class="sub">$${s.cost_this_month.toFixed(2)}</p></div>
          <div class="stat-tile"><p class="label">آخر تحليل</p>
            <p class="value" style="font-size:18px;">${lastDate}</p>
            <p class="sub">&nbsp;</p></div>
        </div>

        <div class="card p-5 mt-4">
          <h3 class="display-font gold mb-3" style="font-size:18px;">📊 توزيع الـ Timeframes</h3>
          ${this._renderDist(s.by_timeframe)}
        </div>

        <div class="card p-5 mt-3">
          <h3 class="display-font gold mb-3" style="font-size:18px;">📈 توزيع الـ Bias</h3>
          ${this._renderDist(s.by_bias, {
            'bullish': 'var(--green)',
            'bearish': 'var(--red)',
            'neutral': 'var(--gold)',
          })}
        </div>
      `;
    },

    _renderDist(map, colors = {}) {
      const total = Object.values(map).reduce((a, b) => a + b, 0) || 1;
      if (total === 0) return '<p class="muted">لا توجد بيانات بعد</p>';
      return Object.entries(map).map(([k, v]) => {
        const pct = (v / total * 100).toFixed(1);
        const color = colors[k] || 'var(--gold)';
        return `
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
            <div style="width:120px;font-size:13px;">${k}</div>
            <div style="flex:1;height:20px;background:var(--bg-elevated);border-radius:4px;overflow:hidden;">
              <div style="width:${pct}%;height:100%;background:${color};"></div>
            </div>
            <div class="mono" style="width:80px;text-align:end;font-size:12px;">${v} (${pct}%)</div>
          </div>`;
      }).join('');
    },
  };

  window.Dashboard = Dashboard;
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => Dashboard.init(), 200);
  });
})();
