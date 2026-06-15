# -*- coding: utf-8 -*-
"""
Coletor SofaScore -> futebol.db (SQLite)

Uso:
  py coletor.py dia 2026-06-09                  # jogos de um dia (todos os campeonatos)
  py coletor.py temporada 390 89840             # todos os jogos da Série B 2026
  py coletor.py temporada 390 89840 --detalhes  # + estatísticas/odds/escalações dos encerrados
  py coletor.py classificacao 390 89840         # tabela de classificação
  py coletor.py detalhes 15526111               # detalhes de uma partida específica
  py coletor.py pendentes                       # baixa detalhes de jogos encerrados ainda sem stats

Requisito:  py -m pip install curl-cffi playwright  (e: py -m playwright install chromium)
"""
import argparse
import json
import os
import sqlite3
import sys
import time as _time

import transporte   # camada de rede: curl-cffi -> fallback Playwright

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PASTA = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(PASTA, "futebol.db")


# ----------------------------------------------------------------- API
def api(caminho, ok_404=False):
    """GET na API via camada de transporte (curl-cffi -> fallback Playwright),
    com retry e backoff. Em 403/429 persistente (bloqueio por IP), recua de
    forma agressiva — esse bloqueio libera sozinho; insistir rápido só piora."""
    for tentativa in range(4):
        status, data = transporte.buscar(caminho, ok_404=ok_404)
        if status == 200:
            return data
        if status == 404 and ok_404:
            return None
        if status in (403, 429):
            recuo = [15, 60, 180, 300][min(tentativa, 3)]
            print(f"  ~ {status} em {caminho} — aguardando {recuo}s",
                  file=sys.stderr)
            _time.sleep(recuo)
            continue
        return None
    print(f"  ! falha em {caminho}", file=sys.stderr)
    return None


def odd_decimal(frac):
    """'19/25' -> 1.76 ; None -> None"""
    if not frac:
        return None
    try:
        num, den = frac.split("/")
        return round(int(num) / int(den) + 1, 4)
    except Exception:
        return None


# ----------------------------------------------------------------- DB
def conectar():
    novo = not os.path.exists(DB)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    if novo or not con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='evento'").fetchone():
        with open(os.path.join(PASTA, "schema.sql"), encoding="utf-8") as f:
            con.executescript(f.read())
    return con


def upsert_time(con, t):
    if not t:
        return None
    con.execute(
        "INSERT INTO time (id, nome, nome_curto, slug, pais) VALUES (?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET nome=excluded.nome",
        (t["id"], t.get("name"), t.get("shortName"), t.get("slug"),
         (t.get("country") or {}).get("name")))
    return t["id"]


def upsert_evento(con, ev):
    """Insere/atualiza um evento vindo de qualquer endpoint de lista."""
    ut = (ev.get("tournament") or {}).get("uniqueTournament") or {}
    if ut.get("id"):
        con.execute(
            "INSERT INTO torneio (id, nome, slug, pais) VALUES (?,?,?,?) "
            "ON CONFLICT(id) DO NOTHING",
            (ut["id"], ut.get("name"), ut.get("slug"),
             (ut.get("category") or {}).get("name")))
    se = ev.get("season") or {}
    if se.get("id") and ut.get("id"):
        con.execute(
            "INSERT INTO temporada (id, torneio_id, nome, ano) VALUES (?,?,?,?) "
            "ON CONFLICT(id) DO NOTHING",
            (se["id"], ut["id"], se.get("name"), se.get("year")))
    casa = upsert_time(con, ev.get("homeTeam"))
    fora = upsert_time(con, ev.get("awayTeam"))
    hs, as_ = ev.get("homeScore") or {}, ev.get("awayScore") or {}
    con.execute(
        """INSERT INTO evento (id, custom_id, temporada_id, torneio_id, rodada,
               casa_id, fora_id, inicio_ts, status, vencedor,
               gols_casa, gols_fora, gols_casa_1t, gols_fora_1t, tem_xg,
               arbitro, estadio, atualizado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, vencedor=excluded.vencedor,
               gols_casa=excluded.gols_casa, gols_fora=excluded.gols_fora,
               gols_casa_1t=excluded.gols_casa_1t, gols_fora_1t=excluded.gols_fora_1t,
               tem_xg=excluded.tem_xg, atualizado_em=datetime('now')""",
        (ev["id"], ev.get("customId"), se.get("id"), ut.get("id"),
         (ev.get("roundInfo") or {}).get("round"), casa, fora,
         ev.get("startTimestamp"), (ev.get("status") or {}).get("type"),
         ev.get("winnerCode"), hs.get("current"), as_.get("current"),
         hs.get("period1"), as_.get("period1"),
         1 if ev.get("hasXg") else 0,
         (ev.get("referee") or {}).get("name"),
         (ev.get("venue") or {}).get("name")))
    return ev["id"]


# ----------------------------------------------------------------- coletas
def coletar_dia(con, data):
    d = api(f"/sport/football/scheduled-events/{data}")
    if not d:
        return
    for ev in d.get("events", []):
        upsert_evento(con, ev)
    con.commit()
    print(f"{len(d.get('events', []))} jogos de {data} gravados.")


def coletar_temporada(con, ut_id, season_id, detalhes=False):
    total = 0
    for direcao in ("last", "next"):
        pagina = 0
        while True:
            d = api(f"/unique-tournament/{ut_id}/season/{season_id}"
                    f"/events/{direcao}/{pagina}", ok_404=True)
            if not d or not d.get("events"):
                break
            for ev in d["events"]:
                upsert_evento(con, ev)
                total += 1
            con.commit()
            print(f"  página {direcao}/{pagina}: {len(d['events'])} jogos")
            if not d.get("hasNextPage"):
                break
            pagina += 1
    print(f"{total} jogos da temporada {season_id} gravados.")
    if detalhes:
        coletar_pendentes(con)


def coletar_classificacao(con, ut_id, season_id):
    d = api(f"/unique-tournament/{ut_id}/season/{season_id}/standings/total")
    if not d:
        return
    for grupo in d.get("standings", []):
        for r in grupo.get("rows", []):
            upsert_time(con, r.get("team"))
            con.execute(
                """INSERT INTO classificacao (temporada_id, time_id, tipo, posicao,
                       jogos, vitorias, empates, derrotas, gols_pro, gols_contra,
                       pontos, coletado_em)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(temporada_id, time_id, tipo) DO UPDATE SET
                       posicao=excluded.posicao, jogos=excluded.jogos,
                       vitorias=excluded.vitorias, empates=excluded.empates,
                       derrotas=excluded.derrotas, gols_pro=excluded.gols_pro,
                       gols_contra=excluded.gols_contra, pontos=excluded.pontos,
                       coletado_em=datetime('now')""",
                (season_id, r["team"]["id"], "total", r.get("position"),
                 r.get("matches"), r.get("wins"), r.get("draws"),
                 r.get("losses"), r.get("scoresFor"), r.get("scoresAgainst"),
                 r.get("points")))
    con.commit()
    print(f"Classificação da temporada {season_id} gravada.")


def coletar_detalhes(con, evento_id):
    """Estatísticas, shotmap, escalações, odds e contexto pré-jogo de 1 partida."""
    d = api(f"/event/{evento_id}")
    if not d:
        return
    ev = d["event"]
    upsert_evento(con, ev)
    finalizado = (ev.get("status") or {}).get("type") == "finished"

    # --- odds (existem antes e depois do jogo)
    od = api(f"/event/{evento_id}/odds/1/all", ok_404=True)
    if od:
        for m in od.get("markets", []):
            param = str(m.get("choiceGroup") or "")
            for c in m.get("choices", []):
                dec = odd_decimal(c.get("fractionalValue"))
                if dec is None:
                    continue
                con.execute(
                    """INSERT INTO odd (evento_id, mercado, parametro, escolha,
                           odd_decimal, odd_abertura, coletado_em)
                       VALUES (?,?,?,?,?,?,datetime('now'))
                       ON CONFLICT(evento_id, mercado, parametro, escolha)
                       DO UPDATE SET odd_decimal=excluded.odd_decimal,
                                     coletado_em=datetime('now')""",
                    (evento_id, m.get("marketName"), param, c.get("name"),
                     dec, odd_decimal(c.get("initialFractionalValue"))))

    # --- contexto pré-jogo
    pf = api(f"/event/{evento_id}/pregame-form", ok_404=True)
    h2h = api(f"/event/{evento_id}/h2h", ok_404=True)
    vt = api(f"/event/{evento_id}/votes", ok_404=True)
    ph, pa = (pf or {}).get("homeTeam") or {}, (pf or {}).get("awayTeam") or {}
    duel = (h2h or {}).get("teamDuel") or {}
    voto = (vt or {}).get("vote") or {}
    con.execute(
        """INSERT INTO pre_jogo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(evento_id) DO UPDATE SET
               casa_forma=excluded.casa_forma, fora_forma=excluded.fora_forma,
               votos_casa=excluded.votos_casa, votos_empate=excluded.votos_empate,
               votos_fora=excluded.votos_fora""",
        (evento_id,
         ",".join(ph.get("form") or []), ",".join(pa.get("form") or []),
         ph.get("avgRating"), pa.get("avgRating"),
         ph.get("position"), pa.get("position"),
         duel.get("homeWins"), duel.get("awayWins"), duel.get("draws"),
         voto.get("vote1"), voto.get("voteX"), voto.get("vote2")))

    if finalizado:
        # --- estatísticas por período
        st = api(f"/event/{evento_id}/statistics", ok_404=True)
        if st:
            for per in st.get("statistics", []):
                for g in per.get("groups", []):
                    for item in g.get("statisticsItems", []):
                        con.execute(
                            """INSERT OR REPLACE INTO evento_estatistica
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (evento_id, per.get("period"), g.get("groupName"),
                             item.get("name"), item.get("homeValue"),
                             item.get("awayValue"), str(item.get("home")),
                             str(item.get("away"))))

        # --- shotmap (xG por chute)
        sm = api(f"/event/{evento_id}/shotmap", ok_404=True)
        if sm:
            for s in sm.get("shotmap", []):
                p = s.get("player") or {}
                if p.get("id"):
                    con.execute(
                        "INSERT INTO jogador (id, nome, posicao) VALUES (?,?,?) "
                        "ON CONFLICT(id) DO NOTHING",
                        (p["id"], p.get("name"), p.get("position")))
                pc = s.get("playerCoordinates") or {}
                con.execute(
                    "INSERT OR REPLACE INTO chute VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s.get("id"), evento_id, p.get("id"),
                     1 if s.get("isHome") else 0, s.get("time"),
                     s.get("shotType"), s.get("situation"), s.get("bodyPart"),
                     s.get("xg"), s.get("xgot"), pc.get("x"), pc.get("y")))

        # --- escalações e notas
        ln = api(f"/event/{evento_id}/lineups", ok_404=True)
        if ln:
            for lado, time_id in (("home", ev["homeTeam"]["id"]),
                                  ("away", ev["awayTeam"]["id"])):
                bloco = ln.get(lado) or {}
                notas = []
                for pl in bloco.get("players", []):
                    p = pl.get("player") or {}
                    stt = pl.get("statistics") or {}
                    if not p.get("id"):
                        continue
                    con.execute(
                        "INSERT INTO jogador (id, nome, posicao, data_nasc) "
                        "VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING",
                        (p["id"], p.get("name"), p.get("position"),
                         p.get("dateOfBirthTimestamp")))
                    if stt.get("rating"):
                        notas.append(stt["rating"])
                    con.execute(
                        "INSERT OR REPLACE INTO escalacao VALUES (?,?,?,?,?,?,?,?)",
                        (evento_id, p["id"], time_id,
                         0 if pl.get("substitute") else 1, pl.get("position"),
                         stt.get("rating"), stt.get("minutesPlayed"),
                         stt.get("expectedAssists")))
                con.execute(
                    "INSERT OR REPLACE INTO evento_formacao VALUES (?,?,?,?)",
                    (evento_id, time_id, bloco.get("formation"),
                     round(sum(notas) / len(notas), 2) if notas else None))

    con.commit()
    print(f"Detalhes do evento {evento_id} gravados"
          f" ({'finalizado' if finalizado else 'pré-jogo'}).")


def coletar_pendentes(con, limite=None):
    """Baixa detalhes dos jogos encerrados que ainda não têm estatísticas.
    `limite` restringe quantos por execução (útil em coleta agendada gentil)."""
    ids = [r[0] for r in con.execute(
        """SELECT e.id FROM evento e
           WHERE e.status='finished'
             AND NOT EXISTS (SELECT 1 FROM evento_estatistica s
                             WHERE s.evento_id = e.id)
           ORDER BY e.inicio_ts DESC""")]   # mais recentes primeiro
    total = len(ids)
    if limite:
        ids = ids[:limite]
    print(f"{total} jogos encerrados sem detalhes — processando {len(ids)}.")
    for i, eid in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}]", end=" ")
        coletar_detalhes(con, eid)


# ----------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="Coletor SofaScore -> SQLite")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("dia");           p.add_argument("data")
    p = sub.add_parser("temporada");     p.add_argument("ut_id", type=int)
    p.add_argument("season_id", type=int); p.add_argument("--detalhes", action="store_true")
    p = sub.add_parser("classificacao"); p.add_argument("ut_id", type=int)
    p.add_argument("season_id", type=int)
    p = sub.add_parser("detalhes");      p.add_argument("evento_id", type=int)
    p = sub.add_parser("pendentes");     p.add_argument("--limite", type=int, default=None)

    a = ap.parse_args()
    con = conectar()
    try:
        if a.cmd == "dia":
            coletar_dia(con, a.data)
        elif a.cmd == "temporada":
            coletar_temporada(con, a.ut_id, a.season_id, a.detalhes)
        elif a.cmd == "classificacao":
            coletar_classificacao(con, a.ut_id, a.season_id)
        elif a.cmd == "detalhes":
            coletar_detalhes(con, a.evento_id)
        elif a.cmd == "pendentes":
            coletar_pendentes(con, a.limite)
    finally:
        con.close()
        transporte.fechar()


if __name__ == "__main__":
    main()
