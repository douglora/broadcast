"""
Robo de day trade pela LEITURA DE FLUXO (regra versao 1.1), em SIMULACAO.

E o mesmo desenho de robo.py (le o motor do terminal uma vez por segundo, simula, grava o
estado para a area QUANT), com tres diferencas:
  - alem do preco, le a FITA (negocios com o lado agressor) que o AutopilotFeed 1.3 grava na
    pasta do MetaTrader, e o ajuste de ontem na foto do mesmo robo;
  - no dolar a fita lida e a do contrato CHEIO (DOL), como ele faz, e a ordem simulada e no
    mini; se a fita do cheio nao chega, cai para a do mini e avisa;
  - a regra e a de estrategia_fluxo.py: defesa, perda de nivel confirmada e rompimento depois
    de varias batidas; parcial, zero a zero, stop movel, escada de lote; para com R$ 1.000 de
    perda, 3 negocios perdedores, 20% do lucro do dia devolvido, ou na meta.

SEM FITA NAO OPERA. Se o arquivo da fita nao existe ou parou (robo 1.3 desligado, MetaTrader
fechado), o robo fica parado e diz isso na tela: leitura de fluxo sem fluxo seria a regra
antiga com outro nome.

Nada aqui manda ordem. Uso: python -m quant.daytrade.robo_fluxo [--uma-vez]
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone

from quant.comum import agora_brt, garantir_dir, gravar_atomico, ler_json, log
from quant.daytrade import barras as br
from quant.daytrade import chave
from quant.daytrade import estrategia as es
from quant.daytrade import estrategia_fluxo as ef
from quant.daytrade import estrategias_hist as eh
from quant.daytrade import fluxo as fx
from quant.daytrade import regras_lab
from quant.daytrade.robo import (ABERTURA, ATIVOS, DIARIO_MAX, DIR_DT, FIM_PROCESSO, I_ABE, I_ANT, I_HORA, I_MAX,
                                 I_MEDIO, I_MIN, I_ULT, I_VAR, INTERVALO, MOTOR, SAIDAS_PADRAO, _num, _pontos, _reais,
                                 ler_motor)

ARQ_SERIE = os.path.join(DIR_DT, "serie_fluxo.json")
# o setup PhiCube (decisao do Douglas em 08/10/2026), na segunda leitura dos videos de Bo Williams: media do metodo
# reconstruida, Prisma no grafico de 15 minutos e a virada do ROC de 34 no de 4. Os mesmos parametros do teste
# historico (estrategias_hist.PhiCubeV1), que e a classe usada ao vivo.
PHICUBE = {"maior": 15, "menor": 4, "tipo": "mima", "exige_preco": True, "fundo": 5, "stop_min": 2.0, "stop_max": 8.0,
           "saida": "fixo", "alvo_pts": 35.0, "parcial_r": 1.0}
# o setup "niveis" (escolha do Douglas em 08/10/2026, a "opcao C"): o que os instrutores do PhiCube fazem nas lives.
# Teste de nivel com reacao no grafico de 4 minutos, stop colado atras do nivel, alvo no nivel seguinte.
# Sao os parametros do teste historico (estrategias_hist.NivelReacao), que perdeu cerca de R$ 20 por negocio.
# Em 08/10 (16h) o Douglas pediu para juntar "tape reading em cima de 3 linhas de medias moveis, 205, 72 e 36, grafico de
# 6 minutos": o teste de nivel passou para o grafico de 6 minutos, as tres medias entraram como niveis, e a fita e MEDIDA
# em toda entrada (nao filtra ainda: primeiro se mede se a entrada confirmada pela fita rende mais que a nao confirmada).
NIVEIS = {"tempo": 6, "tol": 1.0, "fura": 2.0, "rejeita": 1.5, "folga": 1.0, "stop_min": 3.0, "stop_max": 10.0, "alvo_min": 13.0,
          "alvo_max": 40.0, "alvo_padrao": 20.0, "rr_min": 2.0, "parcial_r": 1.0, "idade_extremo": 20, "redondo": 10.0,
          "medias": (36, 72, 205), "tempo_medias": 6, "tipo_medias": "sma", "medias_como_nivel": True, "filtro_medias": None}
# 08/10/2026, depois do fechamento ("precisa rever e ver onde errou"): estudo em 888 pregoes (quant/estudos/LEIA.md).
# A entrada de nivel perde o custo (cerca de R$ 23 por negocio) e nenhum filtro testado a salva; a unica leitura de barra
# com efeito do mesmo sinal nas duas metades e o CLIMAX DE VOLUME (tranco de 1 minuto com volume de 3 vezes a media ou
# mais: o preco tende a devolver). No simulador ela empata menos o custo (de -R$ 14 a +R$ 7 por negocio), acertando 2 em 3.
# Por isso, dentro do setup "niveis": quem OPERA e o climax; o teste de nivel continua sendo lido e MEDIDO, com a fita,
# sem operar. As duas chaves abaixo podem ser trocadas em modo_robo.json ("climax_opera", "niveis_opera").
# CALIBRACAO de 08/10/2026, 17h30 ("ajuste para acertar 2 em 3"): 1.200 configuracoes escolhidas na metade 1 de 2026 e
# conferidas na metade 2 (quant/estudos/2026-10-08_calibrar_climax.py). Tranco e volume maiores melhoram nas DUAS metades;
# com tranco >= 5 e volume >= 3x, alvo em 80% do tranco e stop de 10 pontos: 164 negocios em 177 manhas, acerto de 67%,
# +R$ 15,60 por negocio com 2 contratos (metades: +17,50 e +11,90). A configuracao anterior (4 pontos, alvo de 60%) dava
# -R$ 4,30. Entre o limiar de medir e o de operar o sinal so fica guardado.
CLIMAX = {"tranco": 5.0, "vol": 3.0, "janela": 30, "minimo": 10, "stop_fixo": 10.0, "alvo_devolve": 0.8, "tempo_max": 20,
          "atraso_max_s": 8, "medir_tranco": 3.0, "medir_vol": 2.5}
CLIMAX_ESPERA_S = 10.0            # o sinal de climax vale por estes segundos: spread aberto logo depois do tranco fecha em seguida
# PROVA FORA DA AMOSTRA (08/10/2026, 18h32): com as barras de 1 minuto desde out/2021 (quant/estudos/LEIA.md) a mesma
# configuracao, nos 1.071 pregoes que a calibracao nunca viu, acertou 56% e PERDEU R$ 16,50 por negocio com 2 contratos,
# em todos os anos de 2021 a 2025. Das 108 configuracoes da grade, 107 ganham em 2026 e NENHUMA ganha em 2021-2025.
# A calibracao nao se sustenta: o climax segue no ar so para gerar operacoes e medir com a fita, no lote minimo.
CLIMAX_PROVA = {"pregoes": 1071, "de": "outubro de 2021", "ate": "janeiro de 2026", "acerto": 56, "rs_por_negocio_e_contrato": -8.25,
                "acerto_2026": 68, "rs_por_negocio_e_contrato_2026": 10.15, "configuracoes": 108, "ganham_2021_2025": 0}
# SETUP PROPRIO (08/10/2026, 22h): busca em 5 anos de barras de 1 minuto, sete frentes, milhares de hipoteses, com
# descoberta (2021-2024), validacao (2025) e prova (2026) separadas (quant/pesquisa/lab.py; quant/estudos/LEIA.md).
# A unica regra que passou: apostar CONTRA a reacao dos 2 primeiros minutos ao dado americano das 8h30 de Nova York
# (9h30 de Brasilia no horario de verao dos EUA, 10h30 fora), quando ela passa de 4 pontos; sai em 120 minutos ou no
# stop de 40 pontos, sem alvo e sem parcial. Com 2 contratos: descoberta 262 negocios, +R$ 116 por negocio (t 3,2,
# 7 de 7 semestres); validacao 45 negocios, +R$ 19; prova 32 negocios, +R$ 91. Fora da descoberta: 77 negocios, +R$ 49
# (t 0,9): positivo nos seis anos, mas ainda sem forca estatistica sozinho. Os parametros estao CONGELADOS: nao reotimizar.
DADO = {"minutos": 2, "limiar": 4.0, "stop": 40.0, "tempo_max": 120, "atraso_max_s": 8}
DADO_ESPERA_S = 10.0              # como no climax: o sinal vale por estes segundos, se o spread abrir logo depois do dado
DADO_RESERVA_MIN = 22             # antes do dado as outras leituras nao abrem posicao: a vaga e do setup proprio
QUEM_OPERA = {"dado_opera": True, "climax_opera": True, "niveis_opera": False}
# Cotacoes em rajadas: a conexao do MetaTrader com a corretora degrada e os tiques chegam de 20 em 20 segundos (08/10 de
# manha e a tarde, 09/10 as 10h15). O remedio que sempre resolveu e fechar e reabrir o MetaTrader; o robo agora faz sozinho.
FEED_RUIM = {"sem_tique_s": 30.0, "atraso_ms": 15_000.0, "leituras": 3, "espera_s": 180.0, "max_por_dia": 8}


def metatrader_aberto():
    return subprocess.run(["pgrep", "-f", r"MetaTrader 5\\terminal64\.exe"], capture_output=True).returncode == 0


def reabrir_metatrader():
    from quant.daytrade.ligar_fita import _reabrir_metatrader
    try:
        _reabrir_metatrader()
    except Exception as e:                                       # nao consegui reabrir: fica o aviso na tela, o robo segue
        log(f"nao consegui reabrir o MetaTrader: {type(e).__name__}: {e}")
ARQ_MODO = os.path.join(os.path.dirname(DIR_DT), "modo_robo.json")
SETUPS_DE_GRAFICO = ("phicube", "niveis")
FITA_PARADA_S = 30.0
# o ajuste OFICIAL dos futuros, que o terminal coleta do boletim diario da B3. O "fechamento anterior" do
# MetaTrader e o ultimo negocio da noite, nao o ajuste: em 07/10/2026 um era 5.044,0 e o outro 5.027,758
ARQ_FUTUROS_B3 = os.path.expanduser(os.environ.get("QUANT_FUTUROS_B3", "~/Desktop/terminal-artefato/cache/out/deriv/futuros.json"))


def ajustes_oficiais(codigos, hoje, arquivo=None):
    """{WDOFUT: (ajuste, data)} do ultimo pregao ANTERIOR a `hoje`, pelo arquivo de futuros do terminal.

    De manha o arquivo e do pregao de ontem (vale "ajuste"); de noite ja e o de hoje (vale "ajuste_ant").
    Arquivo com mais de 5 dias corridos de atraso e ignorado: ajuste velho como nivel e pior que nenhum.
    """
    d = ler_json(arquivo or ARQ_FUTUROS_B3, padrao=None)
    if not isinstance(d, dict) or not d.get("data"):
        return {}
    data = str(d["data"])
    try:
        atraso = (datetime.strptime(str(hoje), "%Y-%m-%d") - datetime.strptime(data, "%Y-%m-%d")).days
    except ValueError:
        return {}
    if atraso < 0 or atraso > 5:
        return {}
    campo = "ajuste_ant" if atraso == 0 else "ajuste"
    por_codigo = {str(c.get("s")): c for f in (d.get("familias") or []) for c in (f.get("contratos") or []) if isinstance(c, dict)}
    fora = {}
    for a, cod in codigos.items():
        v = _num((por_codigo.get(cod) or {}).get(campo))
        if v and v > 0:
            fora[a] = (v, data if atraso else "pregão anterior")
    return fora


def _relogio_brt(agora):
    """A hora de Brasilia na escala da fita do MetaTrader, que carimba a hora de parede como se fosse UTC."""
    return int(datetime(agora.year, agora.month, agora.day, agora.hour, agora.minute, agora.second, tzinfo=timezone.utc).timestamp())


def _historico_do_climax(lote, capital=None):
    """Frase da tela: o que o historico diz desta configuracao, levado ao lote de partida de hoje."""
    h = CLIMAX_PROVA
    return (f"No teste em {h['pregoes']:,} pregões de {h['de']} a {h['ate']}, que a calibração não viu, esta configuração acertou {h['acerto']}% ".replace(",", ".", 1)
            + f"e PERDEU cerca de R$ {abs(round(h['rs_por_negocio_e_contrato'] * lote + 1e-9))} por negócio com {lote} contratos, em todos os anos. "
            f"Só 2026 deu positivo (acerto de {h['acerto_2026']}%, cerca de R$ {round(h['rs_por_negocio_e_contrato_2026'] * lote)} por negócio): "
            f"de {h['configuracoes']} configurações testadas, nenhuma ganha de 2021 a 2025.")


def hora_da_fita(seg):
    """O MetaTrader carimba o negocio com a hora de Brasilia escrita como se fosse UTC."""
    return datetime.fromtimestamp(int(seg), timezone.utc).strftime("%H:%M:%S")


def ultimas_da_fita(fita, n=40):
    """As ultimas linhas da fita, da mais nova para a mais velha: [hora, preco, compra, venda, compra_grande, venda_grande]."""
    return [[hora_da_fita(x["seg"]), x["preco"], x["compra"], x["venda"], x["compra_grande"], x["venda_grande"]]
            for x in list(fita.linhas)[-n:][::-1]]


def perfil_por_preco(fita, segundos, centro, tick, ticks=20):
    """Volume por preco na janela, do preco mais alto para o mais baixo: [preco, compra, venda]. So ate `ticks` do centro."""
    if centro is None:
        return []
    fora = [[pr, v["compra"], v["venda"]] for pr, v in fita.por_preco(segundos).items() if abs(pr - centro) <= ticks * tick + 1e-9]
    return sorted(fora, key=lambda x: -x[0])


def spread_do_livro(livro, codigo):
    """Distancia entre a melhor venda e a melhor compra na foto do livro; None se a foto nao traz os dois lados."""
    lado = (livro or {}).get(codigo) or {}
    c, v = lado.get("compra") or [], lado.get("venda") or []
    if not c or not v or v[0][0] < c[0][0]:
        return None
    return v[0][0] - c[0][0]


def regras_niveis(p, climax_opera=QUEM_OPERA["climax_opera"], niveis_opera=QUEM_OPERA["niveis_opera"], dado_opera=QUEM_OPERA["dado_opera"]):
    c, x = NIVEIS, CLIMAX
    parar = [f"com {ef._rs(p.perda_maxima_dia_rs)} de perda no dia", f"depois de {p.perdas_para_parar} negócios perdedores",
             f"quando devolve {p.devolucao_para:.0%} do lucro que o dia já teve"]
    if p.meta_dia_rs:
        parar.append(f"ou ao ganhar {ef._rs(p.meta_dia_rs)} (a sua meta de 1%)")
    quem = ("Opera o climax de volume; o teste de nível é só medido." if climax_opera and not niveis_opera else
            "Opera o climax de volume e o teste de nível." if climax_opera else
            "Opera o teste de nível; o climax de volume é só medido." if niveis_opera else "As duas leituras estão só sendo medidas: o robô não entra.")
    d = DADO
    proprio = [
        "SETUP PRÓPRIO, REVERSÃO DO DADO AMERICANO" + ("" if dado_opera else " (só medido)") + ": às 9h30 (10h30 quando os Estados Unidos estão "
        f"fora do horário de verão) saem os dados americanos. Se nos {d['minutos']} primeiros minutos o mini-dólar andar mais de {ef._n(d['limiar'])} "
        f"pontos, o robô entra CONTRA esse movimento no minuto seguinte. Sem alvo e sem parcial: sai depois de {d['tempo_max']} minutos, ou no "
        f"stop de {ef._n(d['stop'])} pontos. Antes do dado as outras leituras não abrem posição: a vaga é deste setup.",
        "De onde veio: busca de 08/10/2026 em 5 anos de barras de 1 minuto (sete frentes, milhares de hipóteses). Foi a única regra que "
        "passou. Com 2 contratos: 2021 a 2024, 262 negócios, 59% de acerto, +R$ 116 por negócio; 2025, 45 negócios, +R$ 19; 2026, 32 "
        "negócios, +R$ 91. Positivo nos seis anos, mas nos dois últimos (os que a busca não viu) a média é +R$ 49 e ainda pode ser acaso. "
        "Dá 1 entrada a cada 3 a 6 pregões; cada negócio ganha ou perde perto de R$ 400 e o stop cheio custa R$ 815.",
    ]
    return proprio + [
        "Só mini-dólar, em simulação. " + quem + " Revisão de 08/10/2026: em 888 pregões o teste de nível perdeu o custo da operação "
        "(cerca de R$ 23 por negócio) e nenhum filtro testado mudou isso. O climax de volume ganhou em 2026, mas perdeu nos cinco anos "
        "anteriores: nenhuma das regras testadas ganha depois de custo. O robô opera para gerar operações e medir com a fita.",
        f"CLIMAX DE VOLUME (tape reading na barra): um minuto anda {ef._n(x['tranco'])} pontos ou mais, do abre ao fecha, com volume de "
        f"{ef._n(x['vol'])} vezes ou mais a média dos {x['janela']} minutos anteriores. É gente demais correndo para o mesmo lado: o preço "
        "tende a devolver parte do tranco. O robô entra CONTRA o tranco, na abertura do minuto seguinte.",
        f"Climax, saída: alvo quando o preço devolve {x['alvo_devolve']:.0%} do tranco; stop a {ef._n(x['stop_fixo'])} pontos da entrada; "
        f"se em {x['tempo_max']} minutos não fez nem um nem outro, sai a mercado. Perto de 1 entrada por manhã, e 3 a 4 em cada 10 "
        "manhãs sem nenhuma. " + _historico_do_climax(p.lote_base),
        f"Tranco entre {ef._n(x['medir_tranco'])} e {ef._n(x['tranco'])} pontos, ou volume entre {ef._n(x['medir_vol'])} e {ef._n(x['vol'])} vezes: "
        "o robô não entra, só guarda o sinal para medir (no histórico esses perdem o custo).",
        "TESTE DE NÍVEL (" + ("opera" if niveis_opera else "só medido, não opera") + "): níveis de ontem (ajuste, máxima, mínima, fechamento), "
        f"de hoje (abertura, máxima e mínima do dia formadas há {c['idade_extremo']} minutos ou mais), números redondos de {ef._n(c['redondo'])} em "
        f"{ef._n(c['redondo'])} pontos e as médias de {c['medias'][0]}, {c['medias'][1]} e {c['medias'][2]} do gráfico de {c['tempo_medias']} minutos. "
        f"Sinal: uma barra de {c['tempo']} minutos encosta no nível e fecha de volta, {ef._n(c['rejeita'])} ponto ou mais do lado de onde veio. "
        f"Stop de {ef._n(c['stop_min'])} a {ef._n(c['stop_max'])} pontos atrás da barra; alvo no nível seguinte, pagando {ef._n(c['rr_min'])} vezes o risco ou mais.",
        "MEDIÇÃO: todo sinal das duas leituras fica guardado, o dia inteiro, com o que a fita mostrava (quem agredia nos últimos 15 "
        "segundos, quanto bateram no nível, lotes de instituição). Com cerca de 100 sinais dá para saber se a fita separa a entrada boa "
        "da ruim; só então ela vira filtro.",
        f"Lote: {p.lote_base} contratos de mini-dólar; sobe {p.lote_por_degrau} a cada {ef._rs(p.colchao_por_degrau)} de lucro acumulado (até {p.lote_maximo}).",
        "Para " + ", ".join(parar) + ". O limite vale para o dia inteiro, mesmo que a regra mude no meio do pregão.",
        f"Entradas das {ef.ATIVOS['WDOFUT'].hora_inicio} às {p.hora_ultima_entrada}, menos de {p.pausa_dado[0]} a {p.pausa_dado[1]} (dado das 9h30) "
        f"e com o spread aberto. Às {p.hora_zerar} zera tudo.",
    ]


def regras_phicube(p):
    c = PHICUBE
    parar = [f"com {ef._rs(p.perda_maxima_dia_rs)} de perda no dia", f"depois de {p.perdas_para_parar} negócios perdedores",
             f"quando devolve {p.devolucao_para:.0%} do lucro que o dia já teve"]
    if p.meta_dia_rs:
        parar.append(f"ou ao ganhar {ef._rs(p.meta_dia_rs)} (a sua meta de 1%)")
    return [
        "Setup PhiCube, de Bo Williams, só no mini-dólar. As três médias do método (34, 144 e 610 períodos) são calculadas por uma "
        "reconstrução de terceiros: ele não publica a fórmula.",
        f"FILTRO, no gráfico de {c['maior']} minutos: o Prisma soma 1 se a média de 34 sobe, 2 se a de 144 sobe e 4 se a de 610 sobe. "
        "Com 6 ou 7 e o preço acima das três médias, só compra; com 0 ou 1 e o preço abaixo das três, só vende; o resto é consolidação "
        "e o robô fica de fora.",
        f"GATILHO, no gráfico de {c['menor']} minutos: a média de 34 vira a favor (deixa de cair e passa a subir, na compra) com as de 144 "
        "e de 610 já a favor. É o \"virou\" dele.",
        f"Stop: atrás do fundo (ou topo) das últimas {c['fundo']} barras de {c['menor']} minutos, entre {ef._n(c['stop_min'])} e "
        f"{ef._n(c['stop_max'])} pontos. Ele só diz \"stop curto, atrás do pivô\"; os limites são nossos.",
        f"Saída: metade com {ef._n(c['parcial_r'])} vez o risco, e o stop vai para o preço de entrada; o resto no alvo de "
        f"{ef._n(c['alvo_pts'])} pontos (o exemplo que ele dá no dólar; nas lives os alvos ficam entre 15 e 40).",
        f"Lote: {p.lote_base} contratos de mini-dólar; sobe {p.lote_por_degrau} a cada {ef._rs(p.colchao_por_degrau)} de lucro acumulado (até {p.lote_maximo}).",
        "Para " + ", ".join(parar) + ".",
        f"Entradas das {ef.ATIVOS['WDOFUT'].hora_inicio} às {p.hora_ultima_entrada}, menos de {p.pausa_dado[0]} a {p.pausa_dado[1]} (dado das 9h30) "
        f"e com o spread aberto. Às {p.hora_zerar} zera tudo.",
        "Ainda não entra: o indicador Santo (fórmula não publicada), as linhas verdes e vermelhas como alvo, o pivô com reteste "
        "que os instrutores usam nas lives, e a operação nas pontas de uma consolidação larga.",
    ]


def codigo_da_fonte(ativo, codigo_mini):
    """WDOX26 -> DOLX26: o contrato onde se le o fluxo tem o mesmo vencimento do mini."""
    fonte = ef.ATIVOS[ativo].fonte_fluxo
    return codigo_mini if not codigo_mini or codigo_mini.startswith(fonte) else fonte + codigo_mini[3:]


class RoboFluxo:
    def __init__(self, hoje, saidas=None, motor=MOTOR, pasta_mt5=fx.PASTA_MT5, setup="fluxo"):
        self.hoje = str(hoje)
        self.saidas = list(saidas or SAIDAS_PADRAO)
        self.motor = motor
        self.setup = setup                                       # "fluxo" (fita), "phicube" ou "niveis" (os dois de grafico)
        self.grafico = setup in SETUPS_DE_GRAFICO
        self.arq_serie = ARQ_SERIE if setup == "fluxo" else os.path.join(DIR_DT, f"serie_{setup}.json")
        self.p = ef.ParamFluxo()
        self.janela = chave.janela(self.hoje)                   # a janela do dia e do Douglas (pode ter excecao por data)
        self.p.hora_ultima_entrada, self.p.hora_zerar = self.janela["ultima_entrada"], self.janela["zerar"]
        self.pasta = os.path.join(DIR_DT, self.hoje)
        garantir_dir(self.pasta)
        self.arq_estado = os.path.join(self.pasta, f"estado_{setup}.json")
        salvo = ler_json(self.arq_estado, padrao=None) or {}
        self.estados = {}
        for a in ATIVOS:
            e = ef.EstadoF(a)
            s = (salvo.get("estados") or {}).get(a) or {}
            e.operacoes = int(s.get("operacoes") or 0)
            e.ultima_saida_ts = float(s.get("ultima_saida_ts") or 0.0)
            e.lado_dos_niveis = dict(s.get("lado_dos_niveis") or {})
            e.perdas = dict(s.get("perdas") or {})
            e.extremos = dict(s.get("extremos") or {})
            e.contras = dict(s.get("contras") or {})
            e.ultima_foi_perda = bool(s.get("ultima_foi_perda"))
            if isinstance(s.get("posicao"), dict):
                e.posicao = ef.PosicaoF(**s["posicao"])
            self.estados[a] = e
        self.operacoes = list(salvo.get("operacoes") or [])      # parciais e saidas, na ordem
        self.diario = list(salvo.get("diario") or [])
        self.curva = list(salvo.get("curva") or [])
        self.trava = salvo.get("trava")                          # None | "meta" | "perda" | "tres_perdas" | "devolucao"
        self.pico_realizado = float(salvo.get("pico_realizado") or 0.0)   # o maior lucro REALIZADO que o dia ja teve
        self.perdas = int(salvo.get("perdas") or 0)              # negocios (entrada ate a saida final) que perderam
        self.negocio = dict(salvo.get("negocio") or {})          # ativo -> resultado acumulado do negocio aberto
        self.pico, self.vale = float(salvo.get("pico") or 0.0), float(salvo.get("vale") or 0.0)
        self.desde = salvo.get("desde") or agora_brt().isoformat(timespec="seconds")
        self.marcos = set(salvo.get("marcos") or [])
        self.codigos = dict(salvo.get("codigos") or {})          # WINFUT -> WINV26
        self.ajustes = dict(salvo.get("ajustes") or {})
        self.leitor = fx.Leitor(pasta=pasta_mt5, dia=self.hoje.replace("-", ""))
        # duas fitas por contrato: a da FONTE do fluxo (no dolar, o contrato cheio, sem lote de robo) e a do mini
        self.fitas = {a: fx.Fita(a, es.CONTRATOS[a]["tick"], sem_lote_de_robo=ef.ATIVOS[a].sem_lote_de_robo) for a in ATIVOS}
        self.fitas_mini = {a: fx.Fita(a, es.CONTRATOS[a]["tick"]) for a in ATIVOS}
        self.fita_em = {}                                        # (ativo, "fonte" | "mini") -> relogio da ultima linha
        self.ultima_fita = 0.0                                   # relogio da ultima linha de fita recebida
        self.cot, self.feed, self.feed_em, self.livro = {}, {}, 0.0, {}
        self.feed_visto, self.feed_ruim, self.reconectou_em, self.reconexoes = 0.0, 0, 0.0, 0
        self.chave = chave.ler()                                 # liga/desliga do Douglas
        self.preparado = False                                   # ja leu contratos e ajuste nesta execucao?
        self.barras, self.sinais_pc, self.leitura_pc, self.ordem_pc, self.minuto_pc = {}, {}, {}, {}, None
        if self.grafico:
            for a in ATIVOS:
                self.barras[a] = br.Barras(a, DIR_DT, pasta_mt5)
                self.sinais_pc[a] = br.SinalNiveis(**NIVEIS) if setup == "niveis" else br.SinalPhiCube(eh.PhiCubeV1, **PHICUBE)
        modo = ler_json(ARQ_MODO, padrao=None) or {}
        try:                                                     # o lote de partida e do Douglas ("lote_base" em modo_robo.json)
            if modo.get("lote_base"):
                self.p.lote_base = max(1, min(int(modo["lote_base"]), self.p.lote_maximo))
        except (TypeError, ValueError):
            pass
        self.climax_opera = bool(modo.get("climax_opera", QUEM_OPERA["climax_opera"])) and setup == "niveis"
        self.dado_opera = bool(modo.get("dado_opera", QUEM_OPERA["dado_opera"])) and setup == "niveis"
        self.dado = {a: br.SinalDado(**DADO) for a in ATIVOS} if setup == "niveis" else {}
        self.leitura_dado, self.dado_pendente = {}, {}
        # regras do laboratorio que a rotina da noite registrou (quant/pesquisa/setups.json): rodam so no setup "niveis"
        self.labs, falhas = regras_lab.carregar() if setup == "niveis" else ([], [])
        for nome, motivo in falhas:
            log(f"regra de laboratorio {nome} nao carregou: {motivo}")
        self._sinais_hoje = (None, [])                           # (minuto, lista): refeita uma vez por minuto para a tela
        self.niveis_opera = bool(modo.get("niveis_opera", QUEM_OPERA["niveis_opera"]))
        self.climax = {a: br.SinalClimax(**CLIMAX) for a in ATIVOS} if setup == "niveis" else {}
        self.leitura_climax, self.climax_pendente = {}, {}
        self.outras = self._outras_regras_do_dia()               # o dia e um so: perdas e resultado das regras que ja rodaram hoje
        self.acumulado_antes = self._acumulado_antes()

    # ── persistencia ─────────────────────────────────────────
    def _acumulado_antes(self):
        serie = ler_json(self.arq_serie, padrao=None)
        return sum(float(x.get("resultado") or 0.0) for x in (serie if isinstance(serie, list) else [])
                   if isinstance(x, dict) and x.get("data") != self.hoje)

    def _outras_regras_do_dia(self):
        """Resultado e negocios perdedores de HOJE nas outras regras (o robo trocou de regra durante o dia). Em 08/10/2026
        a regra mudou quatro vezes e cada troca zerou a conta das tres perdas: o limite do dia tem de valer para o dia."""
        resultado, perdas = 0.0, 0
        for nome in ("estado.json", "estado_fluxo.json", "estado_phicube.json", "estado_niveis.json"):
            arq = os.path.join(self.pasta, nome)
            if os.path.abspath(arq) == os.path.abspath(self.arq_estado):
                continue
            negocios = {}
            for o in (ler_json(arq, padrao=None) or {}).get("operacoes") or []:
                try:
                    k = (o.get("ativo"), o.get("hora_entrada"))
                    negocios[k] = negocios.get(k, 0.0) + float(o.get("resultado") or 0.0)
                except (TypeError, ValueError):
                    continue
            resultado += sum(negocios.values())
            perdas += sum(1 for v in negocios.values() if v < 0)
        return {"resultado": round(resultado, 2), "perdas": perdas}

    def _salvar(self):
        est = {a: {"operacoes": e.operacoes, "ultima_saida_ts": e.ultima_saida_ts, "lado_dos_niveis": e.lado_dos_niveis,
                   "perdas": e.perdas, "extremos": e.extremos, "contras": e.contras, "ultima_foi_perda": e.ultima_foi_perda,
                   "posicao": asdict(e.posicao) if e.posicao else None} for a, e in self.estados.items()}
        gravar_atomico(self.arq_estado, json.dumps({
            "desde": self.desde, "estados": est, "operacoes": self.operacoes, "diario": self.diario[-DIARIO_MAX:],
            "curva": self.curva[-700:], "trava": self.trava, "perdas": self.perdas, "negocio": self.negocio,
            "pico": self.pico, "vale": self.vale, "pico_realizado": self.pico_realizado,
            "marcos": sorted(self.marcos), "codigos": self.codigos,
            "ajustes": self.ajustes}, ensure_ascii=False))

    def anotar(self, tipo, texto, agora=None):
        self.diario.append({"hora": (agora or agora_brt()).strftime("%H:%M:%S"), "tipo": tipo, "texto": texto})
        self.diario = self.diario[-DIARIO_MAX:]
        log(f"[{tipo}] {texto}")

    def marco(self, chave, tipo, texto, agora=None):
        if chave in self.marcos:
            return False
        self.marcos.add(chave)
        self.anotar(tipo, texto, agora)
        return True

    # ── fita, contratos e ajuste ─────────────────────────────
    def preparar(self):
        """Descobre o contrato vigente de cada futuro, pede a fita dele e le o ajuste de ontem."""
        for a in ATIVOS:
            if a not in self.codigos:
                s = ler_motor(f"/vivo/intradia?s={a}&dias=1", self.motor, timeout=8.0) or {}
                if s.get("codigo"):
                    self.codigos[a] = str(s["codigo"])
        if all(a in self.codigos for a in ATIVOS):
            try:                                         # a fita do mini e a do contrato onde se le o fluxo
                meus = {a: self.codigos[a] for a in ATIVOS}
                self.leitor.pedir(sorted(set(meus.values()) | {codigo_da_fonte(a, c) for a, c in meus.items()}))
            except OSError as e:
                log(f"nao consegui pedir a fita ao MetaTrader: {e}")
        meus = {a: c for a, c in self.codigos.items() if a in ATIVOS}
        oficiais = ajustes_oficiais(meus, self.hoje)           # ajuste de ontem: o oficial da B3, pelo terminal
        for a, (v, _data) in oficiais.items():
            self.ajustes[a] = v
        if len(oficiais) < len(meus):
            try:                                         # sem o oficial: coluna 12 da foto do MetaTrader, quando vem preenchida
                with open(os.path.join(self.leitor.pasta, "autopilot_feed.csv"), "r", encoding="latin-1", errors="ignore") as f:
                    for ln in f:
                        c = ln.strip().split(";")
                        for a, cod in meus.items():
                            if a not in oficiais and c and c[0] == cod and len(c) > 12 and (_num(c[12]) or 0) > 0:
                                self.ajustes[a] = _num(c[12])
            except OSError:
                pass

    def ler_fita(self):
        mini = {cod: a for a, cod in self.codigos.items() if a in ATIVOS}
        fonte = {codigo_da_fonte(a, cod): a for a, cod in self.codigos.items() if a in ATIVOS}
        n, agora = 0, time.time()
        for ln in self.leitor.novas_linhas():
            for de, fitas, tipo in ((fonte, self.fitas, "fonte"), (mini, self.fitas_mini, "mini")):
                a = de.get(ln["simbolo"])
                if a:
                    fitas[a].acrescentar(dict(ln, simbolo=a))
                    self.fita_em[(a, tipo)] = agora
                    n += 1
        if n:
            self.ultima_fita = agora
        relogio = max((f.ultimo_seg for f in list(self.fitas.values()) + list(self.fitas_mini.values())), default=0)
        for f in list(self.fitas.values()) + list(self.fitas_mini.values()):
            f.agora = relogio                              # o "agora" do pregao, pelo contrato que negociou por ultimo
        return n

    def fita_de(self, a):
        """A fita que a regra le agora e o nome dela. No dolar e a do contrato cheio; sem ela, a do mini."""
        agora = time.time()
        if agora - self.fita_em.get((a, "fonte"), 0.0) <= FITA_PARADA_S:
            return self.fitas[a], ef.ATIVOS[a].fonte_fluxo
        if agora - self.fita_em.get((a, "mini"), 0.0) <= FITA_PARADA_S:
            return self.fitas_mini[a], "mini"
        return self.fitas[a], None

    # ── contas ───────────────────────────────────────────────
    def resultado(self):
        realizado = sum(float(o["resultado"]) for o in self.operacoes)
        custos = sum(float(o["custos"]) for o in self.operacoes)
        aberto = 0.0
        for a, e in self.estados.items():
            c = self.cot.get(a)
            if e.posicao is not None and c:
                k = es.CONTRATOS[a]
                pts = ef._pontos(e.posicao, c["preco"])
                cst = 2 * k["custo"] * e.posicao.contratos
                aberto += pts * k["valor_ponto"] * e.posicao.contratos - cst
                custos += cst
        return realizado, aberto, custos

    def _frescor(self):
        if time.time() - self.feed_em < 6.0:
            return
        self.feed_em = time.time()
        s = ler_motor("/vivo/saude", self.motor, timeout=2.0)
        mt5 = next((f for f in ((s or {}).get("fontes") or []) if f.get("id") == "mt5"), None)
        self.feed = {} if not mt5 else {
            "sem_tique_s": _num((mt5.get("idade_s") or {}).get("menor")),
            "atraso_ms": _num((mt5.get("atraso_tique_acima_do_melhor_ms") or {}).get("p50")), "mt5": mt5.get("estado")}

    def _vigiar_feed(self, agora):
        """Cotacoes em rajadas por tres leituras seguidas da saude do motor: reabre o MetaTrader sozinho (conexao nova).
        So no pregao, so se o MetaTrader estiver aberto (fechado de proposito, nao reabre), com espera entre uma e outra."""
        hm = agora.strftime("%H:%M")
        if agora.weekday() >= 5 or not ("09:05" <= hm < "18:20") or self.feed_em == self.feed_visto:
            return False
        self.feed_visto = self.feed_em
        f = self.feed or {}
        ruim = (f.get("sem_tique_s") or 0) >= FEED_RUIM["sem_tique_s"] or (f.get("atraso_ms") or 0) >= FEED_RUIM["atraso_ms"]
        self.feed_ruim = self.feed_ruim + 1 if ruim else 0
        if self.feed_ruim < FEED_RUIM["leituras"] or time.time() - self.reconectou_em < FEED_RUIM["espera_s"] \
                or self.reconexoes >= FEED_RUIM["max_por_dia"] or not metatrader_aberto():
            return False
        self.feed_ruim, self.reconectou_em, self.reconexoes = 0, time.time(), self.reconexoes + 1
        self.anotar("feed", f"Cotações do MetaTrader em rajadas (último tique há {f.get('sem_tique_s') or 0:.0f} s, atraso típico de "
                    f"{(f.get('atraso_ms') or 0) / 1000:.0f} s). Reabrindo o MetaTrader sozinho ({self.reconexoes}ª vez hoje); "
                    "as cotações voltam em cerca de 40 segundos.", agora)
        threading.Thread(target=reabrir_metatrader, daemon=True).start()
        return True

    def _registrar(self, ev, agora):
        a, nome = ev["ativo"], es.CONTRATOS[ev["ativo"]]["nome"]
        if ev["tipo"] == "entrada":
            self.negocio[a] = 0.0
            m = ev.get("medidas") or {}
            try:                                             # cada entrada fica guardada com as medidas, para medir depois
                with open(os.path.join(self.pasta, "sinais.jsonl" if self.setup == "fluxo" else f"sinais_{self.setup}.jsonl"),
                          "a", encoding="utf-8") as f:
                    f.write(json.dumps(dict(ev, quando=agora.isoformat(timespec="seconds"), seg_fita=self.fitas_mini[a].ultimo_seg,
                                            contrato=self.codigos.get(a)), ensure_ascii=False) + "\n")
            except OSError:
                pass
            if ev.get("tecnica") == "reversão do dado":
                self.anotar("entrada", f"{nome}: {'COMPROU' if ev['lado'] == 'C' else 'VENDEU'} {ev['contratos']} a {_pontos(ev['entrada'], a)} "
                            f"contra a {ev['nome_nivel']} (setup próprio); stop {_pontos(ev['stop'], a)}, sem alvo: "
                            f"sai em {m.get('tempo_max_min')} minutos.", agora)
                return
            if ev.get("tecnica") == "climax de volume":
                self.anotar("entrada", f"{nome}: {'COMPROU' if ev['lado'] == 'C' else 'VENDEU'} {ev['contratos']} a {_pontos(ev['entrada'], a)} "
                            f"contra um {ev['nome_nivel']}; stop {_pontos(ev['stop'], a)}, alvo a {_pontos(m.get('alvo_pts') or 0, a)} pontos, "
                            f"sai em {m.get('tempo_max_min')} minutos se não andar.", agora)
                return
            if self.setup == "niveis":
                ft = m.get("fita") or {}
                if ft.get("confirmou") is None:
                    da_fita = "fita: sem leitura"
                else:
                    da_fita = (f"fita: {(ft.get('fracao_a_favor') or 0) * 100:.0f}% da agressão a favor em 15 s, "
                               + ("CONFIRMA" if ft["confirmou"] else "não confirma" + ("" if ft.get("amostra_basta") else " (pouco volume)")))
                self.anotar("entrada", f"{nome}: {'COMPROU' if ev['lado'] == 'C' else 'VENDEU'} {ev['contratos']} a {_pontos(ev['entrada'], a)} "
                            f"(teste de {ev['nome_nivel']} em {_pontos(ev['nivel'], a)}, rejeitado); stop {_pontos(ev['stop'], a)}, "
                            f"alvo a {_pontos(m.get('alvo_pts') or 0, a)} pontos; {da_fita}", agora)
                return
            if self.setup == "phicube":
                self.anotar("entrada", f"{nome}: {'COMPROU' if ev['lado'] == 'C' else 'VENDEU'} {ev['contratos']} a {_pontos(ev['entrada'], a)} "
                            f"(PhiCube: tendência de {m.get('tendencia')} em {m.get('maior_min')} minutos e virada em {m.get('menor_min')}); "
                            f"stop {_pontos(ev['stop'], a)}", agora)
                return
            self.anotar("entrada", f"{nome}: {'COMPROU' if ev['lado'] == 'C' else 'VENDEU'} {ev['contratos']} a {_pontos(ev['entrada'], a)} "
                        f"por {ev['tecnica']} em {ev['nome_nivel']} ({_pontos(ev['nivel'], a)}); stop {_pontos(ev['stop'], a)}; "
                        f"{(m.get('fracao_a_favor') or 0) * 100:.0f}% da agressão a favor", agora)
            return
        ev = dict(ev, n=len(self.operacoes) + 1)
        self.operacoes.append(ev)
        self.negocio[a] = float(self.negocio.get(a) or 0.0) + float(ev["resultado"])
        sinal = "+" if ev["pontos"] >= 0 else ""
        if ev["tipo"] == "parcial":
            self.anotar("parcial", f"{nome}: parcial de {ev['contratos']} a {_pontos(ev['saida'], a)} ({sinal}{_pontos(ev['pontos'], a)} pontos, "
                        f"{_reais(ev['resultado'])}); stop no preço de entrada.", agora)
            return
        total = self.negocio.pop(a, 0.0)
        if total < 0:
            self.perdas += 1
        self.anotar("saida", f"{nome}: saiu por {ev['motivo'].replace('_', ' ')} a {_pontos(ev['saida'], a)} ({sinal}{_pontos(ev['pontos'], a)} pontos); "
                    f"negócio fechou em {_reais(total)}.", agora)

    # ── um ciclo ─────────────────────────────────────────────
    def ciclo(self, agora=None, retrato=None):
        agora = agora or agora_brt()
        hora, ts = agora.strftime("%H:%M:%S"), agora.timestamp()
        if retrato is None:
            retrato = ler_motor("/vivo/retrato", self.motor)
        self._frescor()
        self._vigiar_feed(agora)
        pregao = agora.weekday() < 5 and ABERTURA <= hora[:5]
        if pregao and (not all(a in self.codigos for a in ATIVOS) or int(ts) % 60 == 0 or not self.preparado):
            self.preparar()
            self.preparado = True
        self.ler_fita()
        fita_ok = (time.time() - self.ultima_fita) <= FITA_PARADA_S if self.ultima_fita else False
        q = (retrato or {}).get("q") or {}
        lote = ef.lote_do_dia(self.acumulado_antes, self.p)
        self.chave = chave.ler()
        if not self.chave["ligado"]:                       # o Douglas desligou: zera o que houver e nao entra
            for a in ATIVOS:
                c = self.cot.get(a)
                ev = ef.zerar(self.estados[a], ts, hora, c["preco"], "desligado") if c else None
                if ev:
                    self._registrar(ev, agora)
        for a in ATIVOS:
            c = q.get(a)
            if not isinstance(c, list) or len(c) <= I_HORA:
                continue
            preco, ts_tique = _num(c[I_ULT]), _num(c[I_HORA])
            de_hoje = ts_tique is not None and datetime.fromtimestamp(ts_tique, agora.tzinfo).strftime("%Y-%m-%d") == self.hoje
            if preco is None or preco <= 0 or not de_hoje or not pregao:
                continue
            idade = ts - ts_tique
            spread = spread_do_livro(self.livro, self.codigos.get(a) or "")   # o motor nao traz compra e venda dos futuros
            fita, fonte = self.fita_de(a)
            self.cot[a] = {"preco": preco, "medio": _num(c[I_MEDIO]) if len(c) > I_MEDIO else None, "maxima": _num(c[I_MAX]),
                           "minima": _num(c[I_MIN]), "abertura": _num(c[I_ABE]), "anterior": _num(c[I_ANT]),
                           "var": _num(c[I_VAR]), "idade_s": idade, "ajuste": self.ajustes.get(a), "spread": spread,
                           "fonte_fluxo": fonte}
            if idade > 15.0:
                continue                                   # preco velho nao dispara nada
            base = self.ajustes.get(a) or self.cot[a]["anterior"]
            contexto = {"medio": self.cot[a]["medio"], "spread": spread, "fita_volume": self.fitas_mini[a],
                        "var": (preco / base - 1.0) if base and base > 0 else None}
            self.cot[a]["var_ajuste"] = contexto["var"]
            pode = self.trava is None and self.chave["ligado"] \
                and (self.perdas + self.outras["perdas"]) < self.p.perdas_para_parar      # o limite e do dia, nao da regra
            if self.grafico:
                contexto["sinal"] = self._sinal_phicube(a, agora)        # None na maior parte do tempo; a fita nao decide
            else:
                pode = pode and fonte is not None                        # leitura de fluxo sem fita nao entra
            for ev in ef.passo(self.estados[a], ts, hora, preco, fita, ef.niveis_do_dia(self.cot[a], self.p), self.p, lote,
                               pode_entrar=pode, feed_ok=True, contexto=contexto):
                self._registrar(ev, agora)
        realizado, aberto, _c = self.resultado()
        total = realizado + aberto
        motivo = None
        self.pico_realizado = max(self.pico_realizado, realizado)
        sem_posicao = all(e.posicao is None for e in self.estados.values())
        total_dia = total + self.outras["resultado"]             # o dia inteiro, com as regras que ja rodaram hoje
        perdas_dia = self.perdas + self.outras["perdas"]
        if self.trava is None:
            if total_dia <= -self.p.perda_maxima_dia_rs:
                self.trava, motivo = "perda", "perda_maxima"
            elif self.p.meta_dia_rs and total_dia >= self.p.meta_dia_rs:
                self.trava, motivo = "meta", "meta"
            elif perdas_dia >= self.p.perdas_para_parar and sem_posicao:
                self.trava = "tres_perdas"
                de_antes = f" ({self.outras['perdas']} deles em outra regra, mais cedo)" if self.outras["perdas"] else ""
                self.anotar("trava", f"{perdas_dia} negócios perdedores no dia{de_antes}: o robô não entra mais hoje.", agora)
            elif sem_posicao and self.pico_realizado >= self.p.devolucao_piso_rs \
                    and realizado <= self.pico_realizado * (1.0 - self.p.devolucao_para):
                self.trava = "devolucao"                         # dele: devolveu 20% do lucro do dia, para
                self.anotar("trava", f"O dia chegou a {_reais(self.pico_realizado)} e devolveu {self.p.devolucao_para:.0%} "
                            f"ou mais (está em {_reais(realizado)}): o robô não entra mais hoje.", agora)
        if motivo:
            for a in ATIVOS:
                c = self.cot.get(a)
                ev = ef.zerar(self.estados[a], ts, hora, c["preco"], motivo) if c else None
                if ev:
                    self._registrar(ev, agora)
            realizado, aberto, _c = self.resultado()
            total = realizado + aberto
            self.anotar("trava", ("Perda máxima do dia atingida" if self.trava == "perda" else "Meta do dia atingida")
                        + f": {_reais(total_dia)}"
                        + (f" (com {_reais(self.outras['resultado'])} das regras de mais cedo)" if self.outras["resultado"] else "")
                        + ". Tudo zerado; o robô não entra mais hoje.", agora)
        self.pico, self.vale = max(self.pico, total), min(self.vale, total)
        if pregao:
            if self.curva and self.curva[-1][0] == hora[:5]:
                self.curva[-1][1] = round(total, 2)
            else:
                self.curva.append([hora[:5], round(total, 2)])
        estado = self.estado(agora, retrato, realizado, aberto, fita_ok, lote, pregao)
        self._gravar(estado)
        self._salvar()
        return estado

    # ── setups de grafico: barras de 1 minuto e sinal ────────
    def _sinal_phicube(self, a, agora):
        """Uma vez por minuto fechado: traz os minutos de hoje, refaz a leitura e ve se ha ordem.
        A ordem vale so no ciclo em que nasce: se o robo nao puder entrar agora, ela se perde.

        O minuto que manda e o da FITA quando ela esta viva (ai a barra do minuto que fechou esta inteira, com maxima,
        minima e volume); so sem fita vale o relogio, com o fechamento que o motor da."""
        sinal_dado = self._sinal_dado(a, agora) if self.setup == "niveis" else None
        sinal_climax = self._sinal_climax(a, agora) if self.setup == "niveis" else None
        fita_viva = time.time() - self.fita_em.get((a, "mini"), 0.0) <= FITA_PARADA_S
        minuto = ("fita", self.fitas_mini[a].relogio() // 60) if fita_viva else ("relogio", int(agora.timestamp() // 60))
        sinal = None
        if self.minuto_pc != (a, minuto):
            self.minuto_pc = (a, minuto)
            serie = ler_motor(f"/vivo/intradia?s={a}&dias=1", self.motor, timeout=6.0) or {}
            try:
                b = self.barras[a]
                # o minuto inteiro vem da fita do mini; onde ela nao tem, o fechamento do motor. Os ultimos 15 minutos da
                # fita vao de novo: barra que entrou so com o fechamento e trocada pela inteira.
                de = None if b.ultimo_minuto is None else b.ultimo_minuto - br.pd.Timedelta(minutes=15)
                b.acrescentar(br.juntar_minutos(br.minutos_do_motor(serie, agora), br.minutos_da_fita(self.fitas_mini[a], de)))
                if self.setup == "niveis":
                    extras = [(self.ajustes[a], "ajuste de ontem")] if self.ajustes.get(a) else []
                    self.leitura_pc[a], ordem = self.sinais_pc[a].atualizar(b.df, extras)
                else:
                    self.leitura_pc[a], ordem = self.sinais_pc[a].atualizar(b.df)
            except Exception as e:                               # barra estragada nao derruba o robo: fica sem sinal e avisa
                self.leitura_pc[a], ordem = {"pronto": False, "motivo": f"erro nas barras: {type(e).__name__}: {e}"}, None
            if ordem is not None and self.setup == "niveis":
                fita = self.leitura_da_fita(a, ordem.lado, ordem.nivel)
                sinal = {"tecnica": "nível e reação", "lado": ordem.lado, "nivel": ordem.nivel, "nome_nivel": ordem.nome_nivel,
                         "stop_pts": ordem.stop_pts, "parcial_pts": ordem.parcial_pts, "alvo_pts": ordem.alvo_pts, "sem_arrasto": True,
                         "medidas": {"risco_pts": ordem.stop_pts, "alvo_pts": ordem.alvo_pts,
                                     "retorno_risco": round(ordem.alvo_pts / ordem.stop_pts, 2),
                                     "fracao_a_favor": fita.get("fracao_a_favor"), "fita": fita}}
                opera_nivel = self.niveis_opera and not self._perto_do_dado(agora)
                self._guardar_sinal(a, sinal, agora, opera=opera_nivel)
                if not opera_nivel:
                    sinal = None                                 # so medido: nao vira entrada
            if self.setup == "niveis" and sinal is None and a in self.barras:
                for sl in self.labs:                             # regras do laboratorio, na barra de 1 minuto que acabou de fechar
                    s_lab = sl.atualizar(self.barras[a].df)
                    if s_lab is None:
                        continue
                    opera_lab = sl.estado == "opera" and not self._perto_do_dado(agora)
                    s_lab["medidas"]["fita"] = self.leitura_da_fita(a, s_lab["lado"], s_lab["nivel"])
                    self._guardar_sinal(a, s_lab, agora, opera=opera_lab)
                    if opera_lab and sinal is None:
                        sinal = s_lab
            if ordem is not None and self.setup == "phicube":
                l = self.leitura_pc[a]
                sinal = {"tecnica": "phicube", "lado": ordem.lado, "nivel": l["medias_menor"][0],
                         "nome_nivel": f"média de {l['periodos'][0]} em {l['menor_min']} minutos (Prisma {l.get('prisma_maior', '?')})",
                         "stop_pts": ordem.stop_pts, "parcial_pts": ordem.parcial_pts, "alvo_pts": ordem.alvo_pts,
                         "sem_arrasto": ordem.arrasto_pts is None,
                         "medidas": {"tendencia": l["tendencia"], "maior_min": l["maior_min"], "menor_min": l["menor_min"],
                                     "medias_maior": l["medias_maior"], "medias_menor": l["medias_menor"],
                                     "risco_pts": ordem.stop_pts, "fracao_a_favor": None}}
        return sinal_dado or sinal_climax or sinal

    def _perto_do_dado(self, agora):
        """Da reserva antes do dado ate o minuto da entrada, a vaga e do setup proprio."""
        if not self.dado_opera:
            return False
        dado, _decide, entra = next(iter(self.dado.values())).horarios(agora.date())
        t = br.pd.Timestamp(agora.replace(tzinfo=None))
        return dado - br.pd.Timedelta(minutes=DADO_RESERVA_MIN) <= t < entra + br.pd.Timedelta(seconds=DADO_ESPERA_S)

    def _sinal_dado(self, a, agora):
        """Setup proprio: reversao da reacao ao dado americano. A ordem nasce no primeiro ciclo do minuto de entrada."""
        try:
            fita = self.fitas_mini[a]
            self.leitura_dado[a], ordem = self.dado[a].atualizar(fita)
            if ordem is None:
                pend = self.dado_pendente.get(a)
                if pend is None:
                    return None
                if self.estados[a].posicao is not None or agora.timestamp() > pend[1]:
                    self.dado_pendente.pop(a, None)
                    return None
                return pend[0]
            atraso = _relogio_brt(agora) - fita.relogio()
            medida = self.leitura_da_fita(a, ordem.lado, ordem.nivel)
            sinal = {"tecnica": "reversão do dado", "lado": ordem.lado, "nivel": ordem.nivel, "nome_nivel": ordem.nome_nivel,
                     "stop_pts": ordem.stop_pts, "parcial_pts": None, "alvo_pts": None, "sem_arrasto": True, "sem_parcial": True,
                     "ignora_pausa": True, "tempo_max_s": ordem.tempo_max * 60.0,
                     "medidas": dict(ordem.info, risco_pts=ordem.stop_pts, tempo_max_min=ordem.tempo_max, atraso_fita_s=atraso,
                                     fracao_a_favor=medida.get("fracao_a_favor"), fita=medida)}
            opera = bool(self.dado_opera and -5 <= atraso <= 12)
            self._guardar_sinal(a, sinal, agora, opera=opera)
            if not opera:
                return None
            self.dado_pendente[a] = (sinal, agora.timestamp() + DADO_ESPERA_S)
            return sinal
        except Exception as e:                                   # leitura que falha nao derruba o robo
            self.leitura_dado[a] = {"pronto": False, "motivo": f"erro na leitura do dado: {type(e).__name__}: {e}"}
            return None

    def _sinal_climax(self, a, agora):
        """Climax de volume, lido na fita do mini a cada ciclo; a ordem nasce no primeiro ciclo do minuto seguinte ao tranco."""
        try:
            fita = self.fitas_mini[a]
            self.leitura_climax[a], ordem = self.climax[a].atualizar(fita)
            if ordem is None:
                pend = self.climax_pendente.get(a)               # o sinal que nasceu ha pouco e ainda nao conseguiu entrar
                if pend is None:
                    return None
                if self.estados[a].posicao is not None or agora.timestamp() > pend[1]:
                    self.climax_pendente.pop(a, None)
                    return None
                return pend[0]
            atraso = _relogio_brt(agora) - fita.relogio()        # a fita esta em dia com o relogio? tranco velho nao serve
            medida = self.leitura_da_fita(a, ordem.lado, ordem.nivel)
            sinal = {"tecnica": "climax de volume", "lado": ordem.lado, "nivel": ordem.nivel, "nome_nivel": ordem.nome_nivel,
                     "stop_pts": ordem.stop_pts, "parcial_pts": ordem.parcial_pts, "alvo_pts": ordem.alvo_pts, "sem_arrasto": True,
                     "tempo_max_s": ordem.tempo_max * 60.0,
                     "medidas": dict(ordem.info, risco_pts=ordem.stop_pts, alvo_pts=round(ordem.alvo_pts, 2), tempo_max_min=ordem.tempo_max,
                                     atraso_fita_s=atraso, fracao_a_favor=medida.get("fracao_a_favor"), fita=medida)}
            em_dia = -5 <= atraso <= 12
            opera = bool(self.climax_opera and em_dia and ordem.info.get("opera", True) and not self._perto_do_dado(agora))
            self._guardar_sinal(a, sinal, agora, opera=opera, diario=bool(ordem.info.get("opera", True)))
            if not opera:
                return None
            self.climax_pendente[a] = (sinal, agora.timestamp() + CLIMAX_ESPERA_S)
            return sinal
        except Exception as e:                                   # leitura que falha nao derruba o robo
            self.leitura_climax[a] = {"pronto": False, "motivo": f"erro na leitura do climax: {type(e).__name__}: {e}"}
            return None

    def _guardar_sinal(self, a, sinal, agora, opera, diario=True):
        """Todo sinal fica guardado (operando ou so medindo), o dia inteiro, com o preco e a leitura da fita: e com
        isso que `medir` calcula depois o que cada entrada teria dado e se a fita separa as boas das ruins."""
        c = self.cot.get(a) or {}
        pr, tick = c.get("preco"), es.CONTRATOS[a]["tick"]
        entrada = None if pr is None else es.arredondar(pr + tick if sinal["lado"] == "C" else pr - tick, tick)
        try:
            with open(os.path.join(self.pasta, f"sinais_{self.setup}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"tipo": "sinal", "ativo": a, "tecnica": sinal["tecnica"], "lado": sinal["lado"], "entrada": entrada,
                                    "stop_pts": sinal["stop_pts"], "parcial_pts": sinal.get("parcial_pts"), "alvo_pts": sinal.get("alvo_pts"),
                                    "tempo_max_s": sinal.get("tempo_max_s"), "nivel": sinal["nivel"], "nome_nivel": sinal["nome_nivel"],
                                    "medidas": sinal.get("medidas"), "opera": bool(opera), "hora": agora.strftime("%H:%M:%S"),
                                    "quando": agora.isoformat(timespec="seconds"), "seg_fita": self.fitas_mini[a].ultimo_seg,
                                    "contrato": self.codigos.get(a)}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if not opera and diario and entrada is not None:
            ft = (sinal.get("medidas") or {}).get("fita") or {}
            fita = "sem leitura da fita" if ft.get("confirmou") is None else ("a fita confirma" if ft["confirmou"] else "a fita não confirma")
            self.anotar("medida", f"{es.CONTRATOS[a]['nome']}: só medindo, sem operar: {sinal['tecnica']} em {sinal['nome_nivel']} "
                        f"({_pontos(sinal['nivel'], a)}); {'compraria' if sinal['lado'] == 'C' else 'venderia'} a {_pontos(entrada, a)}; {fita}.", agora)

    def leitura_da_fita(self, a, lado, nivel):
        """O que a fita mostra no instante de uma entrada de grafico. E so MEDIDA, guardada com a operacao: serve para
        saber, depois de algumas semanas, se a entrada que a fita confirma rende mais que a que ela nao confirma.

        confirmou = nos ultimos 15 s (relogio do pregao) ha amostra que basta e 60% ou mais da agressao e a favor.
        No nivel: quanto bateram nele nos ultimos 15 minutos sem passar, quantas vezes foi testado e quantos lotes de
        instituicao (so no contrato cheio)."""
        try:
            mini, cheio = self.fitas_mini[a], self.fitas[a]
            viva = ef.fita_viva(mini, cheio)
            if not viva.linhas:
                return {"tem_fita": False, "confirmou": None}
            conf = ef.confirmacao(viva, self.p)
            favor = None if conf["fracao_compra"] is None else (conf["fracao_compra"] if lado == "C" else 1.0 - conf["fracao_compra"])
            min1 = viva.agressao(60)
            saldo60 = min1["saldo"] if lado == "C" else -min1["saldo"]
            cfg, tick = ef.ATIVOS[a], es.CONTRATOS[a]["tick"]
            zona, afasta = max(1, round(cfg.zona_pts / tick)), max(1, round(cfg.afasta_pts / tick))
            lado_nivel = "compra" if lado == "C" else "venda"
            nv = es.arredondar(nivel, tick)
            ab = viva.absorcao(nv, lado_nivel, self.p.janela_defesa_s, folga_ticks=zona, tolerancia_ticks=4)
            grandes = cheio.absorcao(nv, lado_nivel, self.p.janela_defesa_s, folga_ticks=zona, tolerancia_ticks=4)["rodadas_grandes"] \
                if cheio.linhas and cheio.separa_tamanho else None
            return {"tem_fita": True, "fonte": "mini" if viva is mini else ef.ATIVOS[a].fonte_fluxo,
                    "fracao_a_favor": None if favor is None else round(favor, 3), "volume_15s": conf["total"], "negocios_15s": conf["negocios"],
                    "tipico_15s": conf["tipico"], "amostra_basta": bool(conf["vale"]),
                    "confirmou": bool(conf["vale"] and favor is not None and favor >= self.p.fracao_confirma),
                    "saldo_a_favor_60s": saldo60, "batido_no_nivel_15min": ab["agredido"],
                    "testes_do_nivel": viva.testes(nv, lado_nivel, self.p.janela_defesa_s, zona_ticks=zona, afasta_ticks=afasta),
                    "lotes_de_instituicao_no_nivel": grandes}
        except Exception as e:                                   # medida que falha nao pode derrubar a entrada
            return {"tem_fita": False, "confirmou": None, "erro": f"{type(e).__name__}: {e}"}

    # ── o que a tela mostra alem do resultado ────────────────
    def leitura_dos_niveis(self, a, fita, preco):
        """Para cada nivel perto do preco: de que lado esta, quantos testes, quanto bateram nele e quanto a regra pede."""
        cfg, tick, p = ef.ATIVOS[a], es.CONTRATOS[a]["tick"], self.p
        tipico = fita.volume_tipico(p.janela_tipico_s) if fita.linhas else None
        zona, afasta = max(1, round(cfg.zona_pts / tick)), max(1, round(cfg.afasta_pts / tick))
        e, fora = self.estados[a], {}
        for nome, nivel in ef.niveis_do_dia(self.cot.get(a) or {}, p):
            nivel_t = es.arredondar(nivel, tick)
            if preco is None or abs(preco - nivel_t) > 3 * cfg.perseguir_pts + 1e-9 or not fita.linhas:
                continue
            lado = "compra" if preco >= nivel_t else "venda"
            ab = fita.absorcao(nivel_t, lado, p.janela_defesa_s, folga_ticks=zona, tolerancia_ticks=1)
            perda = e.perdas.get(nome)
            fora[nome] = {"papel": "suporte" if lado == "compra" else "resistência",
                          "testes": fita.testes(nivel_t, lado, p.janela_defesa_s, zona_ticks=zona, afasta_ticks=afasta),
                          "testes_min": p.testes_min, "testes_max": p.testes_max,
                          "agredido": ab["agredido"], "precisa": (p.mult_defesa * tipico) if tipico else None,
                          "lotes_grandes": ab["rodadas_grandes"], "lotes_grandes_min": p.rodadas_grandes_min if fita.separa_tamanho else None,
                          "furou": ab["furou"], "perdido": bool(perda), "retestou": bool(perda and perda.get("retestou"))}
        return fora

    def o_que_espera(self, a, leitura, agora, fonte):
        """Em frases curtas: por que o robo nao esta entrando agora, ou o que falta no nivel mais perto."""
        cfg, p, e, c = ef.ATIVOS[a], self.p, self.estados[a], self.cot.get(a) or {}
        hm, pr = agora.strftime("%H:%M"), c.get("preco")
        if e.posicao is not None:
            return ["Com posição aberta: conduzindo pelo stop, pela parcial e pelo alvo." if self.grafico
                    else "Com posição aberta: conduzindo pelo stop, pela parcial e pelo stop móvel."]
        if self.setup == "niveis":
            return self._espera_niveis(a, agora)
        if self.setup == "phicube":
            return self._espera_phicube(a, agora)
        if not self.chave["ligado"]:
            return ["Desligado por você: não entra."]
        if self.trava:
            return ["Parado até amanhã: o limite do dia foi atingido."]
        if fonte is None:
            return ["Sem a fita de negócios: sem fluxo o robô não entra."]
        if hm < cfg.hora_inicio:
            return [f"Antes do horário deste contrato: entra a partir das {cfg.hora_inicio}."]
        if hm >= p.hora_ultima_entrada:
            return [f"Sem novas entradas desde as {p.hora_ultima_entrada}."]
        if p.pausa_dado and p.pausa_dado[0] <= hm < p.pausa_dado[1]:
            return [f"Pausa do dado das 9h30: volta às {p.pausa_dado[1]}."]
        frases = []
        espera = p.espera_apos_perda_s if e.ultima_foi_perda else p.espera_apos_saida_s
        falta = espera - (agora.timestamp() - e.ultima_saida_ts)
        if e.ultima_saida_ts and falta > 0:
            frases.append(f"Respirando depois da última saída: mais {int(falta)} s.")
        if c.get("spread") is not None and c["spread"] >= cfg.spread_max_pts - 1e-9:
            frases.append(f"Spread aberto ({_pontos(c['spread'], a)} pontos): falta volume, não entra.")
        if not leitura:
            frases.append("Nenhum nível perto do preço. Esperando o preço chegar a um nível ou uma corrida esticada.")
            return frases
        nome, l = min(leitura.items(), key=lambda kv: abs((pr or 0) - es.arredondar(dict(ef.niveis_do_dia(c, p))[kv[0]], es.CONTRATOS[a]["tick"])))
        if l["perdido"]:
            frases.append(f"{nome.capitalize()} foi perdido: esperando o preço voltar ao nível e falhar"
                          + (" (já voltou; falta sair de novo com agressão a favor)." if l["retestou"] else "."))
            return frases
        partes = [f"testes {l['testes']} de {l['testes_min']}"]
        if l["precisa"]:
            partes.append(f"volume batido no nível {l['agredido']:.0f} de {l['precisa']:.0f}")
        if l["lotes_grandes_min"]:
            partes.append(f"lotes de instituição {l['lotes_grandes']} de {l['lotes_grandes_min']}")
        frases.append(f"Mais perto: {nome} como {l['papel']}. " + "; ".join(partes) + "."
                      + (" O nível foi furado nos últimos 15 minutos." if l["furou"] else "")
                      + (" Testado demais: o robô só opera a perda dele." if l["testes"] > l["testes_max"] else ""))
        return frases

    def _espera_niveis(self, a, agora):
        cfg, p, e, c = ef.ATIVOS[a], self.p, self.estados[a], self.cot.get(a) or {}
        hm, l, pr = agora.strftime("%H:%M"), self.leitura_pc.get(a) or {}, c.get("preco")
        if not self.chave["ligado"]:
            return ["Desligado por você: não entra."]
        if self.trava:
            return ["Parado até amanhã: o limite do dia foi atingido."]
        if not l.get("pronto"):
            return ["Ainda sem leitura do gráfico: " + str(l.get("motivo") or "esperando o primeiro minuto fechar") + "."]
        frases = []
        if hm < cfg.hora_inicio:
            frases.append(f"Antes do horário: entra a partir das {cfg.hora_inicio}.")
        elif hm >= p.hora_ultima_entrada:
            frases.append(f"Sem novas entradas desde as {p.hora_ultima_entrada}.")
        elif p.pausa_dado and p.pausa_dado[0] <= hm < p.pausa_dado[1]:
            frases.append(f"Pausa do dado das 9h30: volta às {p.pausa_dado[1]}.")
        espera = p.espera_apos_perda_s if e.ultima_foi_perda else p.espera_apos_saida_s
        falta = espera - (agora.timestamp() - e.ultima_saida_ts)
        if e.ultima_saida_ts and falta > 0:
            frases.append(f"Respirando depois da última saída: mais {int(falta)} s.")
        if c.get("spread") is not None and c["spread"] >= cfg.spread_max_pts - 1e-9:
            frases.append(f"Spread aberto ({_pontos(c['spread'], a)} pontos): não entra.")
        if self.outras["perdas"] or self.outras["resultado"]:
            frases.append(f"Hoje, em outra regra mais cedo: {_reais(self.outras['resultado'])} e {self.outras['perdas']} negócio(s) perdedor(es); "
                          "contam para o limite do dia.")
        ld = self.leitura_dado.get(a) or {}
        if ld.get("pronto") and self.dado_opera:
            if not ld["decidido"]:
                frases.append(f"Setup do dado americano: hoje o dado sai às {ld['hora_dado']}. Se o mini-dólar andar mais de {_pontos(ld['limiar'], a)} "
                              f"pontos nos {ld['minutos']} primeiros minutos, o robô entra contra às {ld['entra_as']} e segura por até "
                              f"{ld['tempo_max']} minutos (stop de {_pontos(ld['stop'], a)} pontos).")
            elif ld.get("movimento") is not None:
                frases.append(f"Setup do dado americano: o mini-dólar andou {_pontos(ld['movimento'], a)} pontos na reação ao dado das {ld['hora_dado']} "
                              + ("(passou do limite: entrada contra)." if abs(ld["movimento"]) > ld["limiar"]
                                 else f"(pede mais de {_pontos(ld['limiar'], a)}): sem entrada hoje."))
        lc = self.leitura_climax.get(a) or {}
        if lc.get("pronto"):
            frases.append(f"Climax de volume{'' if self.climax_opera else ' (só medindo)'}: o minuto das {lc['minuto']} andou "
                          f"{_pontos(abs(lc['tranco']), a)} pontos com volume de {lc['volume_x']:.1f} vezes a média; "
                          f"entra contra o tranco com {_pontos(lc['pede_tranco'], a)} pontos e {lc['pede_volume_x']:g} vezes ou mais.")
        else:
            frases.append("Climax de volume: " + str(lc.get("motivo") or "esperando a fita") + ".")
        nomes = {n["preco"]: n["nome"] for n in l["niveis"]}
        partes = []
        for chave_, lado in (("acima", "vende"), ("abaixo", "compra")):
            v = l.get(chave_)
            if v is not None and pr is not None:
                partes.append(f"{nomes.get(v, 'nível')} em {_pontos(v, a)} ({'a' if chave_ == 'acima' else 'a'} {_pontos(abs(v - pr), a)} pontos {chave_}: "
                              f"se o preço encostar e for rejeitado, {lado})")
        frases.append((f"Esperando o preço testar um nível e voltar, no gráfico de {l['tempo_min']} minutos. Mais perto: " if self.niveis_opera
                       else f"Teste de nível (só medindo, gráfico de {l['tempo_min']} minutos). Mais perto: ") + "; ".join(partes) + ".")
        return frases

    def _espera_phicube(self, a, agora):
        cfg, p, e, c = ef.ATIVOS[a], self.p, self.estados[a], self.cot.get(a) or {}
        hm, l = agora.strftime("%H:%M"), self.leitura_pc.get(a) or {}
        if not self.chave["ligado"]:
            return ["Desligado por você: não entra."]
        if self.trava:
            return ["Parado até amanhã: o limite do dia foi atingido."]
        if not l.get("pronto"):
            return ["Ainda sem leitura do gráfico: " + str(l.get("motivo") or "esperando o primeiro minuto fechar") + "."]
        frases = []
        if hm < cfg.hora_inicio:
            frases.append(f"Antes do horário: entra a partir das {cfg.hora_inicio}.")
        elif hm >= p.hora_ultima_entrada:
            frases.append(f"Sem novas entradas desde as {p.hora_ultima_entrada}.")
        elif p.pausa_dado and p.pausa_dado[0] <= hm < p.pausa_dado[1]:
            frases.append(f"Pausa do dado das 9h30: volta às {p.pausa_dado[1]}.")
        m = l["medias_maior"]
        if l["tendencia"] == "consolidação":
            frases.append(f"Gráfico de {l['maior_min']} minutos em consolidação"
                          + (f" (Prisma {l['prisma_maior']}, de 0 a 7)" if l.get("prisma_maior") is not None else " (preço ou médias fora de ordem)")
                          + ": pelo método, fica de fora.")
        else:
            lado = "compra" if l["tendencia"] == "alta" else "venda"
            vira = "para cima" if l["tendencia"] == "alta" else "para baixo"
            agora_menor = (f"a média de 34 está {l['lado_menor']}" if l.get("versao") == 1
                           else f"o preço está {l['lado_menor']} da média de {l['periodos'][0]}")
            frases.append(f"Gráfico de {l['maior_min']} minutos em tendência de {l['tendencia']}: só {lado}. Esperando o de "
                          f"{l['menor_min']} minutos virar {vira} (agora {agora_menor}).")
        frases.append(f"Médias de {l['maior_min']} minutos: {l['periodos'][0]} em {_pontos(m[0], a)}, {l['periodos'][1]} em {_pontos(m[1], a)}, "
                      f"{l['periodos'][2]} em {_pontos(m[2], a)}.")
        return frases

    # ── o estado que a tela le ───────────────────────────────
    def estado(self, agora, retrato, realizado, aberto, fita_ok, lote, pregao):
        p, hm = self.p, agora.strftime("%H:%M")
        inicio = min((ef.ATIVOS[a].hora_inicio for a in ATIVOS), default="09:15")
        total = realizado + aberto
        _r, _a, custos = self.resultado()
        parado, atraso = _num(self.feed.get("sem_tique_s")), _num(self.feed.get("atraso_ms"))
        em_hora = pregao and hm < p.hora_zerar
        feed_ruim = em_hora and ((parado is not None and parado > 15) or (atraso is not None and atraso > 5000))
        abertas = sum(1 for e in self.estados.values() if e.posicao is not None)
        if agora.weekday() >= 5 or hm < ABERTURA:
            fase, texto = "aguardando_abertura", "Aguardando a abertura dos futuros (9h00)."
        elif not self.chave["ligado"]:
            fase = "desligado"
            texto = (f"Robô DESLIGADO por você às {chave.hora_de(self.chave)}. Nada aberto, nenhuma entrada. "
                     f"Resultado do dia: {_reais(total)}. Para religar: ícone \"Robô - ligar\" na Mesa, ou peça \"ligue o robô\".")
        elif self.trava == "meta":
            fase, texto = "meta_batida", f"Meta do dia atingida ({_reais(total)}). Parado até amanhã."
        elif self.trava == "devolucao":
            fase = "meta_batida"
            texto = (f"O dia chegou a {_reais(self.pico_realizado)} e devolveu {p.devolucao_para:.0%} do lucro "
                     f"(está em {_reais(total)}). Parado até amanhã.")
        elif self.trava in ("perda", "tres_perdas"):
            fase = "perda_maxima"
            texto = (f"Perda máxima do dia atingida ({_reais(total)}). Parado até amanhã." if self.trava == "perda"
                     else f"{self.perdas + self.outras['perdas']} negócios perdedores no dia ({_reais(total + self.outras['resultado'])}"
                          + (", somando as regras de mais cedo" if self.outras["perdas"] else "") + "). Parado até amanhã.")
        elif hm < inicio:
            fase, texto = "formando_faixa", (f"Lendo o gráfico da abertura; entradas a partir das {inicio}." if self.grafico
                                             else f"Lendo o fluxo da abertura; entradas a partir das {inicio}.")
        elif hm >= p.hora_zerar:
            fase, texto = "encerrado", f"Operações encerradas ({p.hora_zerar}). Resultado do dia: {_reais(total)}."
        elif hm >= p.hora_ultima_entrada:
            fase, texto = "encerrando", f"Sem novas entradas desde as {p.hora_ultima_entrada}; {abertas} posição(ões) aberta(s) até as {p.hora_zerar}."
        else:
            fase = "operando"
            texto = ((("Lendo a fita (climax de volume) e medindo os níveis: " if self.climax_opera and not self.niveis_opera
                       else "Lendo o gráfico (níveis): ") if self.setup == "niveis" else "Lendo o gráfico (PhiCube): " if self.grafico else "Lendo o fluxo: ")
                     + f"{abertas} posição(ões) aberta(s), {len(self.operacoes)} saída(s) e parcial(is), resultado do dia {_reais(total)}.")
        if self.setup == "niveis":
            avisos = ["Simulação: nenhuma ordem é enviada à corretora.",
                      "Revisão de 08/10/2026: o teste de nível perdeu cerca de R$ 23 por negócio em 888 pregões (2023 a 2026), e nenhum "
                      "filtro testado (de onde o preço veio, hora, tipo de nível, lado das médias, insistir no mesmo lado) mudou isso. "
                      + ("Por isso ele deixou de operar e passou a ser só medido, com a leitura da fita em cada sinal."
                         if not self.niveis_opera else "Ele segue operando por escolha sua."),
                      "Quem opera é o climax de volume: tranco de 1 minuto de 5 pontos ou mais com volume de 3 vezes a média ou mais, "
                      "entrada contra o tranco. ATENÇÃO: a calibração de 08/10/2026 NÃO se confirmou. " + _historico_do_climax(p.lote_base)
                      + " Está no ar para gerar operações e medir com a leitura da fita, não porque ganha. Não é para dinheiro real.",
                      "Custos da B3 estimados e 1 tick contra nas ordens a mercado; imposto de day trade (20%) não descontado."]
        elif self.setup == "phicube":
            avisos = ["Simulação: nenhuma ordem é enviada à corretora.",
                      "Setup PhiCube, de Bo Williams: o Prisma no gráfico de 15 minutos diz o lado, a virada da média de 34 no de 4 minutos "
                      "é o gatilho, e em consolidação o robô fica de fora. É seletivo: no histórico deu 1 entrada a cada 5 pregões nesta janela.",
                      "ATENÇÃO: no teste histórico (mini-dólar, cerca de 100 pregões de 2026, das 9h15 às 13h) esta versão PERDEU dinheiro "
                      "depois de custos: 19 negócios, R$ 13 de perda média por negócio; antes de custos, ficou perto de zero. A amostra é "
                      "pequena. Está no ar a pedido, para acompanhar.",
                      "Custos da B3 estimados e 1 tick contra nas ordens a mercado; imposto de day trade (20%) não descontado."]
        else:
            avisos = ["Simulação: nenhuma ordem é enviada à corretora.",
                      "Regra tirada do que Alison Correia ensina e faz no canal dele, sem a parte que depende de saber qual corretora está "
                      "de cada lado (o MetaTrader não informa). Os limiares de \"muita agressão\" são nossos, ainda sem teste histórico.",
                      *(["Mini-índice: adaptação nossa. Ele opera a sala de dólar; do índice mostra pouco."] if "WINFUT" in ATIVOS else []),
                      "Custos da B3 estimados e 1 tick contra nas ordens a mercado; imposto de day trade (20%) não descontado."]
        sem_cheio = [es.CONTRATOS[a]["nome"] for a in ATIVOS if (self.cot.get(a) or {}).get("fonte_fluxo") == "mini"
                     and ef.ATIVOS[a].fonte_fluxo != self.codigos.get(a, "")[:3]]
        sem_ajuste = [es.CONTRATOS[a]["nome"] for a in ATIVOS if a in self.cot and not self.ajustes.get(a)]
        if em_hora and sem_ajuste:
            avisos.insert(1, "Sem o ajuste oficial de ontem (" + ", ".join(sem_ajuste) + "): o nível do ajuste ficou de fora e a "
                          "variação do dia usa o último negócio de ontem.")
        if em_hora and sem_cheio:
            avisos.insert(1, "Fluxo lido no mini (" + ", ".join(sem_cheio) + "): a fita do contrato cheio não está chegando. "
                          "Ele lê no cheio; no mini os lotes de robô entram na conta.")
        if em_hora and not fita_ok and not self.grafico:
            alerta = ("ATENÇÃO: sem a fita de negócios do MetaTrader (robô 1.3 desligado ou parado). "
                      "Sem fluxo o robô não entra; posição aberta segue com o stop.")
            avisos.insert(0, alerta)
            texto = alerta + " " + texto
        elif feed_ruim:
            alerta = "ATENÇÃO: cotações da B3 atrasadas ou paradas (MetaTrader). Com preço velho o robô não entra nem sai."
            avisos.insert(0, alerta)
            texto = alerta + " " + texto
        instrumentos, ops, posicoes = [], [dict(o, aberta=False) for o in self.operacoes], []
        for a in ATIVOS:
            e, c, k = self.estados[a], self.cot.get(a) or {}, es.CONTRATOS[a]
            f, fonte = self.fita_de(a)
            pr = c.get("preco")
            pos = None
            if e.posicao is not None:
                pts = ef._pontos(e.posicao, pr) if pr is not None else None
                ab = (pts * k["valor_ponto"] * e.posicao.contratos - 2 * k["custo"] * e.posicao.contratos) if pts is not None else None
                cfg = ef.ATIVOS[a]
                sinal_lado = 1.0 if e.posicao.lado == "C" else -1.0
                parcial_pts = e.posicao.parcial_pts if e.posicao.parcial_pts is not None else cfg.parcial_pts
                parcial_em = None if e.posicao.parcial_feita or e.posicao.sem_parcial else e.posicao.entrada + sinal_lado * parcial_pts
                do_alvo = f" Alvo em {_pontos(e.posicao.alvo, a)}." if e.posicao.alvo is not None else ""
                if e.posicao.sem_parcial:
                    falta = None if not e.posicao.tempo_max_s or not e.posicao.ts_entrada else e.posicao.tempo_max_s - (agora.timestamp() - e.posicao.ts_entrada)
                    passo_txt = ("Sem alvo e sem parcial: segura até o stop"
                                 + (f" ou até o tempo acabar (faltam {max(0, int(falta // 60))} minutos)." if falta is not None else ".") + do_alvo)
                elif e.posicao.parcial_feita and e.posicao.sem_arrasto:
                    passo_txt = f"Parcial feita. Stop no preço de entrada ({_pontos(e.posicao.stop, a)}); o resto espera o alvo." + do_alvo
                elif e.posicao.parcial_feita:
                    passo_txt = f"Parcial feita. Stop em {_pontos(e.posicao.stop, a)}, andando {_pontos(cfg.arrasto_pts, a)} pontos atrás do melhor preço."
                else:
                    passo_txt = (f"Parcial de metade em {_pontos(parcial_em, a)}"
                                 + (f" (faltam {_pontos(abs(parcial_em - pr), a)} pontos)" if pr is not None else "")
                                 + "; depois o stop vai para o preço de entrada." + do_alvo)
                pos = dict(asdict(e.posicao), pontos=pts, aberto=ab, risco_pts=abs(e.posicao.entrada - e.posicao.stop),
                           protegido=e.posicao.parcial_feita, parcial_em=parcial_em,
                           ha_s=max(0, int(agora.timestamp() - e.posicao.ts_entrada)) if e.posicao.ts_entrada else None,
                           stop_distancia_pts=abs(pr - e.posicao.stop) if pr is not None else None,
                           risco_rs=abs(e.posicao.entrada - e.posicao.stop) * k["valor_ponto"] * e.posicao.contratos,
                           proximo_passo=passo_txt)
                posicoes.append(dict(pos, ativo=a, nome=k["nome"], contrato=self.codigos.get(a), ultimo=pr))
                ops.append({"n": len(ops) + 1, "ativo": a, "lado": e.posicao.lado, "contratos": e.posicao.contratos,
                            "entrada": e.posicao.entrada, "hora_entrada": e.posicao.hora, "saida": None, "hora_saida": None,
                            "motivo": None, "stop": e.posicao.stop, "alvo": e.posicao.alvo, "pontos": pts,
                            "custos": 2 * k["custo"] * e.posicao.contratos, "resultado": ab, "aberta": True,
                            "tecnica": e.posicao.tecnica, "nome_nivel": e.posicao.nome_nivel})
            a15, a60 = f.agressao(15), f.agressao(60)
            leitura = self.leitura_dos_niveis(a, f, pr)
            niveis = [{"nome": n, "preco": v, "distancia_pts": (pr - v) if pr is not None else None, "leitura": leitura.get(n)}
                      for n, v in ef.niveis_do_dia(c, p)]
            lg = self.leitura_pc.get(a) or {}
            if self.setup == "niveis" and lg.get("pronto"):
                niveis = [{"nome": n["nome"], "preco": n["preco"], "distancia_pts": (pr - n["preco"]) if pr is not None else None, "leitura": None}
                          for n in sorted(lg["niveis"], key=lambda x: -x["preco"])]
            mini = self.fitas_mini[a]
            dia = f.agressao(fx.JANELA_MAXIMA_S)
            corr = f.corrida(p.janela_esticada_s) if f.linhas else None
            cod_fonte = codigo_da_fonte(a, self.codigos.get(a) or "")
            livro = (self.livro or {}).get(cod_fonte if fonte not in (None, "mini") else (self.codigos.get(a) or ""), {})
            fechadas = [o for o in self.operacoes if o["ativo"] == a]
            instrumentos.append({
                "ativo": a, "nome": k["nome"], "contrato": self.codigos.get(a), "valor_ponto": k["valor_ponto"], "tick": k["tick"],
                "ultimo": pr, "variacao_pct": c.get("var"), "medio_dia": c.get("medio"), "maxima": c.get("maxima"),
                "minima": c.get("minima"), "abertura": c.get("abertura"), "anterior": c.get("anterior"), "ajuste": c.get("ajuste"),
                "idade_s": c.get("idade_s"),
                "lado_do_medio": (None if pr is None or not c.get("medio") else ("acima" if pr > c["medio"] else "abaixo")),
                "faixa_abertura": None, "gatilho_compra": None, "gatilho_venda": None,
                "risco_pts_agora": ef.ATIVOS[a].stop_teto_rapido_pts if ef.dia_rapido(a, f) else ef.ATIVOS[a].stop_teto_pts,
                "spread_pts": c.get("spread"),
                "niveis": niveis,
                "espera": self.o_que_espera(a, leitura, agora, fonte),
                "phicube": self.leitura_pc.get(a) if self.setup == "phicube" else None,
                "grafico": self.leitura_pc.get(a) if self.setup == "niveis" else None,
                "climax": self.leitura_climax.get(a) if self.setup == "niveis" else None,
                "dado": self.leitura_dado.get(a) if self.setup == "niveis" else None,
                "variacao_ajuste": c.get("var_ajuste"),
                "corrida": None if not corr else {"alta_pts": corr["alta"]["tamanho"], "topo": corr["alta"]["extremo"],
                                                  "baixa_pts": corr["baixa"]["tamanho"], "fundo": corr["baixa"]["extremo"],
                                                  "minutos": p.janela_esticada_s // 60, "esticada_pts": ef.ATIVOS[a].esticada_pts},
                "fluxo": {"fonte": fonte, "contrato_fonte": cod_fonte if fonte not in (None, "mini") else self.codigos.get(a),
                          "sem_lote_de_robo": bool(f.sem_lote_de_robo and f.separa_tamanho), "dia_rapido": ef.dia_rapido(a, f),
                          "vai_e_vem_1min": f.amplitude_tipica(60),
                          "agressao_15s": a15, "agressao_60s": a60, "tipico_30s": f.volume_tipico(p.janela_tipico_s),
                          "tipico_15s": f.volume_tipico(15), "tipico_60s": f.volume_tipico(60),
                          "linhas": len(f.linhas),
                          "saldo_dia": {"compra": dia["compra"], "venda": dia["venda"], "saldo": dia["saldo"],
                                        "desde": hora_da_fita(f.linhas[0]["seg"]) if f.linhas else None},
                          "fita": ultimas_da_fita(f), "fita_mini": ultimas_da_fita(mini) if fonte not in (None, "mini") and mini is not f else [],
                          "perfil": perfil_por_preco(mini if mini.linhas else f, p.janela_defesa_s, pr, k["tick"]),
                          "perfil_minutos": p.janela_defesa_s // 60,
                          "livro_compra": (livro.get("compra") or [])[:10], "livro_venda": (livro.get("venda") or [])[:10]},
                "posicao": pos, "operacoes_hoje": e.operacoes, "restam": max(p.max_operacoes - e.operacoes, 0),
                "resultado": sum(float(o["resultado"]) for o in fechadas) + ((pos or {}).get("aberto") or 0.0)})
        finais = [o for o in self.operacoes if o["tipo"] == "saida"]
        ganhos = [o for o in self.operacoes if o["resultado"] > 0]
        perdas = [o for o in self.operacoes if o["resultado"] <= 0]
        serie = self._serie(total, len(finais), pregao)
        acumulado = sum(float(x.get("resultado") or 0.0) for x in serie)
        return {
            "v": 2, "tipo": "daytrade", "regra": self.setup, "gerado": agora.isoformat(timespec="seconds"),
            "vivo": {"ligado": True, "fase": fase, "fase_texto": texto, "desde": self.desde,
                     "batida": agora.isoformat(timespec="seconds"), "intervalo_s": INTERVALO,
                     "motor": {"ok": retrato is not None and not feed_ruim and (fita_ok or not em_hora or self.grafico),
                               "b3_sem_tique_s": parado, "b3_atraso_ms": atraso, "mt5": self.feed.get("mt5"),
                               "fita_ok": fita_ok}},
            "modo": "paper", "origem": "real", "capital": p.capital, "pronto": True, "bloqueios": [], "avisos": avisos,
            "regras": ({"nome": "Setup PhiCube (Bo Williams): Prisma em 15 minutos, virada em 4 minutos (versão 1)",
                        "itens": regras_phicube(p), "parametros": dict(asdict(p), lote_hoje=lote, phicube=PHICUBE)}
                       if self.setup == "phicube" else
                       {"nome": "Setup de níveis: teste de nível com reação, como nas lives da sala do PhiCube (versão 0)",
                        "itens": regras_niveis(p, self.climax_opera, self.niveis_opera, self.dado_opera),
                        "parametros": dict(asdict(p), lote_hoje=lote, niveis=NIVEIS, climax=CLIMAX, dado=DADO, dado_opera=self.dado_opera,
                                           climax_opera=self.climax_opera,
                                           niveis_opera=self.niveis_opera, outras_regras_hoje=self.outras)}
                       if self.setup == "niveis" else
                       {"nome": "Leitura de fluxo como Alison Correia ensina: defesa, nível perdido, rompimento e exaustão (versão 1.2)",
                        "itens": ef.regras_em_texto(p), "parametros": dict(asdict(p), lote_hoje=lote)}),
            "resultado": {"dia": total, "dia_pct": total / p.capital if p.capital else None, "realizado": realizado,
                          "aberto": aberto, "custos": custos, "operacoes": len(finais), "abertas": abertas,
                          "ganhadoras": len(ganhos), "perdedoras": len(perdas),
                          "taxa_acerto": (len(ganhos) / len(self.operacoes)) if self.operacoes else None,
                          "maior_ganho": max((o["resultado"] for o in ganhos), default=None),
                          "maior_perda": min((o["resultado"] for o in perdas), default=None),
                          "meta": p.meta_dia_rs, "perda_maxima": -p.perda_maxima_dia_rs,
                          "pico": self.pico, "vale": self.vale, "pico_realizado": self.pico_realizado,
                          "trava": {"tres_perdas": "perda", "devolucao": "meta"}.get(self.trava, self.trava),
                          "motivo_trava": self.trava,
                          "negocios_perdedores": self.perdas, "lote_hoje": lote,
                          "patrimonio": p.capital + acumulado, "acumulado": acumulado, "dias": len(serie)},
            "instrumentos": instrumentos, "posicoes": posicoes, "operacoes": list(reversed(ops)),
            "sinais_hoje": self.sinais_hoje(agora),
            "regras_de_laboratorio": [{"nome": x.nome, "titulo": x.titulo, "estado": x.estado, "erro": x.erro} for x in self.labs],
            "chave": {"ligado": self.chave["ligado"], "desde": self.chave["desde"]},
            "janela": {"inicio": min((ef.ATIVOS[a].hora_inicio for a in ATIVOS), default="09:15"), "ultima_entrada": p.hora_ultima_entrada,
                       "zerar": p.hora_zerar, "motivo": self.janela.get("motivo") or ""},
            "curva": [{"hora": h, "resultado": v} for h, v in self.curva], "serie": serie,
            "diario": list(reversed(self.diario[-DIARIO_MAX:])),
            "fontes": {"cotacoes": "motor do Autopilot Terminal (MetaTrader)",
                       "fluxo": "AutopilotFeed 1.3: negócios por segundo com o lado agressor e livro de ofertas",
                       "regra": "quant/daytrade/estrategia_fluxo.py", "metodo": "quant/docs/metodo-alison-correia.md"}}

    def sinais_hoje(self, agora):
        """Para a tela: todo sinal guardado hoje (operando ou so medindo) e o que cada um deu ou esta dando, pelas barras de 1 minuto.
        Refeito uma vez por minuto."""
        minuto = agora.strftime("%H:%M")
        if self._sinais_hoje[0] == minuto:
            return self._sinais_hoje[1]
        fora = []
        try:
            from quant.daytrade import medir
            with open(os.path.join(self.pasta, f"sinais_{self.setup}.jsonl"), encoding="utf-8") as f:
                linhas = [json.loads(x) for x in f if x.strip()]
            for ev in linhas:
                if ev.get("tipo") != "sinal" or ev.get("entrada") is None:
                    continue
                b = self.barras.get(ev.get("ativo"))
                r = medir.hipotetico(ev, b.df) if b is not None else None
                fora.append({"hora": ev.get("hora"), "ativo": ev.get("ativo"), "tecnica": ev.get("tecnica"), "lado": ev.get("lado"),
                             "entrada": ev.get("entrada"), "opera": bool(ev.get("opera")), "nome_nivel": ev.get("nome_nivel"),
                             "fita_confirmou": ((ev.get("medidas") or {}).get("fita") or {}).get("confirmou"),
                             "situacao": "aberto" if r is None else "fechado", "saida": None if r is None else r["saida"],
                             "pontos": None if r is None else round(r["pontos"], 2), "resultado": None if r is None else round(r["resultado"], 2)})
        except (OSError, ValueError):
            pass
        fora.reverse()                                           # o mais novo em cima
        self._sinais_hoje = (minuto, fora)
        return fora

    def _serie(self, total, n_ops, pregao):
        serie = ler_json(self.arq_serie, padrao=None)
        serie = [x for x in (serie if isinstance(serie, list) else []) if isinstance(x, dict) and x.get("data") != self.hoje]
        if pregao and (self.ultima_fita or self.operacoes or self.grafico):
            serie.append({"data": self.hoje, "resultado": round(float(total), 2), "operacoes": int(n_ops)})
            try:
                garantir_dir(DIR_DT)
                gravar_atomico(self.arq_serie, json.dumps(serie, ensure_ascii=False))
            except OSError:
                pass
        acum = 0.0
        for x in serie:
            acum += float(x.get("resultado") or 0.0)
            x["patrimonio"] = round(self.p.capital + acum, 2)
        return serie[-400:]

    def _gravar(self, estado):
        from quant.rodar_diario import limpar
        texto = json.dumps(limpar(estado), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        for c in self.saidas:
            try:
                garantir_dir(os.path.dirname(c))
                gravar_atomico(c, texto)
            except OSError as e:
                log(f"nao gravei {c}: {type(e).__name__}: {e}")


def rodar(uma_vez=False, saidas=None, motor=MOTOR, intervalo=INTERVALO, ate=FIM_PROCESSO, setup="fluxo"):
    agora = agora_brt()
    hoje = agora.strftime("%Y-%m-%d")
    if not uma_vez:
        import fcntl
        garantir_dir(DIR_DT)
        trava = open(os.path.join(DIR_DT, "robo.trava"), "w")       # a mesma trava do robo antigo: um so por maquina
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("ja existe um robo de day trade nesta maquina; este processo sai sem fazer nada")
            return 3
    robo = RoboFluxo(hoje, saidas=saidas, motor=motor, setup=setup)
    if setup == "niveis":
        robo.marco("ligado_niveis", "preparo", "Robô de day trade pelo setup de níveis (teste de nível com reação) ligado (simulação), placar zerado.", agora)
        robo.marco("climax_" + hoje, "preparo", ("Opera o climax de volume" if robo.climax_opera else "Climax de volume só medido")
                   + ("; o teste de nível opera." if robo.niveis_opera else "; o teste de nível fica só medido (revisão de 08/10/2026).")
                   + " O limite do dia vale para o dia inteiro.", agora)
    elif setup == "phicube":
        robo.marco("ligado_phicube", "preparo", "Robô de day trade pelo setup PhiCube ligado (simulação), placar zerado.", agora)
    else:
        robo.marco("ligado_fluxo", "preparo", "Robô de day trade por leitura de fluxo ligado (simulação), regra versão 1.2.", agora)
    n = 0
    while True:
        agora = agora_brt()
        try:
            robo.livro = robo.leitor.livro() or robo.livro     # foto pela metade: fica a anterior
            robo.ciclo(agora)
        except Exception as e:
            log(f"ciclo falhou: {type(e).__name__}: {e}")
        n += 1
        hm = agora.strftime("%H:%M")
        if uma_vez or hm >= ate or agora.strftime("%Y-%m-%d") != hoje:
            return 0
        time.sleep(intervalo if ABERTURA <= hm < "17:25" else 10.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Robo de day trade por leitura de fluxo (simulacao)")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--saida", action="append")
    args = ap.parse_args(argv)
    return rodar(uma_vez=args.uma_vez, saidas=args.saida)


if __name__ == "__main__":
    sys.exit(main())
