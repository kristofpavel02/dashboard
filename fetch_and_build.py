import requests, math, datetime, pathlib

# Predchozi pracovni den (vcera, preskoci vikend)
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
    ("ALWN.AT",  "Allwyn",            "Ateny (Euronext)"),
]

rows = []
for ticker, label, exchange in stocks:
    price, currency = get_stock(ticker, target_yf)
    if price:
        price_str = f"{price:.2f} {currency}"
        print(f"  {label}: {price_str}")
        rows.append((label, ticker, exchange, price_str))
    else:
        rows.append((label, ticker, exchange, "Nedostupne"))

eur_val = f"{eur_rate:.4f} CZK" if eur_rate else "N/A"
rows.append(("Kurz CZK/EUR (CNB)", "", "CNB", eur_val))

# --- HTML ---
now = datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M")
rows_html = ""
for label, ticker, exchange, value in rows:
    rows_html += f"<tr><td class='col-name'>{label}</td><td class='col-ticker'>{ticker}</td><td class='col-exch'>{exchange}</td><td class='col-price'>{value}</td></tr>"

html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard {data_date}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Segoe UI, Arial, sans-serif; background: #0f1117; color: #e0e0e0; min-height: 100vh; padding: 36px 28px; }}
    h1 {{ font-size: 1.55rem; font-weight: 700; color: #fff; margin-bottom: 4px; }}
    .subtitle {{ font-size: 1rem; color: #4ecca3; font-weight: 600; margin-bottom: 4px; }}
    .updated {{ font-size: .80rem; color: #444; margin-bottom: 30px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .91rem; }}
    thead th {{ background: #161922; color: #888; font-weight: 600; font-size: .76rem; text-transform: uppercase; letter-spacing: .07em; padding: 11px 16px; text-align: left; border-bottom: 1px solid #252836; }}
    tbody tr {{ border-bottom: 1px solid #1c1f2c; }}
    tbody tr:hover {{ background: #161922; }}
    tbody td {{ padding: 14px 16px; vertical-align: middle; }}
    .col-name {{ font-weight: 600; color: #fff; }}
    .col-ticker {{ font-family: Consolas, monospace; font-size: .85rem; color: #4ecca3; }}
    .col-exch {{ font-size: .82rem; color: #666; }}
    .col-price {{ font-weight: 600; text-align: right; }}
    footer {{ margin-top: 40px; font-size: .74rem; color: #444; }}
  </style>
</head>
<body>
  <h1>Financni dashboard</h1>
  <p class="subtitle">Uzaviraci ceny k {data_date}</p>
  <p class="updated">Vygenerovano: {now} UTC</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Polozka</th><th>Ticker</th><th>Burza</th><th style="text-align:right">Hodnota</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <footer>Zdroje: Yahoo Finance &bull; Ceska narodni banka CNB &bull; Generovano GitHub Actions</footer>
</body>
</html>"""

pathlib.Path("index.html").write_text(html, encoding="utf-8")
print(f"HTML vygenerovan pro datum: {data_date}")