"""Ferramentas do modo local (computador do Douglas): tudo aqui roda sem rede."""

import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(RAIZ, "ferramentas", "local")
for p in (RAIZ, LOCAL_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import fita  # noqa: E402
import mesa  # noqa: E402
import opcoes  # noqa: E402
import porque  # noqa: E402


def _json(gerado_em, **extra):
    return json.dumps({"gerado_em": gerado_em, **extra}).encode("utf-8")


def test_coleta_local_so_entra_quando_e_mais_nova(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mesa, "LOCAL", str(tmp_path))
    monkeypatch.setattr(mesa, "_LOCAL_AVISADO", set())
    os.makedirs(tmp_path / "ativos")
    (tmp_path / "ativos" / "CURY3.json").write_bytes(_json("2026-10-01T01:50:34Z", origem="pc"))
    # branch mais velho: vale a copia local, e o leitor avisa de onde veio
    escolhido = mesa._coleta_local("ativos/CURY3.json", _json("2026-09-30T22:57:41Z"))
    assert json.loads(escolhido)["origem"] == "pc"
    assert "coleta local" in capsys.readouterr().out
    # branch igual ou mais novo: o branch volta a mandar
    assert mesa._coleta_local("ativos/CURY3.json", _json("2026-10-01T01:50:34Z")) is None
    assert mesa._coleta_local("ativos/CURY3.json", _json("2026-10-01T02:10:00Z")) is None
    # arquivo que nao existe em dados_local/ nunca entra
    assert mesa._coleta_local("ativos/DIRR3.json", _json("2026-09-30T22:57:41Z")) is None


def test_coleta_local_cobre_o_branch_que_nao_respondeu(tmp_path, monkeypatch):
    monkeypatch.setattr(mesa, "LOCAL", str(tmp_path))
    monkeypatch.setattr(mesa, "_LOCAL_AVISADO", set())
    os.makedirs(tmp_path / "releases" / "CURY3")
    (tmp_path / "releases" / "CURY3" / "2026-08-11.txt").write_text("release", encoding="utf-8")
    assert mesa._coleta_local("releases/CURY3/2026-08-11.txt", None) == b"release"
    # texto de release e igual nos dois lados: com o branch respondendo, vale o branch
    assert mesa._coleta_local("releases/CURY3/2026-08-11.txt", b"release") is None


def test_simbolo_yahoo():
    assert fita.simbolo_yahoo("cury3") == "CURY3.SA"
    assert fita.simbolo_yahoo("SANB11") == "SANB11.SA"
    assert fita.simbolo_yahoo("IBOV") == "^BVSP"          # benchmark do config/livro.yaml
    assert fita.simbolo_yahoo("BRENT") == "BZ=F"          # id do livro
    assert fita.simbolo_yahoo("MU") == "MU"
    assert fita.simbolo_yahoo("CSPX.L") == "CSPX.L"


def test_formatos_brasileiros():
    assert fita.pct(-3.41) == "−3,4%"
    assert fita.pct(0.5) == "+0,5%"
    assert fita.pct(None) == "-"
    assert fita.num(186340.45, 0) == "186.340"
    assert porque.pp(-2.9) == "−2,9 pp"


def test_correlacao_dos_pares():
    from datetime import date, timedelta
    dias = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    a = {d: (i % 7) - 3.0 for i, d in enumerate(dias)}
    junto = {d: v * 0.8 for d, v in a.items()}
    contra = {d: -v for d, v in a.items()}
    assert porque.correlacao(a, junto) > 0.99
    assert porque.correlacao(a, contra) < -0.99
    assert porque.correlacao(a, {d: 1.0 for d in dias[:10]}) is None   # poucos dias em comum


def test_black_scholes_ida_e_volta():
    s0, k, t, r = 69.91, 66.64, 11 / 252, 0.1288
    for put in (True, False):
        premio = opcoes.bs_preco(s0, k, t, r, 0.34, put)
        assert abs(opcoes.vol_implicita(premio, s0, k, t, r, put) - 0.34) < 1e-4
    assert -1 < opcoes.bs_delta(s0, k, t, r, 0.34, True) < 0 < opcoes.bs_delta(s0, k, t, r, 0.34, False) < 1
    # premio abaixo do valor intrinseco nao tem volatilidade implicita
    assert opcoes.vol_implicita(0.01, 60.0, 70.0, 0.1, 0.13, True) is None


def test_cadeia_de_opcoes_montada_dos_arquivos_da_b3():
    from datetime import date
    instrumentos = [
        {"TckrSymb": "VALEV666", "Asst": "VALE3", "SctyCtgyNm": "OPTION ON EQUITIES", "OptnTp": "Put",
         "ExrcPric": "66,64", "XprtnDt": "2026-10-16", "OptnStyle": "EURO"},
        {"TckrSymb": "VALEV681W1", "Asst": "VALE3", "SctyCtgyNm": "OPTION ON EQUITIES", "OptnTp": "Put",
         "ExrcPric": "66,39", "XprtnDt": "2026-10-02", "OptnStyle": "EURO"},
        {"TckrSymb": "VALEJ700", "Asst": "VALE3", "SctyCtgyNm": "OPTION ON EQUITIES", "OptnTp": "Call",
         "ExrcPric": "70,00", "XprtnDt": "2026-10-16", "OptnStyle": "AMER"},
        {"TckrSymb": "VALEV500", "Asst": "VALE3", "SctyCtgyNm": "OPTION ON EQUITIES", "OptnTp": "Put",
         "ExrcPric": "50,00", "XprtnDt": "2026-10-16", "OptnStyle": "EURO"},
    ]
    negocios = [
        {"TckrSymb": "VALE3", "LastPric": "69,91", "TradQty": "30000"},
        {"TckrSymb": "VALEV666", "LastPric": "0,65", "RefPric": "0,66", "TradQty": "422", "NtlFinVol": "623000"},
        {"TckrSymb": "VALEV681W1", "LastPric": "0,03", "TradQty": "11", "NtlFinVol": "2000"},
        {"TckrSymb": "VALEJ700", "LastPric": "1,50", "TradQty": "10", "NtlFinVol": "9000"},
    ]
    c = opcoes.montar("VALE3", instrumentos, negocios, date(2026, 9, 30), 13.75, "put", (0.85, 1.02), False, None, 3)
    assert c["spot"] == 69.91
    series = [s for _v, lista in c["vencimentos"] for s in lista]
    assert [s["codigo"] for s in series] == ["VALEV666"]          # semanal, call e fora da faixa nao entram
    s = series[0]
    assert s["premio"] == 0.65 and s["origem"] == "ultimo" and s["negocios"] == 422
    assert abs(s["equilibrio"] - 65.99) < 1e-9 and 0.2 < s["vi"] < 0.6 and -0.5 < s["delta"] < 0
    com_semanais = opcoes.montar("VALE3", instrumentos, negocios, date(2026, 9, 30), 13.75, "put", (0.85, 1.02), False, None, 3, True)
    assert len(com_semanais["vencimentos"]) == 2
