from flask import Flask, jsonify, request
from flask_cors import CORS
import os, random, time, re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# --- App & CORS (uma única vez) ---
app = Flask(__name__)
CORS(app)

# ---------- CONFIG ----------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}
FALLBACK_URLS = [
    "https://fbref.com",
    "https://www.fotmob.com"
]
CACHE = {}
CACHE_EXPIRY = timedelta(minutes=30)

# ---------- UTILS ----------
def safe_request(url):
    try:
        time.sleep(random.uniform(3, 6))  # comportamento humano
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code == 200:
            return r.text
        print(f"[!] HTTP {r.status_code} em {url}")
        return None
    except Exception as e:
        print(f"[!] Falha na requisição: {e}")
        return None

def normalize_value(val):
    if not val:
        return None
    val = val.replace('%', '').replace(',', '.')
    try:
        return float(val)
    except ValueError:
        return val

# ---------- PARSERS ----------
def parse_flashscore_match(url):
    # cache
    if url in CACHE and datetime.now() - CACHE[url]['timestamp'] < CACHE_EXPIRY:
        return CACHE[url]['data']

    html = safe_request(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    data = {"source": "flashscore", "url": url}

    # título
    title = soup.find("title")
    data["title"] = title.text.strip() if title else "N/A"

    # estatísticas principais
    stats_section = soup.find_all("div", class_="stat__row")
    team_stats = {
        "home": {"corners": None, "sot": None, "shots": None, "goals": None, "cards_yellow": None, "cards_red": None},
        "away": {"corners": None, "sot": None, "shots": None, "goals": None, "cards_yellow": None, "cards_red": None}
    }
    for stat in stats_section:
        label = stat.find("div", class_="stat__categoryName")
        h = stat.find("div", class_="stat__homeValue")
        a = stat.find("div", class_="stat__awayValue")
        if not (label and h and a):
            continue
        key = label.text.strip().lower()
        hv = normalize_value(h.text.strip())
        av = normalize_value(a.text.strip())

        if "corner" in key:
            team_stats["home"]["corners"] = hv
            team_stats["away"]["corners"] = av
        elif "shots on target" in key or "s.o.t" in key or "on target" in key:
            team_stats["home"]["sot"] = hv
            team_stats["away"]["sot"] = av
        elif key == "shots" or "total shots" in key:
            team_stats["home"]["shots"] = hv
            team_stats["away"]["shots"] = av
        elif "yellow" in key:
            team_stats["home"]["cards_yellow"] = hv
            team_stats["away"]["cards_yellow"] = av
        elif "red" in key:
            team_stats["home"]["cards_red"] = hv
            team_stats["away"]["cards_red"] = av
        elif "possession" in key:
            data["possession"] = {"home": hv, "away": av}
        elif "goals" in key:
            team_stats["home"]["goals"] = hv
            team_stats["away"]["goals"] = av

    data.update(team_stats)

    # cacheia
    CACHE[url] = {"timestamp": datetime.now(), "data": data}
    return data

def parse_fallback_source(url):
    html = safe_request(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return {
        "source": "fallback",
        "url": url,
        "title": soup.find("title").text.strip() if soup.find("title") else "N/A"
    }

# ---------- ROUTES ----------
@app.get("/")
def root():
    return jsonify({
        "service": "magno-scouter-actions",
        "status": "ok",
        "message": "Magno Scouter API online. Use /health, /search, /get_stats."
    }), 200

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "magno-scouter-actions", "version": "1.0.0"}), 200

@app.get("/search")
def search():
    q = (request.args.get("q") or "").strip()
    sport = (request.args.get("sport") or "football").strip()
    if not q:
        return jsonify({"q": q, "results": []}), 200
    return jsonify({
        "q": q, "sport": sport,
        "results": [
            {"title": f"{q} – Flashscore", "source": "flashscore", "url": "https://www.flashscore.com/match/XXXXXX/"},
            {"title": f"{q} – FBref",      "source": "fbref",      "url": "https://fbref.com/en/matches/XXXXXX"},
            {"title": f"{q} – FotMob",     "source": "fotmob",     "url": "https://www.fotmob.com/match/XXXXXX"}
        ]
    }), 200

@app.get("/get_stats")
def get_stats():
    match_url = (request.args.get("url") or "").strip()
    sport = (request.args.get("sport") or "football").strip()
    if not match_url:
        return jsonify({"status": "error", "error": "URL não fornecida."}), 400

    stats = parse_flashscore_match(match_url)
    if stats:
        stats["sport"] = sport
        stats.setdefault("notes", []).append("flashscore parsed")
        return jsonify({"status":"ok", **stats}), 200

    for fb in FALLBACK_URLS:
        fb_data = parse_fallback_source(fb)
        if fb_data:
            return jsonify({"status":"partial", **fb_data}), 200

    return jsonify({"status":"error", "error": "Falha ao obter estatísticas de todas as fontes."}), 502

# Execução local apenas
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)





