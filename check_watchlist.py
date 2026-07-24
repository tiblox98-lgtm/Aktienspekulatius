"""
Watchlist Checker fuer GitHub Actions
Prueft ISINs auf Zielkurs / Year-Low / Alltime-Low und verschickt bei Treffer eine E-Mail.
Erzeugt zusaetzlich einen HTML-Report (uebersicht.html), der bei jedem Lauf aktualisiert
und ins Repo zurueckgeschrieben wird (GitHub Pages kann diesen dann anzeigen).
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

        if item.get("alltime"):
            hist = get_history(item["symbol"], outputsize=5000, interval="1week")
            if hist:
                item["all_time_low"] = min(hist)

        hit_reasons = []
        if item.get("target") and price and price <= item["target"]:
            hit_reasons.append(f"Zielkurs {item['target']}")
        if item.get("yearlow") and low52 and price <= low52 * 1.01:
            hit_reasons.append(f"Year-Low {low52:.2f}")
        if item.get("alltime") and item.get("all_time_low") and price <= item["all_time_low"] * 1.01:
            hit_reasons.append(f"Alltime-Low {item['all_time_low']:.2f}")

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
        send_mail(f"🎯 Watchlist Alarm: {len(triggered)} Position(en) erreicht", body)
        print(f"Mail versendet fuer {len(triggered)} Treffer.")
    else:
        print("Keine neuen Alarme.")

    build_html_report(watchlist)

def build_html_report(watchlist):
    rows = ""
    for it in watchlist:
        hit = it.get("notified", False)
        rows += f"""<tr style="background:{'#d1fae5' if hit else '#fff'}">
          <td>{it.get('name') or it['isin']}</td><td>{it['isin']}</td>
          <td>{it.get('price','-')}</td><td>{it.get('target','-')}</td>
          <td>{it.get('low52','-')}</td><td>{it.get('all_time_low','-')}</td>
          <td>{'✅' if hit else ''}</td></tr>"""
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <title>Watchlist Uebersicht</title>
    <style>body{{font-family:Arial;background:#0f172a;color:#e2e8f0;padding:20px}}
    table{{border-collapse:collapse;width:100%}} td,th{{padding:8px;border:1px solid #334155}}
    th{{background:#1e293b}}</style></head><body>
    <h1>📈 Watchlist Uebersicht (automatisch aktualisiert)</h1>
    <table><tr><th>Name</th><th>ISIN</th><th>Kurs</th><th>Ziel</th><th>52W Low</th><th>Alltime Low</th><th>Alarm</th></tr>
    {rows}</table></body></html>"""
    with open("uebersicht.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    main()
