"""
A ponte entre o sistema quant e o Autopilot Terminal: o payload que a aba QUANT chama.

ONDE ISTO RODA. Na maquina do Douglas, dentro do servidor MCP `host:autopilot` que o
Artifact do terminal ja chama hoje para `cotacoes` e `intradia`. O Artifact roda no
navegador e nao alcanca disco nenhum; quem le o banco, o gate e o livro de ordens e este
modulo, do lado de ca. Por isso ele devolve dado puro e serializavel, nunca HTML.

A REGRA QUE GOVERNA TUDO AQUI: nunca inventar. Peca que falta nao vira zero, nem vira o
valor de ontem - vira um bloqueio nomeado, com o comando que o resolve. Um painel de
operacao que mostra numero onde nao ha dado e pior que um painel vazio, porque o numero
parece resultado. E a mesma disciplina do `modo_seguro` e do `_frescor_do_banco`.

O CAMPO QUE A ABA USA PARA DECIDIR O QUE DESENHAR e `pronto`:
  - `pronto: false`  -> a aba desenha a lista de bloqueios, em ordem de resolucao. E o
    estado de hoje: banco vazio, gate nunca rodado.
  - `pronto: true`   -> a aba desenha a cabine: carteira, boleta, posicoes, P&L.

A ORDEM DOS BLOQUEIOS NAO E COSMETICA. Ela e a ordem de dependencia real: sem banco nao ha
gate, sem gate nao ha boleta, sem boleta nao ha o que simular. Mostrar os quatro de uma vez
sem ordem faria o Douglas tentar o quarto primeiro.
"""
import os
from datetime import datetime, timezone

from quant.comum import DIR_SAIDA, ler_json

ARQ_PAINEL = os.path.join(DIR_SAIDA, "painel.json")

# Em que ordem os bloqueios tem de ser resolvidos. Cada um so faz sentido depois do
# anterior: sem banco o gate nao roda, sem gate nao sai boleta, sem boleta nao ha fita
# para casar.
ORDEM = ("banco", "gate", "boleta")


def _agora():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _bloqueio(chave, titulo, detalhe, comando=None):
    return {"chave": chave, "titulo": titulo, "detalhe": detalhe, "comando": comando}


def estado_do_banco():
    """Cobertura do banco de precos, reusando a checagem que a conferencia ja faz."""
    try:
        from quant.dados import conferir
        linhas = conferir.checar_cobertura_de_precos()
    except Exception as e:                       # ler o banco nunca derruba a ponte
        return {"ok": False, "estado": "erro", "detalhe": f"{type(e).__name__}: {e}"}
    if not linhas:
        return {"ok": False, "estado": "erro", "detalhe": "sem resposta da conferencia"}
    cabeca = linhas[0]
    return {"ok": cabeca["estado"] == conferir.OK,
            "estado": cabeca["estado"],
            "detalhe": cabeca["detalhe"],
            "checagens": linhas}


def estado_do_gate():
    from quant.validacao import gate
    return gate.resumo()


def estado_da_boleta():
    """O painel que `rodar_diario` gravou de manha, ou a ausencia dele.

    Le o arquivo em vez de recalcular: recalcular aqui faria a aba disparar o pipeline
    inteiro a cada abertura, e o painel e justamente o artefato que separa o calculo
    (uma vez, de manha) da leitura (o dia todo).
    """
    painel = ler_json(ARQ_PAINEL, padrao=None)
    if not isinstance(painel, dict):
        return {"existe": False, "motivo": "a rodada de hoje nao foi gerada"}
    boleta = painel.get("boleta") or {}
    ms = painel.get("modo_seguro") or {}
    return {
        "existe": True,
        "data": painel.get("data"),
        "origem": painel.get("origem"),
        "emitida": bool(boleta.get("emitida")),
        "modo_seguro": {"ativo": bool(ms.get("ativo")), "motivos": list(ms.get("motivos") or [])},
        "ordens": list(boleta.get("ordens") or []),
        "custo_total": boleta.get("custo_total"),
        "hora_envio": boleta.get("hora_envio"),
    }


def estado_da_campanha():
    """O placar da fase 4, se a campanha ja tiver sessao registrada.

    O `except` aqui cobre banco/arquivo ausente, NAO erro de programacao: se o nome da
    funcao da campanha mudar, isto tem de quebrar alto no teste em vez de virar
    "0 sessoes" em silencio. Por isso `carregar_sessoes` e resolvido por getattr com
    falha explicita.
    """
    from quant.execucao import campanha
    carregar = getattr(campanha, "carregar_sessoes")      # AttributeError = bug, nao estado
    try:
        sessoes = carregar()
    except OSError as e:
        return {"sessoes": 0, "detalhe": f"registro ilegivel ({type(e).__name__})"}
    n = 0 if sessoes is None else len(sessoes)
    return {"sessoes": int(n)}


def bloqueios(banco, gate, boleta):
    """O que impede o robo de operar, na ordem em que tem de ser resolvido."""
    fora = []
    if not banco.get("ok"):
        fora.append(_bloqueio(
            "banco", "O banco de precos nao esta completo", banco.get("detalhe") or "",
            "python3 -m quant.primeira_carga --continuar && python3 -m quant.dados.conferir"))
    if gate.get("passou") is not True:
        fora.append(_bloqueio(
            "gate", "O gate da fase 1 nao esta aprovado", gate.get("motivo") or "",
            "python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026"))
    if not boleta.get("existe"):
        fora.append(_bloqueio(
            "boleta", "A rodada de hoje nao foi gerada", boleta.get("motivo") or "",
            "python3 -m quant.rodar_diario --paper"))
    elif boleta.get("modo_seguro", {}).get("ativo"):
        fora.append(_bloqueio(
            "boleta", "Modo seguro ativo: nenhuma boleta emitida",
            "; ".join(boleta["modo_seguro"]["motivos"]), None))
    fora.sort(key=lambda b: ORDEM.index(b["chave"]) if b["chave"] in ORDEM else 99)
    return fora


def payload(sessao=None):
    """O dicionario que a aba QUANT recebe. Serializavel, sem NaN e sem Timestamp.

    `sessao` e uma `paper_vivo.Sessao` opcional: quando a ponte esta mantendo uma
    simulacao ao vivo, o estado dela entra aqui. Sem sessao o campo vem None, e a aba
    mostra a boleta sem execucao - que e o estado antes das 10:20.
    """
    banco = estado_do_banco()
    gate = estado_do_gate()
    boleta = estado_da_boleta()
    fora = bloqueios(banco, gate, boleta)
    return {
        "gerado_em": _agora(),
        "pronto": not fora,
        "bloqueios": fora,
        "banco": banco,
        "gate": gate,
        "boleta": boleta,
        "campanha": estado_da_campanha(),
        "sessao": sessao.estado() if sessao is not None else None,
    }


def texto(p=None):
    """A mesma coisa em texto, para conferir no terminal sem abrir o navegador."""
    p = p or payload()
    linhas = ["=" * 68, "PONTE DO QUANT PARA O TERMINAL", "=" * 68,
              f"gerado em {p['gerado_em']}", ""]
    if p["pronto"]:
        linhas.append("PRONTO: o robo tem o que operar.")
    else:
        linhas.append(f"NAO PRONTO: {len(p['bloqueios'])} bloqueio(s), nesta ordem:")
        linhas.append("")
        for i, b in enumerate(p["bloqueios"], 1):
            linhas.append(f"  {i}. {b['titulo']}")
            if b["detalhe"]:
                linhas.append(f"     {b['detalhe']}")
            if b["comando"]:
                linhas.append(f"     -> {b['comando']}")
            linhas.append("")
    s = p.get("sessao")
    if s:
        t = s["totais"]
        linhas.append(f"sessao ao vivo: {t['qtd_executada']}/{t['qtd_pedida']} acoes, "
                      f"aberto R$ {t['aberto']:.2f}")
    linhas.append("=" * 68)
    return "\n".join(linhas)


def main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="O payload da aba QUANT do terminal")
    ap.add_argument("--json", action="store_true", help="saida em JSON, para a ponte MCP")
    args = ap.parse_args(argv)
    p = payload()
    print(json.dumps(p, ensure_ascii=False, indent=2) if args.json else texto(p))
    return 0 if p["pronto"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
