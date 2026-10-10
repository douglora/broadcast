"""O laboratorio de pesquisa (quant/pesquisa/lab.py): as contas de execucao tem de ser as conservadoras."""
import numpy as np
import pandas as pd
import pytest

from quant.pesquisa import lab


def _dia(barras, inicio="2024-03-04 09:00"):
    idx = pd.date_range(inicio, periods=len(barras), freq="min", name="hora")
    o, h, l, c = zip(*barras)
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "n": 10.0, "v": 100.0}, index=idx)


def _sinal(m, onde, lado):
    s = np.zeros(len(m))
    s[onde] = lado
    return s


PARADO = (5000.0, 5000.0, 5000.0, 5000.0)


def test_entrada_a_mercado_alvo_so_quando_o_preco_passa_um_tick():
    # sinal na barra 20 (9h20); entra na abertura da 21 (5.000) com 1 tick contra = 5.000,5; alvo de 4 pontos = 5.004,5
    b = [PARADO] * 21 + [(5000.0, 5002.0, 5000.0, 5002.0), (5002.0, 5004.5, 5002.0, 5004.5), (5004.5, 5005.0, 5004.0, 5005.0)] + [PARADO] * 5
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, alvo=4.0)
    assert len(t) == 1 and t.entrada[0] == 5000.5 and t.saida[0] == "alvo" and t.pts[0] == 4.0 and t.hora[0] == "09:20"
    assert t.minutos[0] == 2                                   # na barra 22 o preco so TOCOU 5.004,5: nao executou; passou na 23
    t2 = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, alvo=4.0, alvo_no_toque=True)
    assert t2.minutos[0] == 1
    r = lab.medir(t)
    assert r.res[0] == pytest.approx(4.0 * 10 * 2 - 4.8)


def test_stop_vem_primeiro_e_abertura_alem_do_stop_sai_na_abertura():
    b = [PARADO] * 21 + [(5000.0, 5006.0, 4994.0, 5005.0)] + [PARADO] * 5         # mesma barra bate o alvo e o stop: vale o stop
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, alvo=4.0)
    assert t.saida[0] == "stop" and t.pts[0] == pytest.approx(-6.0 - 0.5)          # stop em 4.994,5, sai 1 tick pior
    b = [PARADO] * 21 + [(5000.0, 5000.0, 4999.0, 4999.0), (4990.0, 4991.0, 4989.0, 4990.0)] + [PARADO] * 5
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0)
    assert t.saida[0] == "stop" and t.pts[0] == pytest.approx(4990.0 - 0.5 - 5000.5)   # abriu abaixo do stop: sai na abertura


def test_venda_tempo_janela_e_uma_posicao_por_vez():
    b = [PARADO] * 40
    m = _dia(b)
    s = _sinal(m, 20, -1)
    s[22] = -1                                                   # segundo sinal com a posicao aberta: ignorado
    t = lab.negocios(m, s, stop=6.0, tempo=10)
    assert len(t) == 1 and t.lado[0] == "V" and t.entrada[0] == 4999.5 and t.saida[0] == "tempo" and t.pts[0] == -1.0
    # sinal antes das 9h15 e depois da ultima entrada nao opera
    assert len(lab.negocios(m, _sinal(m, 5, 1), stop=6.0)) == 0
    assert len(lab.negocios(m, _sinal(m, 30, 1), stop=6.0, ult="09:30")) == 0
    # zera no fim da janela, a mercado
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, zerar="09:30")
    assert t.saida[0] == "fim da janela" and t.pts[0] == -1.0


def test_entrada_por_ordem_parada_exige_passar_um_tick():
    # compra parada em 4.998: a barra 21 so toca 4.998 (nao executa); a 22 vai a 4.997,5 (executa a 4.998, sem deslize)
    b = [PARADO] * 21 + [(5000.0, 5000.0, 4998.0, 4999.0), (4999.0, 4999.0, 4997.5, 4998.5), (4998.5, 5003.0, 4998.5, 5003.0)] + [PARADO] * 5
    m = _dia(b)
    lim = np.full(len(m), np.nan)
    lim[20] = 4998.0
    t = lab.negocios(m, _sinal(m, 20, 1), stop=5.0, alvo=3.0, limite=lim, validade=5)
    assert len(t) == 1 and t.entrada[0] == 4998.0 and t.saida[0] == "alvo" and t.pts[0] == 3.0
    # sem passar o tick dentro da validade, nao ha negocio
    b = [PARADO] * 21 + [(5000.0, 5000.0, 4998.0, 4999.0)] * 8
    assert len(lab.negocios(_dia(b), _sinal(_dia(b), 20, 1), stop=5.0, limite=lim[:29], validade=5)) == 0


def test_arrasto_sobe_o_stop_so_na_barra_seguinte():
    b = [PARADO] * 21 + [(5000.0, 5008.0, 5000.0, 5008.0), (5008.0, 5008.0, 5004.0, 5004.0)] + [PARADO] * 5
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, arrasto=3.0)
    assert t.saida[0] == "stop movel" and t.pts[0] == pytest.approx(5005.0 - 0.5 - 5000.5)   # melhor 5.008, stop movel em 5.005


def test_sem_futuro_pega_regra_que_olha_a_barra_seguinte_e_evento_mede_sem_custo():
    rng = np.random.default_rng(3)
    c = 5000 + np.cumsum(rng.normal(0, 1, 3000)).round(1)
    idx = pd.date_range("2024-03-04 09:00", periods=3000, freq="min", name="hora")
    m = pd.DataFrame({"o": np.r_[5000.0, c[:-1]], "h": c + 1, "l": c - 1, "c": c, "n": 10.0, "v": 100.0}, index=idx)
    honesta = lambda x: np.sign(x.c - x.c.shift(3)).fillna(0).to_numpy()            # noqa: E731
    trapaca = lambda x: np.sign(x.c.shift(-1) - x.c).fillna(0).to_numpy()           # noqa: E731
    assert lab.sem_futuro(honesta, m) is True
    with pytest.raises(AssertionError):
        lab.sem_futuro(trapaca, m)
    tab = lab.evento(m, np.ones(len(m), bool), trapaca(m), horizontes=(1,), ini="00:00", ult="23:59", registrar=False)
    assert tab.media_pts[0] > 0.5                                 # quem ve o futuro ganha: o estudo de evento mede direito


# ── rotina da noite: o protocolo decide quem opera e quem so mede ──────────────────────────────────────────────
def _lista(dado=True, climax=True, niveis=False, lab_estado=None):
    from quant.pesquisa import noite
    modo = {"dado_opera": dado, "climax_opera": climax, "niveis_opera": niveis}
    reg = [] if lab_estado is None else [{"nome": "x", "titulo": "regra x", "estado": lab_estado, "aprovada": True, "historico": "ok"}]
    return noite.leituras(modo, reg), modo


def test_protocolo_rebaixa_a_reprovada_e_a_que_perde_ao_vivo():
    from quant.pesquisa import noite
    lista, modo = _lista()
    d = noite.decidir(lista, {}, modo)
    assert [(x["tecnica"], x["acao"]) for x in d] == [("climax de volume", "rebaixa")] and "reprovada no historico" in d[0]["motivo"]
    # aprovada que opera e perde ao vivo: 10 negocios com media de -R$ 80
    lista, modo = _lista(climax=False)
    pl = {"reversão do dado": {"sinais": 10, "media": -80.0, "t": -1.0, "soma": -800.0, "operados": 10, "soma_operados": -800.0, "media_operados": -80.0}}
    assert [(x["tecnica"], x["acao"]) for x in noite.decidir(lista, pl, modo)] == [("reversão do dado", "rebaixa")]
    pl["reversão do dado"].update(operados=9)                    # com 9 negocios ainda nao age
    assert noite.decidir(lista, pl, modo) == []
    # o que o Douglas travou nao e tocado
    lista, modo = _lista()
    modo["travado_pelo_douglas"] = ["climax_opera"]
    assert noite.decidir(lista, {}, modo) == []


def test_protocolo_promove_so_a_aprovada_com_amostra_e_pede_estudo_da_reprovada():
    from quant.pesquisa import noite
    lista, modo = _lista(climax=False, lab_estado="medido")
    bom = {"sinais": 25, "media": 60.0, "t": 1.4, "soma": 1500.0, "operados": 0, "soma_operados": 0.0, "media_operados": 0.0}
    d = noite.decidir(lista, {"regra x": bom, "nível e reação": dict(bom, sinais=80, t=2.5)}, modo)
    assert sorted((x["tecnica"], x["acao"]) for x in d) == [("nível e reação", "estudo"), ("regra x", "promove")]
    assert noite.decidir(lista, {"regra x": dict(bom, sinais=19)}, modo) == []          # amostra pequena: nao promove
    assert noite.decidir(lista, {"regra x": dict(bom, t=0.5)}, modo) == []


def test_rotina_da_noite_grava_as_chaves_e_o_relatorio(tmp_path, monkeypatch):
    import json as js
    from quant.pesquisa import noite
    arq_modo, arq_set = tmp_path / "modo.json", tmp_path / "setups.json"
    arq_modo.write_text(js.dumps({"regra": "niveis", "dado_opera": True, "climax_opera": True, "niveis_opera": False, "lote_base": 2}))
    arq_set.write_text(js.dumps({"regras": [{"nome": "x", "titulo": "regra x", "estado": "medido", "aprovada": True, "arquivo": "nao_importa.py"}]}))
    monkeypatch.setattr(noite, "DIR_RELATORIOS", str(tmp_path / "rel"))
    monkeypatch.setattr(noite, "ARQ_DECISOES", str(tmp_path / "decisoes.jsonl"))
    monkeypatch.setattr(noite, "agora_brt", lambda: pd.Timestamp("2026-10-09 19:20").to_pydatetime())
    bom = {"sinais": 25, "media": 60.0, "t": 1.4, "soma": 1500.0, "acerto": 60.0, "operados": 0, "soma_operados": 0.0, "media_operados": 0.0, "pregoes": 12, "ultimo": "2026-10-09"}
    monkeypatch.setattr(noite, "placar", lambda *a, **k: {"regra x": bom})
    texto, dec = noite.rodar(ensaio=True, pasta=str(tmp_path / "dt"), arq_modo=str(arq_modo), arq_setups=str(arq_set))
    assert "ENSAIO" in texto and js.loads(arq_modo.read_text())["climax_opera"] is True          # ensaio nao grava
    lista = noite.leituras(js.loads(arq_modo.read_text()), noite.regras_lab.ler_registro(str(arq_set)))
    noite.aplicar(dec, lista, str(arq_modo), str(arq_set), str(tmp_path / "decisoes.jsonl"))
    m = js.loads(arq_modo.read_text())
    assert m["climax_opera"] is False and m["dado_opera"] is True and m["lote_base"] == 2        # so a chave da leitura muda
    assert js.loads(arq_set.read_text())["regras"][0]["estado"] == "opera"
    assert "climax de volume: PASSA A SO MEDIR" in texto and "regra x: PASSA A OPERAR" in texto and "| regra x | opera | 25 em 12 pregoes" in texto
    # com o pregao aberto a rotina se recusa a mexer no robo
    monkeypatch.setattr(noite, "agora_brt", lambda: pd.Timestamp("2026-10-09 10:20").to_pydatetime())
    with pytest.raises(SystemExit):
        noite.rodar(ensaio=False, pasta=str(tmp_path / "dt"), arq_modo=str(arq_modo), arq_setups=str(arq_set))


def test_regra_de_laboratorio_roda_ao_vivo_uma_vez_por_barra(tmp_path):
    from quant.daytrade import regras_lab
    (tmp_path / "r.py").write_text("import numpy as np\ndef regra(m):\n    return np.where(m.c - m.o >= 3, -1.0, 0.0)\n")
    (tmp_path / "ruim.py").write_text("def regra(m):\n    raise ValueError('quebrou')\n")
    reg = {"regras": [{"nome": "contra_barra", "titulo": "contra a barra de 3 pontos", "arquivo": str(tmp_path / "r.py"), "estado": "medido",
                       "saida": {"stop": 8, "alvo": 4, "tempo": 15}},
                      {"nome": "ruim", "arquivo": str(tmp_path / "ruim.py"), "estado": "opera"},
                      {"nome": "aposentada", "arquivo": str(tmp_path / "r.py"), "estado": "aposentado"},
                      {"nome": "sem_arquivo", "arquivo": str(tmp_path / "nao_existe.py"), "estado": "medido"}]}
    (tmp_path / "setups.json").write_text(__import__("json").dumps(reg))
    boas, falhas = regras_lab.carregar(str(tmp_path / "setups.json"))
    assert [x.nome for x in boas] == ["contra_barra", "ruim"] and [f[0] for f in falhas] == ["sem_arquivo"]
    m = _dia([PARADO] * 20 + [(5000.0, 5004.0, 5000.0, 5004.0)])
    s = boas[0].atualizar(m)
    assert (s["tecnica"], s["lado"], s["stop_pts"], s["alvo_pts"], s["tempo_max_s"], s["sem_parcial"]) == ("contra a barra de 3 pontos", "V", 8.0, 4, 900.0, True)
    assert boas[0].atualizar(m) is None                              # a mesma barra nao da dois sinais
    assert boas[1].atualizar(m) is None and "quebrou" in boas[1].erro     # regra que quebra nao derruba nada
    assert boas[0].atualizar(_dia([PARADO] * 22)) is None


def test_contas_do_mini_indice_e_de_acao():
    # mini-indice: tick de 5 pontos, R$ 0,20 por ponto, R$ 0,30 por contrato e lado, 2 contratos
    b = [(130000.0,) * 4] * 21 + [(130000.0, 130400.0, 130000.0, 130400.0), (130400.0, 130400.0, 130300.0, 130300.0)] + [(130300.0,) * 4] * 5
    m = _dia(b)
    r = lab.avaliar(m, _sinal(m, 20, 1), "x", stop=300.0, alvo=200.0, ativo="WIN", registrar=False)
    t = lab.medir(r["negocios"], espec=lab.espec_de("WIN"))
    assert t.entrada[0] == 130005.0 and t.saida[0] == "alvo" and t.pts[0] == 200.0             # entra 1 tick (5 pontos) contra
    assert t.res[0] == pytest.approx(200.0 * 0.20 * 2 - 2 * 0.30 * 2) and r["ativo"] == "WIN"
    # acao de R$ 40: tick de 1 centavo, R$ 20 mil por negocio (500 acoes), taxa de 0,025% do financeiro por lado
    b = [(40.0,) * 4] * 21 + [(40.0, 40.5, 40.0, 40.5), (40.5, 40.5, 40.4, 40.4)] + [(40.4,) * 4] * 5
    m = _dia(b, "2024-03-04 10:00")
    r = lab.avaliar(m, _sinal(m, 20, 1), "x", stop=0.5, alvo=0.3, ativo="PETR4", ini="10:05", ult="16:30", zerar="16:50", registrar=False)
    t = lab.medir(r["negocios"], espec=lab.espec_de("PETR4"))
    assert t.entrada[0] == pytest.approx(40.01) and t.pts[0] == pytest.approx(0.3)
    qtd = 400.0                                                 # R$ 20 mil / 40,01 = 499 -> lote de 100: 400
    assert t.res[0] == pytest.approx(0.3 * qtd - 0.00025 * (40.01 + 40.31) * qtd)
    # o padrao continua sendo o mini-dolar
    assert lab.espec_de(None)["valor_ponto"] == 10.0 and lab.espec_de("vale3")["tipo"] == "acao"


def test_prova_viva_mede_so_os_pregoes_novos(tmp_path):
    from quant.pesquisa import prova_viva as pv
    (tmp_path / "r.py").write_text("import numpy as np\ndef regra(m):\n    return np.where((m.index.strftime('%H:%M') == '09:20'), 1.0, 0.0)\n")
    dias = []
    for d, sobe in (("2026-10-08", 3.0), ("2026-10-13", 3.0), ("2026-10-14", -2.0)):
        b = [PARADO] * 21 + [(5000.0 + sobe * k / 9, 5000.0 + sobe * (k + 1) / 9, 5000.0 + sobe * k / 9, 5000.0 + sobe * (k + 1) / 9) for k in range(9)] + [PARADO] * 3
        dias.append(_dia(b, d + " 09:00"))
    barras = pd.concat(dias)
    r = {"nome": "x", "arquivo": str(tmp_path / "r.py"), "ativo": "WDO", "desde": "2026-10-10", "kw": {"stop": 10.0, "tempo": 8}}
    res = pv.medir_regra(r, barras)
    assert res["negocios"] == 2 and res["ultimo"] == "2026-10-14" and res["pedir_estudo"] is False     # o pregao de 08/10 fica de fora
    assert "2 negocios desde 2026-10-10" in pv.texto([res]) and "ainda sem negocio" in pv.texto([dict(res, negocios=0)])
