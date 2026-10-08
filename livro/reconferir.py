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
        # tudo que foi publicado como mensagem conta (pelo cron nao ha ack, entao o
        # alerta fica pendente ou expira sem virar "entregue"); alerta nascido no
        # intradia era parcial por definicao e nao e "numero errado"
        if regra not in REGRAS or a.get("canal") != "mensagem":
            continue
        if a.get("status") not in ("entregue", "pendente", "expirado"):
            continue
        if a.get("slot") == "intradia" or "(parcial" in str(a.get("titulo") or ""):
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


def tabela(anterior: dict | None, series: dict, series_info: dict, universo, ids: list[str],
           ja_corrigidos: dict | None = None, tol: float = TOLERANCIA) -> list[dict]:
    """Numero de TABELA ja publicado que a serie corrigida desmente.

    O erro que motivou tudo (23/09) nao era alerta: era a linha do Brent (-1,4% a 97,83;
    foi +3,86% a 103,08) e a do dolar (-0,2%; subiu ~1,3%) na tabela e na Leitura. O
    `fechamento.json` anterior guarda o que foi publicado; aqui ele e comparado com a
    serie de agora, so para os drivers e os destaques (o que a leitura usa)."""
    ja = ja_corrigidos or {}
    if not anterior:
        return []
    jan = anterior.get("janelas") or {}
    out = []
    for ativo in ids:
        j = jan.get(ativo) or {}
        d, var_e, ult_e = j.get("data"), j.get("dia"), j.get("ultimo")
        if not d or var_e is None or j.get("dia_confirmado") is False:
            continue                                   # o que saiu "a confirmar" nao foi afirmado
        chave = f"tabela:{ativo}:{d}"
        if chave in ja:
            continue
        df = series.get(ativo)
        info = series_info.get(ativo) or {}
        if df is None or pd.Timestamp(d) not in df.index:
            continue
        i = df.index.get_loc(pd.Timestamp(d))
        if not isinstance(i, int) or i == 0:
            continue
        obj = universo.por_id(ativo)
        ant = df.index[i - 1].date().isoformat()
        if qa.dias_sem_barra(getattr(obj, "mercado", "NYSE"), ant, d):
            continue
        # so corrige com o dado de agora confirmado para aquela data
        q = info.get("qualidade") or {}
        if q.get("data_barra") == d and q.get("status") == qa.NAO_CONFIRMADO:
            continue
        var_n = float(df["adj"].iloc[i] / df["adj"].iloc[i - 1] - 1.0)
        close_n = float(df["close"].iloc[i])
        inverteu = var_e * var_n < 0 and abs(var_e - var_n) > 0.005
        if not inverteu and abs(var_n - var_e) <= tol:
            continue
        decimais = getattr(obj, "decimais", None)
        out.append({"id": f"{chave}-correcao", "original": chave, "regra": "tabela", "ativo": ativo, "data": d,
                    "var_entregue": var_e, "close_entregue": ult_e, "var_certa": var_n, "close_certo": close_n,
                    "texto": (f"CORREÇÃO tabela · {ativo} {fmt.data_br(d)}: saiu {fmt.pct(var_e)}"
                              + (f" a {fmt.preco(ult_e, decimais)}" if ult_e else "")
                              + f"; o certo é {fmt.pct(var_n)} a {fmt.preco(close_n, decimais)}"
                              + (" (sinal invertido)" if inverteu else ""))})
    return out
