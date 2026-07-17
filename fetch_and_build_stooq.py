import requests, datetime, pathlib, json, zipfile, io

# ============================================================
#  Paralelni "autoritativni" varianta dashboardu -> stooq.html
#  - Moneta: z prazske burzy (PSE) - denni kurzovni listek PL.ZIP
#  - Allwyn: stockanalysis.com, zaloha Yahoo (zatim beze zmeny)
#  - TMR: z BCPB ; Kurz EUR/CZK: z CNB
#  POJISTKA NA DATUM: cena se pouzije JEN za cilovy den, jinak "Nedostupne".
#  Skript vypisuje do logu, co ze zdroju prislo (kvuli ladeni).
# ============================================================

MONETA_ISIN = "CZ0008040318"   # Moneta Money Bank na PSE
ALLWYN_SA   = "ATH:ALWN"       # Allwyn na stockanalysis.com

target = datetime.date.today() - datetime.timedelta(days=1)
while target.weekday() >= 5:
    target -= datetime.timedelta(days=1)

target_str = target.strftime("%d.%m.%Y")
target_iso = target.strftime("%Y-%m-%d")

print(f"[ALT] Stahuji data za: {target_str}")

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
            eur_rate = round(float(parts[4].strip().replace(",", ".")) / float(parts[2].strip()), 4)
            print(f"  EUR/CZK = {eur_rate} (k {cnb_date})")
            break
except Exception as e:
    print(f"  CHYBA CNB: {e}")
data_date = cnb_date if cnb_date else target_str

# --- prevod ruznych tvaru data na YYYY-MM-DD ---
def to_iso(val):
    if val is None:
        return None
    try:
        n = float(val)
        if n > 10_000_000:
            return datetime.datetime.utcfromtimestamp(n).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    s = str(val).strip().strip('"').strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(s[:len(fmt)+4], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s[:10]

def norm_num(raw):
    p = str(raw).replace(" ", "").replace("\xa0", "")
    if "." in p and "," in p:      # 1.234,50 -> tisice teckou, desetiny carkou
        p = p.replace(".", "").replace(",", ".")
    elif "," in p:                 # 191,20 -> 191.20
        p = p.replace(",", ".")
    return round(float(p), 2)

# --- Moneta z PSE: denni kurzovni listek PL.ZIP (soubor AK) ---
def get_pse_close(isin, target_iso):
    url = "http://ftp.pse.cz/results.ak/PL.ZIP"
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        print(f"  PSE GET {url} -> HTTP {r.status_code}, {len(r.content)} B")
        if r.status_code != 200 or not r.content:
            return None, "PSE: stazeni selhalo"
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        print(f"  PSE ZIP obsahuje: {names}")
        ak = next((n for n in names if n.split('/')[-1].upper().startswith("AK")), None)
        if not ak:
            return None, "PSE: AK soubor nenalezen"
        raw = zf.read(ak)
        try:
            text = raw.decode("cp1250")
        except Exception:
            text = raw.decode("latin-1", errors="replace")
        for line in text.splitlines():
            if isin in line:
                print(f"  PSE radek Moneta: {line[:130]!r}")
                delim = ";" if ";" in line else ("," if line.count(",") >= 4 else None)
                fields = [f.strip() for f in line.split(delim)] if delim else line.split()
                if len(fields) < 5:
                    return None, "PSE: neznamy format"
                trad_day = to_iso(fields[3])
                try:
                    price = norm_num(fields[4])
                except ValueError:
                    return None, f"PSE: cislo necitelne ({fields[4]!r})"
                if trad_day == target_iso:
                    print(f"  PSE [{isin}]: {price} za {target_iso} OK")
                    return price, "PSE"
                print(f"  PSE [{isin}]: den {trad_day} != {target_iso} -> nepouzivam")
                return None, f"PSE: den {trad_day}"
        return None, "PSE: ISIN nenalezen"
    except Exception as e:
        print(f"  PSE chyba: {e}")
        return None, "PSE: chyba"

# --- stockanalysis.com (pro Allwyn): zaverka JEN za cilovy den ---
def get_stockanalysis(symbol, target_iso):
    exch, tick = symbol.split(":")
    for url in [
        f"https://stockanalysis.com/api/symbol/e/{symbol}/history?range=3M&period=Daily",
        f"https://stockanalysis.com/api/symbol/e/{exch.lower()}/{tick}/history?range=3M&period=Daily",
    ]:
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            print(f"  SA GET {url} -> HTTP {r.status_code}")
            if r.status_code != 200:
                continue
            j = r.json()
            print(f"  SA vzorek: {str(j)[:300]}")
            rows = None
            if isinstance(j, dict):
                d = j.get("data")
                rows = d if isinstance(d, list) else (d.get("data") if isinstance(d, dict) else None)
            elif isinstance(j, list):
                rows = j
            if not rows:
                continue
            for row in rows:
                if isinstance(row, dict):
                    dt = to_iso(row.get("t") or row.get("date") or row.get("dateFormatted") or row.get("Date"))
                    cl = row.get("c", row.get("close", row.get("Close", row.get("adjClose"))))
                elif isinstance(row, (list, tuple)) and len(row) >= 5:
                    dt = to_iso(row[0]); cl = row[4]
                else:
                    continue
                if dt == target_iso and cl not in (None, "", "N/A"):
                    return round(float(cl), 2), "stockanalysis"
            return None, "SA: den chybi"
        except Exception as e:
            print(f"  SA chyba: {e}")
    return None, "SA: nedostupne"

# --- Yahoo zaloha: JEN za cilovy den ---
def get_yahoo_exact(ticker, target_iso):
    for base in ["query1", "query2"]:
        try:
            url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=15d"
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            res = r.json()["chart"]["result"][0]
            closes = res["indicators"]["quote"][0]["close"]
            ts = res["timestamp"]; cur = res["meta"]["currency"]
            for i, t in enumerate(ts):
                if datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d") == target_iso and closes[i]:
                    return round(closes[i], 2), cur
        except Exception:
            pass
    return None, None

# --- TMR z BCPB ---
def get_tmr():
    try:
        today = datetime.date.today().strftime("%Y-%m-%d")
        url = f"https://www.bsse.sk/BCPB_WEB_API/api/Security/GetOne?find=%23KEY%3DA%7C%5E%7C2147%23&tradesummday={today}&daysinterval=7&lang=SK"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bsse.sk/bcpb/detail-cp/?isin=%23KEY%3DA%7C%5E%7C2147%23"})
        rr = json.loads(json.loads(r.text))["Tables"][0]["Rows"]
        if not rr:
            return None, None
        return round(float(rr[-1]["Cells"][1].replace(",", ".")), 2), rr[-1]["Cells"][2]
    except Exception as e:
        print(f"  CHYBA TMR: {e}")
        return None, None

# ============================================================
#  Sestaveni radku
# ============================================================
rows = []

# Moneta: PSE primarne, Yahoo zaloha
m_price, m_src = get_pse_close(MONETA_ISIN, target_iso)
if m_price is None:
    yp, _ = get_yahoo_exact("MONET.PR", target_iso)
    if yp is not None:
        print(f"  Yahoo [MONET.PR]: {yp} za {target_iso} OK (zaloha)")
        m_price, m_src = yp, "Yahoo (zaloha)"
rows.append(("Moneta Money Bank", "MONET.PR", f"Praha \u00b7 {m_src}",
             f"{m_price:.2f}".replace(".", ",") if m_price is not None else "Nedostupne",
             "CZK" if m_price is not None else ""))

# TMR z BCPB
tmr_price, tmr_cur = get_tmr()
rows.append(("Tatry Mountain Resorts", "TMR", "Bratislava (BCPB)",
             f"{tmr_price:.2f}".replace(".", ",") if tmr_price else "Nedostupne",
             tmr_cur if tmr_price else ""))

# Allwyn: stockanalysis primarne, Yahoo zaloha
a_price, a_src = get_stockanalysis(ALLWYN_SA, target_iso)
if a_price is None:
    yp, _ = get_yahoo_exact("ALWN.AT", target_iso)
    if yp is not None:
        print(f"  Yahoo [ALWN.AT]: {yp} za {target_iso} OK (zaloha)")
        a_price, a_src = yp, "Yahoo (zaloha)"
rows.append(("Allwyn", "ALWN.AT", f"Ateny (ATHEX) \u00b7 {a_src}",
             f"{a_price:.2f}".replace(".", ",") if a_price is not None else "Nedostupne",
             "EUR" if a_price is not None else ""))

# Kurz EUR/CZK
eur_fmt = f"{eur_rate:.4f}".replace(".", ",") if eur_rate else "N/A"
rows.append(("Kurz CZK/EUR", "", "CNB", eur_fmt, "CZK/EUR"))

# ============================================================
#  HTML
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
  <title>Dashboard (autoritativni zdroje) {data_date}</title>
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
  <h1>Financni dashboard <span class="tag">autoritativni zdroje (test)</span></h1>
  <p class="subtitle">Uzaviraci ceny k {data_date}</p>
  <p class="updated">Vygenerovano: {now} UTC &bull; ceny jen za uvedene datum (jinak "Nedostupne")</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Polozka</th><th>Ticker</th><th>Zdroj</th><th style="text-align:right">Hodnota</th><th>Jednotka</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <footer>Zdroje: PSE (Moneta) &bull; stockanalysis/Yahoo (Allwyn) &bull; BCPB (TMR) &bull; CNB (kurz) &bull; Generovano GitHub Actions</footer>
</body>
</html>"""

pathlib.Path("stooq.html").write_text(html, encoding="utf-8")
print(f"[ALT] stooq.html vygenerovan pro datum: {data_date}")
