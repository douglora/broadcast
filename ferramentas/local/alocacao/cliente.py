"""Ficha do cliente, propostas, visoes do Douglas e diario da conversa.

Tudo fica em ~/Documents/Asset Allocation/<cliente>/ (LGPD: dado de cliente nunca vai ao git nem a Artifact):
  ficha.json     o que se sabe do cliente (e o que falta perguntar)
  atual.json     carteira atual lida do extrato (opcional)
  proposta.json  a proposta vigente; versoes/proposta_vN.json guarda cada versao
  visoes.json    opinioes do Douglas que mudam as premissas (com a tese)
  diario.md      a conversa em linhas curtas: o que ele disse, o que a mesa respondeu, o que mudou
  saida/         relatorios gerados
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import config as C

FICHA_PADRAO = {
    "nome": "", "tipo": "prospect", "criada_em": "",
    "pessoa": {"idade": None, "estado_civil": None, "dependentes": None, "profissao": None, "estabilidade_renda": None},
    "patrimonio": {"financeiro": None, "imoveis": None, "empresa_participacoes": None, "dividas": None,
                   "ganho_latente_a_realizar": None},
    "fluxo": {"renda_mensal": None, "despesa_mensal": None, "aporte_mensal": 0.0, "eventos": [],
              "renda_anual_para_irpfm": None},
    "objetivo": {"descricao": None, "meta_patrimonio": None, "prazo_anos": None, "retorno_real_desejado": None},
    "risco": {"perfil": None, "queda_maxima_tolerada": None, "reacao_a_queda_20pct": None, "experiencia": {}},
    "liquidez": {"reserva_meses": 12, "obrigacoes_12m": 0.0},
    "restricoes": {"classes_vetadas": [], "bandas": {}, "esg": None, "instituicoes_ja_usadas": []},
    "moeda": {"despesas_em_dolar_pct": 0.0, "filhos_exterior": None, "planos_mudanca": None},
    "fiscal": {"declaracao_completa": None, "usa_pgbl": None},
    "sucessao": {"testamento_ou_holding": None, "seguro_de_vida": None, "previdencia_existente": None},
    "observacoes": [],
}

# (caminho, peso, pergunta). Peso: 1 = sem isto nao ha proposta; 2 = muda a proposta; 3 = refina.
LACUNAS = [
    ("patrimonio.financeiro", 1, "Quanto tem para investir hoje (valor financeiro, fora imóvel e empresa)?"),
    ("objetivo.prazo_anos", 1, "Para quando é o objetivo principal? Em quantos anos precisa do dinheiro, ou qual o horizonte de longo prazo?"),
    ("risco.perfil", 1, "Qual o perfil de suitability dele (conservador, moderado, arrojado ou agressivo), no questionário da instituição?"),
    ("objetivo.descricao", 1, "Qual o objetivo: viver de renda, preservar patrimônio, comprar algo, sucessão, crescer?"),
    ("fluxo.despesa_mensal", 2, "Quanto gasta por mês? (define a reserva de liquidez)"),
    ("risco.queda_maxima_tolerada", 2, "Qual a maior queda do patrimônio, de pico a vale, que ele suporta sem mudar de ideia? (em %)"),
    ("pessoa.idade", 2, "Qual a idade?"),
    ("fluxo.aporte_mensal_definido", 2, "Vai aportar ou retirar dinheiro ao longo do tempo? Quanto por mês e até quando?"),
    ("patrimonio.imoveis", 2, "Tem imóveis, empresa ou participações? Quanto do patrimônio total isso é (concentração)?"),
    ("fluxo.renda_anual_para_irpfm", 2, "Qual a renda anual total (para saber se o IRPFM da Lei 15.270 o alcança)?"),
    ("pessoa.dependentes", 3, "Tem dependentes?"),
    ("pessoa.profissao", 3, "Profissão e estabilidade da renda (CLT, autônomo, empresário)?"),
    ("risco.reacao_a_queda_20pct", 3, "Se a carteira cair 20% em um ano, vende, mantém ou compra mais?"),
    ("risco.experiencia", 3, "Já investiu em bolsa, FIIs, exterior, cripto, multimercado? Como foi?"),
    ("moeda.despesas_em_dolar_definido", 3, "Tem despesa em dólar (filhos fora, viagens, imóvel fora) ou plano de morar fora?"),
    ("fiscal.declaracao_completa", 3, "Declara pelo modelo completo? Usa PGBL?"),
    ("sucessao.testamento_ou_holding", 3, "Há planejamento sucessório (testamento, holding, seguro de vida, previdência)?"),
    ("patrimonio.ganho_latente_a_realizar", 3, "Se tem carteira legada, há ganho latente grande (imposto para sair)?"),
    ("restricoes.instituicoes_ja_usadas", 3, "Em quais instituições já tem dinheiro? (limite do FGC por banco)"),
]


def slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "cliente"


def pasta(nome: str) -> Path:
    return C.CLIENTES / slug(nome)


def _mescla(base: dict, novo: dict) -> dict:
    for k, v in novo.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _mescla(base[k], v)
        else:
            base[k] = v
    return base


def _ler(arq: Path, padrao):
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _gravar(arq: Path, dado) -> None:
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(arq.suffix + ".tmp")
    tmp.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(arq)


def existe(nome: str) -> bool:
    return (pasta(nome) / "ficha.json").exists()


def listar() -> list[str]:
    if not C.CLIENTES.exists():
        return []
    return sorted(p.name for p in C.CLIENTES.iterdir() if p.is_dir() and (p / "ficha.json").exists())


def novo(nome: str, **campos) -> dict:
    if existe(nome):
        raise FileExistsError(f"ja existe a ficha de {nome!r} em {pasta(nome)}")
    f = json.loads(json.dumps(FICHA_PADRAO))
    f["nome"] = nome
    f["criada_em"] = datetime.now().isoformat(timespec="minutes")
    _gravar(pasta(nome) / "ficha.json", f)
    (pasta(nome) / "saida").mkdir(exist_ok=True)
    if campos:
        f = atualizar(nome, campos)
    anotar(nome, f"Ficha criada ({nome}).")
    return f


def ler_ficha(nome: str) -> dict:
    f = _ler(pasta(nome) / "ficha.json", None)
    if f is None:
        raise FileNotFoundError(f"nao ha ficha de {nome!r}: rode `alocar.py novo \"{nome}\"` (clientes: {', '.join(listar()) or 'nenhum'})")
    return _mescla(json.loads(json.dumps(FICHA_PADRAO)), f)


def atualizar(nome: str, campos: dict) -> dict:
    """`campos` pode usar caminhos com ponto: {"pessoa.idade": 52, "patrimonio.financeiro": 8000000}."""
    f = ler_ficha(nome)
    for caminho, valor in campos.items():
        alvo = f
        partes = caminho.split(".")
        for p in partes[:-1]:
            alvo = alvo.setdefault(p, {})
        alvo[partes[-1]] = valor
    _gravar(pasta(nome) / "ficha.json", f)
    return f


def _tem(f: dict, caminho: str) -> bool:
    # chaves virtuais: o padrao (0 / lista vazia) nao conta como respondido
    if caminho == "fluxo.aporte_mensal_definido":
        return f["fluxo"].get("aporte_mensal") not in (None, 0, 0.0) or bool(f["fluxo"].get("eventos")) or bool(f.get("_aporte_confirmado"))
    if caminho == "moeda.despesas_em_dolar_definido":
        return (f["moeda"].get("despesas_em_dolar_pct") or 0) > 0 or f["moeda"].get("filhos_exterior") is not None or f["moeda"].get("planos_mudanca") is not None
    v = f
    for p in caminho.split("."):
        v = v.get(p) if isinstance(v, dict) else None
        if v is None:
            return False
    if isinstance(v, (dict, list)) and not v:
        return False
    return v not in ("", None)


def lacunas(f: dict) -> list[dict]:
    """O que ainda falta perguntar, do mais importante ao menos."""
    out = [{"campo": c, "peso": w, "pergunta": q} for c, w, q in LACUNAS if not _tem(f, c)]
    return sorted(out, key=lambda x: x["peso"])


def pronta_para_proposta(f: dict) -> tuple[bool, list[str]]:
    falta = [x["pergunta"] for x in lacunas(f) if x["peso"] == 1]
    return (not falta), falta


# --- proposta, visoes, diario -----------------------------------------------------------------
def ler_proposta(nome: str) -> dict | None:
    return _ler(pasta(nome) / "proposta.json", None)


def gravar_proposta(nome: str, pesos: dict, origem: str, nota: str = "") -> dict:
    anterior = ler_proposta(nome)
    versao = (anterior["versao"] + 1) if anterior else 1
    soma = sum(pesos.values())
    if abs(soma - 1.0) > 0.0051:
        raise ValueError(f"os pesos somam {soma*100:.1f}%, tem de somar 100%")
    prop = {"versao": versao, "data": datetime.now().isoformat(timespec="minutes"), "origem": origem, "nota": nota,
            "pesos": {k: float(v) for k, v in pesos.items() if abs(v) > 1e-9}}
    _gravar(pasta(nome) / "proposta.json", prop)
    _gravar(pasta(nome) / "versoes" / f"proposta_v{versao}.json", prop)
    anotar(nome, f"Proposta v{versao} gravada ({origem}). {nota}".strip())
    return prop


def ler_visoes(nome: str) -> list[dict]:
    return _ler(pasta(nome) / "visoes.json", [])


def gravar_visao(nome: str, classe: str, delta_pp: float, tese: str, direcao: int = 0) -> dict:
    if classe not in C.POR_ID and classe not in ("_cdi", "_ipca"):
        raise ValueError(f"classe desconhecida {classe!r}. Use: {', '.join(C.IDS)}, _cdi ou _ipca")
    v = ler_visoes(nome)
    nova = {"id": len(v) + 1, "data": datetime.now().isoformat(timespec="minutes"), "classe": classe,
            "delta_pp": float(delta_pp), "direcao": int(direcao), "tese": tese, "ativa": True}
    v.append(nova)
    _gravar(pasta(nome) / "visoes.json", v)
    anotar(nome, f"Visao do Douglas: {classe} {delta_pp:+.1f} pp/ano. {tese}")
    return nova


def desativar_visao(nome: str, vid: int) -> None:
    v = ler_visoes(nome)
    for x in v:
        if x["id"] == vid:
            x["ativa"] = False
    _gravar(pasta(nome) / "visoes.json", v)
    anotar(nome, f"Visao #{vid} desativada.")


def visoes_ativas(nome: str) -> list[dict]:
    return [v for v in ler_visoes(nome) if v.get("ativa", True)]


def anotar(nome: str, texto: str) -> None:
    arq = pasta(nome) / "diario.md"
    arq.parent.mkdir(parents=True, exist_ok=True)
    with arq.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.now():%d/%m/%Y %H:%M} — {texto}\n")


def ler_diario(nome: str) -> str:
    try:
        return (pasta(nome) / "diario.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def ler_atual(nome: str) -> dict | None:
    return _ler(pasta(nome) / "atual.json", None)


def gravar_atual(nome: str, dado: dict) -> None:
    _gravar(pasta(nome) / "atual.json", dado)


# --- derivados da ficha, usados por todo o motor -------------------------------------------------
def perfil_da_ficha(f: dict) -> str:
    p = (f["risco"].get("perfil") or "moderado").lower()
    if p not in C.PERFIS:
        raise ValueError(f"perfil {p!r} invalido na ficha (use {', '.join(C.PERFIS)})")
    return p


def bandas_override(f: dict) -> dict:
    """Bandas que o cliente impoe: classes vetadas viram (0, 0); `restricoes.bandas` = {classe: [min%, max%]}."""
    out = {}
    for cid in f["restricoes"].get("classes_vetadas", []):
        if cid in C.POR_ID:
            out[cid] = (0.0, 0.0)
    for cid, mm in (f["restricoes"].get("bandas") or {}).items():
        if cid in C.POR_ID:
            out[cid] = (float(mm[0]) / 100.0, float(mm[1]) / 100.0)
    # despesa em dolar: o piso da renda variavel internacional cobre 80% da parcela das despesas na moeda
    usd = (f["moeda"].get("despesas_em_dolar_pct") or 0.0) / 100.0
    if usd > 0:
        b = C.bandas_do_perfil(perfil_da_ficha(f))
        lo, hi = out.get("rv_int", b["rv_int"])
        piso = min(0.8 * usd, hi)
        if piso > lo:
            out["rv_int"] = (piso, hi)
    # reserva de liquidez: o piso do caixa cobre a reserva pedida (limitado a 25% do patrimonio)
    pl = f["patrimonio"].get("financeiro")
    desp = f["fluxo"].get("despesa_mensal")
    if pl and desp:
        reserva = min((desp * (f["liquidez"].get("reserva_meses") or 0) + (f["liquidez"].get("obrigacoes_12m") or 0.0)) / pl, 0.25)
        lo, hi = out.get("caixa", C.bandas_do_perfil(perfil_da_ficha(f))["caixa"])
        if reserva > lo:
            out["caixa"] = (reserva, max(hi, reserva))
    return out


def horizonte_da_ficha(f: dict) -> float:
    h = f["objetivo"].get("prazo_anos")
    return float(h) if h else 10.0


def reserva_necessaria(f: dict) -> float | None:
    """Reserva de liquidez em R$ (meses de despesa mais obrigacoes dos proximos 12 meses)."""
    desp = f["fluxo"].get("despesa_mensal")
    if desp is None:
        return None
    return float(desp) * float(f["liquidez"].get("reserva_meses") or 0) + float(f["liquidez"].get("obrigacoes_12m") or 0.0)
