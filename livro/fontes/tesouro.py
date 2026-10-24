"""Tesouro Direto via Tesouro Transparente (CKAN): CSV com o historico completo
de taxas e PU de todos os titulos. Casamos cada titulo do livro por (tipo, ano
de vencimento) e guardamos o historico para percentil desde 2010 e DV01.

Colunas do CSV (;): Tipo Titulo; Data Vencimento; Data Base; Taxa Compra Manha;
Taxa Venda Manha; PU Compra Manha; PU Venda Manha; PU Base Manha. Numeros em
pt-BR (virgula), datas dd/mm/aaaa. Titulo fora de venda vem sem taxa de compra:
usamos a taxa de venda e rotulamos 'recompra'. A base e sempre D-1 pela manha.

Reserva (23/10/2026, auditoria do terminal, salto 10): desde 21/10 o CSV responde com a pagina anti-robo da F5 ou "429 - volume
atipico" (no runner do Actions e no Mac) e o livro ficou na base de 15/10. Com o CSV em falha, a taxa e o PU do dia vem do JSON
publico do site do Tesouro Direto (o que a pagina "Precos e taxas" le), somados ao historico guardado: o ponto entra com a data de
precificacao do site, a fonte diz que e a reserva e desde quando o CSV esta fora. Quando o CSV volta, ele substitui tudo."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime

from livro.http import Cliente

PACKAGE_URL = ("https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show"
               "?id=taxas-dos-titulos-ofertados-pelo-tesouro-direto")
SITE_URL = "https://www.tesourodireto.com.br/o/rentabilidade/"
FONTE_CSV = "Tesouro Transparente (CKAN)"
FONTE_SITE = "site do Tesouro Direto"
CSV_DIRETO = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
              "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return s.strip().lower()


def _num(s: str) -> float | None:
    s = (s or "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _data(s: str) -> str | None:
    try:
        return datetime.strptime(str(s).strip()[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def url_csv(cli: Cliente) -> str:
    try:
        r = cli.get(PACKAGE_URL, timeout=30)
        if r.status == 200:
            for res in (r.json().get("result") or {}).get("resources") or []:
                if str(res.get("format", "")).lower() == "csv":
                    return str(res["url"])
    except Exception:
        pass
    return CSV_DIRETO


def parse_csv(texto: str, titulos: list[dict], desde: str = "2010-01-01") -> dict:
    """titulos = [{id, tipo, ano, ...}] -> {id: {tipo, vencimento, historico: [[base, taxa, pu, fonte_taxa]]}}."""
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    try:
        cab = [_norm(c) for c in next(leitor)]
    except StopIteration:
        return {}

    def col(*chaves):
        for i, c in enumerate(cab):
            if all(k in c for k in chaves):
                return i
        return None

    i_tipo, i_venc, i_base = col("tipo"), col("vencimento"), col("data", "base")
    i_tc, i_tv = col("taxa", "compra"), col("taxa", "venda")
    i_pc, i_pv, i_pb = col("pu", "compra"), col("pu", "venda"), col("pu", "base")
    if None in (i_tipo, i_venc, i_base, i_tc):
        raise ValueError("cabecalho inesperado no CSV do Tesouro")
    alvo = {(_norm(t["tipo"]), int(t["ano"])): t["id"] for t in titulos}
    out = {t["id"]: {"id": t["id"], "tipo": t["tipo"], "ano": t["ano"], "apelido": t.get("apelido", t["id"]),
                     "nota": t.get("nota", ""), "vencimento": None, "historico": []} for t in titulos}
    minimo = max(i for i in (i_tipo, i_venc, i_base, i_tc) if i is not None)
    for row in leitor:
        if len(row) <= minimo:
            continue
        tipo = _norm(row[i_tipo])
        venc = _data(row[i_venc])
        if not venc:
            continue
        chave = (tipo, int(venc[:4]))
        tid = alvo.get(chave)
        if not tid:
            continue
        base = _data(row[i_base])
        if not base or base < desde:
            continue
        taxa, fonte = _num(row[i_tc]), "compra"
        if taxa is None and i_tv is not None:
            taxa, fonte = _num(row[i_tv]), "venda"
        pu = (_num(row[i_pc]) if i_pc is not None else None) or \
             (_num(row[i_pv]) if i_pv is not None else None) or \
             (_num(row[i_pb]) if i_pb is not None else None)
        if taxa is None:
            continue
        out[tid]["vencimento"] = venc
        out[tid]["historico"].append([base, taxa, pu, fonte])
    for t in out.values():
        vistos = {}
        for h in t["historico"]:
            vistos[h[0]] = h
        t["historico"] = [vistos[k] for k in sorted(vistos)]
    return out


def _taxa_site(s) -> float | None:
    """'IPCA + 7,45%', 'SELIC + 0,0989%' ou '13,50%' -> o numero; no IPCA+ e no Selic e a taxa sobre o indexador, como no CSV."""
    m = re.findall(r"(\d+(?:\.\d{3})*(?:,\d+)?)\s*%", str(s or ""))
    return _num(m[-1]) if m else None


def coletar_site(titulos: list[dict], cli: Cliente) -> dict:
    """{id: {vencimento, ponto: [base, taxa, pu, fonte], hora}} do site do Tesouro Direto. O "investir" (taxa de compra) vem antes;
    titulo fora de venda so aparece no "resgatar" (taxa de venda, rotulada 'venda' como no CSV). A base e a data de precificacao
    do site (lastMarketPricingDate, horario de Brasilia); a lista TesouroLegado ganha da Tesouro24x7."""
    alvo = {(_norm(t["tipo"]), int(t["ano"])): t["id"] for t in titulos}
    pontos: dict = {}
    for qual, k_taxa, k_pu, fonte in (("investir", "investmentProfitabilityIndexerName", "unitaryInvestmentValue", "compra"),
                                       ("resgatar", "redemptionProfitabilityFeeIndexerName", "unitaryRedemptionValue", "venda")):
        j = cli.get_ok(SITE_URL + qual, timeout=30, headers={"Accept": "application/json"}).json()
        if not isinstance(j, dict):
            raise ValueError(f"resposta inesperada do site do Tesouro Direto ({qual})")
        listas = sorted(((k, v) for k, v in j.items() if isinstance(v, list)), key=lambda kv: kv[0] != "TesouroLegado")
        for _, lista in listas:
            for x in lista:
                if not isinstance(x, dict):
                    continue
                m = re.match(r"^(.*?)\s+(\d{4})$", str(x.get("treasuryBondName") or "").strip())
                venc, quando = str(x.get("maturityDate") or "")[:10], str(x.get("lastMarketPricingDate") or "")
                if not m or len(venc) != 10 or len(quando) < 10:
                    continue
                tid = alvo.get((_norm(m.group(1)), int(venc[:4])))
                taxa, pu = _taxa_site(x.get(k_taxa)), x.get(k_pu)
                if not tid or tid in pontos or taxa is None or not isinstance(pu, (int, float)) or pu <= 0:
                    continue
                pontos[tid] = {"vencimento": venc, "ponto": [quando[:10], taxa, round(float(pu), 2), fonte], "hora": quando[11:16]}
    return pontos


def coletar(titulos: list[dict], cli: Cliente | None = None, anterior: dict | None = None) -> dict:
    """O CSV do Tesouro Transparente e, quando o site do Tesouro Direto tem data mais nova que a dele (CSV parado, como de 15 a 20/10)
    ou o CSV falha (pagina anti-robo, desde 21/10), o ponto do dia pelo site somado ao historico do CSV ou, sem CSV, ao de
    `anterior` (o curvas/tesouro.json guardado). CSV e site em falha: a excecao sobe e o livro registra a falha como antes."""
    cli = cli or Cliente()
    erro = csv = None
    try:
        csv = _coletar_csv(titulos, cli)
    except Exception as e:
        erro = f"{type(e).__name__}: {str(e)[:120]}"
    try:
        pontos = coletar_site(titulos, cli)
    except Exception as e:
        if csv:
            return csv
        raise ValueError(f"CSV do Tesouro Transparente em falha ({erro}) e site do Tesouro Direto em falha "
                         f"({type(e).__name__}: {str(e)[:80]})") from e
    if not pontos:
        if csv:
            return csv
        raise ValueError(f"CSV do Tesouro Transparente em falha ({erro}) e o site do Tesouro Direto sem os titulos do livro")
    base = max(p["ponto"][0] for p in pontos.values())
    if csv and base <= str(csv.get("data_base") or ""):
        return csv
    fundo = csv or anterior or {}
    if csv:
        csv_ate, motivo = csv.get("data_base"), f"CSV do Tesouro Transparente parado na base {csv.get('data_base')}"
    else:
        csv_ate = (fundo.get("reserva") or {}).get("csv_ate") or (fundo.get("data_base") if fundo.get("fonte") == FONTE_CSV else None)
        motivo = f"CSV do Tesouro Transparente em falha: {erro}"
    ant = fundo.get("titulos") or {}
    out, so_resgate = {}, []
    for t in titulos:
        a, p = ant.get(t["id"]) or {}, pontos.get(t["id"])
        hist = [list(h) for h in (a.get("historico") or [])]
        anteriores = [h for h in hist if p and h[0] < p["ponto"][0]]
        if p and anteriores and len(anteriores[-1]) > 3 and anteriores[-1][3] != p["ponto"][3]:
            # o site so tem a taxa de resgate (titulo fora de venda) e o historico tem a de compra: a de resgate fica 0,12 pp acima
            # (medido em 23/10 nos 5 titulos com as duas), do tamanho de uma variacao de dias. Nao mistura: o titulo fica parado.
            so_resgate.append(t["id"])
            p = None
        if p:
            hist = sorted([h for h in hist if h[0] != p["ponto"][0]] + [p["ponto"]], key=lambda h: h[0])
        out[t["id"]] = {"id": t["id"], "tipo": t["tipo"], "ano": t["ano"], "apelido": t.get("apelido", t["id"]),
                        "nota": t.get("nota", ""), "vencimento": (p or {}).get("vencimento") or a.get("vencimento"), "historico": hist}
    for tid in so_resgate:
        pontos.pop(tid, None)
    if not pontos:
        if csv:
            return csv
        raise ValueError(f"CSV do Tesouro Transparente em falha ({erro}) e o site do Tesouro Direto so com taxa de outro tipo")
    base = max(p["ponto"][0] for p in pontos.values())
    hora = max((p["hora"] for p in pontos.values() if p["ponto"][0] == base), default="")
    return {"fonte": FONTE_SITE, "url": SITE_URL, "data_base": base,
            "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "titulos": out,
            "reserva": {"motivo": motivo, "csv_ate": csv_ate, "hora_site": hora, "do_site": sorted(pontos),
                        "sem_site": sorted(t["id"] for t in titulos if t["id"] not in pontos and t["id"] not in so_resgate),
                        "so_resgate": sorted(so_resgate)}}


def _coletar_csv(titulos: list[dict], cli: Cliente) -> dict:
    url = url_csv(cli)
    r = cli.get_ok(url, timeout=180)
    texto = r.content.decode("utf-8-sig", errors="replace")
    if texto.count(";") < 10:
        texto = r.content.decode("latin-1", errors="replace")
    dados = parse_csv(texto, titulos)
    bases = [t["historico"][-1][0] for t in dados.values() if t["historico"]]
    return {"fonte": FONTE_CSV, "url": url, "data_base": max(bases) if bases else None,
            "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "titulos": dados}
