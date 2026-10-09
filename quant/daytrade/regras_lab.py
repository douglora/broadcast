"""
Roda ao vivo, dentro do robo, regras escritas no formato do laboratorio (quant/pesquisa/lab.py):
    regra(m) -> vetor com um valor por barra de 1 minuto (+1 compra, -1 vende, 0 nada), decidido no fechamento.
O codigo que o robo executa e o MESMO que passou pela descoberta, pela validacao e pela prova: nao ha traducao.

O registro fica em quant/pesquisa/setups.json. Cada regra:
    {"nome": "...", "titulo": "nome que aparece na tela", "arquivo": "quant/pesquisa/regras/x.py", "funcao": "regra",
     "saida": {"stop": 40, "alvo": null, "tempo": 120}, "estado": "medido" | "opera", "barras": 15000}
Limites de hoje: a regra so pode usar o, h, l, c e v do mini-dolar (e `nivel`, que ao vivo e o proprio fechamento).
Numero de negocios (n) e outros ativos ainda nao existem nas barras ao vivo.
"""
import importlib.util
import json
import os

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARQ_SETUPS = os.path.join(RAIZ, "quant", "pesquisa", "setups.json")


def ler_registro(arq=None):
    try:
        with open(arq or ARQ_SETUPS, encoding="utf-8") as f:
            return [r for r in (json.load(f).get("regras") or []) if isinstance(r, dict) and r.get("nome")]
    except (OSError, ValueError):
        return []


class SinalLab:
    def __init__(self, setup, raiz=RAIZ):
        self.setup = setup
        self.nome, self.titulo = setup["nome"], setup.get("titulo") or setup["nome"]
        self.estado = setup.get("estado") or "medido"
        self.barras = int(setup.get("barras") or 15_000)
        self.saida = dict(setup.get("saida") or {})
        arq = setup["arquivo"] if os.path.isabs(setup["arquivo"]) else os.path.join(raiz, setup["arquivo"])
        spec = importlib.util.spec_from_file_location(f"regra_lab_{self.nome}", arq)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.regra = getattr(mod, setup.get("funcao") or "regra")
        self.ultima_barra, self.erro = None, None

    def atualizar(self, df):
        """Chamar quando uma barra de 1 minuto acaba de fechar. Devolve o sinal (dict) ou None. Uma vez por barra."""
        if not len(df) or self.ultima_barra == df.index[-1]:
            return None
        self.ultima_barra = df.index[-1]
        d = df.iloc[-self.barras:]
        if "nivel" not in d.columns:
            d = d.assign(nivel=d["c"])
        try:
            v = float(np.nan_to_num(np.asarray(self.regra(d), dtype=float))[-1])
            self.erro = None
        except Exception as e:                                  # regra que quebra nao derruba o robo: fica sem sinal e avisa
            self.erro = f"{type(e).__name__}: {e}"
            return None
        if v == 0:
            return None
        s = self.saida
        tempo = s.get("tempo")
        return {"tecnica": self.titulo, "lado": "C" if v > 0 else "V", "nivel": float(d["c"].iloc[-1]), "nome_nivel": self.titulo,
                "stop_pts": float(s.get("stop") or 10.0), "alvo_pts": s.get("alvo"), "parcial_pts": None, "sem_parcial": True,
                "sem_arrasto": True, "tempo_max_s": None if not tempo else float(tempo) * 60.0,
                "medidas": {"regra": self.nome, "risco_pts": float(s.get("stop") or 10.0), "alvo_pts": s.get("alvo"),
                            "tempo_max_min": tempo, "fracao_a_favor": None}}


def carregar(arq=None, raiz=RAIZ):
    """As regras ligadas (medido ou opera). Regra que nao carrega e pulada, com o motivo."""
    boas, falhas = [], []
    for r in ler_registro(arq):
        if (r.get("estado") or "medido") not in ("medido", "opera"):
            continue
        try:
            boas.append(SinalLab(r, raiz))
        except Exception as e:
            falhas.append((r.get("nome"), f"{type(e).__name__}: {e}"))
    return boas, falhas
