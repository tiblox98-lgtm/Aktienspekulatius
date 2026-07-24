"""
Watchlist Checker fuer GitHub Actions
Prueft ISINs auf Zielkurs / Year-Low / Alltime-Low, verschickt bei Treffer eine E-Mail
und erzeugt einen HTML-Report MIT Charts (Chart.js), der ueber GitHub Pages angezeigt werden kann.
"""
import os, json, smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests

API_KEY = os.environ["TWELVEDATA_API_KEY"]
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
MAIL_TO   = os.environ["MAIL_TO"]

WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def resolve_isin(isin):
    r = requests.get("https://api.twelvedata.com/symbol_search",
                      params={"symbol": isin, "apikey": API_KEY}).json()
    if r.get("data"):
        best = r["data"][0]
        return best["symbol"], best["instrument_name"]
    return None, None

def get_quote(symbol):
    return requests.get("https://api.twelvedata.com/quote",
                         params={"symbol": symbol, "apikey": API_KEY}).json()

def get_history(symbol, outputsize=90, interval="1day"):
    r = requests.get("https://api.twelvedata.com/time_series",
                      params={"symbol": symbol, "interval": interval,
                              "outputsize": outputsize, "apikey": API_KEY}).json()
    vals = r.get("values", [])
    return [float(v["close"]) for v in reversed(vals)] if vals else []

def send_mail(subject, body_html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg.attach(MIMEText(body_html, "html"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, MAIL_TO, msg.as_string())

def main():
    watchlist = load_watchlist()
    triggered = []

    for item in watchlist:
        if not item.get("symbol"):
            symbol, name = resolve_isin(item["isin"])
            item["symbol"], item["name"] = symbol, name
        if not item.get("symbol"):
            continue

        q = get_quote(item["symbol"])
        price = float(q.get("close", 0) or 0)
        low52 = float(q.get("fifty_two_week", {}).get("low", 0) or 0)
        item["price"] = price
        item["low52"] = low52
        item["prev_close"] = float(q.get("previous_close", 0) or 0)

        hist = get_history(item["symbol"], outputsize=90, interval="1day")
        if hist:
            item["history"] = hist

        if item.get("alltime"):
            long_hist = get_history(item["symbol"], outputsize=5000, interval="1week")
            if long_hist:
                item["all_time_low"] = min(long_hist)

        hit_reasons = []
        if item.get("target") and price and price <= item["target"]:
            hit_reasons.append(f"Zielkurs {item['target']}")
        if item.get("yearlow") and low52 and price <= low52 * 1.01:
            hit_reasons.append(f"Year-Low {low52:.2f}")
        if item.get("alltime") and item.get("all_time_low") and price <= item["all_time_low"] * 1.01:
            hit_reasons.append(f"Alltime-Low {item['all_time_low']:.2f}")

        item["hit"] = bool(hit_reasons)
        item["hit_reasons"] = hit_reasons

        already_notified = item.get("notified", False)
        if hit_reasons and not already_notified:
            triggered.append((item, hit_reasons))
            item["notified"] = True
        elif not hit_reasons:
            item["notified"] = False

    save_watchlist(watchlist)

    if triggered:
        rows = "".join(
            f"<tr><td>{it.get('name') or it['isin']}</td><td>{it['isin']}</td>"
            f"<td>{it['price']:.2f}</td><td>{', '.join(reasons)}</td></tr>"
            for it, reasons in triggered
        )
        body = f"""
        <h2>Watchlist Alarm ausgeloest</h2>
        <table border="1" cellpadding="6" style="border-collapse:collapse;font-family:Arial">
        <tr><th>Name</th><th>ISIN</th><th>Kurs</th><th>Grund</th></tr>
        {rows}
        </table>
        """
        send_mail(f"Watchlist Alarm: {len(triggered)} Position(en) erreicht", body)
        print(f"Mail versendet fuer {len(triggered)} Treffer.")
    else:
        print("Keine neuen Alarme.")

    build_html_report(watchlist)

def build_html_report(watchlist):
    cards = ""
    for i, it in enumerate(watchlist):
        hit = it.get("hit", False)
        change = None
        if it.get("price") and it.get("prev_close"):
            change = (it["price"] - it["prev_close"]) / it["prev_close"] * 100
        change_html = ""
        if change is not None:
            color = "#22c55e" if change > 0 else "#ef4444" if change < 0 else "#94a3b8"
            change_html = f'<span style="color:{color};font-size:12px;margin-left:6px;">{change:+.2f}%</span>'

        legend = []
        if it.get("target") is not None:
            legend.append(f'<span style="color:#facc15">● Ziel {it["target"]}</span>')
        if it.get("yearlow"):
            legend.append(f'<span style="color:#ef4444">● Year-Low {it.get("low52","-")}</span>')
        if it.get("alltime"):
            legend.append(f'<span style="color:#a78bfa">● Alltime-Low {it.get("all_time_low","-")}</span>')
        legend_html = " &nbsp; ".join(legend)

        reasons_html = ""
        if hit:
            reasons_html = f'<div style="color:#22c55e;font-weight:bold;margin-top:6px;">✅ Alarm: {", ".join(it.get("hit_reasons",[]))}</div>'

        border = "border:2px solid #22c55e;box-shadow:0 0 12px rgba(34,197,94,.4);" if hit else "border:1px solid #334155;"

        cards += f"""
        <div style="background:#1e293b;border-radius:10px;padding:14px;{border}">
          <h3 style="margin:0 0 2px;font-size:16px;">{it.get('name') or it.get('symbol') or it['isin']}</h3>
          <div style="font-size:11px;color:#94a3b8;">{it['isin']} &middot; {it.get('symbol','-')}</div>
          <div style="font-size:22px;font-weight:700;margin-top:4px;">{it.get('price','-')}{change_html}</div>
          <div style="font-size:11px;color:#94a3b8;margin-top:4px;">{legend_html}</div>
          {reasons_html}
          <canvas id="chart-{i}" style="margin-top:8px;max-height:140px;"></canvas>
        </div>
        """

    chart_scripts = ""
    for i, it in enumerate(watchlist):
        hist = it.get("history", [])
        if not hist:
            continue
        n = len(hist)
        datasets = [f"{{label:'Kurs',data:{hist},borderColor:'#38bdf8',borderWidth:1.5,pointRadius:0,fill:false}}"]
        if it.get("target") is not None:
            datasets.append(f"{{label:'Ziel',data:Array({n}).fill({it['target']}),borderColor:'#facc15',borderWidth:1,borderDash:[5,4],pointRadius:0}}")
        if it.get("yearlow") and it.get("low52"):
            datasets.append(f"{{label:'Year-Low',data:Array({n}).fill({it['low52']}),borderColor:'#ef4444',borderWidth:1,borderDash:[5,4],pointRadius:0}}")
        if it.get("alltime") and it.get("all_time_low"):
            datasets.append(f"{{label:'Alltime-Low',data:Array({n}).fill({it['all_time_low']}),borderColor:'#a78bfa',borderWidth:1,borderDash:[2,3],pointRadius:0}}")
        chart_scripts += f"""
        new Chart(document.getElementById('chart-{i}').getContext('2d'), {{
          type:'line',
          data:{{labels:Array({n}).fill(''), datasets:[{','.join(datasets)}]}},
          options:{{plugins:{{legend:{{display:false}}}}, scales:{{x:{{display:false}}, y:{{display:true,ticks:{{color:'#94a3b8',font:{{size:9}}}}}}}}}}
        }});
        """

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="900">
<title>Watchlist Uebersicht</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px;margin:0;}}
  h1{{font-size:22px;margin-bottom:4px;}}
  .sub{{color:#94a3b8;font-size:13px;margin-bottom:20px;}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;}}
</style>
</head>
<body>
<h1>📈 Watchlist Uebersicht</h1>
<div class="sub">Automatisch aktualisiert durch GitHub Actions &middot; Kursdaten via Twelve Data (ca. 15 Min. verzoegert)</div>
<div class="grid">
{cards}
</div>
<script>
{chart_scripts}
</script>
</body>
</html>"""
    with open("uebersicht.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    main()

