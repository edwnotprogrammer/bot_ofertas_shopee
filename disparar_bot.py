"""
Dispara o workflow "Bot de ofertas Shopee" do GitHub Actions pelo seu computador
(o mesmo que clicar em "Run workflow" no site).

Coloque no .env (na mesma pasta):
    GITHUB_TOKEN=seu_token_fine_grained
    GITHUB_REPO=seu_usuario/nome_do_repositorio

Uso:
    python disparar_bot.py
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")                       # ex.: edwnotprogrammer/bot-ofertas
WORKFLOW = os.getenv("GITHUB_WORKFLOW", "ofertas.yml")  # nome do arquivo do workflow
BRANCH = os.getenv("GITHUB_BRANCH", "main")


def main() -> int:
    faltando = [k for k, v in {"GITHUB_TOKEN": TOKEN, "GITHUB_REPO": REPO}.items() if not v]
    if faltando:
        print(f"Defina no .env: {', '.join(faltando)}")
        return 1

    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        resp = requests.post(url, headers=headers, json={"ref": BRANCH}, timeout=30)
    except requests.RequestException as e:
        print(f"Sem conexão com o GitHub: {e}")
        return 1

    if resp.status_code == 204:
        print("✅ Bot disparado! Em ~2 minutos as ofertas chegam no Telegram.")
        print(f"Acompanhe em: https://github.com/{REPO}/actions")
        return 0

    dicas = {
        401: "Token inválido ou expirado. Gere um novo em GitHub > Settings > Developer settings.",
        403: "O token não tem permissão. Ele precisa de 'Actions: Read and write' neste repositório.",
        404: "Repositório, arquivo do workflow ou acesso do token não encontrado. "
             "Confira GITHUB_REPO (usuario/repositorio) e se o token foi liberado para esse repositório.",
        422: "O workflow não aceita disparo manual ou a branch está errada. "
             f"Confira se o ofertas.yml tem 'workflow_dispatch' e se a branch é '{BRANCH}'.",
    }
    print(f"Erro {resp.status_code}: {dicas.get(resp.status_code, resp.text)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
