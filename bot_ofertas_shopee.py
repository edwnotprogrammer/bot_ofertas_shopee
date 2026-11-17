"""
Bot de ofertas Shopee -> Telegram

Instalação:
    pip install requests python-dotenv

Crie um arquivo .env na mesma pasta com:
    SHOPEE_APP_ID=seu_app_id
    SHOPEE_SECRET=seu_secret
    TELEGRAM_TOKEN=token_do_botfather
    TELEGRAM_CHAT_ID=@seu_canal   (ou ID numérico do grupo)

Uso:
    python bot_ofertas_shopee.py
"""

import hashlib
import html
import json
import os
import random
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIGURAÇÃO ----------------
APP_ID = os.getenv("SHOPEE_APP_ID")
SECRET = os.getenv("SHOPEE_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")
# Opcional: seu chat privado com o bot, para receber cópias prontas p/ WhatsApp
TG_CHAT_WA = os.getenv("TELEGRAM_CHAT_ID_WHATSAPP")
PRODUTOS_WHATSAPP_POR_RODADA = 5  # cópias p/ WhatsApp por rodada

SHOPEE_URL = "https://open-api.affiliate.shopee.com.br/graphql"

DESCONTO_MINIMO = 20          # % mínimo de desconto
AVALIACAO_MINIMA = 4.5        # nota mínima (0 a 5)
VENDAS_MINIMAS = 100          # mínimo de vendas
PRODUTOS_POR_RODADA = 5       # ofertas por horário
INTERVALO_ENTRE_POSTS = int(os.getenv("INTERVALO_ENTRE_POSTS", "60"))  # segundos entre posts
INTERVALO_ENTRE_RODADAS = 30 * 60  # segundos (30 min)
# Cada item é uma busca. Edite à vontade; "" = geral (mais vendidos de tudo).
PALAVRAS_CHAVE = [
    "",                    # geral
    "air fryer",           # casa
    "organizador casa",
    "utensílios cozinha",
    "fone bluetooth",      # tecnologia
    "smartwatch",
    "carregador turbo",
    "luminária led",
    "kit ferramentas",     # utilidades
]

ARQUIVO_POSTADOS = Path("postados.json")


# ---------------- SHOPEE ----------------
def assinar_e_chamar(query: str) -> dict:
    """Envia uma requisição GraphQL assinada (SHA256) para a API de afiliados."""
    payload = json.dumps({"query": query}, separators=(",", ":"))
    timestamp = str(int(time.time()))
    base = f"{APP_ID}{timestamp}{payload}{SECRET}"
    assinatura = hashlib.sha256(base.encode("utf-8")).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "Authorization": (
            f"SHA256 Credential={APP_ID}, Timestamp={timestamp}, Signature={assinatura}"
        ),
    }
    r = requests.post(SHOPEE_URL, data=payload, headers=headers, timeout=30)
    r.raise_for_status()
    dados = r.json()
    if "errors" in dados:
        raise RuntimeError(f"Erro da API Shopee: {dados['errors']}")
    return dados


def buscar_produtos(palavra_chave: str = "", pagina: int = 1, limite: int = 30) -> list:
    # sortType: 1=relevância, 2=mais vendidos, 3=preço asc, 4=preço desc, 5=maior comissão
    filtro_kw = f'keyword: "{palavra_chave}",' if palavra_chave else ""
    query = f"""
    {{
      productOfferV2(
        {filtro_kw}
        sortType: 2,
        page: {pagina},
        limit: {limite}
      ) {{
        nodes {{
          itemId
          productName
          imageUrl
          priceMin
          priceMax
          priceDiscountRate
          ratingStar
          sales
          commissionRate
          shopName
          offerLink
        }}
      }}
    }}
    """
    dados = assinar_e_chamar(query)
    return dados["data"]["productOfferV2"]["nodes"]


def filtrar(produtos: list, ja_postados: set) -> list:
    aprovados = []
    for p in produtos:
        try:
            if str(p["itemId"]) in ja_postados:
                continue
            if float(p.get("priceDiscountRate") or 0) < DESCONTO_MINIMO:
                continue
            if float(p.get("ratingStar") or 0) < AVALIACAO_MINIMA:
                continue
            if int(p.get("sales") or 0) < VENDAS_MINIMAS:
                continue
            aprovados.append(p)
        except (ValueError, TypeError):
            continue
    return aprovados


# ---------------- HISTÓRICO ----------------
def carregar_postados() -> set:
    if ARQUIVO_POSTADOS.exists():
        return set(json.loads(ARQUIVO_POSTADOS.read_text()))
    return set()


def salvar_postados(ids: set) -> None:
    ARQUIVO_POSTADOS.write_text(json.dumps(sorted(ids)))


# ---------------- TELEGRAM ----------------
def formatar_preco(valor) -> str:
    try:
        v = float(valor)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "—"


def montar_legenda(p: dict) -> str:
    nome = html.escape(p["productName"][:120])
    taxa = float(p.get("priceDiscountRate") or 0)
    desconto = int(taxa)
    preco_atual = float(p["priceMin"])
    preco = formatar_preco(preco_atual)
    # A API não informa o preço original: calculamos a partir do desconto
    if 0 < taxa < 100:
        preco_antes = formatar_preco(preco_atual / (1 - taxa / 100))
    else:
        preco_antes = None
    link = p["offerLink"]
    nota = p.get("ratingStar", "")
    vendas = p.get("sales", "")

    linha_preco = (
        f"❌ De <s>{preco_antes}</s>\n✅ Por apenas <b>{preco}</b>\n"
        if preco_antes
        else f"💰 Por apenas <b>{preco}</b>\n"
    )

    return (
        f"🔥 <b>{nome}</b>\n\n"
        f"{linha_preco}"
        f"📉 {desconto}% OFF\n"
        f"⭐ Nota {nota} | 🛒 {vendas} vendidos\n\n"
        f"👉 <a href=\"{link}\">Ver oferta na Shopee</a>\n\n"
        f"<i>Link de afiliado. Preços e estoque podem mudar a qualquer momento.</i>"
    )


def botao_oferta(p: dict) -> str:
    """Botão clicável abaixo da mensagem (formato JSON exigido pelo Telegram)."""
    return json.dumps({
        "inline_keyboard": [[{"text": "🛒 Ver oferta na Shopee", "url": p["offerLink"]}]]
    })


def postar_telegram(p: dict) -> bool:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    resp = requests.post(
        url,
        data={
            "chat_id": TG_CHAT,
            "photo": p["imageUrl"],
            "caption": montar_legenda(p),
            "parse_mode": "HTML",
            "reply_markup": botao_oferta(p),
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Falha ao postar {p['itemId']}: {resp.text}")
    return resp.ok


# ---------------- CÓPIA PARA WHATSAPP (manual) ----------------
def montar_texto_whatsapp(p: dict) -> str:
    """Texto no formato do WhatsApp: *negrito*, ~riscado~."""
    nome = p["productName"][:120]
    for simbolo in "*_~":
        nome = nome.replace(simbolo, "")

    taxa = float(p.get("priceDiscountRate") or 0)
    preco_atual = float(p["priceMin"])
    preco = formatar_preco(preco_atual)

    if 0 < taxa < 100:
        antes = formatar_preco(preco_atual / (1 - taxa / 100))
        linha_preco = f"❌ De ~{antes}~\n✅ Por apenas *{preco}*\n"
    else:
        linha_preco = f"💰 Por apenas *{preco}*\n"

    return (
        f"🔥 *{nome}*\n\n"
        f"{linha_preco}"
        f"📉 {int(taxa)}% OFF\n"
        f"⭐ Nota {p.get('ratingStar', '')} | 🛒 {p.get('sales', '')} vendidos\n\n"
        f"👉 Compre aqui: {p['offerLink']}"
    )


def enviar_copia_whatsapp(p: dict) -> None:
    """Manda foto + texto (sem formatação do Telegram) para o seu chat privado."""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    resp = requests.post(
        url,
        data={
            "chat_id": TG_CHAT_WA,
            "photo": p["imageUrl"],
            "caption": montar_texto_whatsapp(p),
            "reply_markup": botao_oferta(p),
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Falha na cópia p/ WhatsApp {p['itemId']}: {resp.text}")


# ---------------- LOOP PRINCIPAL ----------------
def rodada() -> None:
    postados = carregar_postados()

    # Busca cada categoria e ordena por vendas (mais vendidos primeiro)
    listas = []
    for kw in random.sample(PALAVRAS_CHAVE, len(PALAVRAS_CHAVE)):
        try:
            lista = filtrar(buscar_produtos(kw), postados)
            lista.sort(key=lambda p: int(p.get("sales") or 0), reverse=True)
            listas.append(lista)
        except Exception as e:
            print(f"Erro ao buscar '{kw}': {e}")

    # Intercala as categorias (1 de cada por vez) e remove duplicados
    candidatos, vistos = [], set()
    for i in range(max((len(l) for l in listas), default=0)):
        for lista in listas:
            if i < len(lista) and lista[i]["itemId"] not in vistos:
                vistos.add(lista[i]["itemId"])
                candidatos.append(lista[i])

    enviados = 0
    for p in candidatos:
        if enviados >= PRODUTOS_POR_RODADA:
            break
        if postar_telegram(p):
            postados.add(str(p["itemId"]))
            salvar_postados(postados)
            enviados += 1
            if TG_CHAT_WA and enviados <= PRODUTOS_WHATSAPP_POR_RODADA:
                enviar_copia_whatsapp(p)
            print(f"Postado: {p['productName'][:60]}")
            time.sleep(INTERVALO_ENTRE_POSTS)

    print(f"Rodada concluída: {enviados} oferta(s) postada(s).")


if __name__ == "__main__":
    faltando = [k for k, v in {
        "SHOPEE_APP_ID": APP_ID, "SHOPEE_SECRET": SECRET,
        "TELEGRAM_TOKEN": TG_TOKEN, "TELEGRAM_CHAT_ID": TG_CHAT,
    }.items() if not v]
    if faltando:
        raise SystemExit(f"Defina no .env: {', '.join(faltando)}")

    if os.getenv("RODAR_UMA_VEZ"):
        # Modo GitHub Actions: executa uma rodada e encerra
        rodada()
    else:
        while True:
            rodada()
            time.sleep(INTERVALO_ENTRE_RODADAS)
