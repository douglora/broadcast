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
def preparar(dia=None, repetir=False):
    """Manha. A ordem e a de dependencia: preco -> evento -> balanco -> sinal -> validacao -> boleta."""
    dia = dia or agora_brt().date()
    ano = dia.year
    segunda = dia.weekday() == 0
    if not repetir and _boleta_da_manha(dia) and (_boleta_da_manha(dia) or {}).get("emitida"):
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
        ("boleta", ["-m", "quant.rodar_diario", "--paper"], 600),
    ]
    tudo = True
    for nome, args, limite in passos:
        # validacao e boleta dependem do que veio antes: se algo mudou hoje, refazem
        ok = passo(dia, nome, args, timeout=limite, repetir=repetir or nome in ("validacao", "boleta"))
        tudo = tudo and ok
    return tudo


def vivo(ate=HORA_FIM_VIVO):
    from quant.execucao import robo_vivo
    return robo_vivo.rodar(ate=ate)


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


def dia():
    """O dia inteiro. Sai sozinho em fim de semana e feriado da B3."""
    hoje = agora_brt().date()
    if not calendario.eh_pregao(hoje):
        log(f"{hoje} nao e pregao: nada a fazer")
        return 0
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rotina diaria do robo quant (simulacao)")
    ap.add_argument("comando", choices=["dia", "preparar", "vivo", "fechar", "estado"])
    ap.add_argument("--repetir", action="store_true", help="refaz os passos que ja deram certo hoje")
    ap.add_argument("--data", default=None, help="AAAA-MM-DD (para fechar um pregao passado)")
    ap.add_argument("--fita-do-robo", action="store_true",
                    help="com `fechar`: usa a fita que o robo viu ao vivo em vez da oficial da B3")
    args = ap.parse_args(argv)
    d = datetime.strptime(args.data, "%Y-%m-%d").date() if args.data else agora_brt().date()
    if args.comando == "dia":
        return dia()
    if args.comando == "preparar":
        return 0 if preparar(d, repetir=args.repetir) else 1
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
