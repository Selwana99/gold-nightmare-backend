/* ═════════════════════════════════════════════════════════
   Render — produces HTML from analysis result data
   Shared between the analyzer page and the share/history pages
═════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const Render = {
    fmt(n) {
      if (n == null || isNaN(n)) return '—';
      return Number(n).toFixed(2);
    },
    esc(s) {
      if (s == null) return '';
      return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
    biasLabel(d) {
      return ({ bullish: 'صعودي ▲', bearish: 'هبوطي ▼', ranging: 'عرضي ◇', neutral: 'محايد ◇' }[d]) || '—';
    },
    biasClass(d) {
      return ({ bullish: 'badge-bullish', bearish: 'badge-bearish', ranging: 'badge-neutral', neutral: 'badge-neutral' }[d]) || 'badge-neutral';
    },
    zoneLabel(z) {
      return ({ premium: 'PREMIUM · للبيع', discount: 'DISCOUNT · للشراء', equilibrium: 'EQUILIBRIUM · توازن' }[z]) || z;
    },
    zoneBadge(z) {
      return ({ premium: 'badge-bearish', discount: 'badge-bullish', equilibrium: 'badge-gold' }[z]) || 'badge-neutral';
    },

    analysis(d, options = {}) {
      const meta = d.chart_meta || {};
      const struct = d.structure_read || {};
      const liq = d.liquidity || { bsl: [], ssl: [], swept_recently_ar: [] };
      const obs = d.order_blocks || [];
      const fvgs = d.fvg || [];
      const pd = d.premium_discount || {};
      const bias = d.session_bias || {};
      const setups = d.setups || [];
      const warnings = d.warnings_ar || [];

      let html = '';

      // ── Header card ──
      html += `
        <div class="card-elevated gold-border p-6 reveal">
          <div class="flex justify-between items-start gap-3 flex-wrap">
            <div>
              <p class="mono text-muted" style="font-size:11px;letter-spacing:0.1em;">SYMBOL · TIMEFRAME</p>
              <h2 class="display-font" style="font-size:28px;margin-top:4px;">${this.esc(meta.symbol || '?')} <span class="gold">·</span> <span class="mono" style="font-size:22px;">${this.esc(meta.timeframe || '?')}</span></h2>
            </div>
            <div class="text-end">
              <p class="mono text-muted" style="font-size:11px;letter-spacing:0.1em;">CURRENT PRICE</p>
              <p class="display-font mono tnum text-gradient-gold" style="font-size:32px;margin-top:4px;">${this.fmt(meta.current_price)}</p>
            </div>
          </div>
          <div class="mt-4 flex items-center gap-3 flex-wrap">
            <span class="badge ${this.biasClass(meta.trend_direction)}">${this.biasLabel(meta.trend_direction)}</span>
            ${meta.last_candle ? `<span class="mono text-muted" style="font-size:11px;">
              O ${this.fmt(meta.last_candle.open)} · H ${this.fmt(meta.last_candle.high)} · L ${this.fmt(meta.last_candle.low)} · C ${this.fmt(meta.last_candle.close)}
            </span>` : ''}
          </div>
          ${struct.summary_ar ? `<p class="mt-5" style="line-height:1.7;">${this.esc(struct.summary_ar)}</p>` : ''}
          ${d.mtf_alignment_ar ? `<div class="mt-4 p-3" style="background:var(--gold-glow);border-radius:var(--r-md);"><p class="gold" style="font-size:12px;margin-bottom:4px;font-weight:700;">⚡ MTF ALIGNMENT</p><p style="font-size:14px;">${this.esc(d.mtf_alignment_ar)}</p></div>` : ''}
        </div>`;

      // ── Structure ──
      if (struct.key_swing_high || struct.key_swing_low) {
        html += `
          <div class="card p-6 reveal">
            <h3 class="display-font gold mb-4" style="font-size:22px;">هيكل السوق</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
              <div class="price-tile">
                <p class="text-muted" style="font-size:11px;">SWING HIGH</p>
                <p class="mono tnum" style="font-size:20px;color:var(--red);margin-top:4px;">${this.fmt(struct.key_swing_high)}</p>
              </div>
              <div class="price-tile">
                <p class="text-muted" style="font-size:11px;">SWING LOW</p>
                <p class="mono tnum" style="font-size:20px;color:var(--green);margin-top:4px;">${this.fmt(struct.key_swing_low)}</p>
              </div>
            </div>
            ${struct.displacement_note_ar ? `<p class="muted" style="font-size:14px;">${this.esc(struct.displacement_note_ar)}</p>` : ''}
          </div>`;
      }

      // ── Liquidity ──
      html += `
        <div class="card p-6 reveal">
          <h3 class="display-font gold mb-4" style="font-size:22px;">السيولة · Liquidity</h3>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
            <div>
              <p class="text-muted mb-2" style="font-size:11px;letter-spacing:0.1em;">▲ BSL · فوق السعر</p>
              ${(liq.bsl || []).length ? liq.bsl.map(l => `
                <div class="liquidity-pill liquidity-bsl">
                  <span>↑</span><span class="tnum">${this.fmt(l)}</span>
                </div>`).join('') : '<p class="text-muted" style="font-size:13px;">—</p>'}
            </div>
            <div>
              <p class="text-muted mb-2" style="font-size:11px;letter-spacing:0.1em;">▼ SSL · تحت السعر</p>
              ${(liq.ssl || []).length ? liq.ssl.map(l => `
                <div class="liquidity-pill liquidity-ssl">
                  <span>↓</span><span class="tnum">${this.fmt(l)}</span>
                </div>`).join('') : '<p class="text-muted" style="font-size:13px;">—</p>'}
            </div>
          </div>
          ${(liq.swept_recently_ar || []).length ? `
            <div class="mt-4 p-3" style="background:var(--gold-glow);border:1px solid rgba(212,175,55,0.3);border-radius:var(--r-md);">
              <p class="gold mb-2" style="font-size:11px;font-weight:700;">⚡ تم السحب مؤخراً</p>
              ${liq.swept_recently_ar.map(s => `<p style="font-size:13px;margin-top:4px;">• ${this.esc(s)}</p>`).join('')}
            </div>` : ''}
        </div>`;

      // ── OB & FVG ──
      if (obs.length || fvgs.length) {
        html += `<div style="display:grid;grid-template-columns:1fr;gap:20px;" class="reveal">`;
        if (obs.length) {
          html += `<div class="card p-6">
            <h3 class="display-font gold mb-4" style="font-size:22px;">Order Blocks</h3>`;
          obs.forEach(ob => {
            html += `
              <div class="price-tile mb-2">
                <div class="flex justify-between items-center">
                  <span class="badge badge-${ob.type === 'bullish' ? 'bullish' : 'bearish'}">${this.esc(ob.type)} OB${ob.tf_origin ? ' · ' + this.esc(ob.tf_origin) : ''}</span>
                  <span class="mono tnum" style="font-size:13px;">${this.fmt(ob.low)} – ${this.fmt(ob.high)}</span>
                </div>
                ${ob.note_ar ? `<p class="muted mt-2" style="font-size:12px;">${this.esc(ob.note_ar)}</p>` : ''}
              </div>`;
          });
          html += `</div>`;
        }
        if (fvgs.length) {
          html += `<div class="card p-6">
            <h3 class="display-font gold mb-4" style="font-size:22px;">Fair Value Gaps</h3>`;
          fvgs.forEach(f => {
            html += `
              <div class="price-tile mb-2">
                <div class="flex justify-between items-center">
                  <span class="badge badge-${f.type === 'bullish' ? 'bullish' : 'bearish'}">${this.esc(f.type)} FVG${f.tf_origin ? ' · ' + this.esc(f.tf_origin) : ''}</span>
                  <span class="mono tnum" style="font-size:13px;">${this.fmt(f.low)} – ${this.fmt(f.high)}</span>
                </div>
                ${f.note_ar ? `<p class="muted mt-2" style="font-size:12px;">${this.esc(f.note_ar)}</p>` : ''}
              </div>`;
          });
          html += `</div>`;
        }
        html += `</div>`;
      }

      // ── Premium / Discount ──
      if (pd.midpoint != null) {
        html += `
          <div class="card p-6 reveal">
            <h3 class="display-font gold mb-4" style="font-size:22px;">Premium · Discount</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">
              <div class="price-tile text-center">
                <p class="text-muted" style="font-size:11px;">RANGE HIGH</p>
                <p class="mono tnum mt-2" style="color:var(--red);font-size:18px;">${this.fmt(pd.range_high)}</p>
              </div>
              <div class="price-tile text-center" style="border-color:var(--gold);background:var(--gold-glow);">
                <p class="gold" style="font-size:11px;">EQUILIBRIUM</p>
                <p class="mono tnum gold mt-2" style="font-size:18px;">${this.fmt(pd.midpoint)}</p>
              </div>
              <div class="price-tile text-center">
                <p class="text-muted" style="font-size:11px;">RANGE LOW</p>
                <p class="mono tnum mt-2" style="color:var(--green);font-size:18px;">${this.fmt(pd.range_low)}</p>
              </div>
            </div>
            <p class="text-center mt-4" style="font-size:14px;">
              السعر في:
              <span class="badge ${this.zoneBadge(pd.current_zone)}">${this.zoneLabel(pd.current_zone)}</span>
            </p>
          </div>`;
      }

      // ── Setups ──
      if (setups.length) {
        html += `<div class="reveal">
          <h3 class="display-font gold text-center mb-4" style="font-size:28px;">⚜ صفقات اليوم ⚜</h3>
          <div style="display:flex;flex-direction:column;gap:16px;">`;
        setups.forEach((s, idx) => { html += this.setup(s, idx); });
        html += `</div></div>`;
      }

      // ── Session bias ──
      if (bias.asia_ar || bias.london_ar || bias.ny_ar) {
        html += `
          <div class="card p-6 reveal">
            <h3 class="display-font gold mb-4" style="font-size:22px;">Session Bias</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;">
              ${bias.asia_ar ? `<div class="price-tile"><p class="gold mb-2" style="font-size:11px;font-weight:700;">🌏 ASIA</p><p style="font-size:13px;">${this.esc(bias.asia_ar)}</p></div>` : ''}
              ${bias.london_ar ? `<div class="price-tile"><p class="gold mb-2" style="font-size:11px;font-weight:700;">🇬🇧 LONDON</p><p style="font-size:13px;">${this.esc(bias.london_ar)}</p></div>` : ''}
              ${bias.ny_ar ? `<div class="price-tile"><p class="gold mb-2" style="font-size:11px;font-weight:700;">🗽 NEW YORK</p><p style="font-size:13px;">${this.esc(bias.ny_ar)}</p></div>` : ''}
            </div>
            <div class="mt-4 text-center">
              <span class="text-muted" style="font-size:12px;">Primary Bias:</span>
              <span class="badge ${this.biasClass(bias.primary_bias)}">${this.biasLabel(bias.primary_bias)}</span>
            </div>
          </div>`;
      }

      // ── Decision tree ──
      if (d.decision_tree_ar) {
        html += `
          <div class="card p-6 reveal">
            <h3 class="display-font gold mb-4" style="font-size:22px;">شجرة القرار</h3>
            <pre style="white-space:pre-wrap;font-family:'IBM Plex Sans Arabic',sans-serif;line-height:1.7;margin:0;">${this.esc(d.decision_tree_ar)}</pre>
          </div>`;
      }

      // ── Warnings ──
      if (warnings.length) {
        html += `
          <div class="card p-6 reveal" style="border-color:rgba(229,72,72,0.4);">
            <h3 class="display-font mb-3" style="color:var(--red);font-size:22px;">⚠ تحذيرات</h3>
            <ul style="list-style:none;padding:0;">
              ${warnings.map(w => `<li style="font-size:13px;display:flex;gap:8px;margin-bottom:8px;"><span style="color:var(--red);">•</span><span>${this.esc(w)}</span></li>`).join('')}
            </ul>
          </div>`;
      }

      return html;
    },

    setup(s, idx) {
      const cls = s.direction === 'sell' ? 'sell' : 'buy';
      const dirColor = s.direction === 'sell' ? 'var(--red)' : 'var(--green)';
      const priorityClass = `badge-${s.priority || 'secondary'}`;
      const tps = s.take_profits || [];

      return `
        <div class="setup-card ${cls}">
          <div class="flex justify-between items-start gap-3 flex-wrap mb-4">
            <div>
              <h4 class="display-font" style="font-size:22px;color:${dirColor};">${this.esc(s.label)}</h4>
              <div class="flex items-center gap-2 mt-2 flex-wrap">
                <span class="badge ${priorityClass}">${this.esc(s.priority || '')}</span>
                ${s.ml_quality_score != null ? `<span class="badge badge-gold" style="margin-inline-start:6px;font-size:11px;" title="ML Pattern Classifier · احتمالية نجاح الـ setup حسب نموذج XGBoost المُدرَّب على outcomes تاريخية">🤖 ${(s.ml_quality_score * 100).toFixed(0)}%</span>` : ''}
                <span class="badge badge-neutral">${this.esc(s.order_type || '')}</span>
              </div>
            </div>
            <div class="text-end">
              <p class="text-muted" style="font-size:11px;">RISK : REWARD</p>
              <p class="display-font gold mt-1" style="font-size:18px;">${this.esc(s.risk_reward || '—')}</p>
            </div>
          </div>

          ${s.trigger_ar ? `
            <div class="p-3 mb-4" style="background:var(--gold-glow);border-right:3px solid var(--gold);border-radius:var(--r-md);">
              <p class="gold mb-1" style="font-size:11px;letter-spacing:0.1em;font-weight:700;">⚡ TRIGGER</p>
              <p style="font-size:14px;">${this.esc(s.trigger_ar)}</p>
            </div>` : ''}

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
            <div class="price-tile">
              <p class="text-muted" style="font-size:11px;">ENTRY</p>
              ${(s.entries || []).map(e => `<p class="mono tnum mt-1" style="font-size:18px;">${this.fmt(e)}</p>`).join('')}
              ${(s.entries || []).length > 1 ? `<p class="text-muted mt-1" style="font-size:11px;">avg: ${this.fmt(s.avg_entry)}</p>` : ''}
            </div>
            <div class="price-tile" style="border-color:var(--red-border);background:var(--red-soft);">
              <p class="text-muted" style="font-size:11px;">STOP LOSS</p>
              <p class="mono tnum mt-1" style="font-size:18px;color:var(--red);">${this.fmt(s.stop_loss)}</p>
            </div>
          </div>

          <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px;">
            <p class="text-muted" style="font-size:11px;letter-spacing:0.1em;">TAKE PROFITS</p>
            ${tps.map((tp, i) => `
              <div class="price-target">
                <span class="badge badge-gold" style="min-width:40px;justify-content:center;">TP${i + 1}</span>
                <span class="tnum" style="font-weight:700;flex:1;">${this.fmt(tp.level)}</span>
                <span class="text-muted" style="font-size:12px;">إغلاق ${tp.close_pct}%</span>
                ${tp.label_ar ? `<span class="muted" style="font-size:12px;">· ${this.esc(tp.label_ar)}</span>` : ''}
              </div>`).join('')}
          </div>

          ${s.rationale_ar ? `
            <details>
              <summary class="gold" style="font-weight:600;font-size:14px;">السبب والمنطق</summary>
              <p class="mt-2" style="line-height:1.7;font-size:14px;">${this.esc(s.rationale_ar)}</p>
            </details>` : ''}

          ${s.invalidation_ar ? `
            <details class="mt-2">
              <summary style="color:var(--red);font-weight:600;font-size:14px;">⛔ متى تلغى الفكرة</summary>
              <p class="mt-2" style="line-height:1.7;font-size:14px;">${this.esc(s.invalidation_ar)}</p>
            </details>` : ''}

          <button data-copy-setup="${idx}" class="btn-ghost mt-4" style="border-color:var(--gold);color:var(--gold);">📋 نسخ</button>
        </div>`;
    },

    copySetupText(s) {
      const tps = (s.take_profits || []).map((tp, i) =>
        `TP${i + 1}: ${this.fmt(tp.level)} (close ${tp.close_pct}%)`).join('\n');
      return `🎯 ${s.label}
─────────────────────
Direction: ${s.direction.toUpperCase()}
Order: ${s.order_type}
Priority: ${s.priority}

Entry: ${(s.entries || []).map(e => this.fmt(e)).join(', ')}${s.entries.length > 1 ? ` (avg ${this.fmt(s.avg_entry)})` : ''}
SL:    ${this.fmt(s.stop_loss)}
${tps}

R:R: ${s.risk_reward}

Trigger: ${s.trigger_ar || ''}

⚡ Gold Nightmare Vision`;
    },
  };

  window.Render = Render;
})();
