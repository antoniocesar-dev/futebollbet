# -*- coding: utf-8 -*-
"""
fbref_forca.py — força histórica dos times via FBref (site paralelo), CACHE-BASED.

REALIDADE (testada): FBref tem Cloudflare; curl-cffi E Playwright (mesmo headed)
tomam 403/"Just a moment..." — só o NAVEGADOR REAL do usuário passa. SofaScore
está bloqueado por IP. Então a arquitetura separa:
  - COLETA: pelo seu Chrome real (extensão/MCP), você abre a página da liga no
    FBref (passa o Cloudflare) e ingere a tabela "Home/Away" aqui -> cache.
  - CONSUMO: o modelo lê o cache (fbref_cache.json), sem tocar no Cloudflare.

A tabela muda devagar (1x/rodada basta). Saída compatível com o blend de força:
{lam_casa, lam_fora, n}, com a média REAL da liga (Dixon-Coles do probabilidades.py).

Uso:
  # 1) no seu Chrome, abra a tabela da liga no FBref e leia as linhas (CSV
  #    "time;hmp;hgf;hga;amp;agf;aga" por linha). Depois ingira:
  py bet365/fbref_forca.py ingerir "Premier League" arquivo.csv
  echo "...csv..." | py bet365/fbref_forca.py ingerir "Premier League" -
  # 2) consumir:
  py bet365/fbref_forca.py forca "Premier League" "Arsenal" "Chelsea"
  py bet365/fbref_forca.py tabela "Premier League"
  py bet365/fbref_forca.py ligas

Fallback (geralmente bloqueado pelo Cloudflare): --fetch <url> tenta Playwright.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sofascore_live import normalizar  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PASTA = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(PASTA, "fbref_cache.json")

# URL FBref de cada liga (pra você abrir no Chrome e coletar a tabela Home/Away)
LIGAS_URL = {
    "premier league":   "https://fbref.com/en/comps/9/Premier-League-Stats",
    "brasileirao":      "https://fbref.com/en/comps/24/Serie-A-Stats",
    "serie a":          "https://fbref.com/en/comps/24/Serie-A-Stats",
    "serie b":          "https://fbref.com/en/comps/38/Serie-B-Stats",
    "la liga":          "https://fbref.com/en/comps/12/La-Liga-Stats",
    "bundesliga":       "https://fbref.com/en/comps/20/Bundesliga-Stats",
    "ligue 1":          "https://fbref.com/en/comps/13/Ligue-1-Stats",
    "serie a italia":   "https://fbref.com/en/comps/11/Serie-A-Stats",
    "veikkausliiga":    "https://fbref.com/en/comps/43/Veikkausliiga-Stats",
    "ykkonen":          "https://fbref.com/en/comps/79/Ykkonen-Stats",
    "primeira liga":    "https://fbref.com/en/comps/32/Primeira-Liga-Stats",
    "eredivisie":       "https://fbref.com/en/comps/23/Eredivisie-Stats",
    "championship":     "https://fbref.com/en/comps/10/Championship-Stats",
    "liga profesional": "https://fbref.com/en/comps/21/Primera-Division-Stats",
    "super lig":        "https://fbref.com/en/comps/26/Super-Lig-Stats",
    "belgian pro league":"https://fbref.com/en/comps/37/Belgian-Pro-League-Stats",
    "liga mx":          "https://fbref.com/en/comps/31/Liga-MX-Stats",
    "major league soccer":"https://fbref.com/en/comps/22/Major-League-Soccer-Stats",
    "scottish premiership":"https://fbref.com/en/comps/40/Scottish-Premiership-Stats",
}

# JS pra colar no Console do FBref (apos o Cloudflare liberar) e copiar a saida:
JS_COLETA = (
    "[...document.querySelectorAll('table')].find(x=>/_home_away$/.test(x.id))"
    ".querySelectorAll('tbody tr')&&(()=>{const t=[...document.querySelectorAll('table')]"
    ".find(x=>/_home_away$/.test(x.id));const L=[];for(const tr of t.querySelectorAll('tbody tr'))"
    "{if(tr.classList.contains('thead'))continue;const g=k=>{const c=tr.querySelector(`[data-stat=\"${k}\"]`);"
    "return c?c.textContent.trim():'';};const n=g('team');if(!n)continue;"
    "L.push([n,g('home_games'),g('home_goals_for'),g('home_goals_against'),"
    "g('away_games'),g('away_goals_for'),g('away_goals_against')].join(';'));}return L.join('\\n');})()"
)


def _carregar():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _salvar(d):
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def ingerir(liga, csv_texto):
    """Ingere a tabela Home/Away (CSV time;hmp;hgf;hga;amp;agf;aga) no cache."""
    times = {}
    for ln in csv_texto.strip().splitlines():
        p = [x.strip() for x in ln.split(";")]
        if len(p) < 7 or not p[1].isdigit():
            continue
        nome = p[0]
        times[normalizar(nome)] = {"team": nome, "hmp": int(p[1]), "hgf": int(p[2]),
                                   "hga": int(p[3]), "amp": int(p[4]), "agf": int(p[5]), "aga": int(p[6])}
    if not times:
        return 0
    th = sum(t["hgf"] for t in times.values()); tj = sum(t["hmp"] for t in times.values()) or 1
    ta = sum(t["agf"] for t in times.values()); tja = sum(t["amp"] for t in times.values()) or 1
    d = _carregar()
    d[normalizar(liga)] = {"liga": liga, "media": {"casa": th / tj, "fora": ta / tja},
                           "atualizado": time.strftime("%Y-%m-%d"), "times": times}
    _salvar(d)
    return len(times)


def _achar_time(d, nome):
    """Acha um time em QUALQUER liga do cache -> (info_liga, registro). Por-time."""
    nn = normalizar(nome)
    for info in d.values():
        if nn in info["times"]:
            return info, info["times"][nn]
    # tenta match por contenção (nomes parciais bet365 x FBref)
    for info in d.values():
        for k, r in info["times"].items():
            if nn and (nn in k or k in nn):
                return info, r
    return None, None


def forca_times(casa, fora):
    """{lam_casa, lam_fora, n} buscando cada time em QUALQUER liga cacheada (cross-liga,
    serve até pra copa entre divisões). Cada lado usa o baseline da PRÓPRIA liga."""
    d = _carregar()
    lc, c = _achar_time(d, casa)
    lf, f = _achar_time(d, fora)
    if not c or not f or c["hmp"] < 3 or f["amp"] < 3:
        return {"erro": "time(s) sem dado", "casa_achou": bool(c), "fora_achou": bool(f)}
    mc, mf = lc["media"]["casa"], lf["media"]["fora"]
    atq_c, def_c = c["hgf"] / c["hmp"], c["hga"] / c["hmp"]
    atq_f, def_f = f["agf"] / f["amp"], f["aga"] / f["amp"]
    return {"lam_casa": round(atq_c * def_f / mc, 3), "lam_fora": round(atq_f * def_c / mf, 3),
            "n": min(c["hmp"], f["amp"], 19),
            "liga_casa": lc["liga"], "liga_fora": lf["liga"]}


def forca_confronto(liga, casa, fora):
    """{lam_casa, lam_fora, n} do confronto, do cache FBref. None se faltar dado."""
    d = _carregar().get(normalizar(liga))
    if not d:
        return None
    c, f = d["times"].get(normalizar(casa)), d["times"].get(normalizar(fora))
    if not c or not f or c["hmp"] < 3 or f["amp"] < 3:
        return None
    mc, mf = d["media"]["casa"], d["media"]["fora"]
    atq_c, def_c = c["hgf"] / c["hmp"], c["hga"] / c["hmp"]
    atq_f, def_f = f["agf"] / f["amp"], f["aga"] / f["amp"]
    return {"lam_casa": round(atq_c * def_f / mc, 3), "lam_fora": round(atq_f * def_c / mf, 3),
            "n": min(c["hmp"], f["amp"], 19)}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("ingerir"); pi.add_argument("liga"); pi.add_argument("arquivo", help="CSV ou '-' p/ stdin")
    pa = sub.add_parser("ingerir-arquivo"); pa.add_argument("arquivo", help="UTF-8, secoes '# Liga' + linhas CSV")
    pf = sub.add_parser("forca"); pf.add_argument("liga"); pf.add_argument("casa"); pf.add_argument("fora")
    p2 = sub.add_parser("times"); p2.add_argument("casa"); p2.add_argument("fora")  # busca em qualquer liga
    pt = sub.add_parser("tabela"); pt.add_argument("liga")
    sub.add_parser("ligas")
    pj = sub.add_parser("js")  # imprime o JS de coleta + a URL da liga
    pj.add_argument("liga")
    a = ap.parse_args()

    if a.cmd == "ingerir":
        txt = sys.stdin.read() if a.arquivo == "-" else open(a.arquivo, encoding="utf-8").read()
        n = ingerir(a.liga, txt)
        print(f"ingeridos {n} times em '{a.liga}'" if n else "nada ingerido (CSV vazio/invalido)")
    elif a.cmd == "ingerir-arquivo":
        txt = open(a.arquivo, encoding="utf-8").read()
        liga, buf = None, []
        def flush():
            if liga and buf:
                print(f"  {ingerir(liga, '\n'.join(buf))} times em '{liga}'")
        for ln in txt.splitlines():
            if ln.startswith("#"):
                flush(); liga = ln[1:].strip(); buf = []
            elif ln.strip():
                buf.append(ln)
        flush()
    elif a.cmd == "forca":
        print(forca_confronto(a.liga, a.casa, a.fora))
    elif a.cmd == "times":
        print(forca_times(a.casa, a.fora))
    elif a.cmd == "tabela":
        d = _carregar().get(normalizar(a.liga))
        if not d:
            print("liga nao está no cache — colete pelo Chrome e ingira"); return
        print(f"{d['liga']} | {len(d['times'])} times | atualizado {d['atualizado']} | "
              f"media casa {d['media']['casa']:.2f} fora {d['media']['fora']:.2f}")
    elif a.cmd == "ligas":
        d = _carregar()
        print("Em cache:", ", ".join(v["liga"] for v in d.values()) or "(nenhuma)")
        print("URLs FBref conhecidas:")
        for k, u in LIGAS_URL.items():
            print(f"  {k:18} {u}")
    elif a.cmd == "js":
        url = LIGAS_URL.get(normalizar(a.liga))
        print("1) Abra no seu Chrome:", url or "(liga sem URL mapeada)")
        print("2) Console (F12), cole e copie a saida:")
        print(JS_COLETA)
        print("3) py bet365/fbref_forca.py ingerir \"%s\" arquivo.csv" % a.liga)


if __name__ == "__main__":
    main()
