"""Prazo de divulgacao pelo calendario FISCAL de quem entrega 10-Q e 10-K na SEC.

A CVM conta o prazo do ITR (45 dias; 90 no 4T) a partir do fim do trimestre do calendario. Nos EUA o
prazo conta do fim do trimestre FISCAL de cada empresa, e muita empresa nao fecha o ano em dezembro: a
Lumentum fecha em junho, a Marvell no fim de janeiro, a Broadcom no comeco de novembro. Medidas pelo
calendario da CVM, elas apareciam com "ITR velho" em novembro por um trimestre que so terminou no fim
de outubro e cujo 10-Q vence em dezembro (LITE e MRVL, 15/11/2026).

Prazos da SEC (Form 10-Q e Form 10-K, General Instruction A): 10-Q em 40 dias para large accelerated e
accelerated filer e 45 para os demais; 10-K em 60, 75 ou 90 dias conforme o porte. A mesa usa o mais
longo de cada um (45 e 90): so acusa atraso quando nenhuma empresa poderia estar em dia, o mesmo
criterio do calendario da CVM.

Os frames do XBRL rotulam cada trimestre fiscal pelo trimestre do calendario com que ele mais se
sobrepoe: o trimestre da Marvell encerrado em 01/08/2026 e o CY2026Q2, e o release dele entra no
indice como 2T26. As contas daqui devolvem o trimestre nesse mesmo rotulo, para comparar direto com a
serie oficial e com os releases.

So biblioteca padrao: mesa.py e coletar_dados.py importam daqui.
"""
import datetime as _dt
import re as _re

PRAZO_10Q = 45
PRAZO_10K = 90
DIAS_TRIMESTRE = 91          # 13 semanas; o trimestre de mes cheio fica a 1 ou 2 dias disso
FOLGA_FIM_EXERCICIO = 20     # dias: tolerancia para achar o trimestre que fecha o exercicio (ano de 53 semanas)


def data(valor):
    """'2026-08-01', date ou datetime -> date. None se nao for data."""
    if isinstance(valor, _dt.datetime):
        return valor.date()
    if isinstance(valor, _dt.date):
        return valor
    try:
        return _dt.date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def par_do_frame(rotulo):
    """'CY2026Q2' (ou 'CY2026Q2I', saldo de balanco) -> (2026, 2). None se nao for trimestre."""
    m = _re.fullmatch(r"CY(\d{4})Q([1-4])I?", str(rotulo or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def frame_da_data(fim):
    """(ano, tri) do calendario em que cai a maior parte do trimestre fiscal que termina em `fim`.

    E a regra dos frames da SEC: 01/08/2026 (Marvell) -> (2026, 2); 26/09/2026 (Lumentum) -> (2026, 3)."""
    d = data(fim)
    if not d:
        return None
    meio = d - _dt.timedelta(days=45)
    return (meio.year, (meio.month - 1) // 3 + 1)


def somar_trimestres(par, k):
    n = par[0] * 4 + (par[1] - 1) + k
    return (n // 4, n % 4 + 1)


def _fim_do_mes(d):
    prox = (d.replace(day=28) + _dt.timedelta(days=4))
    return prox - _dt.timedelta(days=prox.day)


def fim_seguinte(fim, k):
    """Fim do trimestre fiscal `k` trimestres depois (ou antes) do que termina em `fim`.

    Quem fecha no ultimo dia do mes (Amazon, Mercado Livre, quem segue o calendario) anda de 3 em 3
    meses ate o fim do mes; quem usa ano de 52 ou 53 semanas (Lumentum, Broadcom, Nvidia) anda de 13
    em 13 semanas (91 dias)."""
    if fim == _fim_do_mes(fim):
        m = fim.year * 12 + (fim.month - 1) + 3 * k
        return _fim_do_mes(_dt.date(m // 12, m % 12 + 1, 1))
    return fim + _dt.timedelta(days=DIAS_TRIMESTRE * k)


def fecha_exercicio(fim, fim_exercicio):
    """O trimestre fiscal que termina em `fim` e o ultimo do exercicio (entrega 10-K, nao 10-Q)?"""
    f, x = data(fim), data(fim_exercicio)
    if not f or not x:
        return False
    for ano in (f.year - 1, f.year, f.year + 1):
        try:
            alvo = x.replace(year=ano)
        except ValueError:          # 29/02
            alvo = x.replace(year=ano, day=28)
        if abs((f - alvo).days) <= FOLGA_FIM_EXERCICIO:
            return True
    return False


def prazo_dias(fim, fim_exercicio=None):
    return PRAZO_10K if fecha_exercicio(fim, fim_exercicio) else PRAZO_10Q


def vencido_fiscal(fim_periodo, fim_exercicio=None, hoje=None):
    """Ultimo trimestre fiscal cujo prazo na SEC ja venceu, pelas datas reais de fim de trimestre.

    `fim_periodo` = {'CY2026Q2': '2026-08-01', ...}: o fim real de cada trimestre conhecido. O mais novo
    e a ancora; dali para a frente (e para tras, onde faltar data) os trimestres seguem pelo fim_seguinte,
    e cada um so conta como devido depois do prazo da SEC (45 dias; 90 no que fecha o exercicio).
    Trimestre entregue antes do prazo nao conta como devido: a pergunta e "o que ja era para estar
    publicado", a mesma do calendario da CVM. Devolve um dict com `par` (ano, tri no rotulo dos
    frames), `fim` e `vencimento` desse trimestre e `proximo_par`, `proximo_fim` e
    `proximo_vencimento` do seguinte; None sem ancora (quem chama cai no calendario da CVM)."""
    conhecidos = {p: d for p, d in ((par_do_frame(k), data(v)) for k, v in (fim_periodo or {}).items()) if p and d}
    if not conhecidos:
        return None
    h = data(hoje) or _dt.date.today()
    ancora = max(conhecidos)
    fim0 = conhecidos[ancora]

    def fim_de(k):
        return conhecidos.get(somar_trimestres(ancora, k)) or fim_seguinte(fim0, k)

    def venc_de(k):
        f = fim_de(k)
        return f + _dt.timedelta(days=prazo_dias(f, fim_exercicio))

    k = 1
    while venc_de(k) <= h:          # a ancora pode ser velha (XBRL parado): anda ate o primeiro nao vencido
        k += 1
    for k in range(k, -9, -1):
        if h >= venc_de(k):
            return {"par": somar_trimestres(ancora, k), "fim": fim_de(k), "vencimento": venc_de(k),
                    "proximo_par": somar_trimestres(ancora, k + 1), "proximo_fim": fim_de(k + 1),
                    "proximo_vencimento": venc_de(k + 1),
                    "proximo_e_10k": fecha_exercicio(fim_de(k + 1), fim_exercicio), "ancora": ancora}
    return None


def fins_do_yahoo(demonstracoes):
    """{'CY2026Q2': '2026-07-31', ...} pelas colunas da DRE trimestral do Yahoo.

    Plano B para JSON gravado antes de o coletor guardar as datas do XBRL. O Yahoo arredonda para o fim
    do mes (a Marvell fecha em 01/08 e ele mostra 31/07): erro de dias, que o prazo de 45 cobre. So a
    data entra na conta; nenhum numero do Yahoo vira dado oficial."""
    dre = (demonstracoes or {}).get("dre_trimestral") or {}
    datas = set()
    for linha in dre.values():
        if isinstance(linha, dict):
            datas.update(k for k, v in linha.items() if v is not None and data(k))
    out = {}
    for d in sorted(datas):
        p = frame_da_data(d)
        if p:
            out[f"CY{p[0]}Q{p[1]}"] = d
    return out


def q4_fiscal(periodos):
    """{(ano, tri): (valor, fim)} do 4T fiscal: o exercicio menos os tres trimestres dele.

    `periodos` = [(inicio, fim, valor, entregue_em), ...] de uma conta de fluxo do companyfacts. Quem fecha
    o ano em dezembro tem o 4T derivado pelos frames do calendario; quem nao fecha (Broadcom, Ciena,
    Coherent, Lumentum) ficava sem o 4T e, por isso, sem os 12 meses. Aqui o exercicio e os trimestres
    se casam pelas datas reais."""
    tris, anos = {}, {}
    for ini, fim, val, entregue in periodos:
        a, b = data(ini), data(fim)
        if not a or not b or val is None:
            continue
        dias = (b - a).days
        alvo = tris if 80 <= dias <= 100 else anos if 350 <= dias <= 380 else None
        if alvo is None:
            continue
        chave = (a, b)
        if chave not in alvo or str(entregue or "") > alvo[chave][1]:
            alvo[chave] = (val, str(entregue or ""))
    out = {}
    for (ini, fim), (total, _) in anos.items():
        dentro = {}
        for (a, b), (v, _) in tris.items():
            if a >= ini - _dt.timedelta(days=3) and b < fim - _dt.timedelta(days=60):
                dentro[b] = (a, v)          # um trimestre por data de fim
        if len(dentro) != 3:
            continue
        fins = sorted(dentro)
        if abs((dentro[fins[0]][0] - ini).days) > 7:
            continue
        # os tres trimestres tem de ser seguidos: o inicio de cada um logo depois do fim do anterior
        if any(abs((dentro[fins[i + 1]][0] - fins[i]).days) > 7 for i in range(2)):
            continue
        par = frame_da_data(fim)
        if par:
            out[par] = (total - sum(dentro[f][1] for f in fins), fim.isoformat())
    return out
