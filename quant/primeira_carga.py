"""
A primeira carga de dados, em UM comando.

Por que existe: a carga inicial sao nove coletores que precisam rodar NA ORDEM certa —
identidade depende de cotacoes, eventos dependem de identidade, o painel de fundamentos
depende de fundamentos e de setores. Digitar nove comandos, cada um com seus argumentos,
e esperar horas entre eles, e um jeito confiavel de errar a ordem, pular um passo e
descobrir tres dias depois que o backtest rodou sobre dado faltando.

Este modulo roda todos, na ordem, com repeticao em falha de rede, e no fim imprime o que
funcionou, o que faltou e QUAL E O PROXIMO COMANDO. Nao inventa dado: passo que falha e
passo que falha, e o relatorio final diz em que estado o banco ficou.

  python3 -m quant.primeira_carga                 # a carga inteira
  python3 -m quant.primeira_carga --continuar     # pula o que ja esta no disco
  python3 -m quant.primeira_carga --so cotahist   # so um passo
  python3 -m quant.primeira_carga --listar        # o que sera feito, sem fazer

CADA PASSO E IDEMPOTENTE. Rodar de novo continua de onde parou; nenhum coletor apaga o
que ja baixou. Se a rede cair no meio, rode outra vez.

DEMORA. A primeira vez leva horas — a maior parte no COTAHIST (20 anos de arquivos anuais
da B3) e na CVM (DFP e ITR de 2010 para ca). E normal. Deixe rodando.

O QUE ESTE MODULO NAO FAZ: nao roda o gate da fase 1. O gate e uma decisao, nao uma
etapa de carga, e ele tem de ser lido por um humano — por isso o relatorio final imprime
o comando em vez de executa-lo.
"""
import argparse
import os
import sys
import time
import traceback
from datetime import date

from quant.comum import DIR_BANCO, DIR_BRUTOS, log

TENTATIVAS = 3
ESPERA_INICIAL = 5.0          # segundos; dobra a cada tentativa


# ─────────────────────────────────────────────────────────────
# Os passos, na ordem em que dependem uns dos outros
# ─────────────────────────────────────────────────────────────
def _nefin(anos):
    from quant.dados import nefin
    nefin.baixar("fatores")
    try:
        nefin.baixar("aluguel_taxa")
    except Exception as e:                        # o aluguel e opcional para o gate
        log(f"  aluguel_taxa nao veio ({type(e).__name__}); segue sem ele")
    return 0


def _cotahist(anos):
    from quant.dados import cotahist
    return cotahist.main(["--anos", f"{anos[0]}-{anos[1]}"])


def _identidade(anos):
    from quant.dados import identidade
    return identidade.main([])


def _eventos(anos):
    from quant.dados import eventos
    return eventos.main([])


def _cvm(anos):
    from quant.dados import cvm_fundamentos
    return cvm_fundamentos.main(["--anos", f"{max(anos[0], 2010)}-{anos[1]}"])


def _cdi(anos):
    from quant.dados import cdi
    serie = cdi.carregar(permitir_rede=True)
    if serie is None or len(serie) == 0:
        return 1
    log(f"  CDI: {len(serie)} dias, fonte {serie.attrs.get('fonte', 'desconhecida')}")
    return 0


def _setores(anos):
    from quant.dados import setores
    return setores.main([])


def _capital(anos):
    from quant.dados import capital_social
    return capital_social.main(["--anos", f"{max(anos[0], 2010)}-{anos[1]}"])


def _painel(anos):
    from quant.dados import painel_fundamentos
    return painel_fundamentos.main(["--anos", f"{max(anos[0], 2010)}-{anos[1]}"])


# nome, descricao, funcao, obrigatorio para o gate, arquivo/pasta que prova que rodou
PASSOS = [
    ("nefin", "fatores de referencia do NEFIN (GitHub)", _nefin, True,
     os.path.join(DIR_BRUTOS, "nefin")),
    ("cotahist", "20 anos de precos da B3 (o passo mais demorado)", _cotahist, True,
     os.path.join(DIR_BANCO, "cotacoes")),
    ("identidade", "mapa ISIN <-> ticker <-> CD_CVM (FCA + cadastro CVM)", _identidade, True,
     os.path.join(DIR_BANCO, "identidade.parquet")),
    ("eventos", "proventos e desdobramentos (B3 + StatusInvest + curadoria)", _eventos, True,
     os.path.join(DIR_BANCO, "eventos.parquet")),
    ("cvm", "fundamentos point-in-time (DFP/ITR de 2010 para ca)", _cvm, False,
     os.path.join(DIR_BANCO, "fundamentos_pit")),
    ("cdi", "CDI diario (BCB, com queda para o Risk_Free do NEFIN)", _cdi, True,
     os.path.join(DIR_BRUTOS, "bcb")),
    ("setores", "macrossetor por CNPJ", _setores, False,
     os.path.join(DIR_BANCO, "setores.parquet")),
    ("capital", "acoes em circulacao (FCA)", _capital, False,
     os.path.join(DIR_BANCO, "capital_social.parquet")),
    ("painel", "painel PIT de TTM e metricas", _painel, False,
     os.path.join(DIR_BANCO, "painel_fundamentos.parquet")),
]

# O gate da fase 1 so precisa de preco, identidade, evento e a referencia do NEFIN. Os
# fundamentos entram na fase 2: da para rodar o gate sem eles e descobrir cedo que o dado
# de preco esta errado, em vez de esperar a CVM inteira baixar para so entao descobrir.
OBRIGATORIOS_DO_GATE = [p[0] for p in PASSOS if p[3]]


def _feito(caminho):
    """Passo concluido = destino existe E tem conteudo.

    Pasta vazia nao conta: um coletor que criou o diretorio e morreu na primeira
    requisicao deixaria `--continuar` pular o passo para sempre.
    """
    if not caminho or not os.path.exists(caminho):
        return False
    if os.path.isdir(caminho):
        return any(os.scandir(caminho))
    return os.path.getsize(caminho) > 0


def rodar_passo(nome, descricao, funcao, anos, tentativas=TENTATIVAS, espera=ESPERA_INICIAL):
    """Roda um passo com repeticao. Devolve (codigo, mensagem).

    Repete em EXCECAO (rede caiu, conexao resetada), nao em codigo de saida != 0: coletor
    que devolve 1 ja tentou e concluiu que nao deu — insistir so gasta tempo.
    """
    for tentativa in range(1, int(tentativas) + 1):
        try:
            codigo = funcao(anos)
            return (int(codigo or 0), "")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if tentativa >= int(tentativas):
                log(f"  {nome}: falhou em {tentativa} tentativas — {msg}")
                return (1, msg)
            atraso = float(espera) * (2 ** (tentativa - 1))
            log(f"  {nome}: {msg}; tentando de novo em {atraso:.0f}s "
                f"({tentativa}/{tentativas})")
            time.sleep(atraso)
    return (1, "sem tentativas")


def relatorio(resultados):
    """O quadro final: o que rodou, o que falhou e o que fazer agora."""
    largura = max(len(n) for n, *_ in PASSOS) + 2
    linhas = ["", "=" * 72, "RESULTADO DA CARGA", "=" * 72]
    for nome, descricao, _f, obrigatorio, _c in PASSOS:
        r = resultados.get(nome)
        if r is None:
            estado = "nao rodou"
        elif r["codigo"] == 0:
            estado = "ok"
        else:
            estado = "FALHOU"
        marca = " (obrigatorio para o gate)" if obrigatorio else ""
        linhas.append(f"  {nome:<{largura}} {estado:<10} {descricao}{marca}")
        if r and r.get("erro"):
            linhas.append(f"  {'':<{largura}} {'':<10} -> {r['erro'][:110]}")
    faltando = [n for n in OBRIGATORIOS_DO_GATE
                if resultados.get(n, {}).get("codigo", 1) != 0]
    linhas.append("=" * 72)
    if faltando:
        linhas.append("")
        linhas.append(f"O gate da fase 1 NAO pode rodar: falta {', '.join(faltando)}.")
        linhas.append("Rode de novo (os coletores continuam de onde pararam):")
        linhas.append("  python3 -m quant.primeira_carga --continuar")
        linhas.append("")
        linhas.append("Se um passo falhar sempre no mesmo ponto, o motivo costuma estar no")
        linhas.append("log acima: fonte fora do ar, formato mudado, ou rede bloqueada.")
    else:
        linhas.append("")
        linhas.append("Os dados que o gate precisa estao no lugar. Confira o que chegou:")
        linhas.append("  python3 -m quant.dados.conferir")
        linhas.append("")
        linhas.append("E entao rode o gate da fase 1 — o bloqueio duro do plano:")
        linhas.append("  python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026")
        linhas.append("")
        linhas.append("Se o gate falhar, PARE. Nao e o gate que esta apertado: e o banco")
        linhas.append("que esta errado, e seguir constroi a estrategia sobre numeros que")
        linhas.append("nao descrevem a bolsa.")
    linhas.append("")
    return "\n".join(linhas)


def main(argv=None):
    ap = argparse.ArgumentParser(description="A primeira carga de dados, em um comando")
    ap.add_argument("--anos", default=f"2005-{date.today().year}",
                    help="janela do COTAHIST (padrao 2005 ate o ano corrente)")
    ap.add_argument("--continuar", action="store_true",
                    help="pula os passos cujo destino ja existe no disco")
    ap.add_argument("--so", action="append", metavar="PASSO",
                    help="roda so este passo (pode repetir)")
    ap.add_argument("--listar", action="store_true", help="mostra os passos e sai")
    ap.add_argument("--tentativas", type=int, default=TENTATIVAS)
    args = ap.parse_args(argv)

    if args.listar:
        for i, (nome, descricao, _f, obrigatorio, caminho) in enumerate(PASSOS, 1):
            estado = "ja existe" if _feito(caminho) else "pendente"
            marca = "obrigatorio" if obrigatorio else "opcional  "
            print(f"{i}. {nome:<12} [{marca}] {estado:<10} {descricao}")
        return 0

    try:
        ini, fim = (int(x) for x in str(args.anos).split("-", 1))
    except Exception:
        print(f"--anos precisa ser AAAA-AAAA (recebi {args.anos!r})")
        return 2
    anos = (ini, fim)

    escolhidos = set(args.so or [])
    if escolhidos:
        desconhecidos = escolhidos - {p[0] for p in PASSOS}
        if desconhecidos:
            print(f"passo desconhecido: {', '.join(sorted(desconhecidos))}")
            print(f"disponiveis: {', '.join(p[0] for p in PASSOS)}")
            return 2

    log(f"primeira carga: COTAHIST {ini}-{fim} | "
        f"{'so ' + ','.join(sorted(escolhidos)) if escolhidos else 'todos os passos'}")
    log("a primeira vez leva horas. Cada coletor e idempotente: pode interromper e voltar.")
    resultados = {}
    for numero, (nome, descricao, funcao, obrigatorio, caminho) in enumerate(PASSOS, 1):
        if escolhidos and nome not in escolhidos:
            continue
        if args.continuar and _feito(caminho):
            log(f"[{numero}/{len(PASSOS)}] {nome}: ja existe, pulando (--continuar)")
            resultados[nome] = {"codigo": 0, "erro": ""}
            continue
        log(f"[{numero}/{len(PASSOS)}] {nome}: {descricao}")
        comeco = time.time()
        codigo, erro = rodar_passo(nome, descricao, funcao, anos, tentativas=args.tentativas)
        resultados[nome] = {"codigo": codigo, "erro": erro}
        log(f"  {nome}: {'ok' if codigo == 0 else 'FALHOU'} em {time.time() - comeco:.0f}s")

    print(relatorio(resultados))
    faltando = [n for n in OBRIGATORIOS_DO_GATE
                if resultados.get(n, {}).get("codigo", 1) != 0]
    return 0 if not faltando else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrompido. Rode de novo com --continuar para retomar.")
        sys.exit(130)
