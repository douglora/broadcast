"""Taxa indicativa de debentures da ANBIMA: o arquivo diario do mercado secundario.

Por que existe: o boletim comparava debentures pela taxa media ponderada dos negocios de balcao da
B3 (`Trade`). Em papel com muito negocio pequeno essa media pende para a taxa do varejo, que compra
a taxa menor. Medido em 01/10/2026: EQPA18 (Equatorial Para, 2036) saiu a IPCA+7,70% na media de 5
pregoes da B3 e CGOS16 (Equatorial Goias, 2036) a 8,16%, sugerindo 46 pontos-base de diferenca; pela
taxa indicativa da ANBIMA de 30/09/2026 as duas estavam em 8,16% e 8,19%. A indicativa e a
referencia do mercado profissional e nao depende do tamanho dos negocios do dia.

De onde vem (sem cadastro):
  GET https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/dbAAMMDD.txt
  texto em latin-1: uma linha de titulo, uma em branco, o cabecalho e uma debenture por linha;
  campos separados por `@`; numero com virgula decimal; `--` e `N/D` quando nao ha taxa ou preco.
  Colunas: Codigo, Nome, Repac./Venc., Indice/Correcao, Taxa de Compra, Taxa de Venda, Taxa
  Indicativa, Desvio Padrao, Intervalo Indicativo Minimo e Maximo, PU, % PU Par / % VNE, Duration
  (dias uteis), % Reune, Referencia NTN-B.
  A data nao vem dentro do arquivo: e a do nome.

A taxa vem na convencao do indice do papel, a mesma do negocio da B3:
  IPCA + x%      juro real (IPCA + taxa)
  DI + x%        premio sobre o CDI
  x% do DI       percentual do CDI
  PREFIXADO x%   taxa nominal

So ha debentures (1.291 em 30/09/2026, incentivadas ou nao). CRI e CRA nao estao neste arquivo:
continuam so com os negocios da B3.

Medido em 01/10/2026:
- O arquivo do dia sai a noite: nos 13 que o servidor guardava, a hora de publicacao
  (Last-Modified) ficou entre 19h42 e 20h26 de Brasilia (o de 15/09 foi regravado na noite
  seguinte). A rodada das 21h40 costuma ja encontrar o do pregao; quando nao encontra, vale o do
  pregao anterior, com a data dele, e a rodada da manha completa.
- Arquivo que nao existe responde HTTP 404 com uma pagina HTML: e "ainda nao publicado" (ou dia
  sem publicacao). Lacuna declarada, nao erro.
- A pagina da ANBIMA diz que ficam disponiveis os ultimos 5 dias uteis; o servidor ainda tinha 13
  (14/09 a 30/09) e ja respondia 404 para 10/09 e 11/09. Nao da para refazer historico longo.
- A convencao do indice bateu com a do cadastro da B3 nos 1.202 papeis que estavam nos dois.
- Em 14 papeis a data da coluna Repac./Venc. nao e o vencimento do cadastro da B3; em 12 deles
  vem antes (repactuacao ou resgate ja marcado), e a taxa da ANBIMA vale ate essa data. E mais um
  motivo para o premio sobre o juro real usar a duration da propria ANBIMA, nao o vencimento.
- A ANBIMA as vezes retifica um numero sem republicar o arquivo (avisos na pagina do mercado
  secundario). O boletim mostra o que o arquivo trouxe.
"""

from __future__ import annotations

import re
from datetime import date
from email.utils import parsedate_to_datetime

from livro import relogios
from livro.http import Cliente, HttpError

from boletim.b3 import _pedir, sem_acento

URL = "https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db{aammdd}.txt"
FONTE = "ANBIMA, mercado secundario de debentures (taxas indicativas)"
PUBLICADO, NAO_PUBLICADO = "publicado", "nao publicado"
PAUSAS = (5.0,)             # uma nova tentativa em falha passageira; o arquivo e enriquecimento
DIAS_UTEIS_ANO = 252.0      # a duration vem em dias uteis
_FALHAS = "_falhas"         # chave do cache: o que falhou nesta rodada ({motivos por data, quantos sem rede})
MAX_SEM_REDE = 2            # dois arquivos sem resposta da rede e a rodada para de procurar a ANBIMA

# titulo da coluna (sem acento, so letras e numeros) -> campo
COLUNAS = {
    "codigo": "codigo", "nome": "nome", "repac venc": "repac_venc", "indice correcao": "indice",
    "taxa de compra": "compra", "taxa de venda": "venda", "taxa indicativa": "indicativa",
    "desvio padrao": "desvio", "intervalo indicativo minimo": "intervalo_min",
    "intervalo indicativo maximo": "intervalo_max", "pu": "pu", "pu par vne": "pct_pu_par",
    "duration": "duration_du", "reune": "pct_reune", "referencia ntn b": "ntnb_ref",
}
NUMERICAS = ("compra", "venda", "indicativa", "desvio", "intervalo_min", "intervalo_max", "pu", "pct_pu_par",
             "duration_du", "pct_reune")
OBRIGATORIAS = {"codigo", "indice", "indicativa"}
RX_TAXA = re.compile(r"(\d[\d.]*(?:,\d+)?)\s*%")
RX_NUMERO = re.compile(r"-?\d[\d.]*(?:,\d+)?")
RX_MARCA = re.compile(r"\s*\(\*+\)")


class AnbimaErro(Exception):
    """A ANBIMA respondeu fora do esperado (codigo HTTP, pagina no lugar do arquivo, formato novo)."""


def url(d: date) -> str:
    return URL.format(aammdd=d.strftime("%y%m%d"))


def _chave(titulo: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sem_acento(titulo).lower()).strip()


def _num(v):
    """'8,1894' -> 8.1894; '1.027,55' -> 1027.55; '--', 'N/D', vazio e o que nao for numero -> None."""
    s = (v or "").strip()
    if not RX_NUMERO.fullmatch(s):
        return None
    return float(s.replace(".", "").replace(",", "."))


def _data(v):
    """'15/05/2036' -> '2036-05-15'. Vazio ou data que nao existe -> None."""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (v or "").strip())
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat() if m else None
    except ValueError:
        return None


def _indice(texto: str) -> tuple:
    """'IPCA + 6,4895%' -> ('IPCA+', 6.4895). A convencao tem o mesmo nome que boletim/renda_fixa.py
    da a taxa do negocio da B3, para as duas taxas so serem comparadas quando falam a mesma lingua."""
    t = sem_acento(texto or "").upper().strip()
    m = RX_TAXA.search(t)
    taxa = _num(m.group(1)) if m else None
    if t.startswith("IPCA"):
        return "IPCA+", taxa
    if "DO DI" in t or "DO CDI" in t:
        return "% do CDI", taxa
    if t.startswith(("DI", "CDI")):
        return "CDI+", taxa
    if t.startswith("PRE"):
        return "Pré", taxa
    nome = t.split("+")[0].split()[0] if t else ""
    return (nome.title() + "+" if nome else None), taxa


def ler(texto: str) -> dict:
    """{codigo: registro} do arquivo diario. O cabecalho e achado pela coluna `Codigo` e as colunas
    sao lidas pelo titulo, nao pela posicao: coluna nova ou fora de ordem nao troca um numero por
    outro. Pagina de erro ou formato novo levanta AnbimaErro."""
    linhas = texto.splitlines()
    cab = next((i for i, l in enumerate(linhas[:12]) if "codigo" in {_chave(t) for t in l.split("@")}), None)
    if cab is None:
        raise AnbimaErro("sem o cabecalho `Codigo@Nome@...` (formato novo ou pagina de erro)")
    campos = [COLUNAS.get(_chave(t)) for t in linhas[cab].split("@")]
    falta = OBRIGATORIAS - set(campos)
    if falta:
        raise AnbimaErro(f"cabecalho sem a coluna {', '.join(sorted(falta))}")
    out: dict = {}
    for l in linhas[cab + 1:]:
        valores = l.split("@")
        if len(valores) < len(campos):
            continue
        r = {c: v.strip() for c, v in zip(campos, valores) if c}
        cod = r.pop("codigo")
        if not cod:
            continue
        conv, taxa_emissao = _indice(r.get("indice"))
        item = {"nome": RX_MARCA.sub("", r.get("nome") or "").strip(), "repac_venc": _data(r.get("repac_venc")),
                "indice": r.get("indice") or None, "convencao": conv, "taxa_emissao": taxa_emissao,
                "ntnb_ref": _data(r.get("ntnb_ref"))}
        item.update({c: _num(r.get(c)) for c in NUMERICAS})
        out[cod] = item
    if not out:
        raise AnbimaErro("arquivo sem nenhuma debenture")
    return out


def _hora(cabecalho) -> str | None:
    """Last-Modified do servidor na hora de Brasilia, como a B3 informa as dela."""
    try:
        return parsedate_to_datetime(cabecalho).astimezone(relogios.BRT).strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def baixar(cli: Cliente, d: date, pausas: tuple = PAUSAS) -> dict | None:
    """O arquivo do dia `d`, lido. None quando a ANBIMA ainda nao o publicou (HTTP 404)."""
    r = _pedir(lambda: cli.get(url(d), timeout=40), pausas)
    if r.status == 404:
        return None
    if r.status != 200:
        raise AnbimaErro(f"arquivo de {d.isoformat()}: HTTP {r.status}")
    try:
        papeis = ler(r.content.decode("latin-1"))
    except AnbimaErro as e:
        raise AnbimaErro(f"arquivo de {d.isoformat()}: {e}")
    return {"data": d.isoformat(), "url": url(d), "publicado_em": _hora(r.headers.get("last-modified")),
            "bytes": len(r.content), "papeis": papeis}


def do_pregao(cli: Cliente, d: date, cache: dict | None = None, dias_atras: int = 3, pausas: tuple = PAUSAS) -> dict:
    """O arquivo que vale para o pregao `d` e o publicado antes dele (base da variacao da indicativa).

    Vale o do proprio pregao; se a ANBIMA ainda nao o publicou (404) ou a leitura dele falhou, o mais
    recente ate `dias_atras` dias uteis antes, sempre com a data dele. O anterior e procurado ao menos
    um dia util para tras, mesmo com `dias_atras` zero: sem ele nao ha variacao.

    `cache` guarda o que a rodada ja leu, por data: cada arquivo e pedido uma vez so, e o que falhou
    (rede, codigo HTTP, formato) nao e pedido de novo. Com `MAX_SEM_REDE` arquivos sem resposta da rede
    a rodada para de procurar a ANBIMA: site fora do ar nao pode custar mais de um minuto por arquivo
    a cada pregao. Codigo HTTP e formato novo respondem na hora e nao contam. A rodada seguinte tenta
    tudo de novo.

    Devolve {pregao, situacao, arquivo, anterior, tentativas[, erro]}; situacao:
      publicado  o arquivo e do pregao        anterior  o do pregao nao veio: vale um mais antigo
      ausente    nenhum arquivo na janela     falhou    nenhum arquivo, e houve falha de leitura
    `tentativas` diz o que cada data respondeu: publicado, nao publicado, falhou ou nao tentado.
    """
    cache = cache if cache is not None else {}
    falhas: dict = cache.setdefault(_FALHAS, {"motivos": {}, "sem_rede": 0})
    tentativas: dict = {}

    def pega(dia: date):
        iso = dia.isoformat()
        if iso not in cache and iso not in falhas["motivos"]:
            if falhas["sem_rede"] >= MAX_SEM_REDE:
                tentativas[iso] = "nao tentado"
                return None
            try:
                cache[iso] = baixar(cli, dia, pausas)
            except HttpError as e:              # o cliente so levanta por rede; codigo HTTP volta como resposta
                falhas["sem_rede"] += 1
                falhas["motivos"][iso] = f"arquivo de {iso}: " + ("falha de rede" if e.status == 0 else f"HTTP {e.status}")
            except AnbimaErro as e:
                falhas["motivos"][iso] = str(e)[:160]
        if iso in falhas["motivos"]:
            tentativas[iso] = "falhou"
            return None
        tentativas[iso] = PUBLICADO if cache[iso] else NAO_PUBLICADO
        return cache[iso]

    def procura(dia: date, vezes: int):
        for _ in range(vezes):
            arq = pega(dia)
            if arq:
                return arq
            dia = relogios.dia_util_anterior("B3", dia)
        return None

    out: dict = {"pregao": d.isoformat(), "arquivo": procura(d, dias_atras + 1), "anterior": None, "tentativas": tentativas}
    arq = out["arquivo"]
    if arq:
        out["anterior"] = procura(relogios.dia_util_anterior("B3", date.fromisoformat(arq["data"])), max(1, dias_atras))
    # o motivo que vai para a tela e o do primeiro arquivo que falhou; o que cada data respondeu fica em `tentativas`
    motivos = [falhas["motivos"][iso] for iso, resposta in tentativas.items() if resposta == "falhou"]
    if not motivos and "nao tentado" in tentativas.values():
        motivos = ["sem resposta da rede em outros arquivos da rodada; este ficou sem tentativa"]
    if motivos:
        out["erro"] = motivos[0]
    if arq:
        out["situacao"] = PUBLICADO if arq["data"] == d.isoformat() else "anterior"
    else:
        out["situacao"] = "falhou" if motivos else "ausente"
    return out


def situacao(anb: dict) -> dict:
    """O que a leitura da ANBIMA deixa no index.json e no manifest: situacao, datas e tentativas."""
    arq, ant = anb.get("arquivo") or {}, anb.get("anterior") or {}
    item = {"situacao": anb.get("situacao"), "data": arq.get("data"), "papeis": len(arq.get("papeis") or {}) or None,
            "publicado_em": arq.get("publicado_em"), "comparado_com": ant.get("data"),
            "tentativas": anb.get("tentativas") or None, "erro": anb.get("erro")}
    return {k: v for k, v in item.items() if v is not None}
