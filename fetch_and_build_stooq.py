import requests, datetime, pathlib, json, csv, io

# ============================================================
#  Paralelni "Stooq" varianta dashboardu -> generuje stooq.html
#  - Moneta a Allwyn: primarne Stooq, zaloha Yahoo
#  - TMR: z BCPB (stejne jako hlavni stranka)
#  - Kurz EUR/CZK: z CNB (stejne jako hlavni stranka)
#  POJISTKA NA DATUM: cena se pouzije JEN kdyz je za cilovy den.
#  Kdyz zdroj nema zaverku za cilovy den, ukaze se "Nedostupne"
#  (radeji nic, nez o den starsi cislo).
# ============================================================

# --- Symboly na Stooq (BEST GUESS - overit po prvnim behu v logu) ---
MONETA_STOOQ = "monet.cz"
ALLWYN_STOOQ = "alwn.gr"

# Predchozi obchodni den (x-1, o vikendu posledni patek)
target = datetime.date.today() - datetime.timedelta(days=1)
while target.weekday() >= 5:
    target -= datetime.timedelta(days=1)

target_str = target.strftime("%d.%m.%Y")   # 07.07.2026
target_iso = target.strftime("%Y-%m-%d")    # 2026-07-07 (Stooq i Yahoo)

print(f"[STOOQ] Stahuji data za: {target_str}")

# --- Kurz EUR/CZK z CNB (stejne jako hlavni stranka) ---
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

# --- Zaverecna cena ze Stooq, JEN za cilovy den (pojistka na datum) ---
def get_stooq_close(symbol, target_iso):
    d1 = (target - datetime.timedelta(days=12)).strftime("%Y%m%d")
    d2 = target.strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={symbol}&d1={d1}&d2={d2}&i=d"
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text.strip()
        first = text.split("\n")[0] if text else ""
        if (not text) or ("Date" not in first):
            print(f"  Stooq [{symbol}]: nenalezeno / bez dat -> {text[:50]!r}")
            return None, "Stooq: nenalezeno"
        data = list(csv.DictReader(io.StringIO(text)))
        for r in data:
            if r.get("Date") == target_iso and r.get("Close") not in (None, "", "N/A"):
                price = round(float(r["Close"]), 2)
                print(f"  Stooq [{symbol}]: {price} za {target_iso} OK")
                return price, "Stooq"
        last_date = data[-1]["Date"] if data else "?"
        print(f"  Stooq [{symbol}]: za {target_iso} NEMA (posledni {last_date}) -> nepouzivam")
        return None, f"Stooq: jen do {last_date}"
    except Exception as e:
        print(f"  Stooq [{symbol}] CHYBA: {e}")
        return None, "Stooq: chyba"

# --- Zaloha: Yahoo, take JEN za cilovy den (zadne tiche starsi cislo) ---
def get_yahoo_close_exact(ticker, target_iso):
    for base in ["query1", "query2"]:
        try:
            url  = f"https://{base}.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=15d"
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            data = resp.json()
            result     = data["chart"]["result"][0]
            closes     = result["indicators"]["quote"][0]["close"]
            timestamps = result["timestamp"]
            currency   = result["meta"]["currency"]
            for i, ts in enumerate(timestamps):
                dt = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                if dt == target_iso and closes[i]:
                    return round(closes[i], 2), currency
        except:
            pass
    return None, None

# --- Nejprve Stooq, pak Yahoo jako zaloha (oboje jen za cilovy den) ---
def resolve_price(stooq_symbol, yahoo_ticker, currency, target_iso):
    price, src = get_stooq_close(stooq_symbol, target_iso)
    if price is not None:
        return price, currency, src
    yprice, ycur = get_yahoo_close_exact(yahoo_ticker, target_iso)
    if yprice is not None:
        print(f"  Yahoo [{yahoo_ticker}]: {yprice} za {target_iso} OK (zaloha)")
        return yprice, (ycur or currency), "Yahoo (zaloha)"
    print(f"  {yahoo_ticker}: za {target_iso} nedostupne ze Stooq ani Yahoo")
    return None, currency, src

# --- TMR z BCPB (stejne jako hlavni stranka) ---
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
        row   = rows[-1]
        price = round(float(row["Cells"][1].replace(",", ".")), 2)
        return price, row["Cells"][2]
    except Exception as e:
        print(f"  CHYBA TMR: {e}")
        return None, None

# ============================================================
#  Sestaveni radku tabulky
#  Radek = (nazev, ticker, zdroj/stav, hodnota, jednotka)
# ============================================================
rows = []

# Moneta
m_price, m_cur, m_src = resolve_price(MONETA_STOOQ, "MONET.PR", "CZK", target_iso)
if m_price is not None:
    rows.append(("Moneta Money Bank", "MONET.PR", f"Praha \u00b7 {m_src}", f"{m_price:.2f}".replace(".", ","), m_cur))
else:
    rows.append(("Moneta Money Bank", "MONET.PR", f"Praha \u00b7 {m_src}", "Nedostupne", ""))

# TMR (z BCPB)
tmr_price, tmr_cur = get_tmr()
if tmr_price:
    rows.append(("Tatry Mountain Resorts", "TMR", "Bratislava (BCPB)", f"{tmr_price:.2f}".replace(".", ","), tmr_cur))
else:
    rows.append(("Tatry Mountain Resorts", "TMR", "Bratislava (BCPB)", "Nedostupne", ""))

# Allwyn
a_price, a_cur, a_src = resolve_price(ALLWYN_STOOQ, "ALWN.AT", "EUR", target_iso)
if a_price is not None:
    rows.append(("Allwyn", "ALWN.AT", f"Ateny (ATHEX) \u00b7 {a_src}", f"{a_price:.2f}".replace(".", ","), a_cur))
else:
    rows.append(("Allwyn", "ALWN.AT", f"Ateny (ATHEX) \u00b7 {a_src}", "Nedostupne", ""))

# Kurz EUR/CZK z CNB
eur_fmt = f"{eur_rate:.4f}".replace(".", ",") if eur_rate else "N/A"
rows.append(("Kurz CZK/EUR", "", "CNB", eur_fmt, "CZK/EUR"))

# ============================================================
#  HTML (stejny vzhled jako hlavni stranka, jen oznaceno jako STOOQ test)
# ============================================================
now = datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M")
rows_html = ""
for label, ticker, exchange, value, unit in rows:
    rows_html += f"<tr><td class='col-name'>{label}</td><td class='col-ticker'>{ticker}</td><td class='col-exch'>{exchange}</td><td class='col-price'>{value}</td><td class='col-unit'>{unit}</td></tr>"

html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard STOOQ {data_date}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Segoe UI, Arial, sans-serif; background: #0f1117; color: #ffffff; min-height: 100vh; padding: 32px 24px; }}
    h1 {{ font-size: 1.4rem; font-weight: 700; color: #fff; margin-bottom: 4px; }}
    .tag {{ display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #0f1117; background: #ffb84d; padding: 2px 8px; border-radius: 4px; margin-left: 8px; vertical-align: middle; }}
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
  <h1>Financni dashboard <span class="tag">Stooq test</span></h1>
  <p class="subtitle">Uzaviraci ceny k {data_date}</p>
  <p class="updated">Vygenerovano: {now} UTC &bull; ceny jen za uvedene datum (jinak "Nedostupne")</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Polozka</th><th>Ticker</th><th>Zdroj</th><th style="text-align:right">Hodnota</th><th>Jednotka</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <footer>Zdroje: Stooq (Moneta, Allwyn) &bull; Yahoo (zaloha) &bull; BCPB (TMR) &bull; CNB (kurz) &bull; Generovano GitHub Actions</footer>
</body>
</html>"""

pathlib.Path("stooq.html").write_text(html, encoding="utf-8")
print(f"[STOOQ] stooq.html vygenerovan pro datum: {data_date}")
