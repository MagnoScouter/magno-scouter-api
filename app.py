from flask import Flask, jsonify, request
from flask_cors import CORS
import os, random, time, re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import quote_plus

# =========================
# BOOT
# =========================
app = Flask(__name__)
CORS(app)  # libera chamadas vindas do GPT (OpenAI) e navegador

# =========================
# CONFIG
# =========================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

# Fontes permitidas (filtro anti-ruído)
ALLOWED_DOMAINS = [
    "flashscore.com", "www.flashscore.com",
    "sofascore.com", "www.sofascore.com",
    "fbref.com", "www.fbref.com",
    "fotmob.com", "www.fotmob.com",
    "whoscored.com", "www.whoscored.com"
]

# Fallback genérico (título) se parser não disponível
FALLBACK_URLS = [
    "https://fbref.com",
    "https://www.fotmob.com"
]

# Cache simples em memória
CACHE = {}
CACHE_EXPIRY = timedelta(minutes=30)

# =========================
# UTILS
# =========================
def safe_request(url, timeout=25):
    """Requisição com cabeçalhos reais + delay humano para reduzir bloqueios."""
    try:
        time.sleep(random.uniform(3, 6))  # simula comportamento humano
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        print(f"[!] HTTP {r.status_code} em {url}")
        return None
    except Exception as e:
        print(f"[!] Falha na requisição: {e}")
        return None

def normalize_value(val):
    if val is None:
        return None
    s = str(val).strip().replace('%', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        # quando não for número, retorna texto original limpo
        return s

# =========================
# BUSCA (AUTO) – DuckDuckGo HTML
# =========================
def ddg_search(query, site=None, max_results=10):
    """
    Busca leve via DuckDuckGo HTML (sem API).
    Retorna [{title, url}, ...]
    """
    q = f'site:{site} {query}' if site else query
    url = f"https://duckduckgo.com/html/?q={quote_plus(q)}"
    html = safe_request(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    out = []
    # Seletores comuns do resultado leve do DDG
    # (há variações, mas esse é o mais estável)
    for a in soup.select("a.result__a, a.result__a.js-result-title-link"):
        href = a.get("href") or ""
        title = a.get_text(strip=True)
        if href and title:
            out.append({"title": title, "url": href})
            if len(out) >= max_results:
                break
    return out

def search_candidates(query):
    """
    Busca candidatos por domínios prioritários e filtra por ALLOWED_DOMAINS.
    """
    picks = []
    priority_sites = ["flashscore.com", "sofascore.com", "fbref.com", "fotmob.com", "whoscored.com"]

    # 1) tenta por site prioritário
    for site in priority_sites:
        picks += ddg_search(query, site=site, max_results=5)

    # 2) se ainda vazio, busca aberta
    if not picks:
        picks = ddg_search(query, site=None, max_results=10)

    # 3) filtra por domínios permitidos
    filtered = []
    for p in picks:
        u = p.get("url", "")
        if any(dom in u for dom in ALLOWED_DOMAINS):
            filtered.append(p)

    # devolve os 10 mais promissores
    return filtered[:10]

# =========================
# PARSERS
# =========================
def parse_flashscore_match(url):
    """
    Extrai estatísticas básicas de uma página de jogo do Flashscore.
    Retorna dict com title, home/away stats, etc. Usa cache local.
    """
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

    # estatísticas principais (layout comum do Flashscore)
    stats_section = soup.find_all("div", class_="stat__row")

    # estrutura base
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

        key = (label.text or "").strip().lower()
        hv = normalize_value(h.text if h else None)
        av = normalize_value(a.text if a else None)

        if "corner" in key:
            team_stats["home"]["corners"] = hv
            team_stats["away"]["corners"] = av
        elif ("shots on target" in key) or ("s.o.t" in key) or ("on target" in key):
            team_stats["home"]["sot"] = hv
            team_stats["away"]["sot"] = av
        elif key == "shots" or "total shots" in key or "shots total" in key:
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
    """Fallback simples: retorna apenas o <title> da página."""
    html = safe_request(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return {
        "source": "fallback",
        "url": url,
        "title": soup.find("title").text.strip() if soup.find("title") else "N/A"
    }

# =========================
# ROUTES
# =========================
@app.get("/")
def root():
    return jsonify({
        "service": "magno-scouter-actions",
        "status": "ok",
        "message": "Magno Scouter API online. Use /health, /search, /auto_stats, /get_stats."
    }), 200

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "magno-scouter-actions", "version": "1.1.0"}), 200

@app.get("/search")
def search():
    q = (request.args.get("q") or "").strip()
    sport = (request.args.get("sport") or "football").strip()
    if not q:
        return jsonify({"q": q, "results": []}), 200

    cands = search_candidates(q)
    return jsonify({
        "q": q, "sport": sport, "results": cands
    }), 200

@app.get("/auto_stats")
def auto_stats():
    """
    Entrada por NOME DO JOGO (ex.: 'Birmingham vs Ipswich').
    - Busca candidatos multi-fonte (Flashscore, Sofascore, FBref, FotMob, WhoScored)
    - Prioriza Flashscore (parser real)
    - Se não houver parser, devolve melhor candidato como 'partial'
    """
    q = (request.args.get("q") or "").strip()
    sport = (request.args.get("sport") or "football").strip()
    if not q:
        return jsonify({"status": "error", "error": "Parâmetro q (consulta) é obrigatório."}), 400

    cands = search_candidates(q)
    if not cands:
        return jsonify({"status":"error", "error":"Nenhum candidato encontrado nas fontes conhecidas."}), 404

    # tenta em ordem; parser real hoje é Flashscore
    for c in cands:
        url = c.get("url", "")
        if "flashscore.com" in url:
            stats = parse_flashscore_match(url)
            if stats:
                stats["sport"] = sport
                stats.setdefault("notes", []).append("auto: flashscore")
                return jsonify({"status":"ok", "picked": url, **stats}), 200

    # fallback: retorna o melhor candidato disponível (sem parser)
    top = cands[0]
    return jsonify({
        "status":"partial",
        "picked": top.get("url"),
        "title": top.get("title"),
        "notes": ["auto: sem parser específico disponível; tente abrir essa URL ou adicionar novos parsers."]
    }), 200

@app.get("/get_stats")
def get_stats():
    """
    Entrada por URL direta (ex.: /get_stats?url=https://www.flashscore.com/match/XXXXXX/)
    """
    match_url = (request.args.get("url") or "").strip()
    sport = (request.args.get("sport") or "football").strip()
    if not match_url:
        return jsonify({"status": "error", "error": "URL não fornecida."}), 400

    # tenta flashscore
    if "flashscore.com" in match_url:
        stats = parse_flashscore_match(match_url)
        if stats:
            stats["sport"] = sport
            stats.setdefault("notes", []).append("flashscore parsed")
            return jsonify({"status":"ok", **stats}), 200

    # fallbacks (sem parser)
    for fb in FALLBACK_URLS:
        fb_data = parse_fallback_source(fb)
        if fb_data:
            return jsonify({"status":"partial", **fb_data}), 200

    return jsonify({"status":"error", "error": "Falha ao obter estatísticas de todas as fontes."}), 502

# Execução local
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
