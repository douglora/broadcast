from datetime import date, datetime, timezone

from livro import relogios


def test_fechamento_em_brt_antes_e_depois_do_horario_de_verao():
    assert relogios.fechamento_brt("NYSE", date(2026, 9, 18)).strftime("%H:%M") == "17:00"
    assert relogios.fechamento_brt("NYSE", date(2026, 11, 2)).strftime("%H:%M") == "18:00"
    assert relogios.fechamento_brt("LSE", date(2026, 9, 18)).strftime("%H:%M") == "12:30"
    assert relogios.fechamento_brt("LSE", date(2026, 10, 26)).strftime("%H:%M") == "13:30"
    assert relogios.fechamento_brt("B3", date(2026, 11, 2 + 1)).strftime("%H:%M") == "17:00"


def test_feriados_por_mercado():
    assert not relogios.eh_dia_util("B3", date(2026, 10, 12))
    assert relogios.eh_dia_util("NYSE", date(2026, 10, 12))
    assert not relogios.eh_dia_util("NYSE", date(2026, 11, 26))
    assert not relogios.eh_dia_util("LSE", date(2026, 12, 28))
    assert relogios.ultimo_dia_util("B3", date(2026, 10, 12)) == date(2026, 10, 9)


def test_data_referencia_depende_da_hora():
    tarde = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)   # 15h BRT
    assert relogios.data_referencia("LSE", tarde) == date(2026, 9, 18)   # LSE fechou 12h30
    assert relogios.data_referencia("B3", tarde) == date(2026, 9, 17)    # B3 so fecha 17h
    noite = datetime(2026, 9, 18, 21, 40, tzinfo=timezone.utc)   # 18h40 BRT
    assert relogios.data_referencia("B3", noite) == date(2026, 9, 18)
    assert relogios.data_referencia("NYSE", noite) == date(2026, 9, 18)
    sabado = datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)
    assert relogios.data_referencia("B3", sabado) == date(2026, 9, 18)


def test_vencimento_di_e_dias_uteis():
    assert relogios.vencimento_di("DI1F28") == date(2028, 1, 3)
    assert relogios.dias_uteis_b3(date(2026, 9, 18), date(2026, 9, 25)) == 5


def test_base_ytd():
    datas = ["2025-12-29", "2025-12-30", "2026-01-02"]
    assert relogios.base_ytd(datas, 2026) == 1
    assert relogios.base_ytd(["2026-01-02"], 2026) is None
