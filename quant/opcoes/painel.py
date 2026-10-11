"""
Modulo OPCOES do painel: gera `quant_opcoes.json` (formato v1) para o terminal.

  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.painel            # grava nos dois lugares
  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.painel --so-mostrar

De onde vem cada parte:
  estrategias      resultados.json (rodada final da pesquisa, quant/opcoes/resultados.py): historico de cada estrategia
                   e o estado (aprovada / medindo / reprovada). Estrategia reprovada aparece reprovada, com o numero.
  candidatas_hoje  a cadeia mais recente: a base do COTAHIST (ate o ultimo dia no parquet) mais os arquivos DIARIOS da B3
                   (COTAHIST_Dddmmaaaa.ZIP) publicados depois. Sem rede, vale o ultimo dia da base. So estruturas de
                   estrategia NAO reprovada passam por aqui, e so se as pernas cumprem o filtro fixo de liquidez
                   (>= 30 negocios no dia, ofertas dos dois lados, spread <= 30%).
  vertentes        as tres vertentes (especulativa, dividendo sintetico, travas com BOVA11): regra, evidencia, ranking do dia, posicoes, placar e
                   limites (quant/opcoes/vertentes.py; contrato da tela em quant/docs/tela_opcoes_vertentes.md). Livros: carteira_simulada.json (V1)
                   e carteira_vertentes.json (V2 e V3).
  Descreve estrutura que passa nos filtros. NUNCA diz compre ou venda (Resolucao CVM 178).

Escrita atomica: grava num arquivo temporario ao lado e renomeia (os.replace).
"""
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from scipy.special import ndtr

from quant.opcoes import assimetrias, bs, carteira_simulada, dados, teses as livro_teses, vertentes
from quant.opcoes import custos as C
from quant.opcoes.base import DIR_DADOS, DIR_OPC, extrair_zip_diario

SAIDAS = [
    "/Users/douglaslora/Desktop/terminal-artefato/web/d/x/quant_opcoes.json",
    "/Users/douglaslora/Desktop/terminal-artefato/cache/out/pagina/quant_opcoes.json",
]
FUSO = timezone(timedelta(hours=-3))
DU_MIN = 15        # vencimento candidato: o primeiro mensal com pelo menos 15 pregoes pela frente
ATIVOS_HEDGE = "BOVA11"


# ---------------------------------------------------------------------------------------------------- cadeia mais recente
def cadeia_recente(rede=True):
    """(opcoes do ultimo dia, ativo do ultimo dia, data, origem). Usa os arquivos diarios da B3 depois do ultimo dia da base."""
    op26 = pd.read_parquet(os.path.join(DIR_DADOS, "opcoes_2026.parquet"))
    sp26 = pd.read_parquet(os.path.join(DIR_DADOS, "ativo_2026.parquet"))
    ultimo = op26["dia"].max()
    op, sp, origem = op26[op26["dia"] == ultimo], sp26[sp26["dia"] == ultimo], f"base COTAHIST até {ultimo.date()}"
    if rede:
        try:
            from quant.dados import cotahist
            d = ultimo.date() + timedelta(days=1)
            hoje = date.today()
            while d <= hoje:
                if d.weekday() < 5:
                    b = cotahist.baixar_diario(d)
                    if b:
                        o2, s2 = extrair_zip_diario(b)
                        if len(o2):
                            op, sp = o2, s2
                            origem = f"COTAHIST diário de {d.isoformat()} (B3)"
                d += timedelta(days=1)
        except Exception as e:  # noqa: BLE001 -- sem rede o painel continua com a base
            origem += f" (arquivos diários indisponíveis: {type(e).__name__})"
    for c in ("ativo", "tipo"):
        op[c] = op[c].astype(str)
    return op.copy(), sp.copy(), pd.Timestamp(op["dia"].max()), origem


def juro_atual():
    c = dados.cdi_diario()
    taxa_aa = (1.0 + float(c.iloc[-1])) ** 252 - 1.0
    return taxa_aa, math.log1p(taxa_aa), c.index[-1]


def pregoes_ate(dia, venc):
    """Pregoes entre `dia` (exclusive) e `venc` (inclusive), pelo calendario de feriados da B3 (quant/dados/calendario.py)."""
    from quant.dados import calendario
    return len(calendario.pregoes((pd.Timestamp(dia) + pd.Timedelta(days=1)).date(), pd.Timestamp(venc).date()))


def preparar_cadeia(op, sp, dia, ativo):
    """Cadeia mensal do ativo no dia, com IV e delta, ate o primeiro vencimento mensal com du >= DU_MIN."""
    venc_mensais = [v for v in dados.vencimentos_padrao() if v > dia]
    s = sp[sp["ativo"] == ativo]
    if s.empty:
        return None
    spot = float(s["fech"].iloc[0])
    taxa_aa, r, _ = juro_atual()
    d = op[(op["ativo"] == ativo) & (~op["semanal"])].copy()
    escolhido = None
    for v in venc_mensais:
        if pregoes_ate(dia, v) >= DU_MIN:
            escolhido = v
            break
    if escolhido is None:
        return None
    d = d[d["vencimento"] == escolhido]
    du = pregoes_ate(dia, escolhido)
    d["mid"] = np.where(d["oferta_compra"].notna() & d["oferta_venda"].notna(), (d["oferta_compra"] + d["oferta_venda"]) / 2.0, np.nan)
    d["spread"] = (d["oferta_venda"] - d["oferta_compra"]) / d["mid"]
    d["premio_ref"] = d["mid"].fillna(d["fech"])
    put = (d["tipo"] == "P").values
    t = du / 252.0
    iv = bs.vol_implicita_vet(d["premio_ref"].values.astype(float), np.full(len(d), spot), d["exercicio"].values.astype(float),
                              np.full(len(d), t), np.full(len(d), r), put)
    d["iv"] = iv
    d["delta"] = bs.delta_vet(np.full(len(d), spot), d["exercicio"].values.astype(float), np.full(len(d), t), np.full(len(d), r), iv, put)
    return {"spot": spot, "r": r, "taxa_aa": taxa_aa, "venc": escolhido, "du": du, "t": t, "serie": d}


def liquida(d, tipo):
    m = ((d["tipo"] == tipo) & d["iv"].notna() & d["oferta_compra"].notna() & d["oferta_venda"].notna() & (d["oferta_compra"] > 0)
         & (d["oferta_venda"] > d["oferta_compra"]) & (d["negocios"] >= C.NEG_MIN) & (d["spread"] <= C.SPREAD_MAX))
    return d[m]


def perna_por_delta(d, tipo, alvo, tol=0.07):
    el = liquida(d, tipo)
    if el.empty:
        return None
    x = el.assign(dist=(el["delta"].abs() - alvo).abs())
    x = x[x["dist"] <= tol]
    if x.empty:
        return None
    return x.sort_values(["dist", "negocios"], ascending=[True, False]).iloc[0]


def liquidez_perna(r):
    if r["negocios"] >= 100 and r["spread"] <= 0.15:
        return "boa"
    if r["negocios"] >= C.NEG_MIN and r["spread"] <= C.SPREAD_MAX:
        return "media"
    return "fraca"


def pior(liqs):
    ordem = {"boa": 2, "media": 1, "fraca": 0}
    return min(liqs, key=lambda x: ordem[x])


def perna_json(r, lado, spot, t, rr):
    return {"codigo": r["codigo"], "tipo": "put" if r["tipo"] == "P" else "call", "lado": lado,
            "exercicio": round(float(r["exercicio"]), 2), "vencimento": str(pd.Timestamp(r["vencimento"]).date()),
            "premio": round(float(r["premio_ref"]), 2), "oferta_compra": round(float(r["oferta_compra"]), 2),
            "oferta_venda": round(float(r["oferta_venda"]), 2), "delta": round(float(r["delta"]), 3),
            "vol_implicita": round(float(r["iv"]), 4), "negocios": int(r["negocios"]),
            "spread_pct": round(float(r["spread"]) * 100, 1), "liquidez": liquidez_perna(r)}


def prob_abaixo(spot, x, t, r, sig):
    if x <= 0:
        return 0.0
    d2 = (math.log(spot / x) + (r - 0.5 * sig * sig) * t) / (sig * math.sqrt(t))
    return float(ndtr(-d2))


def candidatas(cad, estrategias_estado, R):
    """Estruturas de hoje, so das estrategias NAO reprovadas."""
    out = []
    if cad is None:
        return out
    spot, r, t, d = cad["spot"], cad["r"], cad["t"], cad["serie"]
    fee = C.FEE_PREMIO
    pl25 = perna_por_delta(d, "P", 0.25)
    pl30 = perna_por_delta(d, "P", 0.30)
    ps10 = perna_por_delta(d, "P", 0.10)
    cs25 = perna_por_delta(d, "C", 0.25)
    venc = str(pd.Timestamp(cad["venc"]).date())
    jan = R["protecao"]["bova11"]["janelas"]["crash_2020 (ciclo que vence em 16/03/2020)"]
    ano = R["protecao"]["bova11"]["por_ano"]
    prem = R["protecao"]["bova11"]["premio_medio_pct"]
    base = {"ativo": ATIVOS_HEDGE, "vencimento": venc, "pregoes_ate_o_vencimento": int(cad["du"]), "preco_do_ativo": round(spot, 2),
            "unidade": "R$ por cota de BOVA11 (1 lote de opção = 100 cotas)"}
    if estrategias_estado.get("protecao_put_bova11") != "reprovada" and pl25 is not None:
        custo = float(pl25["oferta_venda"]) * (1 + fee)
        k = float(pl25["exercicio"])
        be = k - custo
        out.append({**base, "estrategia": "protecao_put_bova11", "titulo": f"Put de BOVA11 como seguro da carteira ({pl25['codigo']}, {venc})",
                    "pernas": [perna_json(pl25, "compra", spot, t, r)], "caixa_empenhado": round(custo, 2),
                    "ganho_maximo": round(be, 2), "perda_maxima": round(custo, 2), "ponto_de_equilibrio": round(be, 2),
                    "probabilidade_de_lucro_pct": round(prob_abaixo(spot, be, t, r, float(pl25["iv"])) * 100, 1),
                    "liquidez": liquidez_perna(pl25),
                    "ganho_maximo_obs": "teórico: BOVA11 a zero; a conta é strike menos custo",
                    "protege_abaixo_de": round(k, 2), "protege_a_partir_de_pct": round((k / spot - 1) * 100, 1),
                    "custo_pct_da_carteira": round(custo / spot * 100, 2),
                    "porque_entrou_na_lista": f"Estratégia em 'medindo': como seguro, protegeu em março de 2020 (a carteira nua {jan['nu']}% no ciclo e com a put {jan['put']}%) "
                                              f"e custou em média {prem}% da carteira por mês. A perna cumpre o filtro de liquidez de hoje. "
                                              "Probabilidade = chance, pelo preço da própria opção, de a put terminar valendo mais que o custo (não é previsão)."})
    if estrategias_estado.get("colar_bova11") != "reprovada" and pl25 is not None and cs25 is not None:
        c_put = float(pl25["oferta_venda"]) * (1 + fee)
        c_call = float(cs25["oferta_compra"]) * (1 - fee)
        liquido = c_put - c_call
        kp, kc = float(pl25["exercicio"]), float(cs25["exercicio"])
        sig = float(cs25["iv"])
        be = spot + liquido
        out.append({**base, "estrategia": "colar_bova11", "titulo": f"Colar sobre BOVA11 ({pl25['codigo']} / {cs25['codigo']}, {venc})",
                    "pernas": [perna_json(pl25, "compra", spot, t, r), perna_json(cs25, "venda", spot, t, r)],
                    "caixa_empenhado": round(max(liquido, 0.0), 2), "custo_liquido_por_cota": round(liquido, 2),
                    "ganho_maximo": round(kc - spot - liquido, 2), "perda_maxima": round(spot - kp + liquido, 2),
                    "ponto_de_equilibrio": round(be, 2),
                    "probabilidade_de_lucro_pct": round((1 - prob_abaixo(spot, be, t, r, sig)) * 100, 1),
                    "liquidez": pior([liquidez_perna(pl25), liquidez_perna(cs25)]),
                    "protege_abaixo_de": round(kp, 2), "teto_de_ganho_em": round(kc, 2),
                    "porque_entrou_na_lista": f"Estratégia em 'medindo': o colar limita a perda e a alta; a venda da call paga parte da put. "
                                              f"Em 2020 rendeu {ano['2020']['colar']}% no ano contra {ano['2020']['nu']}% da carteira nua, mas em 2025 devolveu parte da alta "
                                              f"({ano['2025']['colar']}% contra {ano['2025']['nu']}%). Probabilidade = chance, pelo preço da call vendida, de BOVA11 terminar acima do equilíbrio."})
    if estrategias_estado.get("trava_baixa_bova11") != "reprovada" and pl30 is not None and ps10 is not None and ps10["exercicio"] < pl30["exercicio"]:
        deb = float(pl30["oferta_venda"]) * (1 + fee) - float(ps10["oferta_compra"]) * (1 - fee)
        larg = float(pl30["exercicio"]) - float(ps10["exercicio"])
        if deb > 0 and deb < larg:
            be = float(pl30["exercicio"]) - deb
            out.append({**base, "estrategia": "trava_baixa_bova11", "titulo": f"Trava de baixa com puts em BOVA11 ({pl30['codigo']} / {ps10['codigo']}, {venc})",
                        "pernas": [perna_json(pl30, "compra", spot, t, r), perna_json(ps10, "venda", spot, t, r)],
                        "caixa_empenhado": round(deb, 2), "ganho_maximo": round(larg - deb, 2), "perda_maxima": round(deb, 2),
                        "ponto_de_equilibrio": round(be, 2),
                        "probabilidade_de_lucro_pct": round(prob_abaixo(spot, be, t, r, float(pl30["iv"])) * 100, 1),
                        "liquidez": pior([liquidez_perna(pl30), liquidez_perna(ps10)]),
                        "porque_entrou_na_lista": f"Estratégia em 'medindo': custa menos que a put sozinha, mas protege só até o strike da perna vendida "
                                                  f"(em março de 2020 a carteira {jan['nu']}% e com a trava {jan['trava']}%)."})
    return out


# ---------------------------------------------------------------------------------------------------- estrategias
def _hist(m, período, n=None):
    return {"periodo": período, "n": n if n is not None else m.get("n_ops"), "retorno_anual_pct": m.get("retorno_anual_pct"),
            "sharpe": m.get("sharpe"), "queda_maxima_pct": m.get("queda_maxima_pct"), "pior_mes_pct": m.get("pior_mes_pct"),
            "sharpe_deflacionado": m.get("sharpe_deflacionado")}


def montar_estrategias(R):
    pc, pb, cc, tp, pz, pr = R["put_cesta"], R["put_bova11"], R["call_coberta"], R["trava_put"], R["pozinho"], R["protecao"]
    est = []
    m = pc["melhor"]
    e20 = pc["estresse_mar2020"]
    sh_max = max(x["sharpe"] for x in pc["tabela"] if (x["n_ops"] or 0) >= 30)
    est.append({
        "nome": "venda_put_cesta", "titulo": "Venda de put coberta por caixa, mensal, delta 0,15 a 0,30 (PETR4, VALE, ITUB4, BBAS3, BBDC4)",
        "hipotese": "O mercado paga um prêmio de seguro maior que a perda média (prêmio de risco de volatilidade). Do outro lado estão compradores de proteção e de loteria; "
                    "o vendedor ganha o prêmio na maioria dos meses e perde forte em poucos.",
        "estado": "reprovada",
        "historico": _hist(m, "2012-2019 (descoberta)"),
        "nota": (f"{pc['n_configs']} configurações testadas na descoberta, nenhuma passou (maior Sharpe entre as que tiveram 30+ operações: {sh_max}; a barra da fase era 0,3). "
                 f"Prêmio médio {pc['cauda']['premio_medio_pct_do_strike']}% do strike por mês, pagamento médio {pc['cauda']['pagamento_medio_pct_do_strike']}%: o prêmio não cobriu a perda. "
                 f"PIOR CASO: a pior operação foi {pc['cauda']['pior_operacao']} ({pc['cauda']['pior_operacao_pct_do_strike']}% do strike em um mês); em março de 2020, "
                 f"PETR4 perdeu {next((x['perda_pct_do_strike'] for x in e20['por_ativo'] if x['grupo']=='PETR4'), None)}% do strike e a cesta -20% no mês (cenário de estresse, fora do corredor).")})
    b0 = next(x for x in pb["tabela"] if x["cfg"] == "put BOVA11 delta=0.20 exec=oferta")
    est.append({
        "nome": "venda_put_bova11", "titulo": "Venda de put coberta por caixa em BOVA11, mensal, delta 0,15 a 0,30",
        "hipotese": "O prêmio de volatilidade do índice é maior que o das ações isoladas e a perda é diversificada.",
        "estado": "reprovada",
        "historico": _hist(b0["bova_desc"], "2020-2022 (descoberta de BOVA11, só tem opção líquida desde 2020)"),
        "nota": (f"Ganhou em 90% dos meses, mas março de 2020 custou {pb['estresse_mar2020']['perda_pct_do_strike']}% do strike em UM mês e apagou tudo "
                 f"(excesso anual {b0['bova_desc']['excesso_anual_pct']}% sobre o CDI em 2020-2022). 2023 foi positivo ({b0['bova_val']['excesso_anual_pct']}% sobre o CDI, 12 meses) "
                 "mas a validação não foi aberta porque a descoberta falhou. Só 4 anos de liquidez.")})
    cbest = max([x for x in cc["tabela"] if x["cfg"].startswith("call coberta") and "universo=cesta" in x["cfg"] and "exec=oferta" in x["cfg"]], key=lambda x: x["delta_sharpe"])
    est.append({
        "nome": "call_coberta", "titulo": "Venda coberta de call (financiamento) sobre a cesta de ações, delta 0,20 a 0,40",
        "hipotese": "A call vendida embolsa o prêmio de volatilidade e reduz a oscilação da carteira; em troca abre mão da alta forte.",
        "estado": "reprovada",
        "historico": {"periodo": "2012-2019 (descoberta)", "n": cbest["n_ops"], "retorno_anual_pct": cbest["retorno_anual_pct"], "sharpe": cbest["sharpe"],
                      "queda_maxima_pct": cbest["queda_maxima_pct"], "pior_mes_pct": None, "sharpe_deflacionado": None},
        "nota": (f"Melhor configuração: Sharpe {cbest['sharpe']} contra {cbest['acao_sharpe']} da carteira de ações sem a call; retorno {cbest['retorno_anual_pct']}% ao ano "
                 f"contra {cbest['acao_retorno_anual_pct']}%. Reduziu a queda máxima em {cbest['delta_queda_max']} pontos, mas piorou o retorno ajustado ao risco em 10 das 11 configurações (a única melhor, BBDC4, teve 22 operações).")})
    t0 = min(tp["tabela"], key=lambda x: -x["sharpe"])
    est.append({
        "nome": "trava_credito_put", "titulo": "Trava de alta de crédito com puts (vende put delta 0,20-0,30, compra put 5-10% abaixo), cesta de 5 ações",
        "hipotese": "Mesmo prêmio de volatilidade da put vendida, com perda máxima conhecida: tira a cauda do vendedor.",
        "estado": "reprovada", "historico": _hist(t0, "2012-2019 (descoberta)"),
        "nota": f"Retorno sobre o risco máximo negativo em todas as 8 configurações (melhor Sharpe {t0['sharpe']}); perda total da trava em {t0.get('perda_total_pct')}% das operações. O spread das duas pernas come grande parte do crédito."})
    p_all = pr["bova11"]["2020-2026"]
    pb11 = {x["variante"]: x for x in p_all}
    jan = pr["bova11"]["janelas"]["crash_2020 (ciclo que vence em 16/03/2020)"]
    est.append({
        "nome": "protecao_put_bova11", "titulo": "Proteção da carteira com compra de put de BOVA11 (delta ~ -0,25), mensal",
        "hipotese": "Seguro: paga um custo mensal para limitar a perda nas quedas fortes; a venda de mini-índice protege de graça mas tira toda a alta.",
        "estado": "medindo", "historico": _hist(pb11["put"], "2020-2026 (carteira protegida)", n=pb11["put"]["n_ciclos"]),
        "nota": (f"Março de 2020: carteira nua {jan['nu']}% no ciclo, com put {jan['put']}%, com colar {jan['colar']}%, com trava de baixa {jan['trava']}%, vendendo mini-índice {jan['win100']}%. "
                 f"Custo bruto: cerca de {pr['bova11']['premio_medio_pct']}% da carteira por mês (7 a 15% ao ano). Não é estratégia de retorno: o critério é quanto segura e quanto custa. "
                 f"{pr['bova11']['meses_sem_put_liquida']} mês(es) sem put líquida.")})
    est.append({
        "nome": "colar_bova11", "titulo": "Colar sobre BOVA11 (compra put delta -0,25 e vende call delta +0,25), mensal",
        "hipotese": "A call vendida financia parte da put: proteção com custo menor, ao preço de limitar a alta.",
        "estado": "medindo", "historico": _hist(pb11["colar"], "2020-2026 (carteira com colar)", n=pb11["colar"]["n_ciclos"]),
        "nota": f"Foi a variante que mais protegeu por menos custo em 2020 (+{pr['bova11']['por_ano']['2020']['colar']}% no ano contra {pr['bova11']['por_ano']['2020']['nu']}% da carteira nua) e a que mais deu de volta em 2025 ({pr['bova11']['por_ano']['2025']['colar']}% contra {pr['bova11']['por_ano']['2025']['nu']}%)."})
    est.append({
        "nome": "trava_baixa_bova11", "titulo": "Trava de baixa com puts em BOVA11 (compra delta -0,30, vende delta -0,10), mensal",
        "hipotese": "Seguro mais barato que a put seca, protege só até o strike vendido.",
        "estado": "medindo", "historico": _hist(pb11["trava"], "2020-2026 (carteira com trava)", n=pb11["trava"]["n_ciclos"]),
        "nota": f"Em março de 2020 a carteira caiu {jan['nu']}% e com a trava {jan['trava']}%: proteção parcial. Fora de crise custa pouco."})
    pzd = {(x["modo"], x["tipo"]): x for x in pz["descritivo"]}
    pc_ = pzd[("inicio", "C")]
    est.append({
        "nome": "pozinho", "titulo": "Pozinho: call ou put muito fora do dinheiro, até R$ 0,10-0,20, comprada para carregar",
        "hipotese": "Convexidade barata: perde centavos na maioria das vezes e paga múltiplos nas poucas em que o ativo dispara ou desaba.",
        "estado": "reprovada",
        "historico": {"periodo": "2012-2026 (descritivo, bilhete de call, entrada no início do ciclo, teto R$ 0,20)", "n": pc_["n"], "retorno_anual_pct": None,
                      "sharpe": None, "queda_maxima_pct": None, "pior_mes_pct": None, "sharpe_deflacionado": None,
                      "valor_esperado_pct": pc_["ev_pct"], "pct_vira_po": pc_["po_pct"], "pct_5x": pc_["pct_ge5x"], "pct_10x": pc_["pct_ge10x"]},
        "nota": (f"Call: {pc_['po_pct']}% viram pó, {pc_['pct_ge5x']}% multiplicam por 5 e {pc_['pct_ge10x']}% por 10; valor esperado {pc_['ev_pct']}% (IC 90%: {pc_['ev_ic90_pct']}). "
                 "Com vencimento curto (8 pregões) o valor esperado é muito pior. Nenhuma condição testada (volatilidade implícita baixa, queda forte, semana de resultado) ficou positiva na descoberta E na validação. "
                 "O EV positivo das puts vem de março de 2020; sem esse ciclo, " + f"{pz['puts_inicio_teto20_ev_sem_mar2020_pct']}%.")})
    return est


# ---------------------------------------------------------------------------------------------------- termos e avisos
TERMOS = [
    {"termo": "Pozinho", "explicacao": "Opção muito fora do dinheiro, de centavos, comprada como bilhete de loteria: quase sempre vira pó, e às vezes paga várias vezes o que custou."},
    {"termo": "Put", "explicacao": "Opção de venda: quem compra tem o direito de vender o ativo ao preço de exercício; funciona como seguro contra queda. Quem vende assume o compromisso de comprar."},
    {"termo": "Call", "explicacao": "Opção de compra: quem compra tem o direito de comprar o ativo ao preço de exercício; quem vende assume o compromisso de entregar."},
    {"termo": "Preço de exercício (strike)", "explicacao": "Preço combinado a que o ativo pode ser comprado ou vendido no vencimento. Nas opções da B3 ele é ajustado quando a empresa paga dividendo."},
    {"termo": "Prêmio", "explicacao": "O preço da opção, por ação ou cota. Quem compra paga, quem vende recebe."},
    {"termo": "Delta", "explicacao": "Quanto o prêmio muda quando o ativo anda R$ 1. Em módulo, é uma estimativa da chance de a opção terminar dentro do dinheiro, segundo o preço dela."},
    {"termo": "Volatilidade implícita", "explicacao": "A oscilação anual do ativo que o preço da opção está embutindo. Opção cara = volatilidade implícita alta."},
    {"termo": "Oferta de compra e de venda (spread)", "explicacao": "Melhor preço que alguém paga (compra) e melhor preço que alguém pede (venda) no fechamento. Vender na oferta de compra e comprar na de venda é o custo real de entrar; a diferença é o spread."},
    {"termo": "Colar", "explicacao": "Compra de put e venda de call sobre uma carteira: limita a perda e também a alta, com custo menor que a put sozinha."},
    {"termo": "Trava de baixa com puts", "explicacao": "Compra de uma put e venda de outra, mais abaixo: seguro mais barato, que protege só até o strike vendido."},
    {"termo": "Trava de alta de crédito com puts", "explicacao": "Venda de uma put e compra de outra mais baixa: recebe um crédito e tem perda máxima conhecida."},
    {"termo": "Sharpe", "explicacao": "Retorno acima do CDI dividido pela oscilação. Acima de 1 é bom; perto de zero ou negativo, o risco não foi pago."},
    {"termo": "Sharpe deflacionado", "explicacao": "Probabilidade de o Sharpe ser verdadeiro depois de descontar que muitas configurações foram testadas. Acima de 0,95 é o que se exige para aprovar."},
    {"termo": "Queda máxima", "explicacao": "Maior queda da curva de resultado, de um pico a um fundo, medida nos fechamentos mensais; a perda dentro do mês pode ser maior."},
    {"termo": "Simulação", "explicacao": "Resultado calculado sobre preços históricos da B3, cruzando as ofertas do fechamento, com custos de bolsa e sem imposto. Nenhuma ordem real foi enviada."},
]


def montar_avisos(R, origem, data_cadeia):
    return [
        "SIMULAÇÃO: nenhuma ordem real. Este módulo descreve estruturas; não recomenda compra nem venda (Resolução CVM 178). A decisão é do assessor.",
        "Nenhuma estratégia de VENDA DE PRÊMIO (put, call coberta, trava de crédito) passou na descoberta de 2012-2019, e o pozinho tem valor esperado negativo: "
        "estão listadas como reprovadas, com o número. Por isso as candidatas de hoje (bloco candidatas_hoje) são só estruturas de proteção, que são seguro e não fonte de retorno; "
        "o bloco assimetrias traz o ranking das estruturas de risco definido, cada uma com o veredito da sua família.",
        f"Cadeia de {data_cadeia}: {origem}. São as ofertas do FIM do pregão; no pregão seguinte o preço é outro. Confira a oferta na hora.",
        "Resultados antes de imposto (operação comum em opções paga 15% sobre o ganho, sem a isenção das ações) e sem corretagem. Emolumentos: premissa de 0,05% do prêmio por lado.",
        "Marcação mensal: a queda máxima é a do fechamento de cada ciclo; a perda dentro do mês pode ser maior. Opções tratadas como europeias (exercício antecipado ignorado).",
        "Antes de 2020 BOVA11 não tinha opção líquida: a proteção de 2013-2019 usou opções do próprio Ibovespa, com preço estimado (último negócio com 5% contra) em 40 de 47 ciclos.",
        "RANKING DE ASSIMETRIAS: o valor esperado usa 10 anos de histórico do próprio ativo (uma amostra curta, que depende do período) e é a menor de duas contas (histórico puro e reescalado para a volatilidade de agora). "
        "Vantagem positiva não é previsão: dos testes da pesquisa, só o capital protegido e o straddle em opção barata passaram nas três fases, e nenhum foi aprovado (Sharpe deflacionado abaixo de 0,95).",
        "LIVRO DE TESES: dado um cenário (do Douglas, da mesa ou do robô), mostra papel, call, trava e put vendida a preços executáveis, o que cada preço exige de probabilidade e qual cabe no teto de R$ 500 de perda. "
        "No caso das eleições, a probabilidade do cenário político é do Douglas: o painel mostra 40%, 50% e 60%, e nenhuma posição é aberta sozinha com ela.",
        "CARTEIRA SIMULADA: R$ 100 mil fictícios, até 2 posições novas por dia, perda máxima de R$ 500 por estrutura, 6 abertas e 3% do capital em risco. O capital protegido é à parte, com quantidades fracionadas. Não há ordem real.",
    ]


# ---------------------------------------------------------------------------------------------------- principal
def gerar(rede=True, gravar_carteira=True):
    with open(os.path.join(DIR_OPC, "resultados.json"), encoding="utf-8") as f:
        R = json.load(f)
    with open(os.path.join(DIR_OPC, "resultados_assimetrias.json"), encoding="utf-8") as f:
        RA = json.load(f)
    novas = montar_estrategias_novas(RA, R)
    estrategias = novas[:1] + montar_estrategias(R) + novas[1:]
    estado = {e["nome"]: e["estado"] for e in estrategias}
    op, sp, dia, origem = cadeia_recente(rede)
    cad = preparar_cadeia(op, sp, dia, ATIVOS_HEDGE)
    cands = candidatas(cad, estado, R)
    # ranking diario de assimetrias e carteira simulada
    M = assimetrias.montar(op, sp, dia, origem)
    ranking = assimetrias.montar_ranking(M, RA, R)
    arbs, arb_meta = assimetrias.montar_arbitragens(M)
    veredito = lambda r: assimetrias.veredito_familia(RA, R, r)  # noqa: E731
    blocos_teses, teses_abrir = montar_teses(M, dia)
    r1 = vertentes.ranking_v1(M, dia)
    posicoes, resultado, _est = carteira_simulada.atualizar(M, veredito, gravar=gravar_carteira, teses_abrir=teses_abrir, calls_v1=vertentes.aviso_ranking_v1_para_livro(r1))
    bloco_vertentes, _r1, _est23 = vertentes.montar_bloco(M, dia, posicoes, gravar=gravar_carteira)
    pa = M["por_ativo"]
    pa = pa[(pa["series_liquidas"] >= 3)].copy()
    pa["no_ranking"] = pa["ativo"].isin(M["liq_ativos"])
    por_ativo = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()} for r in pa.sort_values(["no_ranking", "negocios_no_dia"], ascending=[False, False]).to_dict("records")]
    agora = datetime.now(FUSO).isoformat(timespec="seconds")
    n_rep = sum(1 for e in estrategias if e["estado"] == "reprovada")
    n_med = sum(1 for e in estrategias if e["estado"] == "medindo")
    n_apr = sum(1 for e in estrategias if e["estado"] == "aprovada")
    texto = (f"{len(estrategias)} estratégias de opções testadas em histórico da B3 (2012-2026): {n_apr} aprovada(s), {n_med} em medição, {n_rep} reprovada(s). "
             "Vender put, vender call coberta, travas de crédito e comprar pozinho não pagaram o risco contra o CDI. "
             "Em medição: o capital protegido (caixa no CDI e 1% desse caixa por mês em calls no dinheiro, que nunca perdeu mais que o orçamento e rendeu cerca de 2 pontos ao ano acima do CDI), "
             "o straddle onde a opção está barata contra a volatilidade realizada de 252 dias, a arbitragem de fechamento e a proteção de BOVA11 com put, colar e trava de baixa. "
             "Nenhuma está aprovada: o Sharpe deflacionado fica abaixo de 0,95.")
    return {
        "v": 1, "tipo": "opcoes", "gerado": agora, "modo": "simulacao",
        "resumo": {"texto": texto, "data_da_cadeia": str(dia.date()), "origem_da_cadeia": origem,
                   "contagem": {"aprovada": n_apr, "medindo": n_med, "reprovada": n_rep},
                   "tentativas": R["tentativas"], "pesquisa_gerada": R["gerado"], "pesquisa_assimetrias_gerada": RA["gerado"],
                   "juro_usado_aa_pct": round(juro_atual()[0] * 100, 3)},
        "estrategias": estrategias, "candidatas_hoje": cands, "posicoes": posicoes, "resultado": resultado,
        "assimetrias": {
            "data_da_cadeia": str(dia.date()),
            "metodo": ("Para cada ativo com opção líquida (6+ séries com 30+ negócios, oferta dos dois lados e spread até 30%, e 1.000+ negócios de opções no dia), monta as estruturas de risco definido "
                       "nos dois vencimentos mensais seguintes a preços executáveis (compra na oferta de venda, venda na de compra, emolumento de 0,05%). O valor esperado usa a distribuição HISTÓRICA dos "
                       "retornos totais do próprio ativo no mesmo prazo (10 anos, janelas sobrepostas) e a mesma distribuição reescalada para a volatilidade realizada de 60 pregões de agora; o ranking vale pela "
                       "menor das duas vantagens (valor esperado sobre o custo, depois do CDI). Cada linha mostra o veredito da família na pesquisa A0 a A6. Descreve estrutura; não recomenda compra nem venda."),
            "ativos_no_ranking": M["liq_ativos"], "vencimentos": [str(pd.Timestamp(v).date()) for v in M["vencs"]], "ativos_com_volatilidade_barata_vs_252d": M["baratos_vr252"],
            "por_ativo": por_ativo, "ranking": ranking, "arbitragens": arbs, "arbitragens_resumo": {**arb_meta, "historico_250_pregoes": {k: v for k, v in RA["A5"].items() if k != "por_tipo"}},
        },
        "teses": blocos_teses,
        "vertentes": bloco_vertentes,
        "avisos": montar_avisos(R, origem, str(dia.date())), "termos": TERMOS + TERMOS_NOVOS,
    }


def sem_nan(x):
    """JSON estrito: NaN e infinito viram null (o navegador nao le NaN)."""
    if isinstance(x, dict):
        return {k: sem_nan(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [sem_nan(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def gravar_atomico(caminho, obj):
    pasta = os.path.dirname(caminho)
    os.makedirs(pasta, exist_ok=True)
    tmp = os.path.join(pasta, f".{os.path.basename(caminho)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sem_nan(obj), f, ensure_ascii=False, indent=1, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    obj = gerar(rede="--sem-rede" not in argv, gravar_carteira="--so-mostrar" not in argv)
    if "--so-mostrar" in argv:
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:6000])
        return 0
    for caminho in SAIDAS:
        gravar_atomico(caminho, obj)
        print("gravado", caminho)
    print(f"{len(obj['estrategias'])} estrategias, {len(obj['candidatas_hoje'])} candidatas, {len(obj['assimetrias']['ranking'])} no ranking, {len(obj['posicoes'])} posicoes, cadeia de {obj['resumo']['data_da_cadeia']}")
    return 0




# ---------------------------------------------------------------------------------------------------- assimetrias (hipoteses A0 a A6)
def _pt(x, casas=1, sinal=False):
    if x is None:
        return "n/d"
    s = f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("+" + s) if (sinal and x > 0) else s


def montar_estrategias_novas(RA, R):
    """Entradas do quadro de estrategias para as hipoteses A0 a A6 (resultados_assimetrias.json). A primeira e o capital protegido."""
    a0, a1, a2, a3, a4, a5, a6 = RA["A0"], RA["A1"], RA["A2"], RA["A3"], RA["A4"], RA["A5"], RA["A6"]
    nome0 = "call_atm_1m orcamento=1.0%"        # o Douglas aprovou 1% por mes em 10/10/2026; desde 11/10 a base e o capital da classe de opcoes
    orc = carteira_simulada.orcamento_mensal()
    base_rs = orc / carteira_simulada.ORCAMENTO_PCT
    h0, v0 = a0["variantes"][nome0], a0["historico_completo"][nome0]
    pr0 = a0["prova"][nome0]
    out = []
    out.append({
        "nome": "capital_protegido", "titulo": (f"Capital protegido feito em casa: caixa no CDI e 1% desse caixa por mês (R$ {_pt(orc, 0)} sobre os R$ {_pt(base_rs / 1000, 0)} mil da classe de opções) "
                   "em calls no dinheiro (PETR4, VALE, BOVA11, ITUB4, BBDC4, BBAS3)"),
        "hipotese": "O caixa rende o CDI (juro alto no Brasil) e só um orçamento fixo por mês compra convexidade: a perda máxima no ano é o orçamento e o ganho é aberto. "
                    "Do outro lado estão os vendedores de volatilidade; a hipótese só paga se a alta em poucos meses compensar o desgaste dos meses parados.",
        "estado": "medindo",
        "historico": {"periodo": "2012-2026 (descoberta 2012-2019, validação 2020-2023, prova 2024-2026)", "n": v0["n_ciclos"], "retorno_anual_pct": v0["retorno_anual_pct"], "sharpe": v0["sharpe"],
                      "queda_maxima_pct": v0["queda_maxima_pct"], "pior_mes_pct": v0["pior_mes_pct"], "sharpe_deflacionado": v0["sharpe_deflacionado"],
                      "excesso_anual_pct": v0["excesso_anual_pct"], "cdi_anual_pct": v0["cdi_anual_pct"], "pior_ano_pct": v0["pior_ano_pct"],
                      "captura_da_alta_pct": v0["captura_da_alta_pct"], "anos_acima_do_cdi_pct": v0["anos_acima_do_cdi_pct"]},
        "nota": (f"Números medidos com o orçamento de 1% ao mês sobre o capital que fica no CDI; por isso a base é o capital da classe de opções, não o do livro inteiro "
                 f"(corrigido em 11/10/2026: 1% do livro inteiro gastaria mais que o rendimento do caixa da classe). PASSOU nas três fases: Sharpe {_pt(h0['descoberta']['sharpe'], 2)} (descoberta), {_pt(h0['validacao']['sharpe'], 2)} (validação) e {_pt(pr0['sharpe'], 2)} (prova 2024-2026, aberta uma vez); "
                 f"excesso sobre o CDI de {_pt(h0['descoberta']['excesso_anual_pct'], 1, True)}, {_pt(h0['validacao']['excesso_anual_pct'], 1, True)} e {_pt(pr0['excesso_anual_pct'], 1, True)} ponto(s) ao ano. "
                 f"NÃO está aprovada: Sharpe deflacionado {_pt(v0['sharpe_deflacionado'], 2)} (exige-se 0,95) e o retorno extra é pequeno. "
                 f"'Nunca perde mais que o orçamento' se confirmou: pior mês {_pt(v0['pior_mes_pct'], 2)}% do patrimônio e pior ano {_pt(v0['pior_ano_pct'], 1)}% (a cesta de ações teve {_pt(v0['pior_ano_do_ativo_pct'], 0)}% em um ano). "
                 f"'Participa da alta' só em parte: captura cerca de {_pt(v0['captura_da_alta_pct'], 0)}% da alta acima do CDI; retorno de {_pt(v0['retorno_anual_pct'], 1)}% ao ano contra CDI {_pt(v0['cdi_anual_pct'], 1)}%, "
                 f"ações {_pt(v0['ref_ativo_aa_pct'], 1)}% e 70% ações + 30% CDI {_pt(v0['ref_70_30_aa_pct'], 1)}%. "
                 f"Custo dos anos parados: {_pt(v0['excesso_medio_ano_parado_pct'], 1, True)} ponto ao ano contra o CDI em média ({v0['anos_parados_n']} de {v0['n_anos']} anos), acima do CDI em {_pt(v0['anos_acima_do_cdi_pct'], 0)}% dos anos. "
                 f"Com orçamento de 0,5% (versão anterior): excesso de {_pt(a0['variantes']['call_atm_1m orcamento=0.5%']['descoberta']['excesso_anual_pct'], 1, True)} a {_pt(a0['prova']['call_atm_1m orcamento=0.5%']['excesso_anual_pct'], 1, True)} ponto(s) ao ano, captura de ~{_pt(a0['historico_completo']['call_atm_1m orcamento=0.5%']['captura_da_alta_pct'], 0)}% da alta e pior mês {_pt(a0['historico_completo']['call_atm_1m orcamento=0.5%']['pior_mes_pct'], 2)}%.")})
    c1 = a1["configs"]["straddle_barato_vr252"]
    p1 = a1["prova"].get("straddle_barato_vr252", {})
    hc1 = a1.get("historico_completo", {}).get("straddle_barato_vr252", {})
    sp1 = a1["configs"]["spread_barato_menos_caro_vr252"]
    out.append({
        "nome": "straddle_vol_barata", "titulo": "Straddle comprado onde a volatilidade realizada de 252 dias supera a implícita de 30 dias (tercil mais barato do mês)",
        "hipotese": "O mercado de opções reage devagar à volatilidade realizada; onde a opção está barata contra o que o ativo andou, quem compra straddle tende a ser pago (Goyal e Saretto, 2009). "
                    "Do outro lado: formadores de mercado que precificam pela volatilidade passada recente.",
        "estado": "medindo",
        "historico": {"periodo": "2012-2026 (descoberta, validação e prova)", "n": hc1.get("n_ops"), "retorno_anual_pct": None, "sharpe": hc1.get("sharpe"), "queda_maxima_pct": None,
                      "pior_mes_pct": hc1.get("pior_mes_por_op_pct"), "sharpe_deflacionado": p1.get("sharpe_deflacionado"), "media_por_straddle_pct": hc1.get("media_por_op_pct"), "t": hc1.get("t")},
        "nota": (f"PASSOU nas três fases pelos critérios fixados: média por straddle de {_pt(c1['descoberta']['media_por_op_pct'], 0, True)}% (n {c1['descoberta']['n_ops']}), {_pt(c1['validacao']['media_por_op_pct'], 0, True)}% (n {c1['validacao']['n_ops']}) "
                 f"e {_pt(p1.get('media_por_op_pct'), 0, True)}% (prova, n {p1.get('n_ops')}), mas com t de {_pt(c1['descoberta']['t'], 2)}, {_pt(c1['validacao']['t'], 2)} e {_pt(p1.get('t'), 2)} e Sharpe deflacionado {_pt(p1.get('sharpe_deflacionado'), 2)}: "
                 f"NÃO está aprovada. O contraste barato menos caro (volatilidade de 252 dias) deu {_pt(sp1['descoberta']['media_pct'], 0, True)}% (t {_pt(sp1['descoberta']['t'], 2)}) e {_pt(sp1['validacao']['media_pct'], 0, True)}% (t {_pt(sp1['validacao']['t'], 2)}). "
                 f"Em ~{_pt(100 - (hc1.get('pct_meses_positivos') or 0), 0)}% dos meses o straddle barato perde; pior caso por straddle {_pt(hc1.get('pior_mes_por_op_pct'), 0)}%. "
                 f"A versão com a volatilidade de 60 dias não passou ({_pt(a1['configs']['spread_barato_menos_caro_vr60']['descoberta']['media_pct'], 0, True)}% na descoberta).")})
    s2, b2 = a2["variantes"]["sempre_put"]["2020-2023"], a2["variantes"]["so_barato_put"]["2020-2023"]
    out.append({
        "nome": "protecao_na_hora_barata", "titulo": "Proteger BOVA11 só quando a volatilidade implícita está baixa (percentil < 30 do ano)",
        "hipotese": "Seguro custa menos quando a volatilidade implícita está baixa contra o próprio ano; proteger só nessas horas reduziria o custo sem abrir mão da cobertura.",
        "estado": "reprovada",
        "historico": {"periodo": "2020-2023", "n": b2["n_ciclos"], "retorno_anual_pct": b2["retorno_anual_pct"], "sharpe": None, "queda_maxima_pct": b2["queda_maxima_pct"], "pior_mes_pct": b2["pior_mes_pct"], "sharpe_deflacionado": None},
        "nota": (f"A regra falha onde importa: em fevereiro de 2020 o percentil da volatilidade de BOVA11 estava em {_pt(a2['mar2020']['perc_vi_na_entrada'], 1)}, acima do corte, então não haveria proteção e o ciclo de março fechou em "
                 f"{_pt(a2['mar2020']['so_barato_put'], 1)}% (proteger sempre: {_pt(a2['mar2020']['sempre_put'], 1)}%). Custo bruto {_pt(b2['custo_bruto_anual_pct'], 1)}% ao ano contra {_pt(s2['custo_bruto_anual_pct'], 1)}% de proteger sempre, "
                 f"mas o retorno caiu de {_pt(s2['retorno_anual_pct'], 1)}% para {_pt(b2['retorno_anual_pct'], 1)}% ao ano e a queda máxima voltou a {_pt(b2['queda_maxima_pct'], 0)}%. 2021-22: proteger sempre {_pt(a2['2021_22']['sempre_put'], 1)}%, só barato {_pt(a2['2021_22']['so_barato_put'], 1)}%.")})
    ic = a3["previsao"]["skew_put_vs_fut21"]
    s3 = a3["estruturas"]
    out.append({
        "nome": "inclinacao_skew", "titulo": "Inclinação da volatilidade (skew): trava de crédito quando a put está cara, trava de baixa quando está barata, e a inclinação como sinal do ativo",
        "hipotese": "Put fora do dinheiro cara demais paga o vendedor; inclinação alta antecipa retorno pior do ativo (Xing, Zhang e Zhao, 2010).",
        "estado": "reprovada",
        "historico": {"periodo": "2012-2023 (descoberta e validação)", "n": s3["trava_baixa_debito_skew_menor_20"]["descoberta"]["n_ops"], "retorno_anual_pct": None, "sharpe": s3["trava_baixa_debito_skew_menor_20"]["validacao"]["sharpe"],
                      "queda_maxima_pct": None, "pior_mes_pct": s3["trava_baixa_debito_skew_menor_20"]["validacao"]["pior_mes_por_op_pct"], "sharpe_deflacionado": s3["trava_baixa_debito_skew_menor_20"]["validacao"]["sharpe_deflacionado"]},
        "nota": (f"Como sinal do ativo: correlação de postos entre a inclinação e o retorno de 21 pregões de {_pt(ic['descoberta']['corte_entre_acoes']['ic_medio'], 3)} (t {_pt(ic['descoberta']['corte_entre_acoes']['t'], 2)}) na descoberta e "
                 f"{_pt(ic['validacao']['corte_entre_acoes']['ic_medio'], 3)} (t {_pt(ic['validacao']['corte_entre_acoes']['t'], 2)}) na validação: sem poder de previsão. Trava de baixa com débito quando a inclinação é baixa: "
                 f"{_pt(s3['trava_baixa_debito_skew_menor_20']['descoberta']['media_por_op_pct'], 0, True)}% por operação na descoberta (n {s3['trava_baixa_debito_skew_menor_20']['descoberta']['n_ops']}) e "
                 f"{_pt(s3['trava_baixa_debito_skew_menor_20']['validacao']['media_por_op_pct'], 0, True)}% na validação. Trava de crédito com puts quando a inclinação é alta: "
                 f"{_pt(s3['trava_credito_put_skew_maior_80']['descoberta']['media_por_op_pct'], 0, True)}% e {_pt(s3['trava_credito_put_skew_maior_80']['validacao']['media_por_op_pct'], 0, True)}% por operação.")})
    ic4 = a4["desvio_paridade_vs_fut21"]
    ic4b = a4["desvio_paridade_vs_fut5"]
    out.append({
        "nome": "paridade_call_put", "titulo": "Desvio da paridade put-call (volatilidade da call menos a da put no mesmo exercício) como sinal do ativo",
        "hipotese": "Compra informada de call aparece como volatilidade de call acima da de put e antecipa retorno melhor do ativo (Cremers e Weinbaum, 2010).",
        "estado": "reprovada",
        "historico": {"periodo": "2012-2023 (descoberta e validação)", "n": ic4["validacao"]["corte_entre_acoes"]["n_datas"], "retorno_anual_pct": None, "sharpe": None, "queda_maxima_pct": None, "pior_mes_pct": None, "sharpe_deflacionado": None},
        "nota": (f"Correlação de postos com o retorno de 5 pregões: {_pt(ic4b['descoberta']['corte_entre_acoes']['ic_medio'], 3)} (t {_pt(ic4b['descoberta']['corte_entre_acoes']['t'], 2)}) na descoberta e "
                 f"{_pt(ic4b['validacao']['corte_entre_acoes']['ic_medio'], 3)} (t {_pt(ic4b['validacao']['corte_entre_acoes']['t'], 2)}) na validação; com 21 pregões, {_pt(ic4['descoberta']['corte_entre_acoes']['ic_medio'], 3)} "
                 f"(t {_pt(ic4['descoberta']['corte_entre_acoes']['t'], 2)}, só {ic4['descoberta']['corte_entre_acoes']['n_datas']} datas) e {_pt(ic4['validacao']['corte_entre_acoes']['ic_medio'], 3)} (t {_pt(ic4['validacao']['corte_entre_acoes']['t'], 2)}). "
                 f"Não se repetiu fora da amostra.")})
    out.append({
        "nome": "arbitragem_fechamento", "titulo": "Arbitragem no fechamento: conversão, reversão, travas e borboletas fora do preço, com a oferta de compra e de venda",
        "hipotese": "Se a oferta de compra e a de venda de pernas diferentes permitem travar ganho, ou é oportunidade pequena ou é cotação velha.",
        "estado": "medindo",
        "historico": {"periodo": a5["periodo"], "n": a5["estritas"], "retorno_anual_pct": None, "sharpe": None, "queda_maxima_pct": None, "pior_mes_pct": None, "sharpe_deflacionado": None},
        "nota": (f"Descritivo de {a5['dias_na_amostra']} pregões: {a5['total_detectadas']} combinações com folga de 2 centavos ou mais depois dos custos ({_pt(a5['por_dia_media'], 1)} por dia); "
                 f"{a5['sobrevivem']} com 5+ negócios e último negócio dentro das ofertas; {a5['estritas']} na versão estrita (20+ negócios, até 90 dias, exercício a até 15% do preço), {_pt(a5['estritas_por_dia'], 1)} por dia. "
                 f"A folga mediana é de centavos por ação; só {_pt(a5['estritas_que_reaparecem_no_pregao_seguinte_pct'], 0)}% reaparecem no pregão seguinte. A maior parte é reversão, que exige alugar a ação, e conversão, que equivale a emprestar dinheiro um pouco acima do CDI. "
                 f"Não é dinheiro livre de risco: é uma lista de perguntas ao livro de ofertas.")})
    out.append({
        "nome": "straddle_pre_resultado", "titulo": "Straddle no dinheiro comprado 5 pregões antes do protocolo do resultado trimestral na CVM e vendido no dia seguinte",
        "hipotese": "A volatilidade implícita sobe antes do resultado e cai depois; só vale se o movimento do ativo superar o que a opção já cobra.",
        "estado": "reprovada",
        "historico": {"periodo": "2012-2023 (descoberta e validação)", "n": a6["descoberta"]["n"] + a6["validacao"]["n"], "retorno_anual_pct": None, "sharpe": None, "queda_maxima_pct": None,
                      "pior_mes_pct": a6["validacao"]["pior_pct"], "sharpe_deflacionado": None, "media_por_operacao_pct": a6["validacao"]["media_pct"]},
        "nota": (f"Perde em média {_pt(-a6['descoberta']['media_pct'], 0)}% por operação na descoberta (n {a6['descoberta']['n']}, t {_pt(a6['descoberta']['t'], 2)}) e {_pt(-a6['validacao']['media_pct'], 0)}% na validação "
                 f"(n {a6['validacao']['n']}, t {_pt(a6['validacao']['t'], 2)}); só {_pt(a6['descoberta']['pct_positivos'], 0)}% e {_pt(a6['validacao']['pct_positivos'], 0)}% das operações ganham. Spread de entrada e de saída mais o desgaste do tempo e a queda da volatilidade pesam mais que o movimento do resultado.")})
    return out


TERMOS_NOVOS = [
    {"termo": "Capital protegido feito em casa", "explicacao": "O caixa fica no CDI e todo mês uma fração fixa do capital (o orçamento) compra opções de alta. O máximo que se perde no mês é o orçamento; o ganho é aberto. É o que um fundo de capital protegido faz, sem a taxa do estruturador."},
    {"termo": "Straddle", "explicacao": "Compra de uma call e uma put do mesmo exercício e vencimento. Ganha se o ativo andar muito para qualquer lado; perde o custo se ficar parado."},
    {"termo": "Percentil da volatilidade", "explicacao": "Onde a volatilidade implícita de hoje está contra os últimos 252 pregões do próprio ativo: 10 é mais baixa que 90% do ano; 90 é mais alta."},
    {"termo": "Inclinação (skew)", "explicacao": "Diferença entre a volatilidade implícita da put fora do dinheiro e a da opção no dinheiro. Inclinação alta = proteção contra queda cara."},
    {"termo": "Conversão e reversão", "explicacao": "Combinações de ação, put e call do mesmo exercício que travam um valor no vencimento. Se o preço de uma das pernas está fora da linha, aparece uma pequena folga; a maioria é cotação do fim do pregão que não se executa."},
    {"termo": "Vantagem", "explicacao": "Valor esperado da estrutura, pela distribuição histórica de retornos do ativo, dividido pelo custo, depois de descontar o CDI do prazo. Negativa = a história do ativo paga menos que o custo."},
    {"termo": "Dividendo sintético", "explicacao": "Renda mensal obtida vendendo opção com garantia (put coberta por caixa ou call coberta) e recomprando quando já se capturou uns 80% do prêmio. Não é dividendo de verdade: o risco é de queda forte (put) ou de abrir mão da alta (call)."},
    {"termo": "Put coberta por caixa", "explicacao": "Venda de put em que o dinheiro para comprar o ativo no strike já está separado (e rende CDI). Se o ativo cair abaixo do strike, você fica com ele pelo preço combinado."},
    {"termo": "Trava de crédito", "explicacao": "Venda de uma opção e compra de outra mais distante do mesmo tipo e vencimento: recebe um crédito, e a perda máxima é a largura menos o crédito. Trava de alta usa puts; trava de baixa usa calls."},
    {"termo": "Retorno sobre o risco", "explicacao": "Crédito da trava dividido pela perda máxima. 30% quer dizer ganhar R$ 30 se tudo der certo contra R$ 100 de risco."},
    {"termo": "Stop em múltiplo do prêmio", "explicacao": "Fechar a venda de opção quando recomprá-la custa, por exemplo, 3 vezes o que se recebeu. Limita a perda, mas pode cortar uma posição que se recuperaria."},
    {"termo": "Roda", "explicacao": "Aceitar a put exercida (ficar com o ativo) e vender call coberta sobre ele, repetindo o ciclo. Não foi testada no histórico."},
]




# ---------------------------------------------------------------------------------------------------- livro de teses
ARQ_TESES = os.path.join(DIR_OPC, "resultados_teses.json")


def _contexto_teses():
    try:
        with open(ARQ_TESES, encoding="utf-8") as f:
            RT = json.load(f)
    except (FileNotFoundError, ValueError):
        RT = None
    if not RT:
        return {"esm_eleicao": -28.0, "esm_resultado": -4.0, "mov_base": 8.5, "RT": None}
    mov = sorted(abs(x["movimento_pct"]) for x in RT["eleicoes"]["bbas3_movimentos"])
    mediana = (mov[len(mov) // 2 - 1] + mov[len(mov) // 2]) / 2 if len(mov) % 2 == 0 else mov[len(mov) // 2]
    return {"esm_eleicao": RT["eleicoes"]["esmagamento_vol_pct"]["mediana"], "esm_resultado": RT["resultado_trimestral"]["esmagamento_vol"]["mediana_pct"], "mov_base": round(mediana, 1), "RT": RT}


def montar_teses(M, dia):
    """Bloco `teses` do JSON e a lista das expressoes escolhidas que a carteira simulada pode abrir (so origem mesa/robo, probabilidade definida)."""
    ctx = _contexto_teses()
    blocos, abrir = [], []
    tr = M.get("tr", {})
    # 1) caso trabalhado do Douglas (BBAS3, 2o turno de 2026): a probabilidade e dele; 40/50/60 e tres tamanhos de movimento
    try:
        base = livro_teses.caso_bbas3(M, ctx["esm_eleicao"], ctx["mov_base"], tr=tr.get("BBAS3"))
        principal = base[0.5]
        principal["sensibilidade_probabilidade"] = {f"{int(p * 100)}%": {"escolhida": b["escolhida"], "valor_esperado_rs": {e["nome"]: e["valor_esperado_rs"] for e in b["expressoes"]}} for p, b in base.items()}
        sens = {}
        for mv in (5.0, ctx["mov_base"], 15.0):
            bb = livro_teses.caso_bbas3(M, ctx["esm_eleicao"], mv, tr=tr.get("BBAS3"))
            sens[f"±{mv:g}%"] = {f"{int(p * 100)}%": {"escolhida": b["escolhida"], "valor_esperado_rs": {e["nome"]: e["valor_esperado_rs"] for e in b["expressoes"]},
                                                   "prob_exigida_pct": {e["nome"]: e["probabilidade_que_o_preco_exige_pct"] for e in b["expressoes"]}} for p, b in bb.items()}
        principal["sensibilidade_movimento"] = sens
        principal["movimento_base_pct"] = ctx["mov_base"]
        principal["nota_probabilidade"] = ("Caso de estudo: mostra como o livro compara papel, call e trava antes de um evento. Não é operação e nada abre a partir dele "
                                           "(o Douglas avisou em 11/10/2026 que o momento de entrada em BBAS3 já passou). 50% é só o ponto médio da tabela.")
        blocos.append(principal)
    except Exception as e:  # noqa: BLE001
        blocos.append({"id": "douglas-bbas3-2o-turno-2026", "ativo": "BBAS3", "direcao": "alta", "origem": "exemplo", "exemplo": True, "expressoes": [], "escolhida": None, "porque": f"Falha ao montar o caso: {type(e).__name__}"})
    # 2) teses da mesa e do robo (arquivos podem nao existir)
    for t in livro_teses.ler_teses_mesa() + livro_teses.teses_da_visao_mesa(dia):
        ev = t.get("evento") or {}
        esm = ctx["esm_eleicao"] if ("eleiç" in str(ev.get("descricao", "")).lower() or "turno" in str(ev.get("descricao", "")).lower()) else ctx["esm_resultado"]
        b, ab = livro_teses.avaliar_tese(t, M, esm, tr=tr.get(t["ativo"]))
        blocos.append(b)
        abrir += ab
    return blocos, abrir


if __name__ == "__main__":
    sys.exit(main())
