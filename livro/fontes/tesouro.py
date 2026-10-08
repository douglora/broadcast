"""Tesouro Direto via Tesouro Transparente (CKAN): CSV com o historico completo
de taxas e PU de todos os titulos. Casamos cada titulo do livro por (tipo, ano
de vencimento) e guardamos o historico para percentil desde 2010 e DV01.

Colunas do CSV (;): Tipo Titulo; Data Vencimento; Data Base; Taxa Compra Manha;
Taxa Venda Manha; PU Compra Manha; PU Venda Manha; PU Base Manha. Numeros em
pt-BR (virgula), datas dd/mm/aaaa. Titulo fora de venda vem sem taxa de compra:
usamos a taxa de venda e rotulamos 'recompra'. A base e sempre D-1 pela manha."""

from __future__ import annotations

import csv
import io
import unicodedata
from datetime import datetime

from livro.http import Cliente

PACKAGE_URL = ("https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show"
               "?id=taxas-dos-titulos-ofertados-pelo-tesouro-direto")
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


def coletar(titulos: list[dict], cli: Cliente | None = None) -> dict:
    cli = cli or Cliente()
    url = url_csv(cli)
    r = cli.get_ok(url, timeout=180)
    texto = r.content.decode("utf-8-sig", errors="replace")
    if texto.count(";") < 10:
        texto = r.content.decode("latin-1", errors="replace")
    dados = parse_csv(texto, titulos)
    bases = [t["historico"][-1][0] for t in dados.values() if t["historico"]]
    return {"fonte": "Tesouro Transparente (CKAN)", "url": url, "data_base": max(bases) if bases else None,
            "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "titulos": dados}
