# -*- coding: utf-8 -*-
"""
ws_sniffer.py — captura a URL e os frames do WebSocket de push do bet365.

O dado ao vivo do bet365 (odds/placares) NAO vem por REST; vem por um WebSocket
proprietario. O leitor de rede do navegador nao mostra frames de WS, mas o
Playwright sim, via page.on("websocket"). Este script:

  1. Abre o Chromium (headed por padrao — o anti-bot do bet365 e mais agressivo
     com headless, igual a licao do raspador do SofaScore).
  2. Registra o listener ANTES de navegar.
  3. Vai pra pagina Ao-Vivo/Futebol e fica escutando os frames por N segundos.
  4. Imprime a URL do WS e salva os primeiros frames brutos em
     bet365/ws_frames.txt pra voce inspecionar o protocolo (delimitadores
     \\x01 \\x02 \\x08, assinatura por topicos — ver MAPEAMENTO-BET365.md).

Uso:
  py bet365/ws_sniffer.py                 # 25s, com janela
  py bet365/ws_sniffer.py --segundos 60
  py bet365/ws_sniffer.py --headless      # menos eficaz contra o anti-bot

Requisito (ja instalado no projeto): playwright + chromium
  py -m pip install playwright ; py -m playwright install chromium

AVISO: somente leitura/inspecao. Nao automatiza apostas. Respeite o ToS do bet365.
"""
import argparse
import os
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PASTA = os.path.dirname(os.path.abspath(__file__))
URL = "https://www.bet365.bet.br/#/IP/B1"
SAIDA = os.path.join(PASTA, "ws_frames.txt")
MAX_FRAMES = 60   # quantos frames brutos gravar pra inspecao


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=int, default=25, help="tempo de escuta")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    sockets = []          # urls de WS vistos
    frames = []           # (sentido, payload_repr)

    def liga_ws(ws):
        sockets.append(ws.url)
        print(f"[WS aberto] {ws.url}")

        def grava(payload, sentido):
            if len(frames) >= MAX_FRAMES:
                return
            if isinstance(payload, (bytes, bytearray)):
                rep = payload[:300].hex()
                tipo = "bin"
            else:
                rep = str(payload)[:300]
                tipo = "txt"
            frames.append(f"[{sentido} {tipo}] {rep}")

        ws.on("framereceived", lambda p: grava(p, "<<"))
        ws.on("framesent",     lambda p: grava(p, ">>"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"),
            locale="pt-BR",
        )
        page = ctx.new_page()
        page.on("websocket", liga_ws)          # ANTES de navegar
        print(f"Navegando: {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        print(f"Escutando {args.segundos}s...")
        time.sleep(args.segundos)
        browser.close()

    print("\n=== RESUMO ===")
    print(f"WebSockets vistos: {len(set(sockets))}")
    for u in sorted(set(sockets)):
        print(f"  - {u}")
    print(f"Frames capturados: {len(frames)} (salvos em {SAIDA})")
    with open(SAIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(sockets and ["URLs:"] + sorted(set(sockets)) + ["", "FRAMES:"] or [])
                + "\n" + "\n".join(frames))


if __name__ == "__main__":
    main()
