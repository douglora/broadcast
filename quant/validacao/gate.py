"""
O veredito do gate da fase 1, gravado em disco e conferido contra o banco que o produziu.

POR QUE ESTE MODULO EXISTE. `replica_nefin.rodar_gate` calculava o veredito, imprimia o JSON
e o resultado morria ali - nao havia artefato nenhum para o resto do sistema ler. Como
`boleta.modo_seguro` bloqueia quando `gate_passou is None`, e bloqueia de proposito (um
sistema que mexe em dinheiro nao pode ter "na duvida, opera" como padrao), `rodar_diario
--paper` e `campanha --sessao` nasciam bloqueados PARA SEMPRE: nenhum dos dois tinha de onde
tirar a aprovacao. O comando da rotina da manha, documentado em rotina-paper-trading.md,
nunca produziria uma boleta - nem com o banco carregado e o gate aprovado.

POR QUE NAO UMA FLAG `--gate-aprovado`. Porque seria o usuario jurando que o gate passou, e
`modo_seguro` existe exatamente para nao aceitar juramento. Este arquivo e o gate dizendo
que passou, com a data e com a impressao digital do banco que ele usou.

A IMPRESSAO E O QUE DA VALIDADE AO VEREDITO. Gate aprovado sobre um banco que mudou depois
nao vale mais: recarregar um ano, consertar um parser ou acrescentar pregao muda os fatores,
e o veredito antigo passa a descrever um banco que nao existe mais. Entao o veredito carrega
a impressao do banco e `ler()` recusa quando ela nao bate - volta a None, que bloqueia.

A impressao e barata de proposito: (ano, bytes) de cada parquet de cotacao da janela, em
sha256. Pega ano acrescentado, ano removido e ano regravado com conteudo diferente, que sao
as tres coisas que de fato acontecem - e a terceira e a que mais importa, porque e o
conserto de parser que mais muda fator. NAO pegaria uma alteracao que preservasse o tamanho
em bytes exatamente, e isso e aceito: a guarda existe contra o banco ter mudado, nao contra
alguem querendo engana-la.

O ARQUIVO FICA EM quant/saida/, QUE E GITIGNORED, e isso e proposital: ele descreve o banco
desta maquina. Um gate aprovado no meu computador nao diz nada sobre o seu.
"""
import hashlib
import json
import os
from datetime import date

from quant.comum import DIR_SAIDA, garantir_dir, gravar_json, ler_json

ARQ_GATE = os.path.join(DIR_SAIDA, "gate_fase1.json")

# Quantos anos antes do inicio da janela o gate carrega para ter historico de momento.
# Tem de ser o mesmo numero de `replica_nefin.rodar_gate`, senao a impressao cobre uma
# janela diferente da que o gate leu.
ANOS_DE_HISTORICO = 2

VERSAO = 1


def impressao_do_banco(ini, fim, caminho_parquet=None):
    """sha256 de (ano, bytes) de cada parquet de cotacao na janela que o gate leu.

    Ano ausente entra como `ausente` em vez de ser pulado: acrescentar o ano depois tem de
    mudar a impressao, senao um gate rodado com buraco continuaria valendo depois que o
    buraco fosse tapado - e o resultado seria outro.
    """
    if caminho_parquet is None:
        from quant.dados import cotahist
        caminho_parquet = cotahist.caminho_parquet
    partes = []
    for ano in range(int(ini) - ANOS_DE_HISTORICO, int(fim) + 1):
        p = caminho_parquet(ano)
        try:
            partes.append(f"{ano}:{os.path.getsize(p)}")
        except OSError:
            partes.append(f"{ano}:ausente")
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()


def gravar(resultado, ini, fim, caminho=ARQ_GATE, hoje=None):
    """Grava o veredito do gate com a impressao do banco que o produziu."""
    quando = str(hoje or date.today())
    corpo = {
        "versao": VERSAO,
        "rodado_em": quando,
        "janela": [int(ini), int(fim)],
        "passou": bool(resultado.get("passou")),
        "impressao_banco": impressao_do_banco(ini, fim),
        "fatores": {k: {"correlacao": v.get("correlacao"),
                        "diferenca_pp": v.get("diferenca_pp"),
                        "n_meses": v.get("n_meses"),
                        "passou": v.get("passou")}
                    for k, v in resultado.items()
                    if k != "passou" and isinstance(v, dict)},
    }
    garantir_dir(os.path.dirname(caminho))
    gravar_json(caminho, corpo)
    return corpo


def ler(caminho=ARQ_GATE):
    """(passou, motivo). `passou` e True, False ou None - e None BLOQUEIA.

    None cobre os quatro jeitos de nao saber: o gate nunca rodou, o arquivo esta ilegivel,
    ele veio de uma versao que nao entendo, ou o banco mudou depois que ele rodou. Nenhum
    deles pode virar "deixa passar".
    """
    corpo = ler_json(caminho, padrao=None)
    if not isinstance(corpo, dict):
        return None, ("o gate da fase 1 nunca rodou nesta maquina; rode "
                      "python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026")
    if int(corpo.get("versao") or 0) != VERSAO:
        return None, (f"gate_fase1.json esta na versao {corpo.get('versao')!r} e eu leio a "
                      f"{VERSAO}; rode o gate de novo")
    janela = corpo.get("janela") or []
    if len(janela) != 2:
        return None, "gate_fase1.json sem janela; rode o gate de novo"
    quando = corpo.get("rodado_em") or "?"
    try:
        atual = impressao_do_banco(janela[0], janela[1])
    except Exception as e:                       # ler o banco nao pode derrubar a rotina
        return None, f"nao consegui conferir o banco contra o gate ({type(e).__name__})"
    if atual != corpo.get("impressao_banco"):
        return None, (f"o gate rodou em {quando} sobre um banco diferente do atual "
                      "(ano recarregado, acrescentado ou removido); rode o gate de novo")
    if corpo.get("passou"):
        return True, f"gate da fase 1 aprovado em {quando}"
    return False, f"o gate da fase 1 REPROVOU em {quando}"


def resumo(caminho=ARQ_GATE):
    """O que o painel mostra: o tri-estado e o motivo, em formato serializavel."""
    passou, motivo = ler(caminho)
    corpo = ler_json(caminho, padrao=None)
    saida = {"passou": passou, "motivo": motivo}
    if isinstance(corpo, dict):
        saida["rodado_em"] = corpo.get("rodado_em")
        saida["janela"] = corpo.get("janela")
        saida["fatores"] = corpo.get("fatores")
    return saida
