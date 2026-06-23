import requests, math, datetime, pathlib, json

# Predchozi obchodni den (x-1, vcera, o vikendu posledni patek)
target = datetime.date.today() - datetime.timedelta(days=1)
while target.weekday() >= 5:
    target -= datetime.timedelta(days=1)

target_str = target.strftime("%d.%m.%Y")
target_yf  = target.strftime("%Y-%m-%d")

print(f"Stahuji data za: {target_str}")

# --- Kurz EUR/CZK z CNB ---
eur_rate = None
cnb_date = ""
try:
    url  = f"https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt?date={target_str}"
    resp = requests.get(url, timeout=15, headers={"User-Agent": "dashboard/1.0"})
    lines = resp.text.splitlines()
    cnb_date = lines[0].split()[0].strip()
    for line in lines:
        if line.lower().startswith("emu|euro|"):
            parts    = line.split("|")
            rate_val = float(parts[4].strip().replace(",", "."))
            amount   = float(parts[2].strip())
            eur_rate = round(rate_val / amount, 4)
            print(f"  EUR/CZK = {eur_rate} (k {cnb_date})")
            break
except Exception as e:
    print(f"  CHYBA CNB: {e}")

data_date = cnb_date if cnb_date else target_str

# --- Ceny akcii z Yahoo Finance ---
def get_stock(ticker, target_yf):
    for base in ["query1", "query2"]:
        try:
            url  = f"https://{base}.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d"
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            data = resp.json()
            result     = data["chart"]["result"][0]
            closes     = result["indicators"]["quote"][0]["close"]
            timestamps = result["timestamp"]
            currency   = result["meta"]["currency"]
            for i, ts in enumerate(timestamps):
                dt = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                if dt == target_yf and closes[i]:
                    return round(closes[i], 2), currency
            for i in range(len(timestamps)-1, -1, -1):
                if closes[i]:
                    return round(closes[i], 2), currency
        except:
            pass
    return None, None

stocks = [
    ("MONET.PR", "Moneta Money Bank", "Praha (PSE)"),
]

def get_tmr():
    try:
        today = datetime.date.today().strftime("%Y-%m-%d")
        url   = f"https://www.bsse.sk/BCPB_WEB_API/api/Security/GetOne?find=%23KEY%3DA%7C%5E%7C2147%23&tradesummday={today}&daysinterval=7&lang=SK"
        resp  = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.bsse.sk/bcpb/detail-cp/?isin=%23KEY%3DA%7C%5E%7C2147%23"
        })
        data  = json.loads(json.loads(resp.text))
        rows  = data["Tables"][0]["Rows"]
        if not rows:
            return None, None
        row   = rows[-1]   # posledni (nejnovejsi) obchod
        price = round(float(row["Cells"][1].replace(",", ".")), 2)
        return price, row["Cells"][2]
    except Exception as e:
        print(f"  CHYBA TMR: {e}")
        return None, None

rows = []
for ticker, label, exchange in stocks:
    price, currency = get_stock(ticker, target_yf)
    if price:
        price_fmt = f"{price:.2f}".replace(".", ",")
        print(f"  {label}: {price_fmt} {currency}")
        rows.append((label, ticker, exchange, price_fmt, currency))
    else:
        rows.append((label, ticker, exchange, "Nedostupne", ""))

tmr_price, tmr_currency = get_tmr()
if tmr_price:
    tmr_fmt = f"{tmr_price:.2f}".replace(".", ",")
    print(f"  TMR: {tmr_fmt} {tmr_currency}")
    rows.append(("Tatry Mountain Resorts", "TMR", "Bratislava (BCPB)", tmr_fmt, tmr_currency))
else:
    rows.append(("Tatry Mountain Resorts", "TMR", "Bratislava (BCPB)", "Nedostupne", ""))

alw_price, alw_currency = get_stock("ALWN.AT", target_yf)
if alw_price:
    alw_fmt = f"{alw_price:.2f}".replace(".", ",")
    print(f"  Allwyn: {alw_fmt} {alw_currency}")
    rows.append(("Allwyn", "ALWN.AT", "Ateny (Euronext)", alw_fmt, alw_currency))
else:
    rows.append(("Allwyn", "ALWN.AT", "Ateny (Euronext)", "Nedostupne", ""))

eur_fmt = f"{eur_rate:.4f}".replace(".", ",") if eur_rate else "N/A"
rows.append(("Kurz CZK/EUR", "", "CNB", eur_fmt, "CZK/EUR"))

# --- HTML ---
now = datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M")
rows_html = ""
for label, ticker, exchange, value, unit in rows:
    rows_html += f"<tr><td class='col-name'>{label}</td><td class='col-ticker'>{ticker}</td><td class='col-exch'>{exchange}</td><td class='col-price'>{value}</td><td class='col-unit'>{unit}</td></tr>"

html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard {data_date}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Segoe UI, Arial, sans-serif; background: #0f1117; color: #ffffff; min-height: 100vh; padding: 32px 24px; }}
    h1 {{ font-size: 1.4rem; font-weight: 700; color: #fff; margin-bottom: 4px; }}
    .subtitle {{ font-size: .95rem; color: #4ecca3; font-weight: 600; margin-bottom: 4px; }}
    .updated {{ font-size: .78rem; color: #aaaaaa; margin-bottom: 24px; }}
    .table-wrap {{ display: inline-block; border: 1px solid #4ecca3; border-radius: 8px; overflow: hidden; }}
    table {{ border-collapse: collapse; font-size: .91rem; }}
    thead th {{ background: #1a1d27; color: #ffffff; font-weight: 700; font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; padding: 9px 14px; text-align: left; border-bottom: 2px solid #4ecca3; border-right: 1px solid #2e3347; white-space: nowrap; }}
    thead th:last-child {{ border-right: none; }}
    tbody tr {{ border-bottom: 1px solid #2e3347; }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:hover {{ background: #1a1d27; }}
    tbody td {{ padding: 9px 14px; vertical-align: middle; color: #ffffff; border-right: 1px solid #2e3347; white-space: nowrap; }}
    tbody td:last-child {{ border-right: none; }}
    .col-name {{ font-weight: 600; }}
    .col-ticker {{ font-family: Consolas, monospace; font-size: .84rem; color: #4ecca3; }}
    .col-exch {{ font-size: .82rem; }}
    .col-price {{ font-weight: 700; text-align: right; }}
    .col-unit {{ font-size: .82rem; color: #aaaaaa; padding-left: 8px; }}
    footer {{ margin-top: 24px; font-size: .74rem; color: #888; }}
  </style>
</head>
<body>
  <h1>Financni dashboard</h1>
  <p class="subtitle">Uzaviraci ceny k {data_date}</p>
  <p class="updated">Vygenerovano: {now} UTC</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Polozka</th><th>Ticker</th><th>Zdroj</th><th style="text-align:right">Hodnota</th><th>Jednotka</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <footer>Zdroje: Yahoo Finance &bull; BCPB (TMR) &bull; Ceska narodni banka CNB &bull; Generovano GitHub Actions</footer>
</body>
</html>"""

pathlib.Path("index.html").write_text(html, encoding="utf-8")
print(f"HTML vygenerovan pro datum: {data_date}")
