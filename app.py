import requests
from bs4 import BeautifulSoup
import random
import time
from flask import Flask, jsonify, request
import re
from datetime import datetime, timedelta

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

FALLBACK_URLS = [
    "https://fbref.com",
    "https://www.fotmob.com"
]

# Cache em memória com timeout de 30 minutos
CACHE = {}
CACHE_EXPIRY = timedelta(minutes=30)

def safe_request(url):
    try:
        time.sleep(random.uniform(3, 6))
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            return response.text
        else:
            print(f"[!] Erro {response.status_code} ao acessar {url}")
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

def parse_flashscore_match(url):
    if url in CACHE and datetime.now() - CACHE[url]['timestamp'] < CACHE_EXPIRY:
        return CACHE[url]['data']

    html = safe_request(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    data = {}

    # Título do jogo
    title = soup.find("title")
    data["title"] = title.text.strip() if title else "N/A"

    # Estatísticas principais
    stats_section = soup.find_all("div", class_="stat__row")
    for stat in stats_section:
        label = stat.find("div", class_="stat__categoryName")
        home_val = stat.find("div", class_="stat__homeValue")
        away_val = stat.find("div", class_="stat__awayValue")
        if label and home_val and away_val:
            stat_key = label.text.strip()
            data[stat_key] = {
                "home": normalize_value(home_val.text.strip()),
                "away": normalize_value(away_val.text.strip())
            }

    # Salvar no cache
    CACHE[url] = {
        'timestamp': datetime.now(),
        'data': data
    }

    return data

def parse_fallback_source(url):
    html = safe_request(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    data = {"fallback": True, "title": soup.find("title").text.strip() if soup.find("title") else "N/A"}
    return data

@app.route("/get_stats", methods=["GET"])
def get_stats():
    match_url = request.args.get("url")
    if not match_url:
        return jsonify({"error": "URL não fornecida."}), 400

    stats = parse_flashscore_match(match_url)
    if stats:
        return jsonify(stats)

    for fallback in FALLBACK_URLS:
        fallback_data = parse_fallback_source(fallback)
        if fallback_data:
            return jsonify(fallback_data)

    return jsonify({"error": "Falha ao obter estatísticas de todas as fontes."}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5001)
