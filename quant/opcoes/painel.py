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

from quant.opcoes import bs, dados
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
        "estão listadas como reprovadas, com o número. Por isso a lista de hoje traz só estruturas de proteção, que são seguro e não fonte de retorno.",
        f"Cadeia de {data_cadeia}: {origem}. São as ofertas do FIM do pregão; no pregão seguinte o preço é outro. Confira a oferta na hora.",
        "Resultados antes de imposto (operação comum em opções paga 15% sobre o ganho, sem a isenção das ações) e sem corretagem. Emolumentos: premissa de 0,05% do prêmio por lado.",
        "Marcação mensal: a queda máxima é a do fechamento de cada ciclo; a perda dentro do mês pode ser maior. Opções tratadas como europeias (exercício antecipado ignorado).",
        "Antes de 2020 BOVA11 não tinha opção líquida: a proteção de 2013-2019 usou opções do próprio Ibovespa, com preço estimado (último negócio com 5% contra) em 40 de 47 ciclos.",
    ]


# ---------------------------------------------------------------------------------------------------- principal
def gerar(rede=True):
    with open(os.path.join(DIR_OPC, "resultados.json"), encoding="utf-8") as f:
        R = json.load(f)
    estrategias = montar_estrategias(R)
    estado = {e["nome"]: e["estado"] for e in estrategias}
    op, sp, dia, origem = cadeia_recente(rede)
    cad = preparar_cadeia(op, sp, dia, ATIVOS_HEDGE)
    cands = candidatas(cad, estado, R)
    agora = datetime.now(FUSO).isoformat(timespec="seconds")
    n_rep = sum(1 for e in estrategias if e["estado"] == "reprovada")
    n_med = sum(1 for e in estrategias if e["estado"] == "medindo")
    n_apr = sum(1 for e in estrategias if e["estado"] == "aprovada")
    texto = (f"{len(estrategias)} estratégias de opções testadas em histórico da B3 (2012-2026): {n_apr} aprovada(s), {n_med} em medição, {n_rep} reprovada(s). "
             "Vender put, vender call coberta, travas de crédito e comprar pozinho não pagaram o risco contra o CDI. "
             "Sobrou a proteção com opções de BOVA11 (put, colar, trava de baixa), que funcionou como seguro em março de 2020 e custa de 7% a 15% da carteira ao ano.")
    return {
        "v": 1, "tipo": "opcoes", "gerado": agora, "modo": "simulacao",
        "resumo": {"texto": texto, "data_da_cadeia": str(dia.date()), "origem_da_cadeia": origem,
                   "contagem": {"aprovada": n_apr, "medindo": n_med, "reprovada": n_rep},
                   "tentativas": R["tentativas"], "pesquisa_gerada": R["gerado"],
                   "juro_usado_aa_pct": round(juro_atual()[0] * 100, 3)},
        "estrategias": estrategias, "candidatas_hoje": cands, "posicoes": [],
        "avisos": montar_avisos(R, origem, str(dia.date())), "termos": TERMOS,
    }


def gravar_atomico(caminho, obj):
    pasta = os.path.dirname(caminho)
    os.makedirs(pasta, exist_ok=True)
    tmp = os.path.join(pasta, f".{os.path.basename(caminho)}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    obj = gerar(rede="--sem-rede" not in argv)
    if "--so-mostrar" in argv:
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:6000])
        return 0
    for caminho in SAIDAS:
        gravar_atomico(caminho, obj)
        print("gravado", caminho)
    print(f"{len(obj['estrategias'])} estrategias, {len(obj['candidatas_hoje'])} candidatas, cadeia de {obj['resumo']['data_da_cadeia']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
