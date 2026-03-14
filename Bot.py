import os
import re
import json
import time
import html
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# =========================
# CONFIGURAÇÕES
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Tempo entre verificações (em segundos)
CHECK_INTERVAL = 900  # 15 minutos

# Arquivo para salvar promoções já enviadas
SENT_FILE = "sent_items.json"

# Palavras que devem existir no título
KEYWORDS = [
    "rx 6600",
    "rx 6650 xt",
    "rx 7600",
    "rtx 3050",
    "rtx 3060",
    "rtx 4060",
    "gtx 1660",
    "gtx 1650",
]

# Preço máximo por produto/termo
MAX_PRICE_BY_KEYWORD = {
    "rx 6600": 1250.0,
    "rx 6650 xt": 1450.0,
    "rx 7600": 1600.0,
    "rtx 3050": 1300.0,
    "rtx 3060": 1700.0,
    "rtx 4060": 1900.0,
    "gtx 1660": 1100.0,
    "gtx 1650": 900.0,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# =========================
# FUNÇÕES BÁSICAS
# =========================

def validate_env():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError(
            "Defina as variáveis TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no Railway."
        )

def load_sent_items():
    if not os.path.exists(SENT_FILE):
        return {}
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_sent_items(data):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    response = requests.post(url, data=payload, timeout=20)
    response.raise_for_status()

def normalize_text(text):
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()

def parse_price(price_text):
    """
    Converte textos como:
    'R$ 1.249,90'
    '1.249,90'
    'R$1,249.90' (fallback)
    """
    if not price_text:
        return None

    text = normalize_text(price_text)
    text = text.replace("R$", "").replace(" ", "")

    # Caso BR: 1.249,90
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        # fallback
        text = text.replace(",", "")

    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None

def get_keyword_match(title):
    title_lower = title.lower()
    for keyword in KEYWORDS:
        if keyword in title_lower:
            return keyword
    return None

def is_good_offer(title, price):
    keyword = get_keyword_match(title)
    if not keyword:
        return False, None

    limit = MAX_PRICE_BY_KEYWORD.get(keyword)
    if limit is None:
        return False, None

    if price is None:
        return False, keyword

    return price <= limit, keyword

def product_id(store, title, price, link):
    base = f"{store}|{title}|{price}|{link}"
    return str(abs(hash(base)))

def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text

# =========================
# SCRAPERS DAS LOJAS
# =========================

def search_kabum(query):
    url = f"https://www.kabum.com.br/busca/{quote_plus(query)}"
    items = []
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "lxml")

    for a in soup.select('a[href*="/produto/"]'):
        href = a.get("href", "")
        title_el = a.select_one("span.nameCard, span.sc-d79c9c3f-0, div.nameCard")
        price_el = a.select_one("span.priceCard, span.sc-620f2d27-2")

        title = normalize_text(title_el.get_text()) if title_el else normalize_text(a.get_text())
        price = parse_price(price_el.get_text()) if price_el else None
        link = href if href.startswith("http") else f"https://www.kabum.com.br{href}"

        if title:
            items.append({
                "store": "Kabum",
                "title": title,
                "price": price,
                "link": link,
            })

    return deduplicate_items(items)

def search_mercado_livre(query):
    url = f"https://lista.mercadolivre.com.br/{quote_plus(query)}"
    items = []
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "lxml")

    for card in soup.select("li.ui-search-layout__item, div.ui-search-result"):
        title_el = card.select_one("h3")
        price_whole = card.select_one(".andes-money-amount__fraction")
        price_cents = card.select_one(".andes-money-amount__cents")
        link_el = card.select_one("a[href]")

        title = normalize_text(title_el.get_text()) if title_el else None

        price = None
        if price_whole:
            raw = price_whole.get_text()
            if price_cents:
                raw += "," + price_cents.get_text()
            price = parse_price(raw)

        link = link_el.get("href") if link_el else None

        if title and link:
            items.append({
                "store": "Mercado Livre",
                "title": title,
                "price": price,
                "link": link,
            })

    return deduplicate_items(items)

def search_magalu(query):
    url = f"https://www.magazineluiza.com.br/busca/{quote_plus(query)}/"
    items = []
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "lxml")

    for a in soup.select('a[href*="/p/"]'):
        title_el = a.select_one("h2, h3")
        price_el = a.select_one('p[data-testid="price-value"], div[data-testid="price-value"]')

        title = normalize_text(title_el.get_text()) if title_el else normalize_text(a.get_text())
        price = parse_price(price_el.get_text()) if price_el else None
        href = a.get("href", "")
        link = href if href.startswith("http") else f"https://www.magazineluiza.com.br{href}"

        if title:
            items.append({
                "store": "Magazine Luiza",
                "title": title,
                "price": price,
                "link": link,
            })

    return deduplicate_items(items)

def search_amazon(query):
    url = f"https://www.amazon.com.br/s?k={quote_plus(query)}"
    items = []
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "lxml")

    for card in soup.select('div[data-component-type="s-search-result"]'):
        title_el = card.select_one("h2 span")
        whole = card.select_one(".a-price-whole")
        frac = card.select_one(".a-price-fraction")
        link_el = card.select_one("h2 a")

        title = normalize_text(title_el.get_text()) if title_el else None

        price = None
        if whole:
            raw = whole.get_text()
            if frac:
                raw += "," + frac.get_text()
            price = parse_price(raw)

        link = None
        if link_el and link_el.get("href"):
            href = link_el.get("href")
            link = href if href.startswith("http") else f"https://www.amazon.com.br{href}"

        if title and link:
            items.append({
                "store": "Amazon",
                "title": title,
                "price": price,
                "link": link,
            })

    return deduplicate_items(items)

def search_shopee(query):
    url = f"https://shopee.com.br/search?keyword={quote_plus(query)}"
    items = []
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "lxml")

    for a in soup.select('a[href*="-i."]'):
        title = normalize_text(a.get("title") or a.get_text())
        link = a.get("href", "")
        if link and not link.startswith("http"):
            link = f"https://shopee.com.br{link}"

        # Shopee varia muito no HTML; preço às vezes não vem fácil
        price = None

        if title and link:
            items.append({
                "store": "Shopee",
                "title": title,
                "price": price,
                "link": link,
            })

    return deduplicate_items(items)

def search_aliexpress(query):
    url = f"https://pt.aliexpress.com/wholesale?SearchText={quote_plus(query)}"
    items = []
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "lxml")

    for a in soup.select('a[href*="/item/"]'):
        title = normalize_text(a.get("title") or a.get_text())
        link = a.get("href", "")
        if link and link.startswith("//"):
            link = "https:" + link
        elif link and not link.startswith("http"):
            link = "https://pt.aliexpress.com" + link

        price = None

        if title and link:
            items.append({
                "store": "AliExpress",
                "title": title,
                "price": price,
                "link": link,
            })

    return deduplicate_items(items)

def deduplicate_items(items):
    seen = set()
    clean = []

    for item in items:
        key = (item["store"], item["title"], item["link"])
        if key not in seen:
            seen.add(key)
            clean.append(item)

    return clean

# =========================
# BUSCA GERAL
# =========================

def collect_all_offers():
    all_items = []

    search_functions = [
        search_kabum,
        search_mercado_livre,
        search_magalu,
        search_amazon,
        search_shopee,
        search_aliexpress,
    ]

    for keyword in KEYWORDS:
        for search_fn in search_functions:
            try:
                print(f"Buscando '{keyword}' em {search_fn.__name__}...")
                results = search_fn(keyword)
                all_items.extend(results)
                time.sleep(2)
            except Exception as e:
                print(f"Erro em {search_fn.__name__} com '{keyword}': {e}")

    return all_items

def format_offer_message(item, matched_keyword):
    price_text = f"R$ {item['price']:.2f}".replace(".", ",") if item["price"] is not None else "Preço não identificado"

    limit = MAX_PRICE_BY_KEYWORD.get(matched_keyword)
    limit_text = f"R$ {limit:.2f}".replace(".", ",") if limit is not None else "-"

    return (
        f"🔥 Promoção encontrada\n\n"
        f"🏪 Loja: {item['store']}\n"
        f"🎮 Produto: {item['title']}\n"
        f"💰 Preço: {price_text}\n"
        f"🎯 Alerta para: {matched_keyword.upper()}\n"
        f"📌 Limite definido: {limit_text}\n\n"
        f"🔗 {item['link']}"
    )

def process_offers():
    sent_items = load_sent_items()
    offers = collect_all_offers()

    print(f"Total encontrado: {len(offers)} itens")

    new_count = 0

    for item in offers:
        good, matched_keyword = is_good_offer(item["title"], item["price"])

        if not good:
            continue

        pid = product_id(item["store"], item["title"], item["price"], item["link"])

        if pid in sent_items:
            continue

        message = format_offer_message(item, matched_keyword)

        try:
            send_telegram_message(message)
            sent_items[pid] = {
                "store": item["store"],
                "title": item["title"],
                "price": item["price"],
                "link": item["link"],
                "keyword": matched_keyword,
                "sent_at": int(time.time()),
            }
            new_count += 1
            print(f"Enviado: {item['title']}")
            time.sleep(2)
        except Exception as e:
            print(f"Erro ao enviar Telegram: {e}")

    save_sent_items(sent_items)
    print(f"Novas promoções enviadas: {new_count}")

# =========================
# LOOP PRINCIPAL
# =========================

def main():
    validate_env()
    print("Bot iniciado com sucesso.")
    send_telegram_message("✅ Bot de promoções iniciado e rodando 24h.")

    while True:
        try:
            print("Iniciando nova verificação...")
            process_offers()
            print(f"Aguardando {CHECK_INTERVAL} segundos para a próxima verificação...")
        except Exception as e:
            print(f"Erro geral no loop: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()