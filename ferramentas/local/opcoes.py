#!/usr/bin/env python3
"""Cadeia de opcoes da B3 com premio REAL, volatilidade implicita e delta.

So roda com internet aberta (computador do Douglas). Na nuvem a B3 era bloqueada e
os premios das puts de VALE3 de 29/09/2026 sairam por estimativa (Black-Scholes com
vol de 30%). Aqui vem o que a bolsa publicou no Boletim Diario do Mercado, arquivos
publicos e oficiais:

  - InstrumentsConsolidated: cada serie com o ativo, tipo, strike e vencimento;
  - TradeInformationConsolidated: minimo, maximo, medio, ultimo, premio de
    referencia, negocios e volume do pregao.

    python3 ferramentas/local/opcoes.py VALE3                        # puts, 3 proximos vencimentos mensais
    python3 ferramentas/local/opcoes.py VALE3 --semanais             # inclui as series semanais (W1, W2...)
    python3 ferramentas/local/opcoes.py VALE3 --tipo call
    python3 ferramentas/local/opcoes.py VALE3 --venc 2026-11         # so o vencimento de novembro
    python3 ferramentas/local/opcoes.py VALE3 --faixa 0.80-1.05 --todas
    python3 ferramentas/local/opcoes.py VALE3 --dia 2026-09-29 --juro 13.65

O arquivo e do FECHAMENTO do pregao (sai a noite; durante o dia, o ultimo e o de
ontem). Premio = ultimo negocio do dia; sem negocio no dia, a serie so entra com
`--todas`, pelo premio de referencia da B3, marcado "ref". Volatilidade implicita e
delta por Black-Scholes sem dividendos (a maioria das series da B3 tem strike
ajustado por provento); para put americana e uma aproximacao. O juro e a Selic meta
do Banco Central, ou `--juro`.

Nada aqui e recomendacao (Resolucao CVM 178): a ficha descreve premio, distancia e
liquidez. Venda de put e compromisso de compra no strike; a decisao e do Douglas.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import os
import re
import sys
from datetime import date, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
for p in (AQUI, RAIZ):
    if p not in sys.path:
        sys.path.insert(0, p)

from fita import num, pct, tabela  # noqa: E402
from livro import relogios  # noqa: E402
from livro.http import Cliente  # noqa: E402

TOKEN_URL = "https://arquivos.b3.com.br/api/download/requestname"
DOWNLOAD_URL = "https://arquivos.b3.com.br/api/download/"
SELIC_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _num(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)
    except ValueError:
        return None


def baixar_arquivo(cli: Cliente, nome: str, d: date) -> list[dict] | None:
    """CSV ';' do Boletim Diario. Dia sem pregao (ou arquivo ainda nao publicado) -> None."""
    r = cli.get(TOKEN_URL, params={"fileName": nome, "date": d.isoformat()}, timeout=40)
    if r.status != 200:
        return None
    token = (r.json() or {}).get("token")
    if not token:
        return None
    r2 = cli.get(DOWNLOAD_URL, params={"token": token}, timeout=180)
    if r2.status != 200:
        return None
    linhas = r2.content.decode("utf-8-sig", errors="replace").splitlines()
    ini = next((i for i, l in enumerate(linhas[:5]) if "TckrSymb" in l), 0)
    return list(csv.DictReader(io.StringIO("\n".join(linhas[ini:])), delimiter=";"))


def ultimo_pregao_publicado(cli: Cliente, a_partir: date) -> tuple[date, list[dict]] | None:
    d = a_partir
    for _ in range(7):
        if d.weekday() < 5:
            neg = baixar_arquivo(cli, "TradeInformationConsolidated", d)
            if neg:
                return d, neg
        d -= timedelta(days=1)
    return None


def selic(cli: Cliente) -> float | None:
    try:
        r = cli.get(SELIC_URL, timeout=12)
        if r.status == 200:
            return _num(str(r.json()[-1]["valor"]))
    except Exception:
        return None
    return None


# ---------- Black-Scholes (sem dividendos) ----------

def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_preco(s: float, k: float, t: float, r: float, vol: float, put: bool) -> float:
    if t <= 0 or vol <= 0:
        return max(k - s, 0.0) if put else max(s - k, 0.0)
    d1 = (math.log(s / k) + (r + vol * vol / 2.0) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if put:
        return k * math.exp(-r * t) * _cdf(-d2) - s * _cdf(-d1)
    return s * _cdf(d1) - k * math.exp(-r * t) * _cdf(d2)


def bs_delta(s: float, k: float, t: float, r: float, vol: float, put: bool) -> float | None:
    if t <= 0 or vol <= 0:
        return None
    d1 = (math.log(s / k) + (r + vol * vol / 2.0) * t) / (vol * math.sqrt(t))
    return _cdf(d1) - 1.0 if put else _cdf(d1)


def vol_implicita(premio: float, s: float, k: float, t: float, r: float, put: bool) -> float | None:
    """Bissecao entre 1% e 300% a.a.; None quando o premio esta abaixo do valor intrinseco."""
    if premio is None or premio <= 0 or t <= 0:
        return None
    lo, hi = 0.01, 3.0
    if bs_preco(s, k, t, r, lo, put) > premio or bs_preco(s, k, t, r, hi, put) < premio:
        return None
    for _ in range(60):
        meio = (lo + hi) / 2.0
        if bs_preco(s, k, t, r, meio, put) > premio:
            hi = meio
        else:
            lo = meio
    return (lo + hi) / 2.0


def montar(tk: str, instrumentos: list[dict], negocios: list[dict], dia: date, juro: float, tipo: str,
           faixa: tuple[float, float], todas: bool, venc: str | None, n_venc: int, semanais: bool = False) -> dict:
    neg = {(r.get("TckrSymb") or "").strip(): r for r in negocios}
    spot = _num((neg.get(tk) or {}).get("LastPric"))
    if not spot:
        raise RuntimeError(f"{tk} sem ultimo preco no arquivo da B3 de {dia.isoformat()}")
    put = tipo == "put"
    r_cont = math.log(1.0 + juro / 100.0)
    series = []
    for i in instrumentos:
        if (i.get("Asst") or "").strip() != tk or "OPTION" not in (i.get("SctyCtgyNm") or "").upper():
            continue
        if ((i.get("OptnTp") or "").strip().lower() == "put") != put:
            continue
        k = _num(i.get("ExrcPric"))
        try:
            vcto = date.fromisoformat((i.get("XprtnDt") or "")[:10])
        except ValueError:
            continue
        if not k or vcto <= dia or not (faixa[0] <= k / spot <= faixa[1]):
            continue
        if venc and not vcto.isoformat().startswith(venc):
            continue
        cod = (i.get("TckrSymb") or "").strip()
        if not semanais and re.search(r"W\d$", cod):
            continue
        n = neg.get(cod) or {}
        ultimo, ref, qtd = _num(n.get("LastPric")), _num(n.get("RefPric")), _num(n.get("TradQty")) or 0
        premio, origem = (ultimo, "ultimo") if ultimo and qtd else (ref, "ref")
        if not premio or (origem == "ref" and not todas):
            continue
        du = relogios.dias_uteis_b3(dia.isoformat(), vcto)
        t = du / 252.0
        vi = vol_implicita(premio, spot, k, t, r_cont, put)
        series.append({
            "codigo": cod, "vencimento": vcto, "du": du, "strike": k, "premio": premio, "origem": origem,
            "medio": _num(n.get("TradAvrgPric")), "negocios": int(qtd), "volume": _num(n.get("NtlFinVol")) or 0.0,
            "estilo": (i.get("OptnStyle") or "").strip()[:4], "vi": vi,
            "delta": bs_delta(spot, k, t, r_cont, vi, put) if vi else None,
            "dist": (k / spot - 1) * 100,
            "premio_sobre_strike": premio / k * 100,
            "equilibrio": (k - premio) if put else (k + premio),
        })
    vencs = sorted({s["vencimento"] for s in series})
    if not venc:
        vencs = vencs[:n_venc]
    return {"ticker": tk, "dia": dia, "spot": spot, "juro": juro, "tipo": tipo,
            "vencimentos": [(v, sorted((s for s in series if s["vencimento"] == v), key=lambda s: s["strike"])) for v in vencs]}


def imprimir(c: dict, faixa: tuple[float, float], todas: bool) -> None:
    tk, put = c["ticker"], c["tipo"] == "put"
    print(f"OPCOES DE {tk} · {'PUTS' if put else 'CALLS'} · fechamento de {c['dia'].strftime('%d/%m/%Y')} (B3, Boletim Diario do Mercado)")
    print(f"{tk} fechou a R$ {num(c['spot'])}. Juro usado: {num(c['juro'])}% a.a. Strikes de {faixa[0] * 100:.0f}% a {faixa[1] * 100:.0f}% do preco."
          + (" Inclui series sem negocio no dia (premio de referencia, marcado ref)." if todas else " So series com negocio no dia."))
    if not c["vencimentos"]:
        print("LACUNA: nenhuma serie na faixa com negocio no dia. Tente --todas ou abra a faixa com --faixa 0.70-1.10.")
        return
    for vcto, series in c["vencimentos"]:
        du = series[0]["du"] if series else 0
        print()
        print(f"Vencimento {vcto.strftime('%d/%m/%Y')} ({MESES[vcto.month - 1]}/{str(vcto.year)[2:]}) · {du} dias uteis")
        lin = []
        for s in series:
            lin.append([
                s["codigo"], num(s["strike"]), pct(s["dist"]),
                num(s["premio"]) + (" ref" if s["origem"] == "ref" else ""),
                num(s["premio_sobre_strike"], 1) + "%",
                num(s["equilibrio"]),
                "-" if s["vi"] is None else num(s["vi"] * 100, 0) + "%",
                "-" if s["delta"] is None else num(s["delta"], 2),
                str(s["negocios"]), num(s["volume"] / 1e3, 0),
            ])
        print(tabela(["serie", "strike", "dist.", "premio", "premio/strike", "equilibrio", "vol impl.", "delta", "negocios", "R$ mil"], lin))
    print()
    print("Como ler: dist. = strike contra o preco da acao; premio/strike = quanto o premio rende sobre o valor")
    print("comprometido ate o vencimento (nao anualizado); equilibrio = strike menos o premio (put) ou mais (call);")
    print("vol impl. = volatilidade anual que o premio embute; delta = sensibilidade ao preco (em modulo, uma")
    print("aproximacao da chance de exercicio); negocios e R$ mil = liquidez do dia. Serie com poucos negocios tem")
    print("premio pouco confiavel: confira o livro de ofertas antes. Descritivo, sem recomendacao (CVM 178).")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticker")
    ap.add_argument("--tipo", default="put", choices=("put", "call"))
    ap.add_argument("--dia", help="AAAA-MM-DD (padrao: ultimo pregao publicado)")
    ap.add_argument("--venc", help="AAAA-MM: so esse vencimento")
    ap.add_argument("--vencimentos", type=int, default=3, help="quantos vencimentos mostrar (padrao 3)")
    ap.add_argument("--faixa", default="", help="strike/preco, ex.: 0.85-1.02 (padrao: 0.85-1.02 em put, 0.98-1.15 em call)")
    ap.add_argument("--todas", action="store_true", help="inclui series sem negocio no dia, pelo premio de referencia")
    ap.add_argument("--semanais", action="store_true", help="inclui as series semanais (codigo terminado em W1 a W5)")
    ap.add_argument("--juro", type=float, help="taxa em %% a.a. (padrao: Selic meta do BCB)")
    a = ap.parse_args(argv[1:])
    tk = a.ticker.strip().upper()
    padrao = (0.85, 1.02) if a.tipo == "put" else (0.98, 1.15)
    try:
        faixa = tuple(float(x) for x in a.faixa.split("-")) if a.faixa else padrao
        assert len(faixa) == 2 and faixa[0] < faixa[1]
    except Exception:
        print("faixa invalida: use, por exemplo, --faixa 0.85-1.02")
        return 2
    cli = Cliente()
    if a.dia:
        dia = date.fromisoformat(a.dia)
        negocios = baixar_arquivo(cli, "TradeInformationConsolidated", dia)
        if not negocios:
            print(f"LACUNA: a B3 nao tem o arquivo de negocios de {dia.isoformat()} (feriado, fim de semana ou ainda nao publicado).")
            return 1
    else:
        achado = ultimo_pregao_publicado(cli, date.today())
        if not achado:
            print("LACUNA: a B3 nao devolveu o arquivo de negocios dos ultimos 7 dias.")
            return 1
        dia, negocios = achado
    instrumentos = baixar_arquivo(cli, "InstrumentsConsolidated", dia)
    if not instrumentos:
        print(f"LACUNA: a B3 nao devolveu o cadastro de instrumentos de {dia.isoformat()}.")
        return 1
    juro = a.juro if a.juro is not None else selic(cli)
    if juro is None:
        print("LACUNA: o Banco Central nao respondeu a Selic. Informe o juro: --juro 15.0")
        return 1
    try:
        c = montar(tk, instrumentos, negocios, dia, juro, a.tipo, faixa, a.todas, a.venc, a.vencimentos, a.semanais)
    except RuntimeError as e:
        print(f"LACUNA: {e}")
        return 1
    imprimir(c, faixa, a.todas)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
