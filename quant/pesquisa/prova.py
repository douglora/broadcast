"""Leva uma candidata da descoberta para a validacao (2025) e, se pedido, para a prova (2026).

Uso: python -m quant.pesquisa.prova <arquivo.py> <funcao> [--prova] [parametros de lab.avaliar em JSON]
A funcao tem a forma regra(m) -> vetor de sinais, ou regra(m) -> (sinais, dict de parametros de saida por barra).
Cada olhada fora da descoberta fica anotada em quant/saida/pesquisa5/acessos_reserva.log."""
import importlib.util
import json
import sys

from quant.pesquisa import lab


def carregar_regra(arquivo, funcao):
    spec = importlib.util.spec_from_file_location("candidata", arquivo)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, funcao)


def rodar(regra, nome, partes=("descoberta", "validacao"), ativo="WDO", **kw):
    fora = {}
    for parte in partes:
        m = lab.carregar(ativo, parte)
        s = regra(m)
        extras = {}
        if isinstance(s, tuple):
            s, extras = s
        r = lab.avaliar(m, s, nome=f"{nome} [{parte}]", familia="prova", **{**kw, **extras})
        fora[parte] = r
        print(lab.texto(r))
    return fora


if __name__ == "__main__":
    arq, fn = sys.argv[1], sys.argv[2]
    resto = [a for a in sys.argv[3:] if a != "--prova"]
    partes = ("descoberta", "validacao", "prova") if "--prova" in sys.argv else ("descoberta", "validacao")
    rodar(carregar_regra(arq, fn), fn, partes, **(json.loads(resto[0]) if resto else {}))
