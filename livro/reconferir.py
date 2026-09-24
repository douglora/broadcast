"""Correcao de alerta ja entregue.

Um alerta de preco carrega o fechamento e a variacao que o dispararam (dados.close,
dados.var ou dados.retorno). Na manha e no fechamento, o runner refaz a conta da
mesma data sobre a serie ATUAL, que ja passou pelo portao de qualidade e pelo
contrato certo do Brent. Se o sinal inverteu, ou a diferenca passa de 1 ponto
percentual, sai uma CORRECAO com o numero entregue e o certo, uma vez so.

Casos que motivaram (auditoria de 23/09): F03 do Brent em 18/09, CRITICO e com push,
"-5,3% a US$ 99,29" (foi -0,9% a US$ 103,87); T05 da MRVE3 em 18/09, CRITICO,
"-8,4%" (foi -3,7%: a serie nao tinha a barra de 17/09); T05 da MMM em 23/09
"+3,2% no dia" (dois pregoes, sem 22/09)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from livro import fmt
from livro import qualidade as qa

# regra -> campo de dados com a variacao entregue
REGRAS = {"F01": "var", "F02": "var", "F03": "var", "F04": "var", "F06": "var", "T05": "retorno"}
TOLERANCIA = 0.01          # 1 ponto percentual
JANELA_DIAS = 7


def reconferir(fila: dict, series: dict, series_info: dict, universo, hoje: date,
               ja_corrigidos: dict | None = None, dias: int = JANELA_DIAS, tol: float = TOLERANCIA) -> list[dict]:
    ja = ja_corrigidos or {}
    out = []
    for a in (fila or {}).values():
        regra, ativo, d = a.get("regra"), a.get("ativo"), a.get("data")
        if regra not in REGRAS or a.get("status") != "entregue" or a.get("canal") != "mensagem":
            continue
        if a["id"] in ja or not d:
            continue
        try:
            dt = date.fromisoformat(str(d)[:10])
        except ValueError:
            continue
        if (hoje - dt).days > dias or dt > hoje:
            continue
        dados = a.get("dados") or {}
        var_e = dados.get(REGRAS[regra])
        df = series.get(ativo)
        if var_e is None or df is None or pd.Timestamp(dt) not in df.index:
            continue
        i = df.index.get_loc(pd.Timestamp(dt))
        if not isinstance(i, int) or i == 0:
            continue
        obj = universo.por_id(ativo) or universo.bench(ativo)
        mercado = getattr(obj, "mercado", "NYSE")
        ant = df.index[i - 1].date().isoformat()
        if qa.dias_sem_barra(mercado, ant, dt.isoformat()):
            continue           # a serie atual tambem nao tem o pregao anterior: nao da para refazer um dia
        col = "adj" if regra == "T05" else "close"
        base = float(df[col].iloc[i - 1])
        if not base:
            continue
        var_n = float(df[col].iloc[i]) / base - 1.0
        close_n = float(df["close"].iloc[i])
        inverteu = var_e * var_n < 0 and abs(var_e - var_n) > 0.005
        if not inverteu and abs(var_n - var_e) <= tol:
            continue
        decimais = getattr(obj, "decimais", None)
        out.append({
            "id": f"{a['id']}-correcao", "original": a["id"], "regra": regra, "ativo": ativo, "data": dt.isoformat(),
            "severidade_original": a.get("severidade"), "titulo_entregue": a.get("titulo"),
            "var_entregue": var_e, "close_entregue": dados.get("close"), "var_certa": var_n, "close_certo": close_n,
            "texto": (f"CORREÇÃO {regra} · {ativo} {fmt.data_br(dt.isoformat())}: saiu "
                      f"{fmt.pct(var_e)}" + (f" a {fmt.preco(dados['close'], decimais)}" if dados.get("close") else "")
                      + f"; o certo é {fmt.pct(var_n)} a {fmt.preco(close_n, decimais)}"
                      + (" (sinal invertido)" if inverteu else "")),
        })
    out.sort(key=lambda x: (x["data"], x["ativo"]))
    return out
