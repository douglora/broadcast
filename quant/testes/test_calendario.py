from datetime import date

from quant.dados import calendario as c


def test_feriados_e_fins_de_semana():
    assert not c.eh_pregao("2026-04-21")      # Tiradentes
    assert not c.eh_pregao("2026-11-20")      # Consciencia Negra (nacional desde 2024)
    assert not c.eh_pregao("2026-09-07")      # Independencia
    assert not c.eh_pregao("2026-09-05")      # sabado
    assert c.eh_pregao("2026-09-08")
    assert c.eh_pregao("2026-09-04")


def test_navegacao():
    assert c.pregao_anterior("2026-09-08") == date(2026, 9, 4)
    assert c.proximo_pregao("2026-09-04") == date(2026, 9, 8)
    assert c.ultimo_pregao_ate("2026-09-07") == date(2026, 9, 4)
    assert c.ultimo_pregao_do_mes(2026, 8) == date(2026, 8, 31)
    assert c.ultimo_pregao_do_mes(2025, 12) == date(2025, 12, 30)   # 31/12 nao tem pregao
    assert c.pregoes_atras("2026-09-08", 2) == date(2026, 9, 3)
    assert len(c.pregoes("2026-09-01", "2026-09-08")) == 5


def test_fora_da_cobertura_b3_usa_anbima():
    assert not c.eh_pregao("2027-04-21")
    assert c.eh_pregao("2027-04-22")
