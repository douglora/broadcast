from datetime import date

import pandas as pd

from livro import indicadores as ind
from livro import politica
from livro.sinais import curvas, fx_commod, tecnicas
from livro.sinais.base import Contexto, Estado


def serie(valores, fim="2026-09-18"):
    datas = pd.bdate_range(end=fim, periods=len(valores))
    return ind.para_df([[d.date().isoformat(), v, v, v, v, v, 100] for d, v in zip(datas, valores)])


def contexto(universo, limiares, series, curvas_=None, macro=None, slot="fechamento"):
    info = {k: {"fresco": True, "esperado_hoje": True, "ultima": "2026-09-18"} for k in series}
    return Contexto(universo=universo, limiares=limiares, hoje=date(2026, 9, 18), slot=slot, series=series,
                    series_info=info, curvas=curvas_ or {}, macro=macro or {})


def test_t01_perda_mm200_dispara_uma_vez_e_respeita_cooldown(universo, limiares):
    vals = [100.0 + (i % 7) * 0.1 for i in range(230)] + [96.0, 95.0]
    ctx = contexto(universo, limiares, {"BBDC4": serie(vals)})
    est = Estado()
    al = tecnicas.T01MM200().avaliar(ctx, est)
    assert len(al) == 1 and al[0].ativo == "BBDC4" and al[0].tag == "perda"
    assert al[0].id == "T01-BBDC4-perda-2026-09-18"
    assert "média de 200 dias" in al[0].titulo
    # segunda avaliacao no mesmo estado: cooldown
    assert tecnicas.T01MM200().avaliar(ctx, est) == []


def test_t01_ucits_usa_nome_por_extenso(universo, limiares):
    vals = [100.0] * 230 + [96.0, 95.0]
    ctx = contexto(universo, limiares, {"VWRA": serie(vals)})
    al = tecnicas.T01MM200().avaliar(ctx, Estado())
    assert al and "Vanguard FTSE All-World" in al[0].titulo


def test_t08_drawdown_degraus_e_rearme(universo, limiares):
    vals = [100.0] * 100 + [90.0, 85.0, 81.0, 79.0]
    ctx = contexto(universo, limiares, {"BABA": serie(vals)})
    est = Estado()
    al = tecnicas.T08Drawdown().avaliar(ctx, est)
    assert al and al[0].tag == "-20" and al[0].severidade == "critico"
    # nao repete no mesmo nivel
    assert tecnicas.T08Drawdown().avaliar(ctx, est) == []


def test_t05_zscore_critico(universo, limiares):
    vals = [100 * (1.001 ** i) for i in range(40)] + [100 * (1.001 ** 40) * 0.90]
    ctx = contexto(universo, limiares, {"KO": serie(vals)})
    al = tecnicas.T05Zscore().avaliar(ctx, Estado())
    assert al and al[0].severidade == "critico" and al[0].ativo == "KO"


def test_t04_maxima_e_progresso_minimo(universo, limiares):
    vals = [float(100 + i) for i in range(100)]
    ctx = contexto(universo, limiares, {"UGPA3": serie(vals)})
    est = Estado()
    al = tecnicas.T04MaxMin().avaliar(ctx, est)
    assert al and al[0].tag == "maxima"
    ctx2 = contexto(universo, limiares, {"UGPA3": serie(vals + [200.5])})
    assert tecnicas.T04MaxMin().avaliar(ctx2, est) == []  # +0,25% nao e progresso de 3%


def test_c04_juro_real_cruza_grade(universo, limiares):
    h = [[f"2026-09-{d:02d}", t, 3000.0 - t * 10, "compra"] for d, t in zip(range(1, 18), [7.3] * 15 + [7.45, 7.61])]
    tes = {"data_base": "2026-09-17", "titulos": {"IPCA2032": {"id": "IPCA2032", "tipo": "Tesouro IPCA+", "ano": 2032,
                                                                "apelido": "IPCA+ 2032", "historico": h}}}
    ctx = contexto(universo, limiares, {}, curvas_={"tesouro": tes})
    al = curvas.C04TesouroJuroReal().avaliar(ctx, Estado())
    assert al and al[0].tag == "cima_7.5" and al[0].severidade == "atencao"
    assert "7,50% real" in al[0].titulo


def test_c07_ust_movimento(universo, limiares):
    h = [[f"2026-09-{d:02d}", 4.4, 4.5, 4.6, 5.1] for d in range(1, 18)] + [["2026-09-18", 4.43, 4.55, 4.83, 5.28]]
    ctx = contexto(universo, limiares, {}, curvas_={"ust": {"prazos": ["2y", "5y", "10y", "30y"], "historico": h}})
    al = curvas.C07UST().avaliar(ctx, Estado())
    assert al and al[0].tag == "abriu" and al[0].severidade == "critico"  # 10y +23 bps
    assert ctx.curvas["ust"]["delta_bps"]["10y"] == 23.0


def test_c01_di_uma_mensagem_por_pregao(universo, limiares):
    datas = pd.bdate_range(end="2026-09-18", periods=30)
    hist = {}
    for c, base in (("DI1F28", 13.3), ("DI1F35", 13.8)):
        hist[c] = [[d.date().isoformat(), base, 80000.0] for d in datas]
        hist[c][-1][1] = base + (0.08 if c == "DI1F28" else 0.21)
    di = {"historico": hist, "ultimo_pregao": "2026-09-18"}
    ctx = contexto(universo, limiares, {}, curvas_={"di": di})
    est = Estado()
    al = curvas.C01DIMovimento().avaliar(ctx, est)
    assert len(al) == 1 and al[0].tag == "abriu" and "ABRIU" in al[0].titulo
    assert curvas.C01DIMovimento().avaliar(ctx, est) == []


def test_f01_usdbrl_nivel_psicologico(universo, limiares):
    vals = [4.95 + (i % 3) * 0.001 for i in range(80)] + [4.99, 5.03]
    ctx = contexto(universo, limiares, {"USDBRL": serie(vals)})
    al = fx_commod.F01USDBRL().avaliar(ctx, Estado())
    assert al and "cruzou R$ 5,00" in al[0].titulo


def test_politica_agrupa_e_limita(limiares):
    def a(regra, ativo, sev, fam="preco"):
        return {"id": f"{regra}-{ativo}-x-2026-09-18", "regra": regra, "ativo": ativo, "severidade": sev, "familia": fam,
                "titulo": f"{ativo} algo", "corpo": [], "por_que": "pq", "como_falar": "", "fonte": "f", "texto": f"[{sev}] {regra} {ativo}"}
    novos = [a("T01", "BBDC4", "atencao"), a("T01", "ITUB4", "atencao"), a("C01", "DI", "atencao", "curva"),
             a("C07", "UST", "critico", "curva"), a("T04", "EWY", "info")]
    r = politica.aplicar(novos, [], limiares, "fechamento", "Fechamento 18h40")
    grupos = {m["grupo"]: m for m in r["mensagens"]}
    assert "curva" in grupos and grupos["curva"]["severidade"] == "critico"
    assert set(grupos["T01"]["ids"]) == {"T01-BBDC4-x-2026-09-18", "T01-ITUB4-x-2026-09-18"}
    assert len(r["linhas_info"]) == 1
    assert grupos["curva"]["push"] and "detalhe na sessão" in grupos["curva"]["push"]


def test_politica_reapresentado_nao_consome_teto(limiares):
    def a(regra, ativo, sev, fam="preco", reap=False):
        d = {"id": f"{regra}-{ativo}-x-2026-09-18", "regra": regra, "ativo": ativo, "severidade": sev, "familia": fam,
             "titulo": f"{ativo} algo", "corpo": [], "por_que": "pq", "como_falar": "", "fonte": "f", "texto": f"[{sev}] {regra} {ativo}"}
        return d
    # 3 pendentes de atencao (ja emitidos antes) + 3 novos de atencao: os novos ainda cabem no slot
    pend = [a("T04", "IB01", "atencao"), a("T08", "BAC", "atencao"), a("F06", "BTC", "atencao", "cripto")]
    novos = [a("T05", "MRVE3", "atencao"), a("C05", "TESOURO", "atencao", "curva"), a("T01", "ITUB4", "atencao")]
    r = politica.aplicar(novos, pend, limiares, "fechamento", "Fechamento 18h40", {"critico": 0, "atencao": 0})
    ids_msg = {i for m in r["mensagens"] for i in m["ids"]}
    assert all(p["id"] in ids_msg for p in pend), "pendente reapresentado nao pode ser suprimido"
    assert all(n["id"] in ids_msg for n in novos), r["suprimidos"]
    # com 4 mensagens de atencao ja emitidas hoje, um novo vira linha
    r2 = politica.aplicar([a("T01", "BBDC4", "atencao")], [], limiares, "fechamento", "Fechamento 18h40", {"critico": 0, "atencao": 4})
    assert not r2["mensagens"] and r2["suprimidos"][0]["motivo"] == "teto de atenção"
