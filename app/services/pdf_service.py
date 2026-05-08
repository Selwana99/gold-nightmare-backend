"""PDF export — render an analysis as a printable PDF report."""

import logging
from datetime import datetime
from io import BytesIO
from typing import Optional

from app.models.analysis import Analysis

logger = logging.getLogger(__name__)


def _safe(v, default="—"):
    return str(v) if v is not None else default


def _generate_html_report(analysis: Analysis) -> str:
    """Build a self-contained HTML doc for PDF rendering."""
    r = analysis.result_json or {}
    meta = r.get("chart_meta", {})
    struct = r.get("structure_read", {})
    liq = r.get("liquidity", {})
    pd = r.get("premium_discount", {})
    setups = r.get("setups", [])
    bias = r.get("session_bias", {})
    warnings = r.get("warnings_ar", [])

    setups_html = ""
    for s in setups:
        tps_html = "".join(
            f"<li><strong>TP{i+1}:</strong> {tp.get('level','—')} ({tp.get('close_pct',0)}%)</li>"
            for i, tp in enumerate(s.get("take_profits", []))
        )
        setups_html += f"""
        <div class="setup">
          <h3>{_safe(s.get('label'))}</h3>
          <p><span class="badge">{_safe(s.get('direction','').upper())}</span>
             <span class="badge">{_safe(s.get('priority',''))}</span>
             <span class="rr">R:R {_safe(s.get('risk_reward'))}</span>
          </p>
          <p><strong>Trigger:</strong> {_safe(s.get('trigger_ar'))}</p>
          <table>
            <tr><td>Entry</td><td>{', '.join(str(e) for e in s.get('entries', []))}</td></tr>
            <tr><td>SL</td><td class="sl">{_safe(s.get('stop_loss'))}</td></tr>
          </table>
          <ul>{tps_html}</ul>
          <p><em>{_safe(s.get('rationale_ar'))}</em></p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>تحليل {analysis.symbol} {analysis.timeframe}</title>
<style>
  @page {{ size: A4; margin: 1.5cm; }}
  body {{ font-family: 'IBM Plex Sans Arabic','Tahoma',sans-serif; color: #111; line-height: 1.6; }}
  h1, h2, h3 {{ color: #8b6914; }}
  h1 {{ border-bottom: 2px solid #d4af37; padding-bottom: 8px; }}
  .header {{ display: flex; justify-content: space-between; }}
  .meta {{ color: #666; font-size: 11px; }}
  .badge {{ display: inline-block; background: #f3e5b3; color: #8b6914; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 4px; }}
  .rr {{ color: #d4af37; font-weight: bold; }}
  .setup {{ border: 1px solid #ddd; border-right: 4px solid #d4af37; padding: 12px; margin: 12px 0; border-radius: 6px; }}
  .sl {{ color: #c00; font-weight: bold; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
  td {{ padding: 4px 8px; border-bottom: 1px solid #eee; }}
  td:first-child {{ color: #666; width: 100px; }}
  .levels {{ display: flex; gap: 12px; }}
  .levels > div {{ flex: 1; padding: 8px; background: #f9f5e7; border-radius: 6px; text-align: center; }}
  .footer {{ position: fixed; bottom: 1cm; right: 1.5cm; left: 1.5cm; text-align: center; font-size: 10px; color: #999; border-top: 1px solid #d4af37; padding-top: 5px; }}
</style>
</head>
<body>
  <div class="header">
    <h1>⚡ Gold Nightmare Vision</h1>
    <span class="meta">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</span>
  </div>

  <h2>{_safe(meta.get('symbol'))} · {_safe(meta.get('timeframe'))}</h2>
  <p>السعر الحالي: <strong>{_safe(meta.get('current_price'))}</strong> ·
     الاتجاه: <strong>{_safe(meta.get('trend_direction'))}</strong></p>

  <h2>هيكل السوق</h2>
  <p>{_safe(struct.get('summary_ar'))}</p>
  <div class="levels">
    <div>Swing High<br><strong>{_safe(struct.get('key_swing_high'))}</strong></div>
    <div>Swing Low<br><strong>{_safe(struct.get('key_swing_low'))}</strong></div>
  </div>

  <h2>السيولة</h2>
  <p><strong>BSL:</strong> {', '.join(str(x) for x in liq.get('bsl', [])) or '—'}</p>
  <p><strong>SSL:</strong> {', '.join(str(x) for x in liq.get('ssl', [])) or '—'}</p>

  <h2>Premium / Discount</h2>
  <div class="levels">
    <div>High<br><strong>{_safe(pd.get('range_high'))}</strong></div>
    <div>Mid<br><strong>{_safe(pd.get('midpoint'))}</strong></div>
    <div>Low<br><strong>{_safe(pd.get('range_low'))}</strong></div>
  </div>
  <p>السعر في: <strong>{_safe(pd.get('current_zone','').upper())}</strong></p>

  <h2>الـ Setups</h2>
  {setups_html or '<p>لا توجد صفقات حالياً</p>'}

  <h2>Session Bias</h2>
  <p><strong>Asia:</strong> {_safe(bias.get('asia_ar'))}</p>
  <p><strong>London:</strong> {_safe(bias.get('london_ar'))}</p>
  <p><strong>NY:</strong> {_safe(bias.get('ny_ar'))}</p>

  {f'<h2>تحذيرات</h2><ul>{"".join(f"<li>{w}</li>" for w in warnings)}</ul>' if warnings else ''}

  <div class="footer">
    Gold Nightmare Vision · @Odai_xau · للأغراض التعليمية فقط
  </div>
</body>
</html>"""


def render_pdf(analysis: Analysis) -> bytes:
    """Render analysis as PDF bytes. Requires WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise RuntimeError(
            "WeasyPrint غير مثبت. ثبّته بـ: pip install weasyprint"
        ) from e

    html = _generate_html_report(analysis)
    pdf_bytes = HTML(string=html).write_pdf()
    return pdf_bytes
