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

CHECK_INTERVAL = 900  # 15 minutos
SENT_FILE = "sent_items.json"

SEARCH_TERMS = [
    "placa de video",
    "gpu",
    "rtx",
    "gtx",
    "rx",
]

GPU_PATTERNS = [
    "rtx",
    "gtx",
    "rx 5",
    "rx 6",
    "rx 7",
    "radeon rx",
    "geforce gtx",
    "geforce rtx",
]

EXCLUDED_TERMS = [
    "suporte",
    "adaptador",
    "cabo",
    "case",
    "fan",
    "cooler",
    "adesivo",
    "miniatura",
    "boneco",
    "controle",
    "fonte",
    "processador",
    "placa mae",
    "placa-mãe",
    "notebook",
]

MAX_GLOBAL_PRICE = 1500.0
MIN_GLOBAL_PRICE = 250.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# =========================
# FUNÇÕES DE AMBIENTE
# =========================

def validate_env():
    missing = []

    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")

    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        raise ValueError("Variáveis ausentes no Railway: " + ", ".join(missing))

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    response = requests.post(url, data=payload, timeout=20)
    response.raise_for_status()

# =========================
# FUNÇÕES ÚTEIS
# =========================

def normalize_text(text):
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()

def parse_price(price_text):
    if not price_text:
        return None

    text = normalize_text(price_text)
    text = text.replace("R$", "").replace(" ", "")

    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")

    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None

def looks_like_gpu(title):
    title_lower = title.lower()

    if any(term in title_lower for term in EXCLUDED_TERMS):
        return False

    return any(pattern in title_lower for pattern in GPU_PATTERNS)

def is_good_offer(title, price):
    if not looks_like_gpu(title):
        return False

    if price is None:
        return False

    if price < MIN_GLOBAL_PRICE:
        return False

    if price > MAX_GLOBAL_PRICE:
        return False

    return True

def product_id(store, title, price, link):
    return f"{store}|{title}|{price}|{link}"

def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text

def deduplicate_items(items):
    seen = set()
    result = []

    for item in items:
        key = (item["store"], item["title"], item["link"])
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result

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

# =========================
# LOJAS
# =========================

def search_kabum(query):
    items = []
    url = f"https://www.kabum.com.br/busca/{quote_plus(query)}"

    try:
        html_text = fetch_html(url)
        soup = BeautifulSoup(html_text, "lxml")

        cards = soup.select('a[href*="/produto/"]')

        for card in cards:
            href = card.get("href", "")
            title_el = card.select_one("span.nameCard, div.nameCard, span.sc-d79c9c3f-0")
            price_el = card.select_one("span.priceCard, span.sc-620f2d27-2")

            title = None
            if title_el:
                title = normalize_text(title_el.get_text())
            else:
                title = normalize_text(card.get_text())

            price = parse_price(price_el.get_text()) if price_el else None

            if href.startswith("http"):
                link = href
            else:
                link = f"https://www.kabum.com.br{href}"

            if title and link:
                items.append({
                    "store": "Kabum",
                    "title": title,
                    "price": price,
                    "link": link,
                })

    except Exception as e:
        print(f"Erro na Kabum para '{query}': {e}")

    return deduplicate_items(items)

def search_mercado_livre(query):
    items = []
    url = f"https://lista.mercadolivre.com.br/{quote_plus(query)}"

    try:
        html_text = fetch_html(url)
        soup = BeautifulSoup(html_text, "lxml")

        cards = soup.select("li.ui-search-layout__item")

        for card in cards:
            title_el = card.select_one("h3")
            link_el = card.select_one("a[href]")
            whole_el = card.select_one(".andes-money-amount__fraction")
            cents_el = card.select_one(".andes-money-amount__cents")

            title = normalize_text(title_el.get_text()) if title_el else None
            link = link_el.get("href") if link_el else None

            price = None
            if whole_el:
                raw_price = whole_el.get_text()
                if cents_el:
                    raw_price += "," + cents_el.get_text()
                price = parse_price(raw_price)

            if title and link:
                items.append({
                    "store": "Mercado Livre",
                    "title": title,
                    "price": price,
                    "link": link,
                })

    except Exception as e:
        print(f"Erro no Mercado Livre para '{query}': {e}")

    return deduplicate_items(items)

def search_magalu(query):
    items = []
    url = f"https://www.magazineluiza.com.br/busca/{quote_plus(query)}/"

    try:
        html_text = fetch_html(url)
        soup = BeautifulSoup(html_text, "lxml")

        cards = soup.select('a[href*="/p/"]')

        for card in cards:
            href = card.get("href", "")
            title_el = card.select_one("h2, h3")
            price_el = card.select_one('p[data-testid="price-value"], div[data-testid="price-value"]')

            title = None
            if title_el:
                title = normalize_text(title_el.get_text())
            else:
                title = normalize_text(card.get_text())

            price = parse_price(price_el.get_text()) if price_el else None

            if href.startswith("http"):
                link = href
            else:
                link = f"https://www.magazineluiza.com.br{href}"

            if title and link:
                items.append({
                    "store": "Magazine Luiza",
                    "title": title,
                    "price": price,
                    "link": link,
                })

    except Exception as e:
        print(f"Erro na Magazine Luiza para '{query}': {e}")

    return deduplicate_items(items)

# =========================
# BUSCA E ALERTA
# =========================

def collect_all_offers():
    all_items = []

    store_functions = [
        search_kabum,
        search_magalu,
    ]

    for term in SEARCH_TERMS:
        for fn in store_functions:
            print(f"Buscando '{term}' em {fn.__name__}...")
            results = fn(term)
            all_items.extend(results)
            time.sleep(2)

    return all_items

def format_offer_message(item):
    price_text = f"R$ {item['price']:.2f}".replace(".", ",")

    return (
        f"🔥 Possível promoção de GPU\n\n"
        f"🏪 Loja: {item['store']}\n"
        f"🎮 Produto: {item['title']}\n"
        f"💰 Preço: {price_text}\n\n"
        f"🔗 {item['link']}"
    )

def process_offers():
    sent_items = load_sent_items()
    offers = collect_all_offers()

    print(f"Total de itens encontrados: {len(offers)}")

    new_count = 0

    for item in offers:
        good = is_good_offer(item["title"], item["price"])

        if not good:
            continue

        pid = product_id(item["store"], item["title"], item["price"], item["link"])

        if pid in sent_items:
            continue

        message = format_offer_message(item)

        try:
            send_telegram_message(message)
            sent_items[pid] = {
                "store": item["store"],
                "title": item["title"],
                "price": item["price"],
                "link": item["link"],
                "sent_at": int(time.time()),
            }
            new_count += 1
            print(f"Enviado para o Telegram: {item['title']}")
            time.sleep(2)
        except Exception as e:
            print(f"Erro ao enviar mensagem no Telegram: {e}")

    save_sent_items(sent_items)
    print(f"Novas promoções enviadas: {new_count}")
    
# =========================
# LOOP PRINCIPAL
# =========================

def main():
    validate_env()
    print("Bot iniciado com sucesso.")

    try:
        send_telegram_message("✅ Bot de promoções iniciado e rodando 24h.")
    except Exception as e:
        print(f"Erro ao enviar mensagem inicial: {e}")

    while True:
        try:
            print("Iniciando nova verificação...")
            process_offers()
            print(f"Aguardando {CHECK_INTERVAL} segundos para a próxima verificação...")
        except Exception as e:
            print(f"Erro geral no loop principal: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()