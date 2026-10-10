"""
Testes do Black-Scholes proprio (quant/opcoes/bs.py).

Os 5 casos reais abaixo sao series de opcoes da B3 (COTAHIST, fechamento do dia de entrada, ponto medio das ofertas) e os
valores esperados foram calculados pela CALCULADORA DO TERMINAL: o objeto BS de
~/Desktop/terminal-artefato/src/js/57-derivativos.js rodado em Node (10/10/2026): volatilidade implicita por bissecao,
premio, delta, gama (por R$ 1), vega (por ponto de volatilidade) e teta (por dia util). O mesmo modelo do coletor de
opcoes do terminal: europeu, sem dividendos, t = dias uteis / 252, juro continuo.
O ultimo teste roda o JS de novo (so se Node e o arquivo do terminal existirem) para pegar divergencia futura.
"""
import json
import math
import os
import shutil
import subprocess

import numpy as np
import pytest

from quant.opcoes import bs

# (codigo, dia, vencimento, S, K, du, r_continuo, premio, put) -> esperado do terminal
CASOS = [
    dict(codigo="PETRM321", dia="2025-12-22", S=31.1, K=29.969999313354492, du=15, r=0.13889183728757404,
         premio=0.19999998807907104, put=True,
         js=dict(vi=0.2288012249022722, preco=0.20000001539225742, delta=-0.2007251460457693, gama=0.16161405256197073,
                 vega=0.021288691182129605, theta=-0.012685397412365705)),
    dict(codigo="VALED705", dia="2024-03-18", S=60.9, K=63.9900016784668, du=23, r=0.10570946529025686,
         premio=0.7899999618530273, put=False,
         js=dict(vi=0.23473586373031136, preco=0.7900000920862418, delta=0.2993003804576953, gama=0.08042215254205796,
                 vega=0.06390237819352267, theta=-0.03992375943772302)),
    dict(codigo="BOVAP172", dia="2026-03-23", S=178.9, K=172.0, du=18, r=0.1367132289536264,
         premio=2.1399998664855957, put=True,
         js=dict(vi=0.2887183759361505, preco=2.1399996164590647, delta=-0.24988051368031516, gama=0.02301393808903513,
                 vega=0.1519000832969584, theta=-0.09640991556101516)),
    dict(codigo="ITUBG415", dia="2026-06-22", S=40.94, K=41.43000030517578, du=19, r=0.1323433623967034,
         premio=0.9300000071525574, put=False,
         js=dict(vi=0.2158516173809767, preco=0.9299998731804351, delta=0.4989030377379234, gama=0.16441019651183422,
                 vega=0.04484693761088134, theta=-0.03571270871299382)),
    dict(codigo="BBASM213", dia="2025-12-22", S=21.3, K=21.209999084472656, du=15, r=0.13889183728757404,
         premio=0.3450000286102295, put=True,
         js=dict(vi=0.2259176684170961, preco=0.3450000340447872, delta=-0.3996027841479357, gama=0.32899098330934584,
                 vega=0.020071698177242966, theta=-0.010233817588860376)),
]


@pytest.mark.parametrize("c", CASOS, ids=[c["codigo"] for c in CASOS])
def test_confere_com_a_calculadora_do_terminal(c):
    t = c["du"] / 252.0
    vi = bs.vol_implicita(c["premio"], c["S"], c["K"], t, c["r"], c["put"])
    assert vi == pytest.approx(c["js"]["vi"], abs=5e-7)            # o terminal para a bissecao em 1e-7
    assert bs.preco(c["S"], c["K"], t, c["r"], vi, c["put"]) == pytest.approx(c["premio"], abs=1e-6)
    g = bs.gregas(c["S"], c["K"], t, c["r"], vi, c["put"])
    assert g["delta"] == pytest.approx(c["js"]["delta"], abs=5e-6)
    assert g["gama"] == pytest.approx(c["js"]["gama"], abs=5e-6)
    assert g["vega"] == pytest.approx(c["js"]["vega"], abs=5e-6)
    assert g["teta"] == pytest.approx(c["js"]["theta"], abs=5e-6)


def test_valor_de_livro_texto():
    # S=K=100, 1 ano, juro continuo 5%, vol 20%: call 10,4506, put 5,5735 (Hull)
    assert bs.preco(100, 100, 1.0, 0.05, 0.20, False) == pytest.approx(10.4506, abs=1e-3)
    assert bs.preco(100, 100, 1.0, 0.05, 0.20, True) == pytest.approx(5.5735, abs=1e-3)


def test_paridade_put_call_e_delta():
    s, k, t, r, sig = 36.5, 38.0, 20 / 252.0, 0.13, 0.33
    c = bs.preco(s, k, t, r, sig, False)
    p = bs.preco(s, k, t, r, sig, True)
    assert c - p == pytest.approx(s - k * math.exp(-r * t), abs=1e-10)
    assert bs.delta(s, k, t, r, sig, False) - bs.delta(s, k, t, r, sig, True) == pytest.approx(1.0, abs=1e-12)
    # gama e vega iguais para call e put; teta difere pelo termo de juro
    assert bs.gama(s, k, t, r, sig) > 0 and bs.vega(s, k, t, r, sig) > 0
    assert bs.teta(s, k, t, r, sig, False) < 0


def test_gregas_batem_com_diferencas_finitas():
    s, k, t, r, sig = 55.0, 52.0, 25 / 252.0, 0.12, 0.30
    for put in (False, True):
        h = 1e-4 * s
        d_num = (bs.preco(s + h, k, t, r, sig, put) - bs.preco(s - h, k, t, r, sig, put)) / (2 * h)
        assert bs.delta(s, k, t, r, sig, put) == pytest.approx(d_num, abs=1e-6)
        g_num = (bs.preco(s + h, k, t, r, sig, put) - 2 * bs.preco(s, k, t, r, sig, put) + bs.preco(s - h, k, t, r, sig, put)) / h ** 2
        assert bs.gama(s, k, t, r, sig) == pytest.approx(g_num, abs=1e-5)
        hv = 1e-5
        v_num = (bs.preco(s, k, t, r, sig + hv, put) - bs.preco(s, k, t, r, sig - hv, put)) / (2 * hv) / 100.0
        assert bs.vega(s, k, t, r, sig) == pytest.approx(v_num, abs=1e-6)
        ht = 1e-6
        t_num = -(bs.preco(s, k, t + ht, r, sig, put) - bs.preco(s, k, t - ht, r, sig, put)) / (2 * ht) / 252.0
        assert bs.teta(s, k, t, r, sig, put) == pytest.approx(t_num, abs=1e-6)


def test_volatilidade_implicita_casos_de_borda():
    t, r = 20 / 252.0, 0.13
    assert bs.vol_implicita(0.0, 30, 31, t, r, False) is None                 # premio zero
    assert bs.vol_implicita(4.0, 30, 25, t, r, False) is None                 # premio abaixo do valor intrinseco: sem resposta
    assert bs.vol_implicita(2.0, 30, 31, 0.0, r, False) is None               # sem prazo
    assert bs.vol_implicita(5.5, 30, 25, t, r, False) is not None             # call dentro do dinheiro com tempo
    assert bs.vol_implicita(25.0, 30, 31, t, r, False) is None                # premio maior que o ativo: sem resposta
    # ida e volta
    for sig in (0.15, 0.4, 0.9, 2.0):
        p = bs.preco(30, 31, t, r, sig, False)
        assert bs.vol_implicita(p, 30, 31, t, r, False) == pytest.approx(sig, abs=1e-6)


def test_prazo_zero_vale_o_intrinseco():
    assert bs.preco(30, 28, 0.0, 0.1, 0.3, False) == 2.0
    assert bs.preco(30, 28, 0.0, 0.1, 0.3, True) == 0.0
    assert bs.preco(26, 28, 0.0, 0.1, 0.3, True) == 2.0
    assert bs.delta(30, 28, 0.0, 0.1, 0.3, False) == 1.0
    assert bs.delta(26, 28, 0.0, 0.1, 0.3, True) == -1.0


def test_versoes_vetorizadas_batem_com_as_escalares():
    rng = np.random.default_rng(3)
    n = 200
    s = rng.uniform(5, 80, n)
    k = s * rng.uniform(0.8, 1.2, n)
    t = rng.integers(5, 60, n) / 252.0
    r = np.full(n, 0.12)
    sig = rng.uniform(0.15, 0.8, n)
    put = rng.random(n) < 0.5
    pv = bs.preco_vet(s, k, t, r, sig, put)
    dv = bs.delta_vet(s, k, t, r, sig, put)
    for i in range(n):
        assert pv[i] == pytest.approx(bs.preco(s[i], k[i], t[i], r[i], sig[i], bool(put[i])), abs=1e-9)
        assert dv[i] == pytest.approx(bs.delta(s[i], k[i], t[i], r[i], sig[i], bool(put[i])), abs=1e-9)
    iv = bs.vol_implicita_vet(pv, s, k, t, r, put)
    ok = ~np.isnan(iv)
    assert ok.mean() > 0.9
    assert np.allclose(iv[ok], sig[ok], atol=1e-5)


def test_dividendo_continuo_reduz_a_call():
    base = bs.preco(100, 100, 1.0, 0.1, 0.25, False)
    com_q = bs.preco(100, 100, 1.0, 0.1, 0.25, False, q=0.04)
    assert com_q < base


def test_roda_o_js_do_terminal_de_novo_se_existir():
    arq = os.path.expanduser("~/Desktop/terminal-artefato/src/js/57-derivativos.js")
    if not shutil.which("node") or not os.path.exists(arq):
        pytest.skip("node ou o arquivo do terminal nao existem nesta maquina")
    src = open(arq, encoding="utf-8").read()
    trecho = src[src.index("function cdfN(x)"):src.index("const CENARIOS")].replace("U.ehNum", "ehNum")
    casos = [dict(S=c["S"], K=c["K"], du=c["du"], r=c["r"], premio=c["premio"], put=c["put"]) for c in CASOS]
    js = ('const ehNum=(v)=>typeof v==="number"&&isFinite(v);\n' + trecho + "\nconst casos=" + json.dumps(casos) +
          ";\nconsole.log(JSON.stringify(casos.map(c=>{const t=c.du/252;const vi=BS.vi(c.premio,c.S,c.K,t,c.r,c.put);"
          "const g=BS.gregas(c.S,c.K,t,c.r,vi,c.put);return {vi,preco:BS.preco(c.S,c.K,t,c.r,vi,c.put),...g}})));")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    saida = json.loads(r.stdout)
    for c, o in zip(CASOS, saida):
        t = c["du"] / 252.0
        vi = bs.vol_implicita(c["premio"], c["S"], c["K"], t, c["r"], c["put"])
        g = bs.gregas(c["S"], c["K"], t, c["r"], vi, c["put"])
        assert vi == pytest.approx(o["vi"], abs=5e-7)
        assert g["delta"] == pytest.approx(o["delta"], abs=5e-6)
        assert g["gama"] == pytest.approx(o["gama"], abs=5e-6)
        assert g["vega"] == pytest.approx(o["vega"], abs=5e-6)
        assert g["teta"] == pytest.approx(o["theta"], abs=5e-6)
