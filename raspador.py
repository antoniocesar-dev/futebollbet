# -*- coding: utf-8 -*-
"""
Raspador via navegador real (Playwright) — pega TUDO de cada partida.

Para cada evento:
  1. Navega na página da partida — o HTML traz dados embutidos (__NEXT_DATA__:
     evento + incidentes) que passam pelo Cloudflare mesmo quando a API está
     bloqueada por fingerprint.
  2. Pela mesma página (sessão real, com cookies), busca os endpoints pesados
     — estatísticas, escalações+notas, shotmap (xG), odds, forma, H2H, votos.
     Quando o IP está saudável, retornam 200 e capturamos tudo; quando o IP
     está em bloqueio duro, degradam sem quebrar (fica só a camada embutida).

Tudo é gravado no mesmo futebol.db, via gravar.py (compartilhado com coletor.py).

Uso:
  py raspador.py evento 15526111
  py raspador.py pendentes --limite 100      # encerrados sem estatísticas
  py raspador.py pendentes                    # todos os pendentes
  py raspador.py --headless evento 15526111   # sem janela (menos eficaz no CF)

Requisito: py -m pip install playwright ; py -m playwright install chromium
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import time as _time

import gravar

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PASTA = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(PASTA, "futebol.db")
SITE = "https://www.sofascore.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


# ----------------------------------------------------------------- DB
def conectar():
    novo = not os.path.exists(DB)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    # garante schema (inclui tabela incidente nova)
    with open(os.path.join(PASTA, "schema.sql"), encoding="utf-8") as f:
        con.executescript(f.read())
    return con


# ----------------------------------------------------------------- navegador
class Navegador:
    def __init__(self, headless=False):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"])
        self._ctx = self._browser.new_context(
            user_agent=UA, locale="pt-BR", viewport={"width": 1366, "height": 900})
        self.page = self._ctx.new_page()
        # passa uma vez pela home p/ assentar cookies/sessão
        self.page.goto(SITE + "/", wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(5000)

    def next_data(self):
        """Lê o pageProps embutido no HTML da página atual (sem tocar na API)."""
        return self.page.evaluate(
            """() => { const n = document.getElementById('__NEXT_DATA__');
                if(!n) return null;
                try { return JSON.parse(n.textContent).props.pageProps; }
                catch(e){ return null; } }""")

    def fechar(self):
        try:
            self._ctx.browser.close()
            self._pw.stop()
        except Exception:
            pass


# ----------------------------------------------------------------- raspagem
ABAS = ["Statistics", "Lineups", "Odds", "H2H", "Estatísticas", "Escalações", "Probabilidades"]


def raspar_evento(con, nav, eid, custom_id, casa_id, fora_id):
    """Navega na partida, clica nas abas e CAPTURA as respostas que a própria
    página carrega (passam pelo Cloudflare). Grava tudo no banco."""
    page = nav.page
    chave = f"/api/v1/event/{eid}/"
    capturado = {}

    def on_resp(resp):
        u = resp.url
        if chave in u and resp.status == 200:
            tipo = u.split(chave)[1].split("?")[0]
            try:
                capturado[tipo] = resp.json()
            except Exception:
                pass

    page.on("response", on_resp)
    try:
        url = f"{SITE}/football/match/match/{custom_id}#id:{eid}" if custom_id \
            else f"{SITE}/football/match/match/{eid}"
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)              # deixa carregar a visão inicial

        # dados embutidos no HTML (evento + incidentes), sempre disponíveis
        pp = nav.next_data() or {}
        ev = pp.get("event")
        if ev:
            gravar.gravar_evento(con, ev)
            casa_id = casa_id or ev.get("homeTeam", {}).get("id")
            fora_id = fora_id or ev.get("awayTeam", {}).get("id")

        # clica nas abas pra forçar a página a buscar estatísticas/odds/h2h/shotmap
        for nome in ABAS:
            try:
                page.get_by_text(nome, exact=True).first.click(timeout=2500)
                page.wait_for_timeout(2800)
            except Exception:
                pass
        page.wait_for_timeout(1500)
    finally:
        page.remove_listener("response", on_resp)

    # grava tudo que a página carregou
    p = {}
    p["incid"] = gravar.gravar_incidentes(con, eid,
                                          capturado.get("incidents") or pp.get("incidents"))
    p["stats"] = gravar.gravar_estatisticas(con, eid, capturado.get("statistics"))
    p["chutes"] = gravar.gravar_shotmap(con, eid, capturado.get("shotmap"))
    p["escal"] = gravar.gravar_lineups(con, eid, casa_id, fora_id, capturado.get("lineups"))
    p["odds"] = gravar.gravar_odds(con, eid, capturado.get("odds/1/all"))
    gravar.gravar_prejogo(con, eid, capturado.get("pregame-form"),
                          capturado.get("h2h"), capturado.get("votes"))
    con.commit()
    print(f"  evento {eid}: " + ", ".join(f"{k}={v}" for k, v in p.items())
          + f"  (endpoints 200: {len(capturado)})")
    _time.sleep(2.0 + random.uniform(0, 2.0))   # pausa humana entre partidas


def pendentes(con, nav, limite=None):
    ids = con.execute(
        """SELECT e.id, e.custom_id, e.casa_id, e.fora_id FROM evento e
           WHERE e.status='finished'
             AND NOT EXISTS (SELECT 1 FROM evento_estatistica s WHERE s.evento_id=e.id)
           ORDER BY e.inicio_ts DESC""").fetchall()
    total = len(ids)
    if limite:
        ids = ids[:limite]
    print(f"{total} encerrados sem detalhes — raspando {len(ids)}.")
    for i, row in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}]", end=" ")
        raspar_evento(con, nav, *row)


def raspar_incidentes(con, nav, eid, custom_id):
    """LEVE: navega na partida e grava só evento + incidentes do __NEXT_DATA__
    (sem clicar abas). Rápido e leve no Cloudflare — ideal p/ backfill de minutagem
    de gols em volume. Use quando só interessa o placar minuto-a-minuto."""
    page = nav.page
    url = f"{SITE}/football/match/match/{custom_id}#id:{eid}" if custom_id \
        else f"{SITE}/football/match/match/{eid}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)              # deixa o __NEXT_DATA__ hidratar
    pp = nav.next_data() or {}
    ev = pp.get("event")
    if ev:
        gravar.gravar_evento(con, ev)
    n = gravar.gravar_incidentes(con, eid, pp.get("incidents"))
    con.commit()
    print(f"  evento {eid}: incid={n}")
    _time.sleep(1.5 + random.uniform(0, 1.5))   # pausa humana
    return n


def pendentes_incidentes(con, nav, limite=None):
    ids = con.execute(
        """SELECT e.id, e.custom_id FROM evento e
           WHERE e.status='finished'
             AND NOT EXISTS (SELECT 1 FROM incidente i WHERE i.evento_id=e.id)
           ORDER BY e.inicio_ts DESC""").fetchall()
    total = len(ids)
    if limite:
        ids = ids[:limite]
    print(f"{total} finalizados sem minutagem — raspando {len(ids)} (modo leve).")
    ok = 0
    for i, row in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}]", end=" ")
        try:
            if raspar_incidentes(con, nav, *row):
                ok += 1
        except Exception as e:
            print(f"  evento {row[0]}: ERRO {e}")
    print(f"Concluído: {ok}/{len(ids)} com gols mapeados.")


def backfill(limite=None, headless=True):
    """Entrada reaproveitável (ex.: manutencao.py): raspa os pendentes."""
    con = conectar()
    nav = Navegador(headless=headless)
    try:
        pendentes(con, nav, limite)
    finally:
        con.close()
        nav.fechar()


def backfill_incidentes(limite=None, headless=True):
    """Backfill leve só de incidentes (minutagem de gols) em volume."""
    con = conectar()
    nav = Navegador(headless=headless)
    try:
        pendentes_incidentes(con, nav, limite)
    finally:
        con.close()
        nav.fechar()


def main():
    ap = argparse.ArgumentParser(description="Raspador SofaScore via navegador")
    ap.add_argument("--headless", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("evento");    p.add_argument("evento_id", type=int)
    p = sub.add_parser("pendentes"); p.add_argument("--limite", type=int, default=None)
    p = sub.add_parser("incidentes"); p.add_argument("--limite", type=int, default=None)
    a = ap.parse_args()

    con = conectar()
    nav = Navegador(headless=a.headless)
    try:
        if a.cmd == "evento":
            row = con.execute(
                "SELECT id, custom_id, casa_id, fora_id FROM evento WHERE id=?",
                (a.evento_id,)).fetchone()
            if not row:
                print("Evento não está no banco — colete a lista da liga antes.")
            else:
                raspar_evento(con, nav, *row)
        elif a.cmd == "pendentes":
            pendentes(con, nav, a.limite)
        elif a.cmd == "incidentes":
            pendentes_incidentes(con, nav, a.limite)
    finally:
        con.close()
        nav.fechar()


if __name__ == "__main__":
    main()
