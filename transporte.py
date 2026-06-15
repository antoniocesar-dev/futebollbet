# -*- coding: utf-8 -*-
"""
Camada de transporte da API do SofaScore com fallback automático.

Estratégia:
  1. Tenta `curl-cffi` (impersonate=chrome) — rápido, leve.
  2. Se tomar 403/429 (challenge do Cloudflare por fingerprint), cai
     automaticamente para um **Chrome real via Playwright**, que navega ao
     site uma vez (passa pelo desafio JS) e busca o JSON pelo contexto da
     página — carregando os cookies de verdade.

Importante: nenhum dos dois fura bloqueio por *reputação de IP* (quando o IP
inteiro é marcado após coleta pesada). Nesse caso ambos retornam 403 e só
resta esperar o IP esfriar — por isso o coletor faz backoff e a tarefa
agendada é gentil.

Exposto:
  buscar(caminho, ok_404=False) -> (status:int, data:dict|None)
  fechar()                      -> encerra o navegador Playwright se aberto
"""
import random
import sys
import time as _time

from curl_cffi import requests as _cffi

BASE = "https://www.sofascore.com/api/v1"
RATE = 1.0
_ultima = [0.0]
_sessao = _cffi.Session(impersonate="chrome")

# estado do Playwright (aberto sob demanda, reaproveitado entre chamadas)
_pw = _ctx = _page = None
_pw_indisponivel = False     # vira True se o Playwright também falhar/não instalar
_modo_pw = False             # quando True, nem tenta mais curl-cffi nesta execução

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _rate():
    esp = RATE + random.uniform(0, 0.5) - (_time.time() - _ultima[0])
    if esp > 0:
        _time.sleep(esp)
    _ultima[0] = _time.time()


# ---------------------------------------------------------------- curl-cffi
def _curl(caminho):
    try:
        r = _sessao.get(BASE + caminho, timeout=25)
        if r.status_code == 200:
            return 200, r.json()
        return r.status_code, None
    except Exception:
        return 0, None


# ---------------------------------------------------------------- playwright
def _abrir_pw(headless=True):
    """Abre o navegador uma vez. headless=True por padrão (bom p/ tarefa
    agendada); se o site exigir, dá pra trocar via abrir_navegador(headless=False)."""
    global _pw, _ctx, _page, _pw_indisponivel
    if _page is not None:
        return _page
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ! Playwright não instalado (py -m pip install playwright; "
              "py -m playwright install chromium)", file=sys.stderr)
        _pw_indisponivel = True
        return None
    try:
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"])
        _ctx = _browser.new_context(user_agent=UA, locale="pt-BR",
                                    viewport={"width": 1280, "height": 800})
        _page = _ctx.new_page()
        _page.goto("https://www.sofascore.com/",
                   wait_until="domcontentloaded", timeout=60000)
        _page.wait_for_timeout(6000)   # tempo pro Cloudflare liberar
        return _page
    except Exception as e:
        print(f"  ! falha ao abrir Playwright: {e}", file=sys.stderr)
        _pw_indisponivel = True
        return None


def _pw_get(caminho):
    page = _abrir_pw()
    if page is None:
        return 0, None
    try:
        res = page.evaluate(
            """async (url) => {
                const r = await fetch(url, {headers: {'Accept': 'application/json'}});
                const t = r.ok ? await r.text() : null;
                return {status: r.status, body: t};
            }""", BASE + caminho)
        if res["status"] == 200 and res["body"]:
            import json
            return 200, json.loads(res["body"])
        return res["status"], None
    except Exception as e:
        print(f"  ! erro no fetch via Playwright: {e}", file=sys.stderr)
        return 0, None


# ---------------------------------------------------------------- API pública
def buscar(caminho, ok_404=False):
    """Retorna (status, data|None). Faz fallback curl-cffi -> Playwright."""
    _rate()
    if _modo_pw:
        return _pw_get(caminho)

    status, data = _curl(caminho)
    if status == 200:
        return 200, data
    if status == 404 and ok_404:
        return 404, None
    if status in (403, 429) and not _pw_indisponivel:
        # challenge de fingerprint: troca pro navegador real pelo resto da execução
        print(f"  ~ curl bloqueado ({status}) — ativando Playwright…", file=sys.stderr)
        globals()["_modo_pw"] = True
        return _pw_get(caminho)
    return status, None


def fechar():
    global _pw, _ctx, _page
    try:
        if _ctx:
            _ctx.browser.close()
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _pw = _ctx = _page = None
