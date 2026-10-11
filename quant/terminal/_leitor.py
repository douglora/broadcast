"""Leitura dos arquivos do Autopilot Terminal: onde ficam, como ler sem travar o robo e quanto cada tipo de dado pode envelhecer.

O terminal grava JSON em `<terminal>/cache/out/` (e o banco historico em `<terminal>/cache/banco/terminal.sqlite`). Aqui so se le:
nada neste pacote escreve no terminal.

Regras
  - Caminho do terminal: variavel de ambiente AUTOPILOT_TERMINAL; sem ela, ~/Desktop/terminal-artefato.
  - Arquivo ausente, ilegivel ou em meio a uma regravacao devolve None. Quem chama transforma isso em "sem dado" com motivo.
  - Os arquivos grandes (multiplos, aluguel, noticias, eventos...) sao guardados em memoria enquanto o arquivo nao mudar
    (mtime e tamanho); `limpar_cache()` zera tudo (os testes chamam).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ENV_TERMINAL = "AUTOPILOT_TERMINAL"
PADRAO_TERMINAL = "~/Desktop/terminal-artefato"
FUSO_BRT = timezone(timedelta(hours=-3))

# Quantos dias cada tipo de dado pode ter, contados da DATA DO DADO ate hoje, antes de virar None com o motivo.
# O que conta como "data do dado" esta ao lado de cada limite. Fim de semana e feriado longo cabem em 4 a 5 dias.
LIMITES_DIAS: dict[str, int] = {
    "tir": 5,          # data do preco usado na TIR (pregao); o modelo e refeito a cada rodada do terminal
    "consenso": 4,     # dia em que o terminal coletou o consenso no agregador (uma coleta por dia, inclusive fim de semana)
    "insiders": 75,    # dias depois do FIM do mes do ultimo formulario entregue (a CVM recebe ate o dia 10 do mes seguinte)
    "aluguel": 5,      # pregao da posicao de aluguel da B3
    "noticias": 2,     # idade do arquivo de noticias (a janela de nota do agente e de poucos dias)
    "eventos": 3,      # idade do calendario (resultados, proventos, assembleias)
    "multiplos": 5,    # data do preco (pregao) usado nos multiplos
    "valuation": 7,    # data do preco usado no valuation historico
    "opcoes": 5,       # pregao do arquivo de opcoes; a volatilidade implicita tem o mesmo teto contado do dia dela
    "divida": 200,     # dias desde o fim do trimestre do balanco (o prazo legal do ITR e 45 dias; sobra para o atraso)
    "fundos": 210,     # dias desde o mes da carteira dos fundos (a CVM publica a carteira com 2 a 3 meses de atraso)
    "pares": 7,        # idade do arquivo de pares proximos
    "agenda": 3,       # idade da agenda economica
}

_MEMO: dict[str, tuple[tuple[int, int], Any]] = {}
_TRAVA = threading.Lock()


def raiz() -> Path:
    return Path(os.environ.get(ENV_TERMINAL) or PADRAO_TERMINAL).expanduser()


def saida() -> Path:
    return raiz() / "cache" / "out"


def caminho_banco() -> Path:
    return raiz() / "cache" / "banco" / "terminal.sqlite"


def limpar_cache() -> None:
    with _TRAVA:
        _MEMO.clear()


def ler(rel: str | Path, *, memo: bool = True) -> Any | None:
    """JSON relativo a `cache/out/` (ou caminho absoluto). None se faltar ou nao for JSON valido."""
    p = Path(rel)
    if not p.is_absolute():
        p = saida() / p
    try:
        st = p.stat()
    except OSError:
        return None
    chave = str(p)
    assinatura = (st.st_mtime_ns, st.st_size)
    if memo:
        with _TRAVA:
            achou = _MEMO.get(chave)
            if achou and achou[0] == assinatura:
                return achou[1]
    try:
        with open(p, "r", encoding="utf-8") as fh:
            dado = json.load(fh)
    except (OSError, ValueError):
        return None
    if memo:
        with _TRAVA:
            _MEMO[chave] = (assinatura, dado)
    return dado


def ler_arquivo_da_cache(rel: str | Path) -> Any | None:
    """Um arquivo fora de `cache/out/` (ex.: cache/notas_agente.json), relativo a raiz do terminal."""
    return ler(raiz() / rel)


def hoje() -> date:
    return datetime.now(FUSO_BRT).date()


def como_data(x: Any) -> date | None:
    """'2026-10-09', '2026-10-09T10:36:37-03:00' ou date -> date. Qualquer outra coisa -> None."""
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str) and len(x) >= 10 and x[4] == "-" and x[7] == "-":
        try:
            return date.fromisoformat(x[:10])
        except ValueError:
            return None
    return None


def idade_dias(dia: Any, ref: date) -> int | None:
    d = como_data(dia)
    return None if d is None else (ref - d).days


def fim_do_mes(ym: str) -> date | None:
    """'2026-08' -> 2026-08-31."""
    try:
        a, m = int(ym[:4]), int(ym[5:7])
        return date(a + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
    except (ValueError, TypeError, IndexError):
        return None


def num(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v or v in (float("inf"), float("-inf")) else v


def inteiro(x: Any) -> int | None:
    v = num(x)
    return None if v is None else int(round(v))


def arred(x: Any, casas: int = 2) -> float | None:
    v = num(x)
    return None if v is None else round(v, casas)


def pct(frac: Any, casas: int = 2) -> float | None:
    """Fracao (0.1839) -> pontos percentuais (18.39)."""
    v = num(frac)
    return None if v is None else round(v * 100.0, casas)


def raiz_do_ticker(t: str) -> str:
    """PETR4 -> PETR; BPAC11 -> BPAC; B3SA3 -> B3SA (mesma chave de empresa que o terminal usa nos arquivos por empresa)."""
    s = t.upper()
    i = len(s)
    while i > 0 and s[i - 1].isdigit():
        i -= 1
    return s[:i] or s
