import os
import re
import json
import time
import html
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# =========================
# CONFIGURAÇÕES
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 600  

SENT_FILE = "sent_items.json"
PRICE_HISTORY_FILE = "price_history.json"

MIN_GLOBAL_PRICE = 500.0
MAX_GLOBAL_PRICE = 1800.0

MIN_DROP_ALERT = 50.0      # alerta se cair pelo menos R$ 50
MIN_DROP_PERCENT = 5.0     # ou pelo menos 5%

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
    "geforce rtx",
    "geforce gtx",
]

EXCLUDED_TERMS = [
    "suporte",
    "adaptador",
    "cabo",
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
    "gabinete",
    "water cooler",
    "kit upgrade",
    "memoria ram",
    "ssd",
    "mouse",
    "teclado",
]

# =========================
# AMBIENTE / TELEGRAM
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
    print(f"[Telegram] status={response.status_code} response={response.text}")

    if response.status_code != 200:
        raise RuntimeError(f"Telegram API error: {response.status_code} - {response.text}")

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
    title_lower = normalize_text(title).lower()

    if any(term in title_lower for term in EXCLUDED_TERMS):
        return False

    return any(pattern in title_lower for pattern in GPU_PATTERNS)

def is_good_offer(title, price):
    if not looks_like_gpu(title):
        return False

    # Se não conseguimos capturar preço, ainda considera para inspecionar (envia alerta de primeira vez)
    if price is None:
        return True

    if price < MIN_GLOBAL_PRICE:
        return False

    if price > MAX_GLOBAL_PRICE:
        return False

    return True

def product_id(store, title, price, link):
    return f"{store}|{title}|{price}|{link}"

def product_key(item):
    title = normalize_text(item["title"]).lower()
    return f"{item['store']}|{title}"

def deduplicate_items(items):
    seen = set()
    result = []

    for item in items:
        key = (item["store"], item["title"], item["link"])
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result

# =========================
# ARQUIVOS JSON
# =========================

def load_json_file(path):
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_sent_items():
    return load_json_file(SENT_FILE)

def save_sent_items(data):
    save_json_file(SENT_FILE, data)

def load_price_history():
    return load_json_file(PRICE_HISTORY_FILE)

def save_price_history(data):
    save_json_file(PRICE_HISTORY_FILE, data)

# =========================
# HISTÓRICO DE PREÇO
# =========================

def check_price_drop(item, history):
    if item["price"] is None:
        return None

    key = product_key(item)
    current_price = item["price"]
    old_data = history.get(key)

    if not old_data:
        history[key] = {
            "title": item["title"],
            "store": item["store"],
            "link": item["link"],
            "lowest_price": current_price,
            "last_price": current_price,
            "last_seen": int(time.time()),
        }
        return None

    previous_price = old_data.get("last_price", current_price)
    lowest_price = old_data.get("lowest_price", current_price)

    drop_value = 0.0
    drop_percent = 0.0

    if previous_price is not None and current_price < previous_price:
        drop_value = previous_price - current_price
        drop_percent = (drop_value / previous_price) * 100

    old_data["last_price"] = current_price
    old_data["last_seen"] = int(time.time())

    if current_price < lowest_price:
        old_data["lowest_price"] = current_price

    history[key] = old_data

    if drop_value >= MIN_DROP_ALERT or drop_percent >= MIN_DROP_PERCENT:
        return {
            "previous_price": previous_price,
            "current_price": current_price,
            "drop_value": drop_value,
            "drop_percent": drop_percent,
        }

    return None

# =========================
# REQUISIÇÕES
# =========================

def fetch_html(url, retries=3, extra_headers=None):
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ]),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    if extra_headers:
        headers.update(extra_headers)

    last_error = None

    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            last_error = e
            print(f"Erro ao acessar {url} | tentativa {attempt + 1}/{retries}: {e}")
            time.sleep(random.uniform(2, 5))

    raise last_error

# =========================
# LOJAS
# =========================

def search_aliexpress(query):
    items = []
    url = f"https://pt.aliexpress.com/wholesale?SearchText={quote_plus(query)}"

    try:
        html_text = fetch_html(url)
        soup = BeautifulSoup(html_text, "lxml")

        cards = soup.select('a[href*="/item/"]')

        for card in cards:
            title = normalize_text(card.get("title") or card.get_text())
            link = card.get("href", "")
            price = None

            if link.startswith("//"):
                link = "https:" + link
            elif link and not link.startswith("http"):
                link = "https://pt.aliexpress.com" + link

            if title and link:
                items.append({
                    "store": "AliExpress",
                    "title": title,
                    "price": price,
                    "link": link,
                })

    except Exception as e:
        print(f"Erro no AliExpress para '{query}': {e}")

    return deduplicate_items(items)


def search_shopee(query):
    items = []
    url = f"https://shopee.com.br/search?keyword={quote_plus(query)}"

    try:
        html_text = fetch_html(url)
        soup = BeautifulSoup(html_text, "lxml")

        cards = soup.select('a[href*="-i."]')

        for card in cards:
            title = normalize_text(card.get("title") or card.get_text())
            link = card.get("href", "")
            price = None

            if link and not link.startswith("http"):
                link = "https://shopee.com.br" + link

            if title and link:
                items.append({
                    "store": "Shopee",
                    "title": title,
                    "price": price,
                    "link": link,
                })

    except Exception as e:
        print(f"Erro na Shopee para '{query}': {e}")

    return deduplicate_items(items)

def search_pichau(query):
    items = []
    url = f"https://www.pichau.com.br/search?q={quote_plus(query)}"

    try:
        html_text = fetch_html(url, extra_headers={
            "Referer": "https://www.pichau.com.br/",
            "Origin": "https://www.pichau.com.br",
        })
        soup = BeautifulSoup(html_text, "lxml")

        cards = soup.select("a[href*='/placa-de-video'], a[href*='/product']")

        for card in cards:
            title_el = card.select_one("h2, h3, span")
            price_el = card.select_one("span.price, span.text-price")

            title = normalize_text(title_el.get_text()) if title_el else None
            price = parse_price(price_el.get_text()) if price_el else None

            link = card.get("href")

            if link and not link.startswith("http"):
                link = "https://www.pichau.com.br" + link

            if title and link:
                items.append({
                    "store": "Pichau",
                    "title": title,
                    "price": price,
                    "link": link,
                })

    except Exception as e:
        print(f"Erro na Pichau para '{query}': {e}")

    return deduplicate_items(items)

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

            title = normalize_text(title_el.get_text()) if title_el else normalize_text(card.get_text())
            price = parse_price(price_el.get_text()) if price_el else None

            link = href if href.startswith("http") else f"https://www.kabum.com.br{href}"

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

            title = normalize_text(title_el.get_text()) if title_el else normalize_text(card.get_text())
            price = parse_price(price_el.get_text()) if price_el else None

            link = href if href.startswith("http") else f"https://www.magazineluiza.com.br{href}"

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
# COLETA / ALERTAS
# =========================

def collect_all_offers():
    all_items = []
    store_functions = [
    search_kabum,
    search_magalu,
    search_pichau,
    search_shopee,
    search_aliexpress,
]

    for term in SEARCH_TERMS:
        for fn in store_functions:
            print(f"Buscando '{term}' em {fn.__name__}...")
            try:
                results = fn(term)
                all_items.extend(results)
            except Exception as e:
                print(f"Erro em {fn.__name__} com termo '{term}': {e}")

            time.sleep(random.uniform(1.5, 4.0))

    return deduplicate_items(all_items)

def format_offer_message(item):
    if item['price'] is not None:
        price_text = f"R$ {item['price']:.2f}".replace(".", ",")
    else:
        price_text = "Preço não disponível"

    return (
        f"🔥 GPU encontrada dentro da faixa\n\n"
        f"🏪 Loja: {item['store']}\n"
        f"🎮 Produto: {item['title']}\n"
        f"💰 Preço: {price_text}\n\n"
        f"🔗 {item['link']}"
    )

def format_price_drop_message(item, drop_info):
    previous_text = f"R$ {drop_info['previous_price']:.2f}".replace(".", ",")
    current_text = f"R$ {drop_info['current_price']:.2f}".replace(".", ",")
    drop_value_text = f"R$ {drop_info['drop_value']:.2f}".replace(".", ",")
    drop_percent_text = f"{drop_info['drop_percent']:.1f}%".replace(".", ",")

    return (
        f"🔥 Queda de preço detectada\n\n"
        f"🏪 Loja: {item['store']}\n"
        f"🎮 Produto: {item['title']}\n"
        f"💰 Agora: {current_text}\n"
        f"📉 Antes: {previous_text}\n"
        f"💸 Queda: {drop_value_text} ({drop_percent_text})\n\n"
        f"🔗 {item['link']}"
    )

def process_offers():
    sent_items = load_sent_items()
    price_history = load_price_history()
    offers = collect_all_offers()

    print(f"Total de itens encontrados: {len(offers)}")
    new_count = 0

    for item in offers:
        if not is_good_offer(item["title"], item["price"]):
            continue

        drop_info = check_price_drop(item, price_history)
        pid = product_id(item["store"], item["title"], item["price"], item["link"])

        if pid in sent_items:
            continue

        message = None

        if drop_info:
            message = format_price_drop_message(item, drop_info)
        else:
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
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            print(f"Erro ao enviar mensagem no Telegram: {e}")

    save_sent_items(sent_items)
    save_price_history(price_history)
    print(f"Novas promoções enviadas: {new_count}")

# =========================
# LOOP PRINCIPAL
# =========================

def main():
    validate_env()
    print("Bot iniciado com sucesso.")

    try:
        send_telegram_message("🤖 Bot online e monitorando promoções de GPU.")
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
