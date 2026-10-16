"""Revisao do pregao (14/10/2026: "todo pregao ele tem que rever a estrategia e ver onde ele errou") e os consertos das falhas
de 14/10: robo cego depois de fechar o MetaTrader, sinal marcado 'opera' que nao entrou, prova viva da noite sem o pregao."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from quant.pesquisa import revisao as rv

BRT = timezone(timedelta(hours=-3))
DIA = "2026-10-14"
_SONO_DO_MAC = rv.sono_do_mac


@pytest.fixture(autouse=True)
def _sem_metatrader_nem_pmset(monkeypatch):
    """Teste nunca pede barras ao MetaTrader de verdade (o pedido vai para a pasta dele, com o pregao aberto) nem le o registro de
    sono DESTE Mac: quem testa o sono passa o texto do pmset."""
    def _sem_servidor(*a, **k):
        raise RuntimeError("teste: sem MetaTrader")
    monkeypatch.setattr(rv, "barras_do_servidor", _sem_servidor)
    monkeypatch.setattr(rv, "sono_do_mac", lambda dia, texto=None: [] if texto is None else _SONO_DO_MAC(dia, texto))


def _barras(inicio="09:00", fim="18:29", preco=5050.0, caminho=None, dia=DIA):
    idx = pd.date_range(f"{dia} {inicio}", f"{dia} {fim}", freq="1min")
    c = np.full(len(idx), preco) if caminho is None else np.asarray(caminho(idx), dtype=float)
    return pd.DataFrame({"o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "n": 10.0, "v": 100.0}, index=idx)


def _dist():
    lista = [-814.8] * 10 + [-300.0] * 20 + [-150.0] * 10 + [100.0] * 30 + [400.0] * 30
    return {rv.DADO: {"n": len(lista), "media": float(np.mean(lista)), "desvio": float(np.std(lista, ddof=1)), "acerto": 60.0, "lista": lista,
                      "sequencias": {"maior": 3, "freq_k": {"1": 0.4, "2": 0.15, "3": 0.05, "4": 0.0}},
                      "contexto_descoberta": {"reacao": {">10": {"n": 73, "media": 167.0, "acerto": 61.6, "t": 2.4}},
                                              "tipo_do_dia": {"cpi": {"n": 31, "media": 74.9, "acerto": 48.4, "t": 0.7},
                                                              "nenhum": {"n": 155, "media": -5.0, "acerto": 48.0, "t": -0.1}},
                                              "lado": {"V": {"n": 149, "media": 95.0, "acerto": 56.4, "t": 1.9}},
                                              "hora": {"09:31": {"n": 234, "media": 107.3, "acerto": 58.5, "t": 2.8}}},
                      "contexto_2025": {"tipo_do_dia": {"cpi": {"n": 10, "media": 40.2}}}},
            "nível e reação": {"n": 1000, "media": -27.0, "desvio": 100.0, "acerto": 43.0,
                               "quantis": {"10": -150.0, "50": -30.0, "90": 120.0}, "sequencias": {"maior": 15, "freq_k": {}}}}


def _pregao(tmp_path, dia=DIA, tipo_do_dia="cpi", resultado=-154.8, sinais_extra=()):
    """Um pregao como o de 14/10: venda do dado as 9h32, saida por tempo as 11h32 com -7,5 pontos."""
    pasta = tmp_path / "dt"
    (pasta / dia).mkdir(parents=True, exist_ok=True)
    est = {"operacoes": [{"tipo": "saida", "ativo": "WDOFUT", "lado": "V", "contratos": 2, "entrada": 5054.0, "hora_entrada": "09:32:00",
                          "saida": 5061.5, "hora_saida": "11:32:00", "motivo": "tempo esgotado", "pontos": -7.5, "custos": 4.8,
                          "tecnica": rv.DADO, "nome_nivel": "reação de +10,5 pontos ao dado das 09h30", "resultado": resultado}],
           "diario": [{"hora": f"{h}:00", "tipo": "feed", "texto": "Cotações em rajadas. Reabrindo o MetaTrader sozinho"} for h in ("09:19", "10:34", "11:52")],
           "curva": [["09:00", 0.0]]}
    (pasta / dia / "estado_niveis.json").write_text(json.dumps(est))
    medidas = {"movimento": 10.5, "hora_dado": "09:30", "tipo_do_dia": tipo_do_dia, "deriva_pre_dado": 9.0}
    linhas = [{"tipo": "sinal", "ativo": "WDOFUT", "tecnica": "nível e reação", "lado": "V", "entrada": 5035.5, "stop_pts": 4.0, "alvo_pts": 14.0,
               "opera": True, "hora": "09:01:01", "quando": f"{dia}T09:01:01-03:00"},
              {"tipo": "sinal", "ativo": "WDOFUT", "tecnica": rv.DADO, "lado": "V", "entrada": 5054.0, "stop_pts": 40.0, "tempo_max_s": 7200.0,
               "opera": True, "hora": "09:32:00", "quando": f"{dia}T09:32:00-03:00", "medidas": medidas},
              {"tipo": "entrada", "ativo": "WDOFUT", "tecnica": rv.DADO, "lado": "V", "contratos": 2, "entrada": 5054.0, "hora": "09:32:00",
               "medidas": medidas},
              {"tipo": "sinal", "ativo": "WDOFUT", "tecnica": "nível e reação", "lado": "C", "entrada": 5050.5, "stop_pts": 4.5, "alvo_pts": 20.0,
               "opera": True, "hora": "09:48:00", "quando": f"{dia}T09:48:00-03:00"}, *sinais_extra]
    (pasta / dia / "sinais_niveis.jsonl").write_text("\n".join(json.dumps(x) for x in linhas) + "\n")
    # o robo montou barras so ate 11h50 (cego depois)
    robo = _barras("09:00", "11:50")
    with open(pasta / "m1_WDOFUT.csv", "a") as f:
        for t, x in robo.iterrows():
            f.write(f"{t:%Y-%m-%d %H:%M:%S};{x.o};{x.h};{x.l};{x.c};{x.v}\n")
    return pasta


def _servidor(dia=DIA):
    # vende a 5054 as 9h32; a minima chega a 5044 (10 pontos a favor) ate 10h20 e o preco sobe a 5061,5 ate 11h32
    def caminho(idx):
        m = (idx - pd.Timestamp(f"{dia} 09:32")).total_seconds() / 60
        return np.where(m < 0, 5050.0, np.where(m < 48, 5054.0 - m * (9.5 / 48), np.minimum(5044.5 + (m - 48) * (17.0 / 72), 5061.5)))
    return _barras(caminho=caminho, dia=dia)


def test_percentil_e_sequencia_contra_o_historico():
    d = _dist()[rv.DADO]
    assert rv.percentil(-154.8, d) == 30.0                                  # 30 de 100 negocios foram iguais ou piores
    assert rv.percentil(-30.0, _dist()["nível e reação"]) == 50.0         # pelos quantis, interpolado
    assert rv.sequencia_final([100, -5, -10]) == 2 and rv.sequencia_final([-1, 5]) == 0
    assert rv.julgar_sequencia(2, d)["normal"] is True and rv.julgar_sequencia(4, d)["normal"] is False
    assert rv._rs(-154.8) == "-R$ 154,80" and rv._rs(1234.5, 0) == "+R$ 1.234" and rv._pt(5054.0) == "5.054,0"   # formato brasileiro
    jv = rv.julgar_ao_vivo([-300.0] * 12, d)
    assert jv["pior"] is True and jv["n"] == 12


def test_saidas_alternativas_com_as_contas_do_laboratorio():
    b = _servidor()
    t0 = pd.Timestamp(f"{DIA} 09:32")
    base = rv.simular_saida(b, t0, 5054.0, "V")                             # stop 40, 120 minutos: sai na abertura das 11h32
    assert base["motivo"] == "tempo" and base["pontos"] == -8.0             # abertura 5061,5 + 1 tick contra
    assert rv.simular_saida(b, t0, 5054.0, "V", alvo=8.0)["motivo"] == "alvo"          # chegou a 10 pontos a favor
    assert rv.simular_saida(b, t0, 5054.0, "V", alvo=10.0)["motivo"] == "tempo"        # alvo so conta passando 1 tick
    assert rv.simular_saida(b, t0, 5054.0, "V", tempo=60)["resultado"] > base["resultado"]
    melhor, pior = rv.caminho(b, t0, pd.Timestamp(f"{DIA} 11:33"), 5054.0, "V")
    assert melhor >= 10.0 and pior <= -7.0


def test_intervalo_cego_e_motivo_de_sinal_que_nao_entrou():
    srv, robo = _barras("09:00", "12:30"), _barras("09:00", "11:50")
    assert rv.intervalos_cegos(srv, robo) == [("11:51", "12:30", 40)]
    assert rv.intervalos_cegos(srv, srv) == []
    neg = [{"tecnica": rv.DADO, "hora_entrada": "09:32:00", "hora_saida": "11:32:00", "resultado": -154.8}]
    ent = [{"tecnica": rv.DADO, "hora": "09:32:00"}]
    m = lambda s: rv.motivo_sem_entrada(s, ent, neg, {}, DIA)
    assert m({"tecnica": rv.DADO, "hora": "09:32:01", "opera": True}) == ("entrou", None)
    assert m({"tecnica": "nível e reação", "hora": "09:01:01", "opera": True})[0] == "antes da janela"
    assert m({"tecnica": "nível e reação", "hora": "09:01:01", "opera": True})[1]               # e uma falha (b)
    assert m({"tecnica": "nível e reação", "hora": "10:12:00", "opera": True}) == ("posição aberta", None)   # uma por vez: regra
    assert m({"tecnica": "nível e reação", "hora": "09:01:01", "opera": False}) == ("só medido", None)
    assert m({"tecnica": "nível e reação", "hora": "09:01:01", "opera": True, "bloqueio": "antes da janela (09:15)"}) == ("antes da janela", None)
    assert m({"tecnica": "nível e reação", "hora": "11:33:00", "opera": True}) == ("espera depois da saída", None)
    assert m({"tecnica": "nível e reação", "hora": "12:10:00", "opera": True})[0] == "sem motivo conhecido"


def test_contexto_do_dado_separa_faixa_sem_vantagem():
    d = _dist()[rv.DADO]
    ctx = rv.contexto_do_dado({"movimento": 10.5, "hora_dado": "09:30", "tipo_do_dia": "cpi", "lado": "V"}, d)
    assert {x["campo"]: x["fora"] for x in ctx} == {"reacao": False, "tipo_do_dia": False, "lado": False, "hora": False}
    ctx = rv.contexto_do_dado({"movimento": 10.5, "hora_dado": "09:30", "tipo_do_dia": "nenhum", "lado": "V"}, d)
    assert [x["faixa"] for x in ctx if x["fora"]] == ["nenhum"]


def test_revisao_do_pregao_de_14_10_ponta_a_ponta(tmp_path, monkeypatch):
    pasta = _pregao(tmp_path)
    monkeypatch.setattr(rv, "ranking_historico_das_saidas", lambda: {"base": 100.0, "tempo 60": 42.0, "tempo 90": 84.0})
    rev = rv.revisar(DIA, pasta=str(pasta), servidor=_servidor(), dist=_dist(), consertos=[])
    chaves = [x["chave"] for x in rev["itens"]]
    assert "b:metatrader:reaberturas" in chaves and "b:metatrader:cego" in chaves
    cego = next(x for x in rev["itens"] if x["chave"] == "b:metatrader:cego")
    assert cego["inicio"] == "11:51" and cego["minutos"] >= 150
    a = next(x for x in rev["itens"] if x["chave"] == f"a:{rv.DADO}:resultado")
    assert a["percentil"] == 30.0 and "dentro do esperado" in a["texto"]
    assert "b:sinal:antes da janela" in chaves and not any(c.startswith("b:sinal:posição") for c in chaves)
    assert not any(x["categoria"] == "c" for x in rev["itens"])               # CPI, reacao > 10, venda: contexto a favor
    d = [x for x in rev["itens"] if x["categoria"] == "d"]
    assert d and d[0]["chave"].startswith(f"d:{rv.DADO}:tempo") and "nada muda" in d[0]["acao"]   # no historico a base rende mais
    regra = next(x for x in rev["por_regra"] if x["tecnica"] == "nível e reação")
    assert regra["sinais"] == 2 and regra["por_motivo"] == {"antes da janela": 1, "posição aberta": 1}
    # gravar: caderno, arquivos do dia e o bloco da tela
    tela = tmp_path / "quant.json"
    tela.write_text(json.dumps({"v": 2, "tipo": "daytrade"}))
    fila = tmp_path / "FILA.md"
    fila.write_text("# Fila\n\n## A testar\n\n6. item velho\n\n## Testadas\n")
    g = rv.gravar(rev, arq_caderno=str(tmp_path / "rev" / "caderno.jsonl"), arq_fila=str(fila), dir_rev=str(tmp_path / "rev"),
                  telas=[str(tela)], consertos=[{"dia": DIA, "chave": "b:metatrader:cego", "texto": "o robô insiste em reabrir", "teste": "t"}])
    assert "percentil 30" in g["manchete"] and "cego" in g["manchete"]
    assert any("Conserto: o robô insiste" in x for x in g["muda_amanha"]) and any("nada muda" in x for x in g["muda_amanha"])
    q = json.loads(tela.read_text())
    assert q["revisao"]["titulo"].startswith("Revisão do pregão") and q["revisao"]["itens"] and q["tipo"] == "daytrade"
    assert (tmp_path / "rev" / f"{DIA}.md").exists() and (tmp_path / "rev" / "caderno_de_erros.md").exists()
    caderno = [json.loads(x) for x in (tmp_path / "rev" / "caderno.jsonl").read_text().splitlines()]
    assert {x["categoria"] for x in caderno} >= {"a", "b", "d"} and fila.read_text().count("[revisao:") == 0    # 1o pregao: nada na fila


def test_padrao_repetido_abre_item_na_fila_e_falha_repetida_vira_manchete(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "ranking_historico_das_saidas", lambda: {"base": 100.0, "tempo 60": 42.0})
    fila = tmp_path / "FILA.md"
    fila.write_text("# Fila\n\n## A testar\n\n6. item velho\n\n26. outro\n\n## Testadas\n")
    kw = dict(arq_caderno=str(tmp_path / "rev" / "caderno.jsonl"), arq_fila=str(fila), dir_rev=str(tmp_path / "rev"), telas=[], consertos=[])
    for dia in ("2026-10-14", "2026-10-15"):
        pasta = _pregao(tmp_path, dia=dia, tipo_do_dia="nenhum")
        g = rv.gravar(rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[]), **kw)
    texto = fila.read_text()
    assert texto.count("[revisao: c:reversão do dado:tipo_do_dia=nenhum]") == 1 and "27. [revisao:" in texto
    assert texto.index("[revisao:") < texto.index("## Testadas")
    assert g["manchete"].startswith("FALHA REPETIDA") and "b:metatrader:cego" in g["caderno"]["falhas_repetidas"]
    # rodar de novo no mesmo dia nao duplica nada
    rv.gravar(rv.revisar("2026-10-15", pasta=str(pasta), servidor=_servidor("2026-10-15"), dist=_dist(), consertos=[]), **kw)
    assert fila.read_text().count("[revisao:") == texto.count("[revisao:")


def test_robo_anota_quando_fica_cego_e_quando_volta(tmp_path, monkeypatch):
    from quant.testes.test_daytrade_fluxo import _robo
    rf, r, _mt5 = _robo(tmp_path, monkeypatch, "2026-10-14")
    t0 = datetime(2026, 10, 14, 11, 52, 0, tzinfo=BRT)
    r.cot = {"WDOFUT": {"preco": 5056.0, "ts_tique": t0.timestamp()}}
    r._vigiar_cegueira(t0 + timedelta(seconds=30))
    assert r.cego_desde is None                                               # 30 s sem tique: ainda nao
    r._vigiar_cegueira(t0 + timedelta(minutes=2))
    assert r.cego_desde == t0.timestamp() and not r.cego_avisado
    r._vigiar_cegueira(t0 + timedelta(minutes=6))
    assert r.cego_avisado and "o robô está cego" in r.diario[-1]["texto"] and "11:52" in r.diario[-1]["texto"]
    assert r._cegueira_ate_agora(t0 + timedelta(minutes=6)) == [["11:52", "11:58", 6]]
    volta = t0 + timedelta(minutes=40)
    r.cot["WDOFUT"]["ts_tique"] = volta.timestamp()
    r._vigiar_cegueira(volta)
    assert r.cegueira == [["11:52", "12:32", 40]] and r.cego_desde is None and "Cotação de volta às 12:32" in r.diario[-1]["texto"]
    r._salvar()
    assert json.loads(open(r.arq_estado).read())["cegueira"] == [["11:52", "12:32", 40]]
    # fora do pregao nao conta
    r.cot["WDOFUT"]["ts_tique"] = 0.0
    r._vigiar_cegueira(datetime(2026, 10, 14, 19, 0, 0, tzinfo=BRT))
    assert r.cego_desde is None


def test_sinal_guarda_por_que_nao_entrou(tmp_path, monkeypatch):
    from quant.daytrade import estrategia_fluxo as ef
    from quant.testes.test_daytrade_fluxo import _robo
    rf, r, _mt5 = _robo(tmp_path, monkeypatch, "2026-10-14")
    s = {"tecnica": "nível e reação", "lado": "V", "nivel": 5040.0, "nome_nivel": "abertura", "stop_pts": 4.0}
    assert r._bloqueio("WDOFUT", datetime(2026, 10, 14, 9, 1, 1, tzinfo=BRT), s).startswith("antes da janela")
    assert r._bloqueio("WDOFUT", datetime(2026, 10, 14, 9, 30, 0, tzinfo=BRT), s) == "pausa do dado"
    assert r._bloqueio("WDOFUT", datetime(2026, 10, 14, 9, 30, 0, tzinfo=BRT), dict(s, ignora_pausa=True)) is None
    r.estados["WDOFUT"].posicao = ef.PosicaoF("V", 2, 5054.0, 5094.0, "09:32:00", rv.DADO, 5043.5, "reação")
    assert r._bloqueio("WDOFUT", datetime(2026, 10, 14, 10, 12, 0, tzinfo=BRT), s) == f"posição aberta ({rv.DADO})"
    r.cot = {"WDOFUT": {"preco": 5063.0}}
    r._guardar_sinal("WDOFUT", s, datetime(2026, 10, 14, 10, 12, 0, tzinfo=BRT), opera=True)
    linha = json.loads(open(tmp_path / "dt" / "2026-10-14" / f"sinais_{r.setup}.jsonl").read().splitlines()[-1])
    assert linha["opera"] is True and linha["bloqueio"] == f"posição aberta ({rv.DADO})"


def test_placar_da_noite_conta_como_operado_so_o_que_entrou(tmp_path):
    from quant.daytrade import medir
    pasta = _pregao(tmp_path)
    s = medir.sinais("niveis", str(pasta), pasta_mt5=str(tmp_path))
    por = {(x["tecnica"], x["hora"]): x for x in s}
    assert por[(rv.DADO, "09:32:00")]["entrou"] is True
    assert por[("nível e reação", "09:01:01")]["opera"] is True and por[("nível e reação", "09:01:01")]["entrou"] is False


def test_prova_viva_da_noite_pede_barras_novas():
    from quant.pesquisa import prova_viva as pv
    manha, noite = datetime(2026, 10, 14, 8, 13, tzinfo=BRT), datetime(2026, 10, 14, 19, 34, tzinfo=BRT)
    assert pv.rotulo_do_pedido(manha, 2) == 2610142                         # o de sempre de manha
    assert pv.rotulo_do_pedido(noite, 2) == 261014 * 100 + 52 != pv.rotulo_do_pedido(manha, 2)


def test_rotina_da_noite_roda_a_revisao_antes_do_protocolo(tmp_path, monkeypatch):
    from quant.pesquisa import noite
    chamadas = []
    monkeypatch.setattr(noite, "agora_brt", lambda: pd.Timestamp("2026-10-14 19:20").to_pydatetime())
    (tmp_path / "dt" / DIA).mkdir(parents=True)
    rev = {"dia": DIA, "manchete": "1 negócio(s), R$ -154.80; perda dentro da distribuição histórica (percentil 33).",
           "itens": [{"categoria": "b", "chave": "b:metatrader:cego", "texto": "o robô ficou sem cotação de 11:51 a 18:19", "acao": "conserto"}],
           "muda_amanha": ["Conserto: o robô insiste em reabrir o MetaTrader"]}
    monkeypatch.setattr(rv, "revisar", lambda dia, pasta=None: chamadas.append(("revisar", dia)) or rev)
    monkeypatch.setattr(rv, "gravar", lambda r, ensaio=False: chamadas.append(("gravar", ensaio)) or r)
    monkeypatch.setattr(noite, "placar", lambda *a, **k: chamadas.append(("placar",)) or {})
    arq_modo = tmp_path / "modo.json"
    arq_modo.write_text(json.dumps({"dado_opera": True, "climax_opera": False, "niveis_opera": False}))
    (tmp_path / "s.json").write_text(json.dumps({"regras": []}))
    texto, _d = noite.rodar(ensaio=True, pasta=str(tmp_path / "dt"), arq_modo=str(arq_modo), arq_setups=str(tmp_path / "s.json"))
    assert [c[0] for c in chamadas] == ["revisar", "gravar", "placar"]
    assert "Revisao do pregao" in texto and "percentil 33" in texto and "Conserto: o robô insiste" in texto


# ── varredura de 15/10/2026 ───────────────────────────────────────────────────
# o registro de energia do macOS na manha de 15/10/2026 (linhas reais, encurtadas): dormiu as 8h00 na bateria, so DarkWakes de
# manutencao, e acordou de verdade as 9h24 com a tampa aberta
PMSET_1510 = """2026-10-15 08:00:15 -0300 DarkWake            \tDarkWake from Deep Idle [CDNP] : due to rtc/Maintenance Using BATT (Charge:100%) 5 secs
2026-10-15 08:00:20 -0300 Sleep               \tEntering Sleep state due to 'Maintenance Sleep':TCPKeepAlive=active Using Batt (Charge:100%) 1056 secs
2026-10-15 08:00:22 -0300 Wake Requests       \t[*process=dasd request=SleepService deltaSecs=1054 wakeAt=2026-10-15 08:17:56]
2026-10-15 09:00:00 -0300 DarkWake            \tDarkWake from Deep Idle [CDNP] : due to rtc/Maintenance Using BATT (Charge:100%) 5 secs
2026-10-15 09:00:05 -0300 Sleep               \tEntering Sleep state due to 'Maintenance Sleep':TCPKeepAlive=active Using Batt (Charge:100%) 70 secs
2026-10-15 09:18:11 -0300 DarkWake            \tDarkWake from Deep Idle [CDNP] : due to rtc/SleepService Using BATT (Charge:100%) 2 secs
2026-10-15 09:18:13 -0300 Sleep               \tEntering Sleep state due to 'Sleep Service Back to Sleep' Using Batt (Charge:100%) 337 secs
2026-10-15 09:24:18 -0300 Wake                \tWake from Deep Idle [CDNVA] : due to smc.sysState.Wake lid SMC.OutboxNotEmpty Using BATT (Charge:100%)
2026-10-15 18:40:00 -0300 Sleep               \tEntering Sleep state due to 'Clamshell Sleep' Using AC (Charge:100%) 60 secs
"""


def _pregao_1510(tmp_path, cegueira, negocios_win=False, sinais_win=False, labs_rodando=None, vespera=None, sinais=()):
    """15/10: o robo so montou barras do mini-dolar a partir das 9h25 (antes o Mac dormia), sem negocio do dolar."""
    dia = "2026-10-15"
    pasta = tmp_path / "dt"
    (pasta / dia).mkdir(parents=True, exist_ok=True)
    est = {"operacoes": [], "diario": [], "curva": [["09:25", 0.0]], "cegueira": cegueira}
    if labs_rodando is not None:
        est["labs_rodando"] = labs_rodando
    if vespera is not None:
        est["vespera"] = vespera
    linhas = list(sinais)
    if negocios_win:      # o mini-indice da regra do laboratorio: comprou 1 a 209.105 as 17h41 e saiu por tempo as 18h06 a 209.400
        est["operacoes"].append({"tipo": "saida", "ativo": "WINFUT", "lado": "C", "contratos": 1, "entrada": 209105.0, "hora_entrada": "17:41:03",
                                 "saida": 209400.0, "hora_saida": "18:06:03", "motivo": "tempo esgotado", "pontos": 295.0, "custos": 0.6,
                                 "tecnica": "fim do pregão (teste)", "nome_nivel": "fim do pregão (teste)", "resultado": 58.4})
    if sinais_win:
        linhas += [{"tipo": "sinal", "ativo": "WINFUT", "tecnica": "fim do pregão (teste)", "lado": "C", "entrada": 209105.0, "stop_pts": 500.0,
                    "tempo_max_s": 1500.0, "opera": True, "bloqueio": None, "hora": "17:41:03", "quando": f"{dia}T17:41:03-03:00", "medidas": {"dose": 1}},
                   {"tipo": "entrada", "ativo": "WINFUT", "tecnica": "fim do pregão (teste)", "lado": "C", "contratos": 1, "entrada": 209105.0, "hora": "17:41:03"}]
    (pasta / dia / "estado_niveis.json").write_text(json.dumps(est))
    (pasta / dia / "sinais_niveis.jsonl").write_text("".join(json.dumps(x) + "\n" for x in linhas))
    with open(pasta / "m1_WDOFUT.csv", "w") as f:
        for t, x in _barras("09:25", "18:19", dia=dia).iterrows():
            f.write(f"{t:%Y-%m-%d %H:%M:%S};{x.o};{x.h};{x.l};{x.c};{x.v}\n")
    with open(pasta / "m1_WINFUT.csv", "w") as f:
        for t, x in _barras("09:00", "18:19", preco=209200.0, dia=dia).iterrows():
            f.write(f"{t:%Y-%m-%d %H:%M:%S};{x.c};{x.c + 250};{x.c - 150};{x.c};0.0\n")
    return pasta, dia


REG_WIN = [{"nome": "win_teste", "titulo": "fim do pregão (teste)", "arquivo": "x.py", "ativo": "WINFUT", "estado": "opera",
            "janela": ["17:30", "18:10"], "saida": {"stop": 500, "tempo": 25}, "contratos": 1}]


def test_sono_do_mac_pelo_registro_de_energia():
    assert rv.sono_do_mac("2026-10-15", PMSET_1510) == [("08:00", "09:24"), ("18:40", "23:59")]   # o DarkWake nao acorda
    assert rv.sono_do_mac("2026-10-14", PMSET_1510) == []
    assert rv.fracao_dormindo("09:00", "09:24", [("08:00", "09:24")]) == 1.0
    assert rv.fracao_dormindo("11:51", "18:19", [("08:00", "09:24")]) == 0.0
    assert rv.sono_do_mac("2026-10-15", "") == []


def test_mac_dormindo_vira_item_proprio_e_nao_falha_repetida_do_metatrader(tmp_path, monkeypatch):
    """Achado 42: o robo de 15/10 ainda grava a cegueira com 3 campos; a revisao reconhece o sono pelo pmset e nao acusa o MetaTrader."""
    pasta, dia = _pregao_1510(tmp_path, cegueira=[["09:00", "09:24", 24]])
    sono = rv.sono_do_mac(dia, PMSET_1510)
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=sono, registro=[])
    chaves = [x["chave"] for x in rev["itens"]]
    assert "b:mac:dormiu" in chaves and "b:metatrader:cego" not in chaves
    item = next(x for x in rev["itens"] if x["chave"] == "b:mac:dormiu")
    assert item["inicio"] == "09:00" and "Mac estava dormindo" in item["texto"] and "tomada" in item["acao"]
    caderno = tmp_path / "rev" / "caderno.jsonl"
    caderno.parent.mkdir()
    caderno.write_text(json.dumps({"dia": "2026-10-14", "categoria": "b", "chave": "b:metatrader:cego", "texto": "cego"}) + "\n"
                       + json.dumps({"dia": "2026-10-14", "categoria": "b", "chave": "b:mac:dormiu", "texto": "dormiu"}) + "\n")
    g = rv.gravar(rev, ensaio=True, arq_caderno=str(caderno), dir_rev=str(tmp_path / "rev"), telas=[], consertos=[])
    assert not g["manchete"].startswith("FALHA REPETIDA") and "Mac dormindo 2" in g["manchete"]
    # o robo novo ja anota o motivo: vale mesmo sem o pmset
    pasta, dia = _pregao_1510(tmp_path / "b", cegueira=[["09:00", "09:24", 24, "mac_dormindo"]])
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=[])
    assert [x["chave"] for x in rev["itens"] if x["chave"].startswith("b:")] == ["b:mac:dormiu"]
    # sem sono, a mesma cegueira continua sendo do MetaTrader
    pasta, dia = _pregao_1510(tmp_path / "c", cegueira=[["09:00", "09:24", 24]])
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=[])
    assert "b:metatrader:cego" in [x["chave"] for x in rev["itens"]]


def test_regra_do_mini_indice_fora_do_robo_nao_e_cegueira(tmp_path, monkeypatch):
    """Achado 10: a revisao de 14/10 disse que a regra do mini-indice 'nao rodou porque o robo estava cego' e que o conserto do
    MetaTrader cobria; ela nunca rodaria, o robo nao percorria o contrato dela."""
    cego = [["11:51", "18:19", 388]]
    pasta, dia = _pregao_1510(tmp_path, cegueira=cego)
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=REG_WIN,
                     ativos_robo=("WDOFUT",))
    fora = [x for x in rev["itens"] if x["chave"] == "b:lab:fora_do_robo:win_teste"]
    assert len(fora) == 1 and "não rodou" in fora[0]["texto"] and "WINFUT" in fora[0]["texto"] and "15/10/2026" in fora[0]["acao"]
    assert not any(x["chave"].startswith("b:cego:") for x in rev["itens"])
    # robo novo (grava labs_rodando) e a regra deu sinal e entrou: nada de "fora do robo" nem de "perdida por cegueira"
    pasta, dia = _pregao_1510(tmp_path / "b", cegueira=cego, negocios_win=True, sinais_win=True, labs_rodando={"win_teste": "WINFUT"})
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=REG_WIN,
                     ativos_robo=("WDOFUT",))
    chaves = [x["chave"] for x in rev["itens"]]
    assert not any(c.startswith(("b:lab:fora_do_robo", "b:cego:")) for c in chaves)
    # o negocio do mini-indice e conferido nas barras do mini-indice (antes: nas do mini-dolar, e a saida "ficava fora da barra")
    assert "b:execucao:saida_fora_da_barra" not in chaves
    regra = next(x for x in rev["por_regra"] if x["tecnica"] == "fim do pregão (teste)")
    assert regra["operados"] == 1 and regra["por_motivo"] == {"entrou": 1}
    # robo novo que rodou a regra, ficou cego na janela e ela nao deu sinal: ai sim e perdida por cegueira
    pasta, dia = _pregao_1510(tmp_path / "c", cegueira=cego, labs_rodando={"win_teste": "WINFUT"})
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=REG_WIN)
    assert [x["chave"] for x in rev["itens"] if x["chave"].startswith(("b:cego:", "b:lab:"))] == ["b:cego:win_teste"]


# ── revisao de 15/10/2026 (problemas apontados pelo revisor no conserto dos achados 10 e 44) ──
def _sinal_win(hora, bloqueio):
    return {"tipo": "sinal", "ativo": "WINFUT", "tecnica": "fim do pregão (teste)", "lado": "C", "entrada": 209105.0, "stop_pts": 500.0,
            "tempo_max_s": 1500.0, "opera": False, "bloqueio": bloqueio, "hora": hora, "quando": f"2026-10-15T{hora}-03:00", "medidas": {"dose": 1}}


def test_barra_atrasada_da_regra_que_opera_vira_item_do_caderno(tmp_path):
    """A regra que opera e ficou so medida porque a barra do motor chegou atrasada e falha de execucao: antes ia so para por_motivo, com uma
    chave por minuto ('barra das 17:39 chegou atrasada', 'barra das 17:40 ...'), e nao virava item do caderno."""
    sinais = [_sinal_win("17:41:03", "barra das 17:39 chegou atrasada"), _sinal_win("17:42:03", "barra das 17:40 chegou atrasada")]
    pasta, dia = _pregao_1510(tmp_path, cegueira=[], labs_rodando={"win_teste": "WINFUT"}, vespera={"WINFUT": None}, sinais=sinais)
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=REG_WIN)
    item = [x for x in rev["itens"] if x["chave"] == "b:sinal:barra atrasada"]
    assert len(item) == 1 and "2 sinal(is) de fim do pregão (teste) (17:41, 17:42)" in item[0]["texto"]
    assert "barra das 17:39 chegou atrasada; barra das 17:40 chegou atrasada" in item[0]["texto"] and "motor" in item[0]["acao"]
    regra = next(x for x in rev["por_regra"] if x["tecnica"] == "fim do pregão (teste)")
    assert regra["por_motivo"] == {"barra atrasada": 2}
    assert not any(x["chave"].startswith("b:lab:vespera") for x in rev["itens"])


def test_vespera_incompleta_do_mini_indice_vira_item_da_regra(tmp_path):
    """A regra do mini-indice decide pela ultima barra do pregao anterior. Com a vespera cortada (15h54) ela decide as 15h23, fora da janela,
    e nao da sinal: a revisao nao acusava nada, porque labs_rodando dizia que a regra rodou. Agora o robo grava a vespera e a revisao acusa."""
    falha = "as barras de 14/10 terminam às 15:54, e o pregão termina às 18:24"
    pasta, dia = _pregao_1510(tmp_path, cegueira=[], labs_rodando={"win_teste": "WINFUT"}, vespera={"WINFUT": falha})
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=REG_WIN)
    item = [x for x in rev["itens"] if x["chave"] == "b:lab:vespera:win_teste"]
    assert len(item) == 1 and falha in item[0]["texto"] and "não deu sinal no minuto da pesquisa" in item[0]["texto"]
    assert "MetaTrader" in item[0]["acao"]
    # com o sinal so medido pela vespera: o mesmo item (da regra), e o sinal conta pelo motivo, sem item duplicado
    sinais = [_sinal_win("17:40:03", "véspera incompleta: " + falha)]
    pasta, dia = _pregao_1510(tmp_path / "b", cegueira=[], labs_rodando={"win_teste": "WINFUT"}, vespera={"WINFUT": falha}, sinais=sinais)
    rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=REG_WIN)
    assert [x["chave"] for x in rev["itens"] if x["chave"].startswith(("b:lab:", "b:sinal:"))] == ["b:lab:vespera:win_teste"]
    assert "o sinal de hoje ficou só medido" in rev["itens"][-1]["texto"]
    assert next(x for x in rev["por_regra"] if x["tecnica"] == "fim do pregão (teste)")["por_motivo"] == {"véspera incompleta": 1}
    # vespera boa, ou estado antigo sem o campo: nada
    for vesp in ({"WINFUT": None}, None):
        pasta, dia = _pregao_1510(tmp_path / f"c{vesp is None}", cegueira=[], labs_rodando={"win_teste": "WINFUT"}, vespera=vesp)
        rev = rv.revisar(dia, pasta=str(pasta), servidor=_servidor(dia), dist=_dist(), consertos=[], sono=[], registro=REG_WIN)
        assert not any(x["chave"].startswith("b:lab:vespera") for x in rev["itens"])
