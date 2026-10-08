"""
Simulacao AO VIVO (estagio 1 do agente no terminal): a mesma boleta e a mesma regra de
casamento do paper trading, so que alimentada pelo tique do MetaTrader conforme ele chega,
em vez da fita arquivada depois do fechamento.

POR QUE ESTE MODULO NAO CASA ORDEM. `paper.simular` ja resolve o casamento inteiro: preco
limite, teto de participacao sobre o volume do periodo em que a ordem esteve viva, consumo
cronologico, preco medio ponderado. Reescrever isso em forma incremental criaria DUAS regras
de casamento - a do vivo e a do fechamento - e na primeira vez que discordassem o paper
trading viraria teatro: "funcionou na simulacao" deixaria de significar coisa alguma. Entao
aqui nao ha regra nova. Este modulo ACUMULA a fita que ja viu e chama `paper.simular` sobre
ela.

O preco disso e recalcular o pregao a cada lote de tiques. Para as 15-25 acoes da estrategia
isso e da ordem de dezenas de milhares de linhas - trivial - e em troca vem uma garantia que
vale mais que o CPU: o estado ao vivo no fim do pregao e, POR CONSTRUCAO, igual ao que a
medicao de fechamento produz. Quem prova isso e
`test_pedacos_dao_o_mesmo_que_a_fita_inteira`: a mesma fita entregue em N pedacos aleatorios
tem de dar exatamente o mesmo resultado que entregue de uma vez.

TIQUE DE COTACAO NAO E NEGOCIO. O MetaTrader entrega na mesma sequencia as mudancas de book
(bid/ask mexeu, ninguem negociou) e os negocios. Contar mudanca de book como negocio infla o
volume do periodo, e o volume do periodo e exatamente o que limita a execucao pelo teto de
participacao - o teto viraria decoracao e a simulacao passaria a executar tudo sempre. Por
isso `de_mt5` so aceita tique com `volume > 0` e `last > 0`, e confere a marca de negocio
nas `flags` quando ela vem.

O QUE ESTE MODULO DELIBERADAMENTE NAO FAZ:
  - NAO manda ordem. Nada aqui toca corretora. Enviar e o estagio 2, e passa por uma guarda
    que exige conta demo;
  - NAO reprecifica. A boleta ja traz os precos das 12:20 e 14:20, mas aplicar a
    reprecificacao exige decidir que alguem chegou no horario, e essa decisao e do estagio 2;
  - NAO inventa preco. Papel sem negocio no periodo fica sem marcacao, e o painel mostra
    "sem negocio" em vez do preco de ontem. Marcacao a mercado com preco velho e a maneira
    mais silenciosa de um P&L mentir.
"""
import math

import pandas as pd

from quant.execucao import paper

# Marca de negocio nas flags do MetaTrader (TICK_FLAG_LAST). Quando as flags vem, ela e a
# resposta; quando nao vem (fita de teste, fonte que nao preenche), caimos no par
# volume > 0 e last > 0, que e o mesmo criterio por outro caminho.
FLAG_NEGOCIO = 8

COLUNAS_NEGOCIOS = list(paper.COLUNAS_NEGOCIOS)


def _num(x, padrao=float("nan")):
    try:
        v = float(x)
        return v if math.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def de_mt5(tiques, ticker):
    """Converte tiques do MetaTrader no formato de negocios que `paper.simular` entende.

    Entrada: iteravel de dicts com `time` (unix, segundos), `last`, `volume` e, quando
    houver, `flags` - e o formato que `b3_mt5_bridge.fetch_recent_ticks` devolve. Saida:
    DataFrame com ticker, hora (HH:MM:SS), preco e quantidade, so com os tiques que sao
    negocio de verdade.
    """
    linhas = []
    for t in tiques or []:
        if not isinstance(t, dict):
            continue
        qtd = _num(t.get("volume"), 0.0)
        preco = _num(t.get("last"), 0.0)
        if not (qtd > 0 and preco > 0):
            continue
        flags = t.get("flags")
        if flags is not None:
            try:
                if not (int(flags) & FLAG_NEGOCIO):
                    continue
            except (TypeError, ValueError):
                pass                      # flag ilegivel nao descarta o negocio
        quando = _num(t.get("time"))
        if not math.isfinite(quando):
            continue
        linhas.append({"ticker": str(ticker).upper().strip(),
                       "hora": pd.Timestamp(int(quando), unit="s", tz="America/Sao_Paulo"
                                            ).strftime("%H:%M:%S"),
                       "preco": float(preco), "quantidade": float(qtd)})
    return pd.DataFrame(linhas, columns=COLUNAS_NEGOCIOS)


class Sessao:
    """Uma sessao de simulacao ao vivo sobre UMA boleta.

    Uso: `s = Sessao(boleta)`, depois `s.aplicar(negocios)` a cada lote de tiques, e
    `s.estado()` para o painel. `aplicar` e idempotente no sentido que importa: o estado e
    sempre funcao da fita inteira acumulada, nunca da ordem em que os lotes chegaram.
    """

    def __init__(self, boleta, participacao_max=paper.MAX_PARTICIPACAO):
        self.boleta = boleta if isinstance(boleta, dict) else {}
        self.participacao_max = participacao_max
        self._fita = pd.DataFrame(columns=COLUNAS_NEGOCIOS)
        self._fills = pd.DataFrame(columns=paper._colunas_fill())

    # ── entrada ──────────────────────────────────────────────
    def aplicar(self, negocios):
        """Acrescenta negocios a fita e recasa a boleta inteira. Devolve `estado()`."""
        novos = paper.normalizar_negocios(negocios)
        if len(novos):
            partes = [p for p in (self._fita, novos) if len(p)]
            self._fita = (pd.concat(partes, ignore_index=True) if len(partes) > 1
                          else partes[0].reset_index(drop=True))
            self._fita = self._fita.sort_values("hora", kind="stable").reset_index(drop=True)
            self._fills = paper.simular(self.boleta, self._fita,
                                        participacao_max=self.participacao_max)
        return self.estado()

    def aplicar_mt5(self, tiques, ticker):
        """Atalho para quem recebe tique cru da ponte: converte e aplica."""
        return self.aplicar(de_mt5(tiques, ticker))

    # ── leitura ──────────────────────────────────────────────
    @property
    def fita(self):
        return self._fita

    @property
    def fills(self):
        return self._fills

    def ultimo_preco(self, ticker):
        """Ultimo negocio visto do papel, ou NaN. Nunca cai para o fechamento de ontem."""
        alvo = str(ticker).upper().strip()
        d = self._fita[self._fita["ticker"] == alvo]
        if len(d) == 0:
            return float("nan")
        return float(d["preco"].to_numpy()[-1])

    def estado(self):
        """O que o painel mostra: uma linha por ordem, mais os totais.

        Por ordem: alvo, executado, preco medio, quanto falta, e a marcacao a mercado
        contra o ultimo negocio visto. `preco_mercado` e `aberto` saem como None quando o
        papel ainda nao negociou - sem negocio nao ha marcacao, e inventar uma e o jeito
        silencioso de o P&L mentir.
        """
        fills = self._fills
        por_ticker = {}
        if len(fills):
            for _, f in fills.iterrows():
                por_ticker[str(f["ticker"])] = f

        ordens = []
        aberto_total, financeiro_total = 0.0, 0.0
        for o in (self.boleta.get("ordens") or []):
            tk = str(o.get("ticker"))
            alvo = int(_num(o.get("qtd"), 0.0) or 0)
            lado = "C" if str(o.get("lado")) == "C" else "V"
            f = por_ticker.get(tk)
            executado = int(_num(f["qtd"], 0.0)) if f is not None else 0
            medio = float(_num(f["preco"])) if f is not None else float("nan")
            mercado = self.ultimo_preco(tk)
            tem_marca = executado > 0 and math.isfinite(medio) and math.isfinite(mercado)
            sinal = 1.0 if lado == "C" else -1.0
            aberto = (mercado - medio) * executado * sinal if tem_marca else None
            if aberto is not None:
                aberto_total += aberto
                financeiro_total += medio * executado
            ordens.append({
                "ticker": tk,
                "lado": lado,
                "alvo": alvo,
                "executado": executado,
                "falta": max(alvo - executado, 0),
                "taxa_execucao": (executado / alvo) if alvo > 0 else None,
                "preco_medio": medio if math.isfinite(medio) else None,
                "preco_limite": float(_num(o.get("preco_limite"))) if math.isfinite(
                    _num(o.get("preco_limite"))) else None,
                "preco_mercado": mercado if math.isfinite(mercado) else None,
                "aberto": aberto,
                "hora_ultimo_fill": str(f["hora"]) if f is not None else None,
            })

        pedido = sum(o["alvo"] for o in ordens)
        feito = sum(o["executado"] for o in ordens)
        return {
            "data": self.boleta.get("data"),
            "boleta": self.boleta.get("id"),
            "emitida": bool(self.boleta.get("emitida", False)),
            "origem": paper.ORIGEM,
            "negocios_vistos": int(len(self._fita)),
            "ordens": ordens,
            "totais": {
                "ordens": len(ordens),
                "qtd_pedida": pedido,
                "qtd_executada": feito,
                "taxa_execucao": (feito / pedido) if pedido > 0 else None,
                "financeiro_executado": financeiro_total,
                "aberto": aberto_total,
            },
        }

    def medicao(self, barras=None):
        """A medicao de slippage e taxa de execucao, igual a do fechamento.

        Reusa `paper.medir_slippage` em vez de recalcular: os tres numeros que ela devolve
        (slippage contra o limite, contra o mid e contra o VWAP) sao o criterio de pronto
        da fase 4, e tem de ser os mesmos no vivo e no fechamento.
        """
        return paper.medir_slippage(self.boleta, self._fills,
                                    barras=self._fita if barras is None else barras)
