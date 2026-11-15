"""Prazo da SEC pelo trimestre FISCAL de cada empresa (calendario_fiscal.py), no leitor e no coletor.

Nasceu do falso alarme de 15/11/2026: LITE e MRVL sairam com "ITR VELHO" e "falta 3T26" porque a
mesa media empresa dos EUA pelo calendario da CVM (3T26 vence em 14/11). A Marvell fecha o ano no fim
de janeiro e o trimestre dela que acabou em 31/10 so tem 10-Q devido em dezembro; a Lumentum fecha em
junho. Junto vieram a receita da Lumentum (trocou de tag no XBRL e parava no 1T25) e o 4T fiscal de
quem nao fecha o ano em dezembro (Broadcom, Ciena, Coherent, Lumentum ficavam sem os 12 meses).

Tudo sem rede: os JSONs e o companyfacts sao de brinquedo. As empresas da B3 continuam no calendario
da CVM, e isso tambem e testado aqui.
"""
import datetime as dt
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import calendario_fiscal as F  # noqa: E402
import mesa  # noqa: E402

try:
    import coletar_dados as CD
except Exception as e:          # ambiente sem as dependencias do coletor (yfinance, flask)
    CD = None
    _MOTIVO_CD = f"coletar_dados nao importa aqui: {type(e).__name__}"
else:
    _MOTIVO_CD = ""

precisa_coletor = pytest.mark.skipif(CD is None, reason=_MOTIVO_CD or "coletor indisponivel")

HOJE = dt.date(2026, 11, 15)
HOJE_DT = dt.datetime(2026, 11, 15, 12, 0)


def _agora_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _release(periodo, data):
    return {"periodo": periodo, "data": data, "fonte": "SEC 8-K", "classe_sec": "sim",
            "caracteres_total": 20000, "preferencia": 1}


def _sec(receita, fim_periodo=None, fim_exercicio=None):
    bloco = {"trimestral": {"receita": receita}}
    if fim_periodo is not None:
        bloco["fim_periodo"] = fim_periodo
    if fim_exercicio is not None:
        bloco["fim_exercicio"] = fim_exercicio
    return bloco


def _mrvl(cabeca="2T26", com_datas=True):
    """Marvell: exercicio fecha no fim de janeiro; o trimestre de 01/08/2026 e o CY2026Q2."""
    sec = _sec({"CY2026Q1": 1.9e9, "CY2026Q2": 2.0e9},
               {"CY2026Q1": "2026-05-02", "CY2026Q2": "2026-08-01"} if com_datas else None,
               "2026-01-31" if com_datas else None)
    d = {"gerado_em": _agora_iso(), "sec_xbrl": sec, "releases_historico": [_release(cabeca, "2026-08-28")]}
    if not com_datas:
        d["yahoo"] = {"demonstracoes": {"dre_trimestral": {"Total Revenue": {"2026-07-31": 2.0e9, "2026-04-30": 1.9e9}}}}
    return d


def _amzn():
    """Quem fecha o ano em dezembro: o 10-Q do 3T26 vencia em 14/11 e continua cobrado."""
    return {"gerado_em": _agora_iso(),
            "sec_xbrl": _sec({"CY2026Q1": 1.0, "CY2026Q2": 1.0}, {"CY2026Q1": "2026-03-31", "CY2026Q2": "2026-06-30"},
                             "2025-12-31"),
            "releases_historico": [_release("2T26", "2026-07-30")]}


def _b3():
    """Companhia da B3 com ITR na CVM ate o 2T26: o calendario da CVM nao muda."""
    return {"gerado_em": _agora_iso(),
            "cvm_demonstracoes": {"serie_trimestral": {"receita_liquida": {"2026T1": 1.0, "2026T2": 1.0}}},
            "releases_historico": [{"periodo": "2T26", "data": "2026-08-10", "fonte": "CVM IPE",
                                    "caracteres_total": 50000, "preferencia": 1}]}


# ───────────────────────── calendario_fiscal.py ─────────────────────────

def test_frame_da_data_segue_a_regra_dos_frames_da_sec():
    assert F.frame_da_data("2026-08-01") == (2026, 2)       # Marvell
    assert F.frame_da_data("2026-09-26") == (2026, 3)       # Lumentum
    assert F.frame_da_data("2026-11-01") == (2026, 3)       # Broadcom (fecha o exercicio)
    assert F.frame_da_data("2026-12-31") == (2026, 4)
    assert F.frame_da_data("lixo") is None


def test_par_do_frame_aceita_saldo_de_balanco():
    assert F.par_do_frame("CY2026Q2") == (2026, 2)
    assert F.par_do_frame("CY2026Q2I") == (2026, 2)
    assert F.par_do_frame("CY2026") is None


def test_fim_seguinte_mes_cheio_e_ano_de_52_semanas():
    assert F.fim_seguinte(dt.date(2026, 6, 30), 1) == dt.date(2026, 9, 30)
    assert F.fim_seguinte(dt.date(2026, 9, 30), 1) == dt.date(2026, 12, 31)
    assert F.fim_seguinte(dt.date(2026, 3, 31), -1) == dt.date(2025, 12, 31)
    assert F.fim_seguinte(dt.date(2026, 9, 26), 1) == dt.date(2026, 12, 26)     # 13 semanas


def test_marvell_trimestre_de_outubro_so_vence_em_dezembro():
    r = F.vencido_fiscal({"CY2026Q2": "2026-08-01"}, "2026-01-31", HOJE)
    assert r["par"] == (2026, 2)
    assert r["proximo_par"] == (2026, 3)
    assert r["proximo_fim"] == dt.date(2026, 10, 31)
    assert r["proximo_vencimento"] == dt.date(2026, 12, 15)
    assert not r["proximo_e_10k"]


def test_broadcom_proximo_e_10k_com_prazo_de_90_dias():
    r = F.vencido_fiscal({"CY2026Q2": "2026-08-02"}, "2025-11-02", HOJE)
    assert r["par"] == (2026, 2)
    assert r["proximo_e_10k"]
    assert r["proximo_vencimento"] == r["proximo_fim"] + dt.timedelta(days=90)


def test_quem_fecha_em_dezembro_continua_com_o_3t_vencido_em_14_11():
    r = F.vencido_fiscal({"CY2026Q2": "2026-06-30"}, "2025-12-31", HOJE)
    assert r["par"] == (2026, 3)
    assert r["vencimento"] == dt.date(2026, 11, 14)


def test_trimestre_entregue_antes_do_prazo_nao_conta_como_devido():
    # Lumentum: 10-Q do trimestre de 26/09 entregue em 04/11, prazo em 10/11
    fins = {"CY2026Q2": "2026-06-27", "CY2026Q3": "2026-09-26"}
    assert F.vencido_fiscal(fins, "2026-06-27", "2026-11-05")["par"] == (2026, 2)
    assert F.vencido_fiscal(fins, "2026-06-27", "2026-11-10")["par"] == (2026, 3)


def test_trimestre_que_fecha_o_exercicio_tem_90_dias():
    # 4T fiscal da Lumentum fechou em 27/06/2026: 10-K vence em 25/09, nao em 11/08
    fins = {"CY2026Q1": "2026-03-28", "CY2026Q2": "2026-06-27"}
    assert F.vencido_fiscal(fins, "2026-06-27", "2026-09-01")["par"] == (2026, 1)
    assert F.vencido_fiscal(fins, "2026-06-27", "2026-09-25")["par"] == (2026, 2)


def test_ancora_velha_anda_ate_hoje():
    # XBRL parado em 2019 (emissor que trocou de formulario): a conta nao para em oito trimestres
    assert F.vencido_fiscal({"CY2019Q2": "2019-06-30"}, "2018-12-31", HOJE)["par"] == (2026, 3)


def test_sem_datas_nao_ha_calendario_fiscal():
    assert F.vencido_fiscal({}, None, HOJE) is None
    assert F.vencido_fiscal(None, None, HOJE) is None


def test_fins_do_yahoo_rotula_pelo_frame():
    dem = {"dre_trimestral": {"Total Revenue": {"2026-07-31": 1.0, "2026-04-30": 1.0, "2026-01-31": None}}}
    assert F.fins_do_yahoo(dem) == {"CY2026Q1": "2026-04-30", "CY2026Q2": "2026-07-31"}
    assert F.fins_do_yahoo(None) == {}


def test_q4_fiscal_exercicio_menos_os_tres_trimestres():
    periodos = [("2025-06-29", "2026-06-27", 1000, "2026-08-20"),          # exercicio
                ("2025-06-29", "2025-09-27", 200, "2025-11-05"),
                ("2025-09-28", "2025-12-27", 240, "2026-02-04"),
                ("2025-12-28", "2026-03-28", 260, "2026-05-06"),
                ("2025-06-29", "2025-12-27", 440, "2026-02-04")]           # semestre acumulado: ignorado
    assert F.q4_fiscal(periodos) == {(2026, 2): (300, "2026-06-27")}


def test_q4_fiscal_recusa_trimestres_com_buraco():
    periodos = [("2025-06-29", "2026-06-27", 1000, "2026-08-20"),
                ("2025-06-29", "2025-09-27", 200, "2025-11-05"),
                ("2025-12-28", "2026-03-28", 260, "2026-05-06")]
    assert F.q4_fiscal(periodos) == {}


# ───────────────────────── leitor (mesa.py) ─────────────────────────

def test_mesa_marvell_nao_acusa_itr_velho():
    motivos, _, detalhes = mesa.avaliar_frescor("MRVL", _mrvl(), hoje=HOJE_DT)
    assert motivos == []
    linha = next(x for x in detalhes if x.startswith("calendario fiscal da SEC"))
    assert "o seguinte fecha em 31/10/2026 e o 10-Q vence em 15/12/2026" in linha


def test_mesa_marvell_sem_datas_do_xbrl_usa_as_do_yahoo():
    motivos, _, detalhes = mesa.avaliar_frescor("MRVL", _mrvl(com_datas=False), hoje=HOJE_DT)
    assert motivos == []
    assert any("datas do Yahoo" in x for x in detalhes)


def test_mesa_quem_fecha_em_dezembro_continua_cobrado():
    motivos, _, _ = mesa.avaliar_frescor("AMZN", _amzn(), hoje=HOJE_DT)
    assert any(m.startswith("ITR VELHO (calendario fiscal da SEC: 3T26 venceu em 14/11, XBRL e 2T26") for m in motivos)


def test_mesa_b3_continua_no_calendario_da_cvm():
    motivos, _, detalhes = mesa.avaliar_frescor("CPLE3", _b3(), hoje=HOJE_DT)
    assert any(m.startswith("ITR VELHO (calendario: 3T26 venceu em 14/11, ITR e 2T26") for m in motivos)
    assert any(m.startswith("RELEASE VELHO (calendario: 3T26") for m in motivos)
    assert not any("fiscal da SEC" in x for x in detalhes)


def test_mesa_janela_da_marvell_e_da_b3():
    assert mesa.janela_obrigatoria(_mrvl(), 8, HOJE_DT)[0] == "2T26"
    assert mesa.janela_obrigatoria(_b3(), 8, HOJE_DT)[0] == "3T26"


def test_mesa_release_um_trimestre_a_frente_empurra_a_janela():
    janela = mesa.janela_obrigatoria(_mrvl(cabeca="3T26"), 8, HOJE_DT)
    assert janela[0] == "3T26" and len(janela) == 8
    # dois trimestres a frente e rotulo suspeito: nao mexe na janela
    assert mesa.janela_obrigatoria(_mrvl(cabeca="4T26"), 8, HOJE_DT)[0] == "2T26"


# ───────────────────────── coletor (coletar_dados.py) ─────────────────────────

@precisa_coletor
def test_coletor_trimestre_vencido_do_ativo():
    assert CD.trimestre_vencido_ativo(_mrvl(), hoje="2026-11-15") == "2026T2"
    assert CD.trimestre_vencido_ativo(_amzn(), hoje="2026-11-15") == "2026T3"
    assert CD.trimestre_vencido_ativo(_b3(), hoje="2026-11-15") == "2026T3"
    assert CD.trimestre_vencido_ativo({}, hoje="2026-11-15") == "2026T3"


@precisa_coletor
def test_coletor_cobertura_da_marvell_fecha_sem_o_3t26():
    janela = ["2T26", "1T26", "4T25", "3T25", "2T25", "1T25", "4T24", "3T24"]
    historico = [_release(p, "2026-01-01") for p in janela]
    venc = CD.trimestre_vencido_ativo(_mrvl(), hoje="2026-11-15")
    c = CD.cobertura_releases(historico, 8, hoje="2026-11-15", vencido=venc)
    assert c["janela"][0] == "2T26" and c["completa"] and not c["faltando"]
    # pelo calendario da CVM a mesma Marvell cobraria o 3T26, que ela ainda nem fechou
    assert "3T26" in CD.cobertura_releases(historico, 8, hoje="2026-11-15")["faltando"]


@precisa_coletor
def test_coletor_referencia_empurrada_pelo_release_recem_saido():
    d = _mrvl()
    ref, origem = CD._referencia_frescor(d, [_release("3T26", "2026-11-02")], hoje="2026-11-15")
    assert (ref, origem) == ("2026T3", "release")
    ref, _ = CD._referencia_frescor(d, [_release("2T26", "2026-08-28")], hoje="2026-11-15")
    assert CD._ano_trimestre(ref) == (2026, 2)
    ref, _ = CD._referencia_frescor(d, [_release("4T26", "2026-11-02")], hoje="2026-11-15")
    assert CD._ano_trimestre(ref) == (2026, 2)


class _Resposta:
    def __init__(self, dados):
        self._dados = dados

    def json(self):
        return self._dados


def _fato(ini, fim, val, fp, form, filed, frame=None):
    f = {"start": ini, "end": fim, "val": val, "fp": fp, "form": form, "filed": filed}
    if frame:
        f["frame"] = frame
    return f


def _companyfacts_lumentum():
    """Lumentum de brinquedo: a tag Excluding para no 1T26 do calendario; a Including vai ate o 3T26."""
    incl = [
        _fato("2025-06-29", "2026-06-27", 1000, "FY", "10-K", "2026-08-20"),
        _fato("2025-06-29", "2025-09-27", 200, "Q1", "10-Q", "2025-11-05", "CY2025Q3"),
        _fato("2025-09-28", "2025-12-27", 240, "Q2", "10-Q", "2026-02-04", "CY2025Q4"),
        _fato("2025-06-29", "2025-12-27", 440, "Q2", "10-Q", "2026-02-04"),
        _fato("2025-12-28", "2026-03-28", 260, "Q3", "10-Q", "2026-05-06", "CY2026Q1"),
        _fato("2026-06-28", "2026-09-26", 330, "Q1", "10-Q", "2026-11-04", "CY2026Q3"),
    ]
    excl = [_fato("2025-06-29", "2025-09-27", 1, "Q1", "10-Q", "2025-11-05", "CY2025Q3"),
            _fato("2025-12-28", "2026-03-28", 1, "Q3", "10-Q", "2026-05-06", "CY2026Q1")]
    return {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": excl}},
        "RevenueFromContractWithCustomerIncludingAssessedTax": {"units": {"USD": incl}},
    }}}


class _DataFixa(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 15, 12, 0, tzinfo=tz)


@precisa_coletor
def test_coletor_xbrl_acha_a_receita_nova_as_datas_e_o_4t_fiscal(monkeypatch):
    monkeypatch.setattr(CD, "_cik_por_ticker", lambda s: 1633978)
    monkeypatch.setattr(CD.app, "http_get", lambda *a, **k: _Resposta(_companyfacts_lumentum()))
    monkeypatch.setattr(CD, "datetime", _DataFixa)
    fontes = {}
    out = CD.coletar_sec_xbrl("LITE", fontes)
    assert out["tags_usadas"]["receita"] == "RevenueFromContractWithCustomerIncludingAssessedTax"
    tri = out["trimestral"]["receita"]
    assert tri["CY2026Q2"] == 300                       # 4T fiscal: 1000 - 200 - 240 - 260
    assert "CY2026Q2" in out["derivados"]["receita"]
    assert out["ltm"]["receita"]["ate"] == "CY2026Q3"
    assert out["ltm"]["receita"]["valor"] == 240 + 260 + 300 + 330
    assert out["fim_periodo"]["CY2026Q3"] == "2026-09-26"
    assert out["fim_periodo"]["CY2026Q2"] == "2026-06-27"
    assert out["fim_exercicio"] == "2026-06-27"
    # e o calendario que sai dessas datas: 10-Q do trimestre de 26/09 venceu em 10/11
    r = CD.calendario_fiscal_do_ativo({"sec_xbrl": out}, hoje="2026-11-15")
    assert r["par"] == (2026, 3) and r["origem"] == "datas do XBRL"


_FUSAO = ("EX-99.1 Exhibit 99.1 MARVELL AND LUMENTUM TO COMBINE, CREATING A CATEGORY LEADER IN AI CONNECTIVITY "
          "Combines two of the fastest-growing enablers of AI. Marvell and Lumentum today announced that they have "
          "entered into a definitive agreement for Marvell to acquire Lumentum in an all-stock transaction. "
          "Combined revenue of $12.4 billion, net revenue growth of 45%, gross margin of 60%, $3.2 billion of cash, "
          "$1.1 billion of operating income and $2.5 billion in synergies. " * 3)
_RESULTADO = ("EX-99.1 NEWS RELEASE LUMENTUM ANNOUNCES FIRST QUARTER OF FISCAL YEAR 2027 FINANCIAL RESULTS "
              "Net revenue of $1.26 billion, GAAP gross margin of 51.0%, GAAP net income of $360.3 million. "
              "Separately, Lumentum entered into a definitive agreement to combine with Marvell. " * 3)


@precisa_coletor
def test_classificador_recusa_anuncio_de_fusao():
    classe, _, motivo = CD.classificar_documento_sec(_FUSAO, "d81187dex991.htm", "3T26")
    assert classe == "nao" and "M&A" in motivo


@precisa_coletor
def test_classificador_aceita_resultado_que_cita_a_fusao():
    assert CD.classificar_documento_sec(_RESULTADO, "lite_ex991xq1fy27.htm", "3T26")[0] == "release"
