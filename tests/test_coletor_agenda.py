"""Coletor: na noite do resultado a agenda abre o site de RI (sem rede)."""

import coletar_dados as cd


def _agenda(tmp_path):
    p = tmp_path / "calendario.yaml"
    p.write_text("resultados:\n"
                 "  - {ticker: VALE3, data: 2026-10-29, quando: apos_b3, confirmado: true}\n"
                 "  - {ticker: VALE3F, data: 2026-07-30, quando: apos_b3}\n", encoding="utf-8")
    return str(p)


def test_agenda_da_o_trimestre_divulgado(tmp_path):
    c = _agenda(tmp_path)
    assert cd.trimestre_da_agenda("VALE3", "2026-10-29", c) == "3T26"
    assert cd.trimestre_da_agenda("VALE3", "2026-11-10", c) == "3T26"
    # antes do dia, longe demais depois e ticker que so comeca igual: nada
    assert cd.trimestre_da_agenda("VALE3", "2026-10-28", c) is None
    assert cd.trimestre_da_agenda("VALE3", "2026-12-15", c) is None
    assert cd.trimestre_da_agenda("VALE", "2026-10-29", c) is None
    assert cd.trimestre_da_agenda("VALE3", "2026-10-29", str(tmp_path / "nao_existe.yaml")) is None


def test_noite_do_resultado_consulta_o_site_de_ri(monkeypatch):
    chamadas = []
    monkeypatch.setattr(cd, "trimestre_da_agenda", lambda tk: "3T26")
    monkeypatch.setattr(cd, "_referencia_frescor", lambda dados: ("2026T2", "calendario"))
    monkeypatch.setattr(cd, "periodos_a_buscar", lambda *a, **k: [])
    monkeypatch.setattr(cd, "periodos_oficiais", lambda dados: [])
    monkeypatch.setattr(cd, "fonte_ri_do_ativo", lambda *a, **k: ({"central": "x"}, "ri_fontes.py"))
    monkeypatch.setattr(cd, "coletar_releases_ri",
                        lambda tk, *a, **k: chamadas.append(k.get("ate_periodo")) or [])
    historico = [{"periodo": "2T26", "preferencia": 1}]
    cd._completar_pelo_site_ri("VALE3", {}, {}, historico, {}, [])
    assert chamadas == ["2T26"]
