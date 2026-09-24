"""Portao de qualidade, Brent por contrato e dolar das 17h.

Fixtures = series reais do branch dados (tests/fixtures/qualidade/), dos commits em
que o livro publicou numero errado:
- BZ_F_1cc16f1: fechamento de 23/09, Brent "-1,4% a 97,83" (volume 111, cotacao 19h48 ET);
  o Brent liquidou +3,86% a 103,08.
- BZ_F_3ecabba: 18/09, barra com abertura 104,09 acima da maxima 100,14 (contratos misturados).
- BZX26_dados: contrato de novembro, com as DUAS barras "de 23/09" que o Yahoo devolve
  (a liquidada, 103,08, e a sessao seguinte, 101,94 com volume 958).
- USDBRL_X_dados: barra de 23/09 fechando em 5,0999 e a de 24/09 abrindo em 5,1625.
- DXY_dados: sem 22/09 e com a barra "de 23/09" feita da sessao da noite.
- MMM_dados: sem 22/09 (o "+3,2% no dia" de 23/09 eram dois pregoes).
- CURY3_dados: barra provisoria do Yahoo (so o fechamento)."""

from __future__ import annotations

import json
import os
import types
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from livro import coletar, qualidade as qa, render
from livro import indicadores as ind
from livro.fontes import futuros, yahoo
from livro.sinais.base import Alerta

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "qualidade")
NOITE_23 = datetime(2026, 9, 23, 23, 59, tzinfo=timezone.utc)   # 20h59 BRT, o fechamento de 23/09
D23 = date(2026, 9, 23)


def fx(nome):
    return json.load(open(os.path.join(FIX, nome), encoding="utf-8"))


def _redatar(d):
    """O que o parser novo faz com duas barras da mesma data (a 2a vai para o dia util seguinte)."""
    out = []
    for b in d["barras"]:
        if out and out[-1][0] == b[0]:
            b = [yahoo._proximo_dia_util(b[0]), *b[1:]]
        out.append(b)
    return {**d, "barras": out}


# ------------------------------------------------------------ Brent
def test_brent_23_09_toco_da_sessao_seguinte_e_descartado():
    v = qa.avaliar(fx("BZ_F_1cc16f1.json"), "BZ=F", "ICE", "commodity", NOITE_23, D23)
    assert v.status == qa.NAO_CONFIRMADO and v.descartar_ultima
    assert v.data_barra == "2026-09-23"
    assert any("sessão seguinte" in m for m in v.motivos)
    assert any("volume 111" in m for m in v.motivos)


def test_brent_18_09_barra_incoerente_e_descartada():
    v = qa.avaliar(fx("BZ_F_3ecabba.json"), "BZ=F", "ICE", "commodity",
                   datetime(2026, 9, 18, 22, 39, tzinfo=timezone.utc), date(2026, 9, 18))
    assert v.status == qa.NAO_CONFIRMADO and v.descartar_ultima
    assert any("incoerente" in m for m in v.motivos)


def test_parser_manda_a_segunda_barra_do_dia_para_o_dia_seguinte():
    d = fx("BZX26_dados.json")
    ny = ZoneInfo("America/New_York")
    stamps, o, h, l, c, v = [], [], [], [], [], []
    for i, b in enumerate(d["barras"]):
        hora = 18 if (i == len(d["barras"]) - 1) else 0     # a ultima e a sessao seguinte (18h ET)
        dt = datetime.fromisoformat(b[0]).replace(hour=hora, minute=30 if hora else 0, tzinfo=ny)
        stamps.append(int(dt.timestamp()))
        o.append(b[1]); h.append(b[2]); l.append(b[3]); c.append(b[4]); v.append(b[6])
    payload = {"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/New_York", "instrumentType": "FUTURE"},
                                     "timestamp": stamps,
                                     "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}],
                                                    "adjclose": [{"adjclose": c}]}}]}}
    out = yahoo.parse_chart(payload, "BZX26.NYM")
    assert [b[0] for b in out["barras"][-3:]] == ["2026-09-22", "2026-09-23", "2026-09-24"]
    assert round(out["barras"][-2][4], 2) == 103.08 and out["barras_redatadas"] == ["2026-09-24"]
    # grafico de minutos nao e redatado: datas repetidas ali sao a regra
    assert "barras_redatadas" not in yahoo.parse_chart(payload, "BZX26.NYM", diario=False)


def test_contrato_de_novembro_da_o_brent_certo_de_18_a_23_09():
    """Os numeros das agencias: 18/09 -0,91%, 21/09 -3,40%, 22/09 -1,09%, 23/09 +3,86%."""
    x26 = _redatar(fx("BZX26_dados.json"))
    barras, corte = futuros.emendar(fx("BZ_F_1cc16f1.json")["barras"], x26["barras"], "X26")
    assert corte == "2026-08-22"
    df = ind.para_df(barras)
    dias = {}
    for d in ("2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23"):
        j = ind.janelas(df, ate=date.fromisoformat(d))
        dias[d] = round(j["dia"] * 100, 2)
    assert dias == {"2026-09-18": -0.91, "2026-09-21": -3.4, "2026-09-22": -1.09, "2026-09-23": 3.86}
    j = ind.janelas(df, ate=D23)
    assert round(j["ultimo"], 2) == 103.08 and round(j["1s"] * 100, 1) == -2.6
    v = qa.avaliar({**x26, "barras": barras}, "BZX26.NYM", "ICE", "commodity", NOITE_23, D23)
    assert v.status == qa.OK and not v.descartar_ultima and v.data_barra == "2026-09-23"
    assert v.volume_provisorio            # volume 47365 repetido de 22/09: o fechamento vale


def test_calendario_de_vencimentos_do_brent():
    assert futuros.vencimento("X26") == date(2026, 9, 30)
    assert futuros.vencimento("V26") == date(2026, 8, 28)   # 31/08 e feriado bancario em Londres
    assert futuros.vencimento("Z26") == date(2026, 10, 30)
    assert futuros.contrato_vigente(date(2026, 9, 23)) == "X26"
    assert futuros.contrato_vigente(date(2026, 9, 30)) == "X26"      # no dia do vencimento ainda e o 1o
    assert futuros.contrato_vigente(date(2026, 10, 1)) == "Z26"
    assert futuros.simbolos_para(date(2026, 10, 1)) == ["BZZ26.NYM", "BZF27.NYM"]
    assert futuros.inicio_vigencia("Z26") == date(2026, 10, 1)


def test_mesclar_nao_deixa_barra_podre_sobrescrever_a_boa():
    boa = fx("BZ_F_1cc16f1.json")                     # 18/09 = 103,87, liquidada
    podre = fx("BZ_F_3ecabba.json")                   # 18/09 = 98,77, abertura acima da maxima
    out = yahoo.mesclar(boa, podre)
    b18 = next(b for b in out["barras"] if b[0] == "2026-09-18")
    assert round(b18[4], 2) == 103.87 and "2026-09-18" in out["revisoes_rejeitadas"]
    # o contrario: barra boa nova substitui a podre guardada
    out2 = yahoo.mesclar(podre, boa)
    b18 = next(b for b in out2["barras"] if b[0] == "2026-09-18")
    assert round(b18[4], 2) == 103.87


# ------------------------------------------------------------ dolar
def test_dolar_23_09_barra_parada_nao_e_confirmada():
    v = qa.avaliar(fx("USDBRL_X_dados.json"), "USDBRL=X", "FX", "fx", NOITE_23, D23)
    assert v.status == qa.NAO_CONFIRMADO and not v.descartar_ultima
    assert any("abertura" in m and "5,1625" in m for m in v.motivos)


def test_dolar_com_fechamento_das_17h_e_confirmado():
    d = fx("USDBRL_X_dados.json")
    barras = [list(b) for b in d["barras"]]
    for b in barras:
        if b[0] == "2026-09-23":
            b[4] = b[5] = 5.1689        # ultimo negocio ate as 17h (InfoMoney: R$ 5,1689, +1,27%)
    v = qa.avaliar({**d, "barras": barras}, "USDBRL=X", "FX", "fx", NOITE_23, D23,
                   confirmadas={"2026-09-23": "17:00"})
    assert v.status == qa.OK
    j = ind.janelas(ind.para_df(qa.limpar_fim_de_semana(barras, "FX")), ate=D23)
    assert round(j["dia"] * 100, 2) == 1.14   # 5,1689 contra a barra de 22/09 do Yahoo (5,1104)


def test_fechamentos_das_17h_pegam_o_ultimo_negocio_ate_o_corte(monkeypatch):
    brt = ZoneInfo("America/Sao_Paulo")
    ts = lambda h, m: int(datetime(2026, 9, 23, h, m, tzinfo=brt).timestamp())
    monkeypatch.setattr(yahoo, "baixar_serie", lambda *a, **k: {
        "_intradia": [[ts(16, 30), 5.160], [ts(16, 45), 5.165], [ts(17, 0), 5.1689], [ts(17, 15), 5.171]]})
    out = yahoo.fechamentos_intradia(None, "USDBRL=X", "17:00")
    assert out == {"2026-09-23": [5.1689, "17:00"]}


def test_domingo_do_cambio_sai_ou_vira_sexta():
    barras = [["2026-09-18", 5.12, 5.16, 5.11, 5.1241, 5.1241, 0], ["2026-09-20", 5.14, 5.14, 5.14, 5.1421, 5.1421, 0],
              ["2026-09-21", 5.13, 5.14, 5.10, 5.1407, 5.1407, 0]]
    assert [b[0] for b in qa.limpar_fim_de_semana(barras, "FX")] == ["2026-09-18", "2026-09-21"]
    sem_sexta = [barras[1], barras[2]]
    assert [b[0] for b in qa.limpar_fim_de_semana(sem_sexta, "FX")] == ["2026-09-18", "2026-09-21"]
    assert qa.limpar_fim_de_semana(barras, "CRIPTO") == barras


# ------------------------------------------------------------ DXY, buracos, provisoria
def test_dxy_sessao_da_noite_sai_e_a_serie_fica_velha():
    """Publicado em 23/09: DXY +0,70%. A barra "de 23/09" era a sessao da noite (cotacao
    21h10 ET) e faltava 22/09. Descartada a da noite, a ultima e 21/09: o card mostra
    "dia 21/09", nunca uma variacao de hoje."""
    v = qa.avaliar(fx("DXY_dados.json"), "DX-Y.NYB", "ICE", "indice", NOITE_23, D23)
    assert v.descartar_ultima and v.status == qa.NAO_CONFIRMADO and v.data_barra == "2026-09-23"
    assert any("sessão seguinte" in m for m in v.motivos)
    sem_noite = {**fx("DXY_dados.json"), "barras": fx("DXY_dados.json")["barras"][:-1]}
    v2 = qa.avaliar(sem_noite, "DX-Y.NYB", "ICE", "indice", NOITE_23, D23)
    assert v2.data_barra == "2026-09-21" and v2.dia_pregoes == 1


def test_mmm_sem_22_09_dia_de_dois_pregoes():
    v = qa.avaliar(fx("MMM_dados.json"), "MMM", "NYSE", "acao", NOITE_23, D23)
    assert v.status == qa.OK and v.dia_pregoes == 2 and v.sem_barra == ["2026-09-22"]
    info = {"esperado_hoje": True, "fresco": True, "qualidade": v.para_json()}
    assert not qa.dia_valido(info)
    assert qa.marcador({"data": "2026-09-23"}, info) == ("2 pregões", False)


def test_barra_provisoria_da_b3_nao_e_suspeita():
    v = qa.avaliar(fx("CURY3_dados.json"), "CURY3.SA", "B3", "acao", NOITE_23, D23)
    assert v.status == qa.OK and not v.descartar_ultima
    assert any("provisória" in m for m in v.motivos)


def test_sem_buraco_em_feriado_do_mercado():
    # 07/09 (Independencia) nao e pregao na B3; 04/09 -> 08/09 nao e buraco
    assert qa.dias_sem_barra("B3", "2026-09-04", "2026-09-08") == []
    assert qa.dias_sem_barra("NYSE", "2026-09-21", "2026-09-23") == ["2026-09-22"]
    assert qa.dias_sem_barra("CRIPTO", "2026-09-21", "2026-09-23") == []


def test_cripto_antes_da_meia_noite_utc_e_parcial():
    barras = [[f"2026-09-{d:02d}", 1, 1.1, 0.9, 1 + d / 100, 1 + d / 100, 10] for d in range(1, 24)]
    v = qa.avaliar({"barras": barras, "tz": "UTC"}, "BTC-USD", "CRIPTO", "cripto",
                   datetime(2026, 9, 23, 21, 5, tzinfo=timezone.utc), D23)
    assert v.parcial and qa.marcador({"data": "2026-09-23"}, {"qualidade": v.para_json()}) == ("parcial", False)


# ------------------------------------------------------------ consumo
def test_marcador_esconde_o_numero_nao_confirmado():
    info = {"esperado_hoje": True, "fresco": True,
            "qualidade": {"status": qa.NAO_CONFIRMADO, "motivos": ["x"], "descartar_ultima": False}}
    assert qa.marcador({"data": "2026-09-23"}, info) == ("dado a confirmar", True)
    velho = {"esperado_hoje": True, "fresco": False, "qualidade": {"status": qa.OK}}
    assert qa.marcador({"data": "2026-09-22"}, velho) == ("dia 22/09", False)
    assert qa.marcador({"data": "2026-09-22"}, {"defasado": True, "fresco": True}) == ("D-1, 22/09", False)


def test_destaques_nao_levam_dia_de_dois_pregoes(universo):
    j = {"MMM": {"dia": 0.0323, "dia_confirmado": False}, "PLTR": {"dia": 0.0368, "dia_confirmado": True},
         "GFS": {"dia": -0.0443, "dia_confirmado": False}, "BABA": {"dia": -0.0474}}
    m = render.movers(j, universo)
    assert [i for i, _ in m["altas"]] == ["PLTR"] and [i for i, _ in m["baixas"]] == ["BABA"]


def _fake(series_info):
    return types.SimpleNamespace(series_info=series_info, falhas={}, REGRAS_DO_DIA=coletar.Coleta.REGRAS_DO_DIA)


def test_portao_segura_alerta_de_serie_nao_confirmada_e_de_dois_pregoes():
    si = {"USDBRL": {"qualidade": {"status": qa.NAO_CONFIRMADO, "motivos": ["barra parada"], "descartar_ultima": False}},
          "MMM": {"qualidade": {"status": qa.OK, "dia_pregoes": 2, "sem_barra": ["2026-09-22"]}},
          "KLBN4": {"qualidade": {"status": qa.OK}}}
    alertas = [Alerta("T02", "USDBRL", "info", "cambio", "USDBRL perdeu a MM50"),
               Alerta("T05", "MMM", "atencao", "preco", "MMM +3,2% no dia"),
               Alerta("T01", "MMM", "info", "preco", "MMM acima da MM200"),          # nivel, nao dia: passa
               Alerta("T05", "KLBN4", "critico", "preco", "KLBN4 -3,2%"),
               Alerta("E05", "USDBRL", "info", "noticia", "dólar dispara 1,28%")]     # noticia nao depende da barra
    f = _fake(si)
    passam = coletar.Coleta._portao_alertas(f, alertas)
    assert [(a.regra, a.ativo) for a in passam] == [("T01", "MMM"), ("T05", "KLBN4"), ("E05", "USDBRL")]
    assert "T05 MMM" in f.falhas["alertas_segurados"] and "T02 USDBRL" in f.falhas["alertas_segurados"]


def test_portao_rebaixa_alerta_de_serie_suspeita():
    si = {"BRENT": {"qualidade": {"status": qa.SUSPEITO, "motivos": ["cotação ao vivo de outro vencimento"]}}}
    a = Alerta("F03", "BRENT", "critico", "commodity", "Brent cai a US$ 98,77")
    passam = coletar.Coleta._portao_alertas(_fake(si), [a])
    assert passam[0].severidade == "atencao" and "(dado a confirmar)" in passam[0].titulo


def test_pares_exigem_as_duas_pernas():
    si = {"PETR4": {"qualidade": {"status": qa.OK}},
          "BRENT": {"qualidade": {"status": qa.NAO_CONFIRMADO, "motivos": ["toco"], "descartar_ultima": False}}}
    a = Alerta("T11", "PETR4", "atencao", "preco", "PETR4 descolou do Brent", dados={"par": ["PETR4", "BRENT"]})
    assert coletar.Coleta._portao_alertas(_fake(si), [a]) == []


def test_drivers_dizem_quem_pode_explicar_o_dia():
    si = {"BRENT": {"esperado_hoje": True, "fresco": True, "qualidade": {"status": qa.OK}},
          "USDBRL": {"esperado_hoje": True, "fresco": True,
                     "qualidade": {"status": qa.NAO_CONFIRMADO, "motivos": ["barra parada"]}}}
    j = {"BRENT": {"data": "2026-09-23", "ultimo": 103.08, "dia": 0.0386},
         "USDBRL": {"data": "2026-09-23", "ultimo": 5.0999, "dia": -0.0021}}
    d = qa.drivers(si, j)
    assert d["BRENT"]["ok"] and d["BRENT"]["dia"] == 0.0386
    assert not d["USDBRL"]["ok"] and d["USDBRL"]["dia"] is None and "barra parada" in d["USDBRL"]["motivos"]


def test_serie_velha_na_manha_nao_tem_dia_confirmado():
    """Na manha o esperado e o pregao de ontem (esperado_hoje e falso para tudo): UCITS
    sem a barra de ontem saia como confirmada."""
    info = {"esperado_hoje": False, "fresco": False, "qualidade": {"status": qa.OK}}
    assert not qa.dia_valido(info)
    assert qa.marcador({"data": "2026-09-22"}, info) == ("dia 22/09", False)


def test_di_da_manha_espera_o_ajuste_de_ontem(universo, limiares):
    from datetime import date as _d
    from livro.sinais import curvas
    from livro.sinais.base import Contexto, Estado
    hist = {c: [["2026-09-22", 13.48, 1.0], ["2026-09-23", 13.57, 1.0]] for c in
            ("DI1F28", "DI1F29", "DI1F30", "DI1F32", "DI1F35")}
    for slot, falha in (("manha", False), ("fechamento", True)):
        ctx = Contexto(universo=universo, limiares=limiares, hoje=_d(2026, 9, 24), slot=slot, series={},
                       series_info={}, curvas={"di": {"historico": hist, "ultimo_pregao": "2026-09-23"}},
                       macro={}, falhas={})
        curvas.C01DIMovimento().avaliar(ctx, Estado())
        assert ("di" in ctx.falhas) is falha, slot


def test_correcao_do_alerta_de_brent_de_18_09(universo):
    """F03 CRITICO entregue em 18/09: '-5,3% a US$ 99,29'. A serie corrigida (contrato
    de novembro) diz -0,9% a 103,87: sai CORRECAO uma vez; na segunda vez, nao."""
    from livro import reconferir
    x26 = _redatar(fx("BZX26_dados.json"))
    barras, _ = futuros.emendar(fx("BZ_F_1cc16f1.json")["barras"], x26["barras"], "X26")
    series = {"BRENT": ind.para_df([b for b in barras if b[0] <= "2026-09-23"])}
    fila = {"F03-BRENT-queda-2026-09-18": {
        "id": "F03-BRENT-queda-2026-09-18", "regra": "F03", "ativo": "BRENT", "data": "2026-09-18",
        "status": "entregue", "canal": "mensagem", "severidade": "critico", "titulo": "Brent cai a US$ 99,29 (-5,3%)",
        "dados": {"close": 99.29, "var": -0.0528}}}
    c = reconferir.reconferir(fila, series, {}, universo, date(2026, 9, 24))
    assert len(c) == 1 and round(c[0]["var_certa"] * 100, 2) == -0.91 and round(c[0]["close_certo"], 2) == 103.87
    assert "o certo é -0,9% a 103,87" in c[0]["texto"]
    assert reconferir.reconferir(fila, series, {}, universo, date(2026, 9, 24), {"F03-BRENT-queda-2026-09-18": "2026-09-24"}) == []
    # alerta certo nao gera correcao; alerta velho demais tambem nao
    fila_ok = {"k": {**fila["F03-BRENT-queda-2026-09-18"], "id": "k", "dados": {"close": 103.87, "var": -0.0091}}}
    assert reconferir.reconferir(fila_ok, series, {}, universo, date(2026, 9, 24)) == []
    assert reconferir.reconferir(fila, series, {}, universo, date(2026, 10, 5)) == []
