"""
Termometro global-Brasil (regra G20 do estudo dos gestores, lente Kinea): sete variaveis diarias, cada uma 0 ou 1;
0 a 1 = calmo, 2 a 3 = alerta, 4 ou mais = estresse. Variavel sem dado conta como desconhecida (nao como 0) e aparece
na lista `desconhecidas`: com 3 ou mais desconhecidas o estado e "sem leitura".

As sete: Treasury de 10 anos +25 pontos-base ou mais em 10 pregoes; DXY +2% ou mais em 10 pregoes; Brent +10% ou mais em
10 pregoes; VIX acima de 20 ou +30% em 10 pregoes; spread high yield dos EUA +40 pontos-base em 10 pregoes; DI de 2 anos
+30 pontos-base em 10 pregoes; dolar/real +3% ou mais em 10 pregoes. SO MEDIDO: nada muda de tamanho por causa dele.
"""
import pandas as pd

from quant.observacao.sinais import _variacao

LIMIARES = {"ust10": 25.0, "dxy": 2.0, "brent": 10.0, "vix_nivel": 20.0, "vix_var": 30.0, "hy": 40.0, "di2": 30.0, "usdbrl": 3.0}
ESTADOS = ((0, 1, "calmo"), (2, 3, "alerta"), (4, 7, "estresse"))


def _bandeira(nome, valor, limiar, unidade):
    if valor is None:
        return {"valor": None, "bandeira": None, "limiar": limiar, "unidade": unidade}
    return {"valor": round(float(valor), 2), "bandeira": int(valor >= limiar), "limiar": limiar, "unidade": unidade}


def ler(f):
    """f = fontes montadas por sinais.montar_fontes. Devolve {estado, pontos, variaveis, desconhecidas, texto}."""
    s = f["series"]
    v = {}
    x = _variacao(s.get("UST10Y", pd.Series(dtype=float)), 10, pct=False)
    v["ust10_10d_bps"] = _bandeira("ust10", None if x is None else x * 100.0, LIMIARES["ust10"], "pontos-base")
    v["dxy_10d_pct"] = _bandeira("dxy", _variacao(s.get("DXY", pd.Series(dtype=float)), 10), LIMIARES["dxy"], "%")
    v["brent_10d_pct"] = _bandeira("brent", _variacao(s.get("BRENT", pd.Series(dtype=float)), 10), LIMIARES["brent"], "%")
    vix = s.get("VIX", pd.Series(dtype=float))
    if len(vix):
        nivel, var = float(vix.iloc[-1]), _variacao(vix, 10)
        v["vix"] = {"valor": round(nivel, 2), "bandeira": int(nivel >= LIMIARES["vix_nivel"] or (var is not None and var >= LIMIARES["vix_var"])),
                    "limiar": f"nivel {LIMIARES['vix_nivel']:.0f} ou +{LIMIARES['vix_var']:.0f}% em 10 pregoes", "unidade": "pontos", "var_10d_pct": None if var is None else round(var, 1)}
    else:
        v["vix"] = {"valor": None, "bandeira": None, "limiar": f"nivel {LIMIARES['vix_nivel']:.0f} ou +{LIMIARES['vix_var']:.0f}%", "unidade": "pontos"}
    x = _variacao(f.get("hy", pd.Series(dtype=float)), 10, pct=False)
    v["hy_10d_bps"] = _bandeira("hy", None if x is None else x * 100.0, LIMIARES["hy"], "pontos-base")
    x = _variacao(s.get("DI2A", pd.Series(dtype=float)), 10, pct=False)
    v["di2_10d_bps"] = _bandeira("di2", None if x is None else x * 100.0, LIMIARES["di2"], "pontos-base")
    v["usdbrl_10d_pct"] = _bandeira("usdbrl", _variacao(s.get("USDBRL", pd.Series(dtype=float)), 10), LIMIARES["usdbrl"], "%")
    desconhecidas = [k for k, b in v.items() if b["bandeira"] is None]
    pontos = sum(b["bandeira"] or 0 for b in v.values())
    if len(desconhecidas) >= 3:
        estado = "sem leitura"
    else:
        estado = next(nome for lo, hi, nome in ESTADOS if lo <= pontos <= hi)
    acesas = [k for k, b in v.items() if b["bandeira"]]
    texto = (f"Termometro {estado}: {pontos} de 7 variaveis acesas" + (f" ({', '.join(acesas)})" if acesas else "")
             + (f"; sem dado: {', '.join(desconhecidas)}" if desconhecidas else "") + ".")
    return {"estado": estado, "pontos": int(pontos), "variaveis": v, "desconhecidas": desconhecidas, "texto": texto}
