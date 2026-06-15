# 🗺️ Mapeamento completo do SofaScore — dados, API e integração

> Levantado em 10/06/2026 navegando no site real e capturando o tráfego de rede.
> Objetivo: alimentar um banco de dados local para calcular probabilidades de vitória.

---

## 1. Como o site funciona por baixo dos panos

- O site é uma aplicação Next.js renderizada no servidor. **Toda informação visível vem de uma API JSON interna**: `https://www.sofascore.com/api/v1/...` (o host antigo `api.sofascore.com/api/v1/...` ainda existe e responde igual).
- Imagens/escudos vêm de `https://img.sofascore.com/api/v1/...` (ex.: `/team/{id}/image`, `/player/{id}/image`).
- **Não há chave de API nem autenticação** — mas há proteção Cloudflare contra robôs:
  - ❌ `Invoke-WebRequest` / `requests` puro / `curl` → **403 Forbidden** (testado)
  - ✅ Python + **`curl-cffi`** com `impersonate="chrome"` → **200 OK** (testado e funcionando nesta máquina)

```python
from curl_cffi import requests
r = requests.get("https://www.sofascore.com/api/v1/event/15526111/statistics",
                 impersonate="chrome")
print(r.json())
```

⚠️ **Nota legal**: a API é não-documentada e os Termos de Uso do SofaScore proíbem uso comercial dos dados. Para uso pessoal/estudo, mantenha um ritmo educado (1 requisição/segundo, cache local — o coletor já faz isso).

---

## 2. Mapa do site → de onde vem cada informação

### 2.1 Página inicial (lista de jogos do dia)
| O que aparece na tela | Endpoint da API |
|---|---|
| Jogos do dia (agendados/encerrados) | `/api/v1/sport/football/scheduled-events/{AAAA-MM-DD}` |
| Jogos ao vivo agora | `/api/v1/sport/football/events/live` |
| Contador de jogos por esporte | `/api/v1/sport/{offset-fuso}/event-count` |

### 2.2 Página da partida — aba **Details** (pré-jogo)
| O que aparece | Endpoint |
|---|---|
| Placar, status, times, árbitro, estádio, rodada | `/api/v1/event/{id}` |
| **Odds 1X2 e todos os mercados** (full time, dupla chance, ambas marcam, over/under, handicap asiático, escanteios, cartões) | `/api/v1/event/{id}/odds/1/all` |
| Forma recente dos dois times (últimos 5 + rating médio + posição) | `/api/v1/event/{id}/pregame-form` |
| Retrospecto do confronto (vitórias de cada lado, empates) | `/api/v1/event/{id}/h2h` |
| Lista de confrontos diretos anteriores | `/api/v1/event/{customId}/h2h/events` *(usa o customId alfanumérico)* |
| Enquete "Quem vai ganhar" (votos da torcida) | `/api/v1/event/{id}/votes` |
| Sequências/streaks ("3 jogos sem perder" etc.) | `/api/v1/event/{id}/team-streaks` |
| Técnicos | `/api/v1/event/{id}/managers` |
| Lesões e suspensões | vem dentro de `/api/v1/event/{id}` + `featured-players` dos times |
| Onde assistir (canais de TV) | `/api/v1/tv/event/{id}/country-channels` |

### 2.3 Página da partida — aba **Statistics** (durante/pós-jogo)
| O que aparece | Endpoint |
|---|---|
| **Estatísticas completas** por período (ALL/1ST/2ND): posse, **xG**, big chances, chutes (no alvo/fora/bloqueados/dentro da área), passes certos, escanteios, faltas, duelos, desarmes, defesas, "goals prevented" | `/api/v1/event/{id}/statistics` |
| **Mapa de chutes com xG e xGOT por chute** (coordenadas, parte do corpo, situação) | `/api/v1/event/{id}/shotmap` |
| Mapa de calor por time | `/api/v1/event/{id}/heatmap/{teamId}` |
| **Gráfico de probabilidade de vitória ao vivo** (o modelo do próprio SofaScore, só existe durante o jogo) | `/api/v1/event/{id}/graph/win-probability` |
| Gráfico de pressão/momentum | `/api/v1/event/{id}/graph` |

### 2.4 Página da partida — aba **Lineups**
| O que aparece | Endpoint |
|---|---|
| Escalações, formação tática (4-2-3-1 etc.), **nota SofaScore de cada jogador** + ~25 estatísticas individuais (passes, xA, toques, recuperações, minutos) | `/api/v1/event/{id}/lineups` |
| Posição média dos jogadores em campo | `/api/v1/event/{id}/average-positions` |
| Melhores jogadores da partida | `/api/v1/event/{id}/best-players/summary` |
| Heatmap individual do jogador na partida | `/api/v1/event/{id}/player/{playerId}/heatmap` |

### 2.5 Página da partida — abas **Standings / H2H / Media**
| O que aparece | Endpoint |
|---|---|
| Tabela de classificação (geral/casa/fora) | `/api/v1/tournament/{tId}/season/{sId}/standings/{total\|home\|away}` ou `/api/v1/unique-tournament/{utId}/season/{sId}/standings/total` |
| Jogos por rodada da liga | `/api/v1/tournament/{tId}/season/{sId}/team-events/total` |
| Gráfico de desempenho do time na temporada (posição rodada a rodada) | `/api/v1/unique-tournament/{utId}/season/{sId}/team/{teamId}/team-performance-graph-data` |
| Vídeos/melhores momentos | `/api/v1/event/{id}/highlights` |

### 2.6 Página do time
| O que aparece | Endpoint |
|---|---|
| Dados do time + forma atual | `/api/v1/team/{id}` |
| Elenco completo | `/api/v1/team/{id}/players` |
| Últimos jogos (paginado) | `/api/v1/team/{id}/events/last/{página}` |
| Próximos jogos (paginado) | `/api/v1/team/{id}/events/next/{página}` |
| **Estatísticas agregadas da temporada** (~120 métricas: gols, xG implícito via chutes, posse média, duelos, clean sheets, erros que geram gol...) | `/api/v1/team/{id}/unique-tournament/{utId}/season/{sId}/statistics/overall` |
| Temporadas disponíveis para estatística | `/api/v1/team/{id}/team-statistics/seasons` |
| Distribuição de gols por faixa de minuto | `/api/v1/team/{id}/unique-tournament/{utId}/season/{sId}/goal-distributions` |
| Melhores jogadores do time na temporada | `/api/v1/team/{id}/unique-tournament/{utId}/season/{sId}/top-players/overall` |
| Jogadores destaque | `/api/v1/team/{id}/featured-players` |

### 2.7 Página do campeonato (unique-tournament)
| O que aparece | Endpoint |
|---|---|
| Info do campeonato | `/api/v1/unique-tournament/{utId}` |
| **Lista de temporadas (histórico!)** | `/api/v1/unique-tournament/{utId}/seasons` |
| Classificação | `/api/v1/unique-tournament/{utId}/season/{sId}/standings/total` |
| Rodadas | `/api/v1/unique-tournament/{utId}/season/{sId}/rounds` |
| **Jogos por rodada** (forma de baixar a temporada inteira) | `/api/v1/unique-tournament/{utId}/season/{sId}/events/round/{n}` |
| Jogos passados/futuros (paginado) | `/api/v1/unique-tournament/{utId}/season/{sId}/events/last/{página}` |
| Ranking de times da temporada | `/api/v1/unique-tournament/{utId}/season/{sId}/top-teams/overall` |
| Ranking de jogadores | `/api/v1/unique-tournament/{utId}/season/{sId}/top-players/overall` |
| Mata-mata (chaveamento) | `/api/v1/unique-tournament/{utId}/season/{sId}/cuptrees` |

### 2.8 Página do jogador e busca
| O que aparece | Endpoint |
|---|---|
| Perfil do jogador | `/api/v1/player/{id}` |
| Estatísticas do jogador na temporada | `/api/v1/player/{id}/unique-tournament/{utId}/season/{sId}/statistics/overall` |
| Últimos jogos do jogador | `/api/v1/player/{id}/events/last/{página}` |
| Atributos (radar) | `/api/v1/player/{id}/attribute-overviews` |
| **Busca global** (times, jogadores, torneios) | `/api/v1/search/all?q={termo}&page=0` |

---

## 3. IDs importantes (Brasil)

| Entidade | ID |
|---|---|
| Brasileirão Série A (unique-tournament) | **325** |
| Brasileirão Série B (unique-tournament) | **390** |
| Temporada Série B 2026 | **89840** |
| Copa do Brasil | 373 |
| Libertadores | 384 |
| Premier League | 17 · La Liga 8 · Champions 7 |
| Ceará (exemplo de time) | 2001 |

> Para descobrir qualquer ID: use a busca `/api/v1/search/all?q=nome` ou abra a página no site — o ID está na URL e no hash (`#id:15526111`).

---

## 4. Estruturas JSON principais (amostras reais em `amostras/`)

- **`event`**: `id`, `customId`, `homeTeam/awayTeam` (id, name), `homeScore/awayScore` (`current`, `period1`, `period2`), `status.type` (`notstarted|inprogress|finished`), `winnerCode` (1=casa, 2=fora, 3=empate), `startTimestamp`, `tournament`, `season`, `roundInfo.round`, `hasXg`, `referee`, `venue`.
- **`statistics`**: lista de períodos (`ALL/1ST/2ND`) → grupos (`Match overview`, `Shots`, `Attack`, `Passes`, `Duels`, `Defending`, `Goalkeeping`) → itens com `name`, `home`, `away`, `homeValue`, `awayValue` (Expected goals está em `Match overview`).
- **`lineups`**: por time → `formation` + `players[]` com `player`, `position`, `substitute`, `statistics` (rating, minutesPlayed, expectedAssists, touches...).
- **`shotmap`**: cada chute com `xg`, `xgot`, `playerCoordinates`, `bodyPart`, `situation`, `shotType`, `time`.
- **`odds /1/all`**: `markets[]` com `marketName` (Full time, Double chance, Both teams to score, Match goals = over/under...) e `choices[]` com `name` e valor **fracionário** (`fractionalValue: "19/25"` → decimal = 19/25 + 1 = 1.76; `initialFractionalValue` = odd de abertura).
- **`standings`**: `rows[]` com `team`, `position`, `matches`, `wins`, `draws`, `losses`, `scoresFor`, `scoresAgainst`, `points`.
- **`pregame-form`**: por time → `form: ["W","L","D",...]`, `avgRating`, `position`, `value`.

---

## 5. Arquitetura proposta do seu sistema

```
┌─────────────┐   curl-cffi    ┌──────────────┐    SQL     ┌──────────────────┐
│  SofaScore   │ ────────────▶ │  coletor.py  │ ─────────▶ │  futebol.db      │
│  API v1      │   1 req/s     │  (agendável) │            │  (SQLite)        │
└─────────────┘                └──────────────┘            └────────┬─────────┘
                                                                    │
                                                          ┌─────────▼─────────┐
                                                          │ probabilidades.py │
                                                          │ Poisson + odds    │
                                                          └───────────────────┘
```

Arquivos deste projeto:
- **`schema.sql`** — modelo do banco (SQLite, fácil migrar p/ Postgres).
- **`coletor.py`** — baixa temporadas inteiras, partidas, estatísticas, odds e classificação para o banco.
- **`probabilidades.py`** — calcula P(vitória casa / empate / vitória fora) combinando modelo de Poisson (força de ataque/defesa) com probabilidade implícita das odds.
- **`amostras/`** — 16 JSONs reais da API para consulta de estrutura.

## 6. Sinais disponíveis para o seu modelo de probabilidade

1. **Odds de mercado** (melhor preditor isolado): probabilidade implícita = `1/odd_decimal`, normalizada para remover a margem da casa.
2. **Força de ataque/defesa via Poisson**: média de gols marcados/sofridos casa-fora (das tabelas `evento` e `classificacao`).
3. **xG agregado** (`evento_estatisticas` / `shotmap`): qualidade de chances, menos ruidoso que gols.
4. **Forma recente** (`pregame-form`, últimos 5) e **streaks**.
5. **H2H** (retrospecto direto).
6. **Ratings SofaScore** dos jogadores escalados (`lineups`) — captura desfalques.
7. **Voto da torcida** (`votes`) — sentimento, fraco mas disponível.
