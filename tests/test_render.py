import json
import os
from datetime import datetime, timezone

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
