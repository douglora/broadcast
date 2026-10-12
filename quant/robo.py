"""
A rotina diaria do robo, em um comando. E o que o agendador do Mac chama; o Douglas nao
precisa lembrar de nada.

    python -m quant.robo dia         # o dia inteiro, cada parte na sua hora
    python -m quant.robo preparar    # manha: dados de ontem, sinais, validacao e a boleta
    python -m quant.robo vivo        # pregao: simulacao ao vivo (robo_vivo)
    python -m quant.robo fechar      # noite: fita oficial da B3 e registro da sessao
    python -m quant.robo estado      # o que ja rodou hoje

TRES MOMENTOS, PORQUE OS DADOS CHEGAM EM TRES HORAS DIFERENTES:
  - de manha ja existem o fechamento de ontem (COTAHIST), o boletim de ontem (BDI) e os
    balancos entregues ate ontem: da para calcular sinais, validar e emitir a boleta;
  - no pregao so existe a cotacao ao vivo: o robo simula a execucao e mostra na tela;
  - a noite a B3 publica o negocio a negocio: a mesma boleta e medida contra a fita
    oficial, e e ESSE resultado que entra no livro e vira a posicao de amanha.

CADA PASSO E UM PROCESSO A PARTE, com tempo maximo e registro em
`quant/saida/rotina/<data>.json`. Passo que falha nao some: fica marcado, com o fim da
saida dele, e a boleta do dia sai bloqueada pelo modo seguro (dado velho ou validacao
ausente) em vez de sair errada. Nada aqui manda ordem a corretora.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from quant.comum import DIR_SAIDA, agora_brt, garantir_dir, gravar_atomico, ler_json, log
from quant.dados import calendario

DIR_ROTINA = os.path.join(DIR_SAIDA, "rotina")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HORA_VIVO = "09:45"          # o robo ao vivo sobe antes da abertura para pegar a linha de base
HORA_FIM_VIVO = "18:30"
HORA_FECHAR = "20:30"        # a B3 publica o negocio a negocio no comeco da noite
HORA_DESISTIR = "23:40"
ESPERA_FITA_MIN = 20


def _arquivos(dia):
    garantir_dir(DIR_ROTINA)
    return (os.path.join(DIR_ROTINA, f"{dia}.json"), os.path.join(DIR_ROTINA, f"{dia}.log"))


def _estado(dia):
    e = ler_json(_arquivos(dia)[0], padrao=None)
    return e if isinstance(e, dict) else {"data": str(dia), "passos": {}}


def _gravar(dia, estado):
    gravar_atomico(_arquivos(dia)[0], json.dumps(estado, ensure_ascii=False, indent=1))


def passo(dia, nome, args, timeout=1800, repetir=False):
    """Roda `python -m ...` e registra. Passo que ja deu certo hoje nao roda de novo."""
    estado = _estado(dia)
    feito = estado["passos"].get(nome) or {}
    if feito.get("ok") and not repetir:
        return True
    arq_log = _arquivos(dia)[1]
    ini = time.time()
    log(f"rotina: {nome} ...")
    try:
        r = subprocess.run([sys.executable, "-W", "ignore", "-u"] + list(args), cwd=RAIZ,
                           capture_output=True, text=True, timeout=timeout)
        saida, codigo = (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired as e:
        saida, codigo = (str(e.stdout or "") + f"\nTEMPO ESGOTADO ({timeout}s)"), 124
    except Exception as e:                                   # o orquestrador nunca cai por um passo
        saida, codigo = f"{type(e).__name__}: {e}", 125
    with open(arq_log, "a", encoding="utf-8") as f:
        f.write(f"\n===== {agora_brt():%H:%M:%S} {nome}: {' '.join(args)} (codigo {codigo}) =====\n{saida}\n")
    cauda = [x for x in saida.strip().splitlines() if x.strip()][-4:]
    estado = _estado(dia)
    estado["passos"][nome] = {"ok": codigo == 0, "codigo": codigo, "quando": agora_brt().isoformat(timespec="seconds"),
                              "segundos": round(time.time() - ini, 1), "cauda": cauda}
    _gravar(dia, estado)
    log(f"rotina: {nome} {'ok' if codigo == 0 else 'FALHOU'} em {time.time() - ini:.0f}s")
    return codigo == 0


# ─────────────────────────────────────────────────────────────
# Os tres momentos
# ─────────────────────────────────────────────────────────────
PASSOS_AUXILIARES = ("risco", "livro", "observacao")   # falha aqui e avisada no log, mas nao reprova a manha


def _boleta_swing_emitida(dia):
    from quant.swing import boleta
    b = boleta.ler_boleta(dia)
    return bool(b and b.get("emitida"))


def preparar(dia=None, repetir=False, mods=None):
    """Manha. A ordem e a de dependencia: preco -> evento -> balanco -> sinal -> validacao -> boleta.

    `mods`: quais modulos a rodada serve (padrao: os de `modulos()`). Os passos de dado sao os mesmos; no fim a carteira de fatores faz risco, livro
    e boleta, e o swing faz a conciliacao com as barras oficiais, os sinais e a boleta de swing (`quant.swing.boleta`). Sem "swing" na lista nada muda
    para a carteira de fatores; com "swing" e sem "fatores", os passos de fatores nao rodam."""
    dia = dia or agora_brt().date()
    ano = dia.year
    segunda = dia.weekday() == 0
    mods = list(mods) if mods is not None else modulos()
    com_swing = "swing" in mods
    com_fatores = "fatores" in mods or not com_swing
    if not com_fatores and not repetir and _boleta_swing_emitida(dia):
        log(f"rotina: a boleta de swing de {dia} ja foi emitida; a preparacao nao roda de novo")
        return True
    if com_fatores and not repetir and _boleta_da_manha(dia) and (_boleta_da_manha(dia) or {}).get("emitida"):
        # reinicio do robo com a boleta de hoje ja emitida: nada a refazer. Rodar de novo os sinais ou a
        # boleta no meio do dia nao muda o que ja saiu (o robo fica com a primeira), so gasta tempo.
        log(f"rotina: a boleta de {dia} ja foi emitida; a preparacao nao roda de novo")
        return True
    passos = [
        # o anual do ano corrente e regravado pela B3 todo dia: traz o fechamento de ontem
        ("cotacoes", ["-m", "quant.dados.cotahist", "--anos", f"{ano}-{ano}"], 900),
        ("identidade", ["-m", "quant.dados.identidade"], 600),
        # sem a BTBTrade (negocio a negocio do aluguel): a exportacao dela estoura o tempo na B3
        # e custava 4 minutos de espera toda manha; o filtro de aluguel segue declarado ausente
        ("boletim", ["-m", "quant.dados.arquivar_b3", "--fontes", "bdi,indices",
                     "--tabelas", "BTBLoanBalance,BTBLendingOpenPosition,SharesInvesVolum"], 900),
        # proventos: as duas fontes da B3 todo dia; o StatusInvest (conferencia) so na segunda
        ("proventos", ["-m", "quant.dados.eventos"] + ([] if segunda else ["--sem-statusinvest"]), 1200),
        ("balancos", ["-m", "quant.dados.cvm_fundamentos", "--anos", f"{ano - 1}-{ano}"], 1800),
        # direto no modulo: `primeira_carga --so cdi` sai com erro quando os OUTROS passos nao rodaram
        # numero de acoes (composicao do capital dos ITR/DFP ja baixados): alimenta o sinal de valor
        ("capital", ["-m", "quant.dados.capital_social", "--anos", f"{ano - 3}-{ano}"], 300),
        ("cdi", ["-c", "import sys; from quant.dados import cdi; s = cdi.carregar(permitir_rede=True); "
                       "print(0 if s is None else len(s), 'dias de CDI'); sys.exit(0 if s is not None and len(s) else 1)"], 300),
        ("fundamentos", ["-m", "quant.dados.painel_fundamentos", "--recente"], 900),
        ("sinais", ["-m", "quant.sinais", "--ini", str(ano - 1), "--fim", str(ano)], 900),
        # o banco mudou (entrou o pregao de ontem): a validacao de ontem nao vale mais
        ("validacao", ["-m", "quant.validacao.replica_nefin", "--ini", "2008", "--fim", str(ano)], 900),
        # orcamento de risco do livro (quant/risco): a mao das acoes pela volatilidade, com a carteira de ontem. A boleta le daqui.
        # Passo auxiliar: se falhar, a boleta sai com mao cheia e diz isso; nao derruba a rotina.
        ("risco", ["-m", "quant.risco.orcamento"], 600),
        ("livro", ["-m", "quant.risco.livro"], 120),
        # camada de observacao (12/10/2026): macro, micro, grafico e fundamento viram sinais SO MEDIDOS, com termometro,
        # dose recomendada e placar; le o terminal e grava em quant/saida/observacao/. Auxiliar: nao muda nenhum modulo.
        ("observacao", ["-m", "quant.observacao"], 300),
    ]
    if com_fatores:
        passos.append(("boleta", ["-m", "quant.rodar_diario", "--paper"], 600))
    # sem fatores, "risco" e "livro" seguem: a exposicao de acoes do swing (config_carteira.exposicao_acoes) vem do orcamento de risco
    if com_swing:
        # swing: concilia as posicoes com as barras oficiais de ontem, acha os sinais do ultimo fechamento e grava a boleta do dia (e a tela)
        passos.append(("swing", ["-m", "quant.swing.boleta"], 900))
    tudo = True
    for nome, args, limite in passos:
        # validacao, risco e boleta dependem do que veio antes: se algo mudou hoje, refazem
        ok = passo(dia, nome, args, timeout=limite, repetir=repetir or nome in ("validacao", "risco", "livro", "observacao", "boleta", "swing"))
        tudo = tudo and (ok or nome in PASSOS_AUXILIARES)
    return tudo


def vivo(ate=HORA_FIM_VIVO):
    from quant.execucao import robo_vivo
    return robo_vivo.rodar(ate=ate)


def vivo_swing(ate=HORA_FIM_VIVO):
    from quant.swing import vivo as vivo_sw
    return vivo_sw.rodar(ate=ate)


def _boleta_da_manha(dia):
    p = ler_json(os.path.join(DIR_SAIDA, "vivo", str(dia), "boleta.json"), padrao=None)
    if isinstance(p, dict) and str(p.get("data")) == str(dia):
        return p
    painel = ler_json(os.path.join(DIR_SAIDA, "painel.json"), padrao=None) or {}
    b = painel.get("boleta") or {}
    return b if str(b.get("data")) == str(dia) else None


def fechar(dia=None, com_a_fita_do_robo=False):
    """Noite: fita oficial, medicao da boleta da manha, fills no livro, linha da campanha.

    `com_a_fita_do_robo`: ultimo recurso. A B3 nem sempre entrega o negocio a negocio (em
    08/10/2026 o endereco respondia 504). Sem sessao registrada nao ha posicao amanha e o robo
    recompraria a carteira inteira; entao, esgotadas as tentativas da noite, a sessao e fechada
    com a fita que o proprio robo viu ao vivo (derivada do volume acumulado) e a linha do dia
    fica anotada como tal em `quant/saida/rotina/<data>.json`.
    """
    from quant.execucao import campanha, robo_vivo
    from quant.validacao import gate
    dia = dia or agora_brt().date()
    b = _boleta_da_manha(dia)
    universo = os.path.join(DIR_SAIDA, "vivo", str(dia), "universo.txt")
    if b and b.get("ordens"):
        garantir_dir(os.path.dirname(universo))
        tk = sorted({str(o.get("ticker")) for o in b["ordens"]} | {str(o.get("ticker")) + "F" for o in b["ordens"]})
        gravar_atomico(universo, "\n".join(tk) + "\n")
    args = ["-m", "quant.dados.arquivar_b3", "--data", str(dia), "--fontes", "negocios,ipe"]
    if os.path.exists(universo):
        args += ["--universo", universo]
    passo(dia, "fita", args, timeout=1200, repetir=True)
    if b is None:
        log("fechar: sem boleta de hoje para medir (a rodada da manha nao emitiu)")
        return False
    passou, motivo = gate.ler()
    fita, origem_fita = None, "oficial da B3 (negocio a negocio)"
    if com_a_fita_do_robo:
        arq = os.path.join(DIR_SAIDA, "vivo", str(dia), "fita.csv")
        try:
            import pandas as pd
            fita = pd.read_csv(arq, sep=";", dtype={"ticker": str, "hora": str})
            origem_fita = "do robo (volume acumulado do MetaTrader); a oficial da B3 nao saiu"
        except Exception as e:
            log(f"fechar: sem a fita do robo ({type(e).__name__}: {e})")
            return False
    registro, msg = campanha.rodar_do_dia(dia, gate_passou=passou, boleta=b, reprecificar=True,
                                          negocios=fita, ate_hora=robo_vivo.FECHAMENTO)
    estado = _estado(dia)
    estado["passos"]["sessao"] = {"ok": registro is not None, "quando": agora_brt().isoformat(timespec="seconds"),
                                  "cauda": [msg], "registro": registro, "fita": origem_fita}
    _gravar(dia, estado)
    log(f"fechar: {msg}" + (f" | executou {registro.get('qtd_executada')} de {registro.get('qtd_pedida')}"
                            if registro else ""))
    return registro is not None


ARQ_MODO = os.path.join(DIR_SAIDA, "modo_robo.json")


def modo():
    """Qual robo esta ligado: "fatores" (carteira de acoes, o padrao) ou "daytrade" (WIN e WDO).

    Em 08/10/2026 o Douglas trocou a estrategia para day trade em mini-indice e mini-dolar. O
    robo de fatores nao foi apagado: fica pausado, e volta trocando este arquivo.
    """
    m = ler_json(ARQ_MODO, padrao=None)
    return str((m or {}).get("robo") or "fatores")


MODULOS_VALIDOS = ("fatores", "swing", "daytrade")


def modulos():
    """Quais robos rodam no dia. Em 10/10/2026 o Douglas pediu os modulos lado a lado (carteira multifatorial e day trade
    de mini-dolar): `"modulos": ["fatores", "daytrade"]` em modo_robo.json. Sem essa chave vale o modo antigo, um so.
    Em 11/10/2026 entrou o "swing" (acoes de curto prazo, ate 10 pregoes): `"modulos": ["swing", "daytrade"]` roda o swing no lugar de "fatores"."""
    m = ler_json(ARQ_MODO, padrao=None) or {}
    lista = m.get("modulos")
    if isinstance(lista, (list, tuple)):
        fora = list(dict.fromkeys(str(x) for x in lista if str(x) in MODULOS_VALIDOS))
        if fora:
            return fora
    return [modo()]


def _dia_dos_dois(hoje, mods=None):
    """Acoes e day trade no mesmo dia, cada um no seu processo: a carteira passa minutos baixando dado de manha e fica ate a noite esperando
    a fita oficial (o swing, ate o fim do pregao); o day trade nao pode esperar por nada disso. Cada robo tem a sua trava de instancia unica,
    o seu estado e o seu arquivo de tela. Este processo so sai depois de o day trade terminar: se saisse antes com erro, o agendador o religaria e
    tentaria subir um segundo day trade.

    O modulo de acoes que roda NESTE processo e o swing quando a lista tem "swing" e nao tem "fatores"; senao e a carteira de fatores (como sempre foi).
    Se a lista tem os dois, o swing sobe num processo a parte, como o day trade."""
    mods = list(mods) if mods is not None else modulos()
    acoes = "swing" if ("swing" in mods and "fatores" not in mods) else "fatores"
    log(f"rotina: {'swing' if acoes == 'swing' else 'carteira de fatores'} e day trade lado a lado, cada um no seu processo (simulacao)")
    filhos = []
    for nome in (["daytrade"] + (["swing"] if ("swing" in mods and "fatores" in mods) else [])):
        try:
            filhos.append(subprocess.Popen([sys.executable, "-W", "ignore", "-u", "-m", "quant.robo", "dia", "--modulo", nome], cwd=RAIZ))
        except OSError as e:
            log(f"rotina: nao consegui subir o modulo {nome} ({type(e).__name__}: {e}); o modulo de acoes segue sozinho")
    try:
        (_dia_swing if acoes == "swing" else _dia_fatores)(hoje)
    except Exception as e:                           # as acoes nao derrubam o day trade
        log(f"rotina: o modulo de acoes ({acoes}) parou com erro ({type(e).__name__}: {e}); o day trade segue ate o fim do pregao")
    for filho in filhos:
        try:
            filho.wait()
        except Exception as e:
            log(f"rotina: esperando o processo filho: {type(e).__name__}: {e}")
    return 0


def dia(so=None):
    """O dia inteiro. Sai sozinho em fim de semana e feriado da B3. `so`: roda um modulo so ("fatores" ou "daytrade")."""
    hoje = agora_brt().date()
    if not calendario.eh_pregao(hoje):
        log(f"{hoje} nao e pregao: nada a fazer")
        return 0
    mods = [so] if so in MODULOS_VALIDOS else modulos()
    if ("fatores" in mods or "swing" in mods) and "daytrade" in mods:
        return _dia_dos_dois(hoje)
    if mods[0] == "swing":
        return _dia_swing(hoje)
    if mods[0] == "daytrade":
        # day trade nao tem preparacao de manha nem medicao a noite: so o pregao, e zera antes do fim
        regra = str((ler_json(ARQ_MODO, padrao=None) or {}).get("regra") or "v0")
        if regra in ("fluxo", "phicube", "niveis"):
            # "fluxo": leitura da fita (precisa do AutopilotFeed 1.3 no MetaTrader); "phicube": grafico (medias de Bo Williams)
            from quant.daytrade import robo_fluxo as dt
            log(f"rotina: modo day trade, setup {regra} (simulacao)")
            dt.rodar(setup=regra)
            return 0
        else:
            from quant.daytrade import robo as dt
            log("rotina: modo day trade, regra versao 0 (mini-indice e mini-dolar, simulacao)")
        dt.rodar()
        return 0
    return _dia_fatores(hoje)


def _dia_fatores(hoje):
    """A carteira de fatores: manha (dados, sinais, validacao, boleta), pregao (simulacao ao vivo) e noite (fita oficial)."""
    hm = lambda: agora_brt().strftime("%H:%M")        # noqa: E731
    if hm() < HORA_FIM_VIVO:
        preparar(hoje)
        vivo()
    while hm() < HORA_FECHAR:
        time.sleep(60)
    while hm() < HORA_DESISTIR:
        if fechar(hoje):
            return 0
        log(f"fita oficial ainda nao saiu; tento de novo em {ESPERA_FITA_MIN} minutos")
        time.sleep(ESPERA_FITA_MIN * 60)
    log("fechar: a fita oficial nao saiu ate o fim da noite; fecho a sessao com a fita que o robo viu ao vivo")
    fechar(hoje, com_a_fita_do_robo=True)
    return 0          # codigo 0 de proposito: o agendador religa o processo quando ele sai com erro


def _dia_swing(hoje):
    """Swing (acoes de curto prazo, ate 10 pregoes): manha (dados, conciliacao com as barras oficiais, sinais, boleta) e pregao (entrada na abertura,
    stop, alvo e prazo ao vivo). Nao ha medicao a noite: as operacoes so medidas sao resolvidas pelas barras oficiais na manha seguinte."""
    hm = lambda: agora_brt().strftime("%H:%M")        # noqa: E731
    if hm() < HORA_FIM_VIVO:
        preparar(hoje, mods=["swing"])
        # visao nova da mesa depois da boleta da manha: acrescenta M1 e M2 a boleta (idempotente: visao ja medida = nada a fazer)
        passo(hoje, "swing_mesa", ["-m", "quant.swing.boleta", "--so-mesa"], timeout=300, repetir=True)
        vivo_swing()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rotina diaria do robo quant (simulacao)")
    ap.add_argument("comando", choices=["dia", "preparar", "vivo", "fechar", "estado", "desligar", "ligar"])
    ap.add_argument("--repetir", action="store_true", help="refaz os passos que ja deram certo hoje")
    ap.add_argument("--data", default=None, help="AAAA-MM-DD (para fechar um pregao passado)")
    ap.add_argument("--fita-do-robo", action="store_true",
                    help="com `fechar`: usa a fita que o robo viu ao vivo em vez da oficial da B3")
    ap.add_argument("--modulo", choices=list(MODULOS_VALIDOS), default=None,
                    help="com `dia`: roda so este modulo (a rotina usa para subir o day trade num processo a parte); "
                         "com `preparar`: prepara so este modulo (ex.: --modulo swing faz a boleta de swing no lugar da de fatores)")
    args = ap.parse_args(argv)
    d = datetime.strptime(args.data, "%Y-%m-%d").date() if args.data else agora_brt().date()
    if args.comando in ("desligar", "ligar"):
        from quant.daytrade import chave
        d = chave.gravar(args.comando == "ligar", motivo="pedido do Douglas")
        print(("Robô LIGADO" if d["ligado"] else "Robô DESLIGADO") + f" às {chave.hora_de(d)}. "
              + ("Ele volta a operar dentro do horário (9h15 às 13h), em simulação." if d["ligado"]
                 else "Em até 2 segundos ele zera o que estiver aberto e não entra mais até você religar."))
        return 0
    if args.comando == "dia":
        return dia(so=args.modulo)
    if args.comando == "preparar":
        return 0 if preparar(d, repetir=args.repetir, mods=[args.modulo] if args.modulo else None) else 1
    if args.comando == "vivo":
        return vivo()
    if args.comando == "fechar":
        return 0 if fechar(d, com_a_fita_do_robo=args.fita_do_robo) else 1
    e = _estado(d)
    for nome, x in e["passos"].items():
        print(f"{'ok    ' if x.get('ok') else 'FALHOU'} {nome:12} {x.get('quando', '')}  {x.get('segundos', '')}s")
        if not x.get("ok"):
            for linha in x.get("cauda") or []:
                print(f"         {linha}")
    if not e["passos"]:
        print(f"nada rodou em {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
