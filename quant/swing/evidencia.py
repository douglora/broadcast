"""
Evidencia dos setups: quais podem usar capital do livro e quais so sao medidos.

REGRA (escrita antes, no pre-registro de 11/10/2026):
  - So pode ter capital a variante que passou na descoberta (2010-2017), na validacao (2018-2021) E na prova (2022-2026, aberta uma vez, so para
    finalista). Quem passou nas tres tem capital marcado "medindo" ate o Sharpe deflacionado (ajustado pelo numero de variantes testadas) chegar a
    0,95; ai vira "validado".
  - Quem reprovou em qualquer etapa fica "so medido": o robo registra o sinal e o resultado como se tivesse operado um valor padrao (R$ 6.000), sem
    capital, para o placar crescer e a pergunta ser respondida com dado novo.
  - Excecao: decisao escrita do Douglas em `quant/saida/swing_config.json` (`"liberar": ["D1.S1"]`). Fica na tela como "liberado pelo Douglas, sem
    evidencia de teste", nunca disfarcado de validado.

Se NENHUMA variante passou (e o caso de 11/10/2026), o resumo diz isso com todas as letras e o livro roda so medido.
"""
import json
import os

from quant.comum import DIR_SAIDA
from quant.swing import mesa_setups, setups

PASTA = os.path.join(DIR_SAIDA, "pesquisa_swing")
ARQ_DV = os.path.join(PASTA, "resultados_dv.json")
ARQ_PROVA = os.path.join(PASTA, "resultados_prova.json")
ARQ_CONFIG = os.environ.get("QUANT_SWING_CONFIG") or os.path.join(DIR_SAIDA, "swing_config.json")
DSR_MIN = 0.95
PADRAO = {"capital": 60_000.0, "risco": 0.005, "teto_nome": 0.12, "max_posicoes": 10, "valor_medido": 6_000.0, "liberar": [],
          "sair_antes_de": None,            # AAAA-MM-DD: o livro sai nesse dia e nao abre posicao nova ate passar (evento binario; decisao escrita)
          "sair_antes_de_fracao": 1.0,      # fracao do financeiro que sai nesse dia: 1,0 = tudo; 0,5 = metade, as maiores posicoes primeiro
          "sair_antes_de_hora": "12:40"}    # HH:MM da saida nesse dia: antes de o Mac desligar as 13h (decisao do Douglas em 21/10/2026)
LIMITES = {"capital": (1_000.0, 10_000_000.0), "risco": (0.0005, 0.02), "teto_nome": (0.02, 0.25), "max_posicoes": (1, 10), "valor_medido": (500.0, 100_000.0),
           "sair_antes_de_fracao": (0.1, 1.0)}

STATUS_TEXTO = {
    "so_medido": "só medido (sem capital)",
    "medindo": "com capital, medindo (Sharpe deflacionado ainda abaixo de 0,95)",
    "validado": "com capital, validado",
    "liberado": "liberado pelo Douglas, sem evidência de teste",
}
COM_CAPITAL = ("medindo", "validado", "liberado")


def _json(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def config(arq=None):
    """Parametros do livro: os padroes do pre-registro, trocaveis por decisao escrita do Douglas, sempre dentro de limites sensatos."""
    c = dict(PADRAO)
    avisos = []
    lido = _json(arq or ARQ_CONFIG)
    if isinstance(lido, dict):
        for k in PADRAO:
            if k not in lido:
                continue
            if k == "liberar":
                ids = lido[k] if isinstance(lido[k], list) else []
                c[k] = [str(x) for x in ids]
                continue
            if k == "sair_antes_de":
                v = lido[k]
                if v in (None, ""):
                    c[k] = None
                elif isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-" and v.replace("-", "").isdigit():
                    c[k] = v
                else:
                    avisos.append(f"sair_antes_de={v!r} ilegível em swing_config.json (use AAAA-MM-DD); ignorado")
                continue
            if k == "sair_antes_de_hora":
                v = lido[k]
                if isinstance(v, str) and len(v) == 5 and v[2] == ":" and v[:2].isdigit() and v[3:].isdigit() and int(v[:2]) < 24 and int(v[3:]) < 60:
                    c[k] = v
                else:
                    avisos.append(f"sair_antes_de_hora={v!r} ilegível em swing_config.json (use HH:MM); vale {PADRAO[k]}")
                continue
            try:
                v = float(lido[k])
            except (TypeError, ValueError):
                avisos.append(f"{k} ilegível em swing_config.json; vale o padrão")
                continue
            lo, hi = LIMITES[k]
            if not (lo <= v <= hi):
                avisos.append(f"{k}={lido[k]} fora do limite [{lo}, {hi}] em swing_config.json; vale o padrão")
                continue
            c[k] = int(v) if k == "max_posicoes" else v
        c["motivo_liberacao"] = lido.get("motivo")
        c["decidido_em"] = lido.get("decidido_em")
    c["avisos"] = avisos
    return c


def por_variante(dv=None, prova=None, cfg=None):
    """id da variante -> {status, motivo, familia, nucleo, overlay, descoberta, validacao, prova, dsr}. Le os JSONs da pesquisa."""
    dv = dv if dv is not None else (_json(ARQ_DV) or {})
    prova = prova if prova is not None else (_json(ARQ_PROVA) or {})
    cfg = cfg if cfg is not None else config()
    liberar = set(cfg.get("liberar") or [])
    prova_fechada = not prova or ("finalistas" in prova and not prova.get("finalistas"))
    out = {}
    for v in setups.variantes():
        vid = v["id"]
        r = dv.get(vid) or {}
        passa = r.get("passa") or {}
        linha = {"id": vid, "familia": v["familia"], "nucleo": v["nucleo"], "overlay": v["overlay"], "rotulo": setups.ROTULOS.get(v["familia"], v["familia"]),
                 "descoberta": _resumo(r.get("descoberta")), "validacao": _resumo(r.get("validacao")), "prova": None, "dsr": None}
        if not r:
            status, motivo = "so_medido", "pesquisa ainda não rodou para esta variante"
        elif not passa.get("finalista"):
            falhas = (passa.get("falhas_descoberta") or []) if not passa.get("descoberta") else (passa.get("falhas_validacao") or [])
            etapa = "descoberta" if not passa.get("descoberta") else "validação"
            status, motivo = "so_medido", f"reprovou na {etapa}" + (f": {falhas[0]}" if falhas else "")
        elif prova_fechada or vid not in prova:
            status, motivo = "so_medido", "passou descoberta e validação; a prova ainda não foi aberta"
        else:
            p = prova[vid]
            linha["prova"] = _resumo(p.get("prova"))
            linha["dsr"] = p.get("dsr_serie_inteira")
            if not p.get("passa_prova"):
                status, motivo = "so_medido", "reprovou na prova (2022-2026)"
            elif (linha["dsr"] or 0.0) >= DSR_MIN:
                status, motivo = "validado", "passou nas três etapas e o Sharpe deflacionado passou de 0,95"
            else:
                status, motivo = "medindo", "passou nas três etapas; capital marcado como medindo até o Sharpe deflacionado chegar a 0,95"
        if vid in liberar and status not in COM_CAPITAL:
            status, motivo = "liberado", "decisão do Douglas" + (f" ({cfg.get('decidido_em')})" if cfg.get("decidido_em") else "") + \
                (f": {cfg['motivo_liberacao']}" if cfg.get("motivo_liberacao") else "")
        linha["status"], linha["motivo"], linha["status_texto"] = status, motivo, STATUS_TEXTO[status]
        linha["sensibilidade_custo_leve"] = bool((r.get("sensibilidade_custo_leve") or {}).get("passaria_dv"))
        out[vid] = linha
    for vid, r in mesa_setups.linhas_de_evidencia(cfg).items():       # M1 e M2: camada de julgamento, sem teste historico, so prova viva
        r["status_texto"] = STATUS_TEXTO[r["status"]]
        out[vid] = r
    return out


def _resumo(m):
    if not isinstance(m, dict):
        return None
    return {k: m.get(k) for k in ("operacoes", "expectativa_pct", "acerto", "payoff", "sharpe", "excesso_aa", "queda_maxima", "anos_positivos", "n_anos")}


def com_capital(variantes):
    return sorted(v for v, r in variantes.items() if r["status"] in COM_CAPITAL)


def aceita(variantes, nucleo, top, ibov_ok):
    """(True, id da variante) se alguma variante do nucleo com capital cobre este sinal: S0 cobre qualquer um, S1 so a metade de cima do ranking,
    S2 so com o Ibovespa acima da media de 200. Escolhe a de status mais forte. (False, None) se nenhuma."""
    ordem = {"validado": 0, "medindo": 1, "liberado": 2}
    achadas = []
    for vid, r in variantes.items():
        if r["nucleo"] != nucleo or r["status"] not in COM_CAPITAL:
            continue
        if (r["overlay"] == "S1" and not top) or (r["overlay"] == "S2" and not ibov_ok):
            continue
        achadas.append((ordem[r["status"]], vid))
    if not achadas:
        return False, None
    return True, sorted(achadas)[0][1]


def resumo(variantes):
    """Frase para a primeira linha da tela e dos relatorios."""
    n = sum(1 for r in variantes.values() if r["familia"] != mesa_setups.FAMILIA)           # os 39 pesquisados; M1 e M2 nao tem teste historico
    cap = com_capital(variantes)
    if not cap:
        d = sum(1 for r in variantes.values() if r["motivo"].startswith("reprovou na descoberta"))
        v = sum(1 for r in variantes.values() if r["motivo"].startswith("reprovou na validação"))
        return (f"Nenhum dos {n} setups de swing passou na descoberta e na validação; a prova (2022 a 2026) continua fechada. "
                f"O livro roda só medido: registra cada sinal e o resultado como se tivesse operado R$ 6.000, sem capital. "
                f"({'todos' if d == n else d} reprovaram na descoberta" + (f", {v} na validação" if v else "") + ".) "
                f"M1 e M2 (convicção e veto da mesa) não têm teste histórico: só prova viva, também sem capital.")
    medindo = [x for x in cap if variantes[x]["status"] == "medindo"]
    lib = [x for x in cap if variantes[x]["status"] == "liberado"]
    partes = [f"{len(cap)} setup(s) com capital: " + ", ".join(cap)]
    if medindo:
        partes.append(f"{len(medindo)} ainda medindo (Sharpe deflacionado < {DSR_MIN:.2f})")
    if lib:
        partes.append(f"{len(lib)} liberado(s) por decisão do Douglas, sem evidência de teste")
    return "; ".join(partes) + "."


def descricao_da_regra():
    return ("Um setup só usa capital se passar na descoberta (2010-2017), na validação (2018-2021) e na prova (2022-2026, aberta uma vez). "
            "Quem passa fica 'medindo' até o Sharpe deflacionado (que desconta o número de variantes testadas) chegar a 0,95. "
            "Quem reprova fica 'só medido': o robô registra o sinal e o resultado, sem capital. M1 e M2 (convicção e veto da mesa) são julgamento, "
            "sem teste histórico possível: só prova viva, nunca capital pela regra. Só o Douglas libera exceção, por escrito.")
