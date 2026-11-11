#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Base comum do analista: caminhos, leitura do ativo, IPCA, formato brasileiro, TIR e
o livro de premissas (cada numero que entra numa conta leva fonte, data e tipo)."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent.parent
LOCAL = Path(os.environ.get("MESA_LOCAL", RAIZ / "dados_local"))
CACHE = LOCAL / "analista"
TERMINAL = Path(os.environ.get("TERMINAL_CACHE", Path.home() / "Desktop/terminal-artefato/cache/out"))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# Unit = pacote de acoes; o preco da unit dividido pelo numero de acoes do pacote da o preco
# medio por acao, que multiplicado pelo total de acoes (CVM) da o valor de mercado.
UNITS = {"TAEE11": 3, "ENGI11": 5, "SAPR11": 5, "KLBN11": 5, "SANB11": 2, "BPAC11": 3,
         "ALUP11": 3, "IGTI11": 3}

# Tipos de premissa, do mais forte ao mais fraco. MESA = escolha nossa, sem documento.
OFICIAL, GUIDANCE, MERCADO, CONSENSO, MESA = "OFICIAL", "GUIDANCE", "MERCADO", "CONSENSO", "MESA"


class SemDado(Exception):
    """Falta um insumo. A conta para aqui: nunca se preenche com numero inventado."""


@dataclass
class Premissa:
    nome: str
    valor: object
    unidade: str = ""
    fonte: str = ""
    data: str = ""
    tipo: str = MESA
    nota: str = ""


@dataclass
class Livro:
    """Livro de premissas de uma conta. O relatorio imprime todas, com o tipo ao lado."""
    itens: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    def p(self, nome, valor, unidade="", fonte="", data="", tipo=MESA, nota=""):
        self.itens.append(Premissa(nome, valor, unidade, fonte, data, tipo, nota))
        return valor

    def aviso(self, txt):
        if txt not in self.avisos:
            self.avisos.append(txt)

    def lista(self):
        return [asdict(i) for i in self.itens]

    def da_mesa(self):
        return [i for i in self.itens if i.tipo == MESA]


# ------------------------------------------------------------------ rede e cache
def http(url, timeout=60, binario=False, tentativas=3):
    import requests
    erro = None
    for i in range(tentativas):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code == 200:
                return r.content if binario else r.text
            erro = f"HTTP {r.status_code}"
        except Exception as e:  # rede
            erro = str(e)[:120]
        time.sleep(1.5 * (i + 1))
    raise SemDado(f"não baixou {url[:90]}: {erro}")


def ler_json(caminho, padrao=None):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def gravar_json(caminho, obj):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, caminho)


def idade_horas(caminho):
    try:
        return (time.time() - os.path.getmtime(caminho)) / 3600.0
    except OSError:
        return 1e9


def ativo(ticker):
    """JSON do ativo pela leitura padrao da mesa (copia local quando mais nova que o branch)."""
    tk = ticker.upper().replace(".SA", "")
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    d = None
    try:
        import mesa
        d = mesa.baixar(f"ativos/{tk}.json")
    except SystemExit:
        d = None
    except Exception:
        d = None
    if not isinstance(d, dict):
        d = ler_json(LOCAL / "ativos" / f"{tk}.json")
    if not isinstance(d, dict):
        raise SemDado(f"{tk} não está coletado: rode python3 ferramentas/local/coletar.py {tk} --pares auto")
    return d


# ------------------------------------------------------------------ IPCA (BCB SGS 433)
def ipca_mensal():
    """{AAAA-MM: variacao % no mes}, do BCB (serie 433). Cache de 1 dia."""
    arq = CACHE / "ipca_433.json"
    if idade_horas(arq) < 24:
        d = ler_json(arq)
        if d:
            return d
    out = {}
    hoje = dt.date.today()
    for ini, fim in ((dt.date(2005, 1, 1), dt.date(2014, 12, 31)), (dt.date(2015, 1, 1), hoje)):
        url = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados?formato=json"
               f"&dataInicial={ini:%d/%m/%Y}&dataFinal={fim:%d/%m/%Y}")
        try:
            for r in json.loads(http(url, timeout=40)):
                d, m, a = r["data"].split("/")
                out[f"{a}-{m}"] = float(r["valor"])
        except Exception:
            pass
    if len(out) < 60:
        velho = ler_json(arq)
        if velho:
            return velho
        raise SemDado("IPCA mensal (BCB série 433) não respondeu e não há cópia")
    gravar_json(arq, out)
    return out


def fator_ipca(de: str, ate: str | None = None, serie=None) -> float:
    """Quanto R$ 1 do fim do mes `de` (AAAA-MM) vale em reais do fim do mes `ate` (padrao: ultimo IPCA)."""
    s = serie or ipca_mensal()
    meses = sorted(s)
    ate = ate or meses[-1]
    f = 1.0
    for m in meses:
        if de < m <= ate:
            f *= 1.0 + s[m] / 100.0
    return f


def ipca_12m(serie=None):
    s = serie or ipca_mensal()
    meses = sorted(s)[-12:]
    f = 1.0
    for m in meses:
        f *= 1.0 + s[m] / 100.0
    return (f - 1.0) * 100.0, meses[-1]


# ------------------------------------------------------------------ matematica
def vpl(taxa, fluxos):
    """fluxos = [(t_em_anos, valor)]"""
    return sum(v / (1.0 + taxa) ** t for t, v in fluxos)


def tir(fluxos, preco, lo=-0.95, hi=3.0, tol=1e-10):
    """Taxa que iguala o valor presente dos fluxos ao preco. Bissecao: sem derivada, sem
    chute inicial. Devolve None quando nao ha troca de sinal (fluxo que nunca paga o preco)."""
    f = lambda r: vpl(r, fluxos) - preco
    a, b = f(lo), f(hi)
    if a * b > 0:
        return None
    for _ in range(300):
        m = (lo + hi) / 2.0
        c = f(m)
        if abs(c) < tol * max(1.0, abs(preco)):
            return m
        if a * c <= 0:
            hi, b = m, c
        else:
            lo, a = m, c
    return (lo + hi) / 2.0


def real(nominal, inflacao):
    """Fisher: taxas em fracao."""
    return (1.0 + nominal) / (1.0 + inflacao) - 1.0


def nominal(real_, inflacao):
    return (1.0 + real_) * (1.0 + inflacao) - 1.0


def mediana(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


# ------------------------------------------------------------------ formato brasileiro
def br(v, casas=2, sinal=False):
    if v is None:
        return "n/d"
    s = f"{v:+,.{casas}f}" if sinal else f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v, casas=1, sinal=False):
    return "n/d" if v is None else br(v * 100.0, casas, sinal) + "%"


def pp(v, casas=1):
    return "n/d" if v is None else br(v * 100.0, casas, True) + " pp"


def reais(v, casas=2):
    return "n/d" if v is None else "R$ " + br(v, casas)


def mi(v):
    """R$ milhoes -> texto curto (R$ 1,2 bi / R$ 340 mi)."""
    if v is None:
        return "n/d"
    if abs(v) >= 1000:
        return "R$ " + br(v / 1000.0, 1) + " bi"
    return "R$ " + br(v, 0) + " mi"


def data_br(iso):
    try:
        a, m, d = str(iso)[:10].split("-")
        return f"{d}/{m}/{a}"
    except Exception:
        return str(iso or "")


def _terminal_multiplos(tk):
    """Preco de 15 minutos e valor de mercado por classe de acao, do cache do terminal."""
    m = ler_json(TERMINAL / "multiplos.json") or {}
    x = (m.get("a") or {}).get(tk)
    if not isinstance(x, dict) or not x.get("preco") or not x.get("mcap"):
        return None
    return x


def preco_e_valor(d, integral=None, livro=None, preco=None):
    """Preco, numero de acoes e valor de mercado (R$ mi), com conferencia cruzada.
    Ordem: preco informado > terminal (cotacao de 15 min, valor de mercado por classe) > coleta da mesa.
    Acoes: capital integralizado menos tesouraria (CVM) quando ha integral; senao Yahoo."""
    tk = d.get("ticker", "").upper()
    y = (d.get("yahoo") or {})
    info = y.get("info") or {}
    t = _terminal_multiplos(tk) if preco is None else None
    fonte_preco, vm_term = "Yahoo (coleta da mesa)", None
    data_preco = (d.get("gerado_em") or "")[:10]
    if preco is not None:
        fonte_preco, data_preco = "informado na pergunta", dt.date.today().isoformat()
    elif t:
        preco, data_preco = t["preco"], str(t.get("preco_de") or "")[:10]
        fonte_preco = "terminal (" + str(t.get("preco_fonte") or "cotacao") + ")"
        vm_term = t["mcap"] / 1e6
    else:
        preco = info.get("currentPrice") or info.get("regularMarketPrice") or (d.get("fundamentus") or {}).get("Cotação")
    if not preco:
        raise SemDado(f"{tk}: sem preço de tela no JSON do ativo")
    acoes = fonte_acoes = None
    if integral and integral.get("acoes"):
        a = integral["acoes"]
        acoes, fonte_acoes = a["total_ex_tesouraria"], f"CVM composição do capital {a['data']}"
        if a.get("escala") == 1000:
            fonte_acoes += " (publicado em milhares; conferido por " + str(a.get("escala_fonte")) + ")"
    elif info.get("sharesOutstanding"):
        acoes, fonte_acoes = float(info["sharesOutstanding"]), "Yahoo sharesOutstanding"
    if not acoes:
        raise SemDado(f"{tk}: sem número de ações")
    por_unit = UNITS.get(tk, 1)
    vm = vm_term if vm_term else preco / por_unit * acoes / 1e6
    vm_yahoo = (info.get("marketCap") or 0) / 1e6 or None
    vm_fund = ((d.get("fundamentus") or {}).get("Valor de mercado") or 0) / 1e6 or None
    if livro is not None:
        livro.p("Preço", preco, "R$", fonte_preco, data_preco, MERCADO)
        livro.p("Ações ex-tesouraria", acoes, "acoes", fonte_acoes, "", OFICIAL if integral else MERCADO)
        if vm_term:
            livro.p("Valor de mercado", vm, "R$ mi", "terminal: soma de cada classe de ação pelo seu preço", data_preco, MERCADO)
            simples = preco / por_unit * acoes / 1e6
            if abs(simples / vm - 1.0) > 0.08:
                livro.aviso(f"Valor de mercado por classe ({mi(vm)}) difere {pct(simples / vm - 1.0, 0, True)} de preço x ações "
                            f"({mi(simples)}): há mais de uma classe de ação ou unit; a conta usa o valor por classe.")
        else:
            for nome, outro in (("Yahoo", vm_yahoo), ("Fundamentus", vm_fund)):
                if outro and abs(vm / outro - 1.0) > 0.08:
                    livro.aviso(f"Valor de mercado calculado ({mi(vm)}) difere {pct(vm / outro - 1.0, 0, True)} do {nome} "
                                f"({mi(outro)}): empresa com mais de uma classe de ação ou unit; confira o preço por classe.")
    return {"preco": float(preco), "data": data_preco, "acoes": float(acoes), "valor_mercado": vm,
            "por_unit": por_unit, "vm_yahoo": vm_yahoo, "vm_fundamentus": vm_fund, "fonte_preco": fonte_preco}
