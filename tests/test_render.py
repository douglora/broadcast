import json
import os
from datetime import date, datetime, timezone

from livro import coletar, fmt


def test_formatacao_brasileira():
    assert fmt.num(1234.5) == "1.234,50"
    assert fmt.pct(0.0123) == "+1,2%"
    assert fmt.pct(0.0996, 1, True, "") == "+10"   # arredonda e tira o decimal
    assert fmt.pct(-0.13) == "-13%"
    assert fmt.pct_col(0.0996) == "  +10"
    assert fmt.bps(15.0) == "+15" and fmt.bps(-3.2, 0) == "-3"
    assert fmt.preco(1688.0) == "1.688" and fmt.preco(5.0841, 4) == "5,0841"


def test_fechamento_offline_cabe_no_celular(fixtures_dir, tmp_path):
    saida = str(tmp_path / "livro")
    agora = datetime(2026, 9, 18, 21, 40, tzinfo=timezone.utc)
    m = coletar.executar("fechamento", saida, offline=fixtures_dir, agora=agora, run_id="teste")
    assert m["slot"] == "fechamento" and m["data_pregao"] == "2026-09-18"
    md = open(os.path.join(saida, "saida", "fechamento.md"), encoding="utf-8").read()
    blocos = md.split("```")
    a, b = blocos[1], blocos[3]
    assert len(a) <= 4000 and len(b) <= 4000
    for linha in (a + b).splitlines():
        assert len(linha) <= 52, linha
    assert "<<LEITURA_DA_MESA>>" in a
    assert "CURVAS" in a and "AGENDA" in a and "LACUNAS" in a
    assert "N/D" not in md and " ? " not in md
    # legenda com os 8 UCITS por extenso e a nota do IUAA (a legenda quebra linhas em 52 colunas)
    plano = " ".join(md.split())
    for nome in ("Vanguard FTSE All-World", "iShares Core S&P 500", "iShares NASDAQ 100", "High Dividend Yield",
                 "SPDR MSCI World Utilities", "Automation & Robotics", "iShares US Aggregate Bond", "Treasury Bond 0-1yr"):
        assert nome in plano
    assert "ultracurta" in plano
    # curvas com bps e vocabulario ABRIU/FECHOU
    assert "bps" in a and ("ABRIU" in a or "FECHOU" in a or "estável" in a)
    # json com janelas e insumos
    fj = json.load(open(os.path.join(saida, "saida", "fechamento.json"), encoding="utf-8"))
    assert "VALE3" in fj["janelas"] and fj["leitura_insumos"].get("ust")
    assert len(fj["push_sugerido"]) <= 200
    # celular: <= 41 colunas
    cel = open(os.path.join(saida, "saida", "fechamento_celular.md"), encoding="utf-8").read().split("```")[1]
    assert all(len(l) <= 41 for l in cel.splitlines())
    # alertas.md existe e o estado foi gravado com ids deterministicos
    fila = json.load(open(os.path.join(saida, "estado", "alertas.json"), encoding="utf-8"))
    assert all("-2026-09-1" in k for k in fila)
    # ack marca entregue sem recalcular nada
    ids = ",".join(list(fila)[:2])
    m2 = coletar.executar("ack", saida, ids_entregues=ids, agora=agora)
    assert m2["ack"] == 2
    fila2 = json.load(open(os.path.join(saida, "estado", "alertas.json"), encoding="utf-8"))
    assert all(fila2[i]["status"] == "entregue" for i in ids.split(","))


def test_intradia_sem_novidade_e_uma_linha(fixtures_dir, tmp_path):
    saida = str(tmp_path / "livro")
    agora = datetime(2026, 9, 18, 16, 20, tzinfo=timezone.utc)  # 13h20 BRT
    coletar.executar("intradia", saida, offline=fixtures_dir, agora=agora)
    txt = open(os.path.join(saida, "saida", "intradia.md"), encoding="utf-8").read().strip()
    assert txt.startswith("13h20 · sem alerta novo") or txt.startswith("ALERTAS")


def test_pct_sem_zero_negativo():
    assert fmt.pct(-0.0001) == "0,0%" and fmt.pct(0.0002) == "0,0%" and fmt.pct_col(-0.0003) == "  0,0"
    assert fmt.pct(-0.0006) == "-0,1%"


def test_backfill_nao_gera_alerta(fixtures_dir, tmp_path):
    saida = str(tmp_path / "livro")
    agora = datetime(2026, 9, 18, 21, 40, tzinfo=timezone.utc)
    m = coletar.executar("backfill", saida, offline=fixtures_dir, agora=agora, dias_backfill=5)
    assert m["slot"] == "backfill" and "alertas" not in m
    assert not os.path.exists(os.path.join(saida, "saida", "alertas.md"))
    assert not os.path.exists(os.path.join(saida, "estado", "alertas.json"))


def test_push_do_fechamento_cabe_e_nao_repete_ativo(fixtures_dir, tmp_path):
    saida = str(tmp_path / "livro")
    agora = datetime(2026, 9, 18, 22, 41, tzinfo=timezone.utc)
    coletar.executar("fechamento", saida, offline=fixtures_dir, agora=agora)
    fj = json.load(open(os.path.join(saida, "saida", "fechamento.json"), encoding="utf-8"))
    p = fj["push_sugerido"]
    assert len(p) <= 195 and p.endswith("Leitura na sessão.") and "MRVE3 MRVE3" not in p and "BRENT Brent" not in p
    assert "IPCA2032 IPCA+" not in p and "IPCA2035 IPCA+" not in p
    md = open(os.path.join(saida, "saida", "fechamento.md"), encoding="utf-8").read()
    assert "· 19h41 BRT" in md.splitlines()[2]
    # alertas que sairam como mensagem ficam marcados; os que viraram linha nao voltam a disputar o teto
    fila = json.load(open(os.path.join(saida, "estado", "alertas.json"), encoding="utf-8"))
    canais = {v.get("canal") for v in fila.values()}
    assert canais <= {"mensagem", "info"} and "mensagem" in canais
    assert all(v["status"] == "linha" for v in fila.values() if v.get("canal") == "info")


def test_bloco_a_nao_conta_manchete_no_digest():
    from livro import render
    do_dia = ([{"regra": "T05", "ativo": "MRVE3", "severidade": "critico", "familia": "preco", "titulo": "MRVE3 -8,4%", "status": "pendente"}]
              + [{"regra": "E03", "ativo": "PETR4", "severidade": "atencao", "familia": "evento", "titulo": "Fato Relevante: x",
                  "status": "pendente", "canal": "mensagem", "dados": {"manchete": "Fato Relevante: x", "veiculo": "CVM"}}]
              # cortada pelo teto: severidade atencao, mas nunca virou mensagem
              + [{"regra": "E05", "ativo": "VALE3", "severidade": "atencao", "familia": "noticia", "titulo": "cortada pelo teto",
                  "status": "linha", "canal": "info", "dados": {"manchete": "cortada pelo teto", "veiculo": "V"}}]
              # backlog antigo, sem canal gravado
              + [{"regra": "E05", "ativo": "KO", "severidade": "info", "familia": "noticia", "titulo": f"manchete {i}",
                  "status": "linha", "dados": {"manchete": f"manchete {i}", "veiculo": "V"}} for i in range(600)])
    a = render.bloco_a(date(2026, 9, 18), "Yahoo 18h40", do_dia, [], {}, ["DI"], ["agenda"], [], ["Yahoo"])
    assert "ALERTAS DO DIA (2 · 1 crítico)" in a
    plano = " ".join(a.split())
    # a contagem de manchetes sem materialidade so existe em noticias.md
    assert "NOTÍCIAS E FATOS (1 com materialidade · noticias.md)" in plano
    assert "601 só manchete" not in plano
    assert "manchete 0" not in a and "cortada pelo teto" not in a
    md = render.alertas_md({"mensagens": [], "linhas_info": [], "suprimidos": []}, do_dia, "Fechamento 18h40")
    assert "(+601 notícias só manchete, em noticias.md)" in md and "manchete 0" not in md


def test_podar_tira_manchete_antiga_e_guarda_o_que_virou_mensagem():
    from livro.estado import Repositorio
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = Repositorio(d)
        r.fila = {
            "velha-manchete": {"familia": "noticia", "canal": "info", "gerado_em": "2026-09-10T12:00:00Z"},
            "velha-mensagem": {"familia": "noticia", "canal": "mensagem", "gerado_em": "2026-09-10T12:00:00Z"},
            "tecnica-antiga": {"familia": "preco", "gerado_em": "2026-09-10T12:00:00Z"},
            "tecnica-velhissima": {"familia": "preco", "gerado_em": "2025-01-10T12:00:00Z"},
        }
        r.podar(dias=30, dias_manchete=2)
        assert set(r.fila) == {"velha-mensagem", "tecnica-antiga"}


def test_mesclar_detecta_rolagem_de_contrato_continuo():
    """BZ=F troca de vencimento e o Yahoo reprecifica a serie: unir misturaria contratos."""
    import pandas as pd
    from livro.fontes import yahoo
    dias = [d.date().isoformat() for d in pd.bdate_range(end="2026-09-18", periods=40)]
    antiga = {"barras": [[d, 98.0, 98.0, 98.0, 98.0, 98.0, 1] for d in dias]}
    # mesma serie 5% acima (rolagem): a nova vale sozinha, sem recuperar barra antiga
    nova = {"meta": {}, "barras": [[d, 103.0, 103.0, 103.0, 103.0, 103.0, 1] for d in dias[:-1]]}
    m = yahoo.mesclar(antiga, nova)
    assert m.get("reprecificada") and len(m["barras"]) == 39 and "barras_recuperadas" not in m
    # variacao normal do dia a dia nao dispara: a barra que falta e recuperada
    nova2 = {"meta": {}, "barras": [[d, 98.2, 98.2, 98.2, 98.2, 98.2, 1] for d in dias[:-1]]}
    m2 = yahoo.mesclar(antiga, nova2)
    assert "reprecificada" not in m2 and m2["barras_recuperadas"] == [dias[-1]]


def test_fechamento_usa_a_barra_do_pregao_em_mercado_continuo():
    """Fechamento do pregao de 18/09 nao pode usar a barra de 19/09 do BTC (24/7)."""
    import pandas as pd
    from livro import indicadores as ind
    barras = [[d.date().isoformat(), 100.0, 100.0, 100.0, 100.0, 100.0, 1] for d in pd.bdate_range(end="2026-09-17", periods=300)]
    barras += [["2026-09-18", 110.0, 110.0, 110.0, 110.0, 110.0, 1], ["2026-09-19", 99999.0, 99999.0, 99999.0, 99999.0, 99999.0, 1]]
    df = ind.para_df(barras)
    assert ind.janelas(df)["data"] == "2026-09-19"                      # sem corte, pega o sabado
    j = ind.janelas(df, ate=date(2026, 9, 18))
    assert j["data"] == "2026-09-18" and j["ultimo"] == 110.0 and round(j["dia"], 3) == 0.1


def test_cabecalho_avisa_coleta_de_outro_dia():
    from livro import render
    a = render.bloco_a(date(2026, 9, 18), "Yahoo 15h10", [], [], {}, ["DI"], ["agenda"], [], ["Yahoo"], hora="15h10 de 19/09")
    assert a.splitlines()[0] == "FECHAMENTO DO LIVRO · sex 18/09 · 15h10 de 19/09 BRT"


def test_do_dia_inclui_o_que_foi_descoberto_hoje_sobre_documento_antigo():
    from livro.estado import Repositorio
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = Repositorio(d)
        r.fila = {
            "E04-AMZN-x-2026-09-09": {"data": "2026-09-09", "gerado_em": "2026-09-19T18:22:00Z", "severidade": "atencao"},
            "T05-MRVE3-x-2026-09-18": {"data": "2026-09-18", "gerado_em": "2026-09-18T21:40:00Z", "severidade": "critico"},
            "E05-KO-x-2026-09-05": {"data": "2026-09-05", "gerado_em": "2026-09-05T12:00:00Z", "severidade": "info"},
        }
        # so o pregao: o 8-K achado hoje fica de fora
        assert {a["data"] for a in r.do_dia("2026-09-18")} == {"2026-09-18"}
        # pregao + data da coleta: entra, e o antigo de verdade continua fora
        ordem = r.do_dia("2026-09-18", "2026-09-19")
        assert {a["data"] for a in ordem} == {"2026-09-18", "2026-09-09"}
        # critico primeiro; dentro da severidade, o mais recente na frente
        r.fila["E03-PETR4-y-2026-09-18"] = {"data": "2026-09-18", "gerado_em": "2026-09-18T09:00:00Z", "severidade": "atencao"}
        at = [a["gerado_em"] for a in r.do_dia("2026-09-18", "2026-09-19") if a["severidade"] == "atencao"]
        assert at == sorted(at, reverse=True)


def test_alerta_reavaliado_sai_com_o_numero_final():
    """Yahoo reprecifica a serie no meio do dia: o texto na fila tem de acompanhar,
    senao o alerta diz 98,77 e a tabela diz 99,29 no mesmo fechamento."""
    import tempfile
    from livro.estado import Repositorio
    from livro.sinais.base import Alerta

    def brent(preco, ret):
        return Alerta("F03", "BRENT", "critico", "commodity",
                      f"Brent cai a US$ {preco} ({ret}% no dia · cruzou US$ 100)",
                      tag="queda", data="2026-09-18", corpo=[f"Em reais: R$ {preco}/barril"],
                      por_que="queda do barril reduz receita", fonte="ICE via Yahoo 18/09",
                      dados={"close": preco})

    with tempfile.TemporaryDirectory() as d:
        repo = Repositorio(d)
        assert len(repo.registrar([brent("98,77", "-5,8")], "intradia")) == 1
        repo.marcar_entregues([brent("98,77", "-5,8").id])
        # mesma regra, mesmo id, numero final no fechamento
        assert repo.registrar([brent("99,29", "-5,3")], "fechamento") == []
        v = repo.fila[brent("99,29", "-5,3").id]
        assert "99,29" in v["titulo"] and "-5,3" in v["titulo"]
        assert "Em reais: R$ 99,29/barril" in v["corpo"]
        assert v["dados"]["close"] == "99,29"
        assert v["titulo_inicial"].startswith("Brent cai a US$ 98,77")   # trilha de auditoria
        assert v["atualizado_em"]
        # o que e estado de entrega nao pode ter sido mexido
        assert v["status"] == "entregue" and v["entregue_em"] and v["slot"] == "intradia"
        assert v["severidade"] == "critico"


def test_alerta_sem_mudanca_nao_marca_atualizacao():
    import tempfile
    from livro.estado import Repositorio
    from livro.sinais.base import Alerta
    a = Alerta("T05", "MRVE3", "critico", "preco", "MRVE3 -8,4%", tag="queda", data="2026-09-18")
    with tempfile.TemporaryDirectory() as d:
        repo = Repositorio(d)
        repo.registrar([a], "fechamento")
        repo.registrar([a], "fechamento")
        assert "atualizado_em" not in repo.fila[a.id]
        assert "titulo_inicial" not in repo.fila[a.id]


def test_do_dia_conta_a_coleta_em_brt_e_nao_puxa_alerta_de_preco_de_ontem():
    from livro.estado import Repositorio
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = Repositorio(d)
        r.fila = {
            # fechamento de 23/09 rodado as 21h03 BRT = 00h03 UTC de 24/09
            "C07-UST-x-2026-09-23": {"data": "2026-09-23", "gerado_em": "2026-09-24T00:03:00Z", "severidade": "critico",
                                     "familia": "curva"},
            "E05-PETR4-x-2026-09-23": {"data": "2026-09-23", "gerado_em": "2026-09-24T00:03:00Z", "severidade": "atencao",
                                       "familia": "noticia"},
            "T08-COHR-x-2026-09-24": {"data": "2026-09-24", "gerado_em": "2026-09-24T21:13:00Z", "severidade": "critico",
                                      "familia": "preco"},
            "E03-AXIA3-x-2026-09-22": {"data": "2026-09-22", "gerado_em": "2026-09-24T14:00:00Z", "severidade": "atencao",
                                       "familia": "evento"},
        }
        ids = {k for k, v in r.fila.items() if v in r.do_dia("2026-09-24", "2026-09-24")}
        assert ids == {"T08-COHR-x-2026-09-24", "E03-AXIA3-x-2026-09-22"}
        # a noticia das 21h de 23/09 (BRT) conta para 23/09
        assert "E05-PETR4-x-2026-09-23" in {k for k, v in r.fila.items() if v in r.do_dia("2026-09-23")}
