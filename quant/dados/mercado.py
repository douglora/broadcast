"""
Mercado e mecanica do futuro de indice (M8-hedge): excesso do mercado, nivel do Ibovespa,
nocional do WIN, retorno do hedge vendido e beta movel da carteira.

Por que existe: a carteira do plano e long-only em acoes com HEDGE PARCIAL DE BETA em
mini-indice (WIN). Para simular esse hedge o backtest precisa de tres coisas que nenhum
outro modulo do pacote entrega:

  (1) a serie diaria do EXCESSO de retorno do mercado sobre o CDI. Um futuro de indice
      TOTALMENTE COLATERALIZADO paga exatamente isso: quem compra ganha a variacao do
      indice e abre mao do CDI da margem; quem vende ganha o CDI e paga a variacao. Por
      isso o retorno de um hedge vendido e -(excesso) x nocional / patrimonio, e nao
      -(retorno do indice);
  (2) o NIVEL do indice, porque o tamanho do contrato NAO e uma fracao do patrimonio: e
      nivel x R$0,20 (WIN). Com o indice em 125.000 pontos um WIN vale R$25.000, ou seja
      25% de uma carteira de R$100 mil - o hedge e quantizado em passos grossos e o
      backtest precisa do nivel data a data para saber quantos contratos cabem;
  (3) o BETA MOVEL da carteira contra o mercado, que dita quantos contratos vender.

Fontes do excesso
  Fonte 1 (PADRAO): Rm_minus_Rf do NEFIN (quant/dados/nefin.py), decimal diario desde
    2001-01-02, fixado por hash (pin). Por definicao do NEFIN e "carteira de mercado menos
    taxa livre de risco (CDI)" - a mesma coisa que o futuro paga. Nao depende de rede
    porque o snapshot fica versionado em quant/dados_brutos/nefin/.
  Fonte 2 (CONFERENCIA): retorno do ^BVSP menos o CDI diario (quant/dados/cdi.py). So
    existe quando ha rede e NUNCA e dependencia - serve para comparar_fontes() dizer se as
    duas contam a mesma historia.
  O IBOVESPA JA E UM INDICE DE RETORNO TOTAL: a carteira teorica reinveste os proventos
  das acoes que a compoem, entao ret_total == ret_preco para o indice. Nao existe (e nao se
  deve procurar) uma serie "Ibovespa com dividendos" separada; o que existe e o IBXX/IBOV
  em outras moedas, que nao interessa aqui.

SUPOSICOES QUE PRECISAM SER VALIDADAS COM FONTE REAL (anotar em
quant/docs/validar-com-fonte-real.md):

  - NIVEL_ANCORA = 125.000 pontos em 30/12/2021. E o unico numero deste modulo que vem de
    memoria, sem fonte. ELE ESCALA O NOCIONAL INTEIRO DO HEDGE POR UMA CONSTANTE: se o
    nivel verdadeiro for 105.000, todo nocional calculado aqui esta ~19% alto, o hedge
    simulado fica ~19% maior que o real e o erro e SISTEMATICO (viesa o resultado do
    backtest numa direcao), nao ruido que se dilui na amostra. De memoria, o fechamento
    real do Ibovespa em 30/12/2021 fica perto de 105.000 pontos, ou seja a constante
    provavelmente esta errada. Ela nao foi alterada porque a especificacao a fixou:
    CORRIJA com o fechamento oficial (B3, ou baixar_ibov_yahoo() com rede) ANTES de tirar
    qualquer conclusao do backtest com hedge.
  - O NIVEL COMPOSTO AQUI NAO E A TRAJETORIA DO IBOVESPA. A carteira de mercado do NEFIN e
    ponderada por valor com todas as acoes elegiveis, nao a carteira teorica do Ibovespa;
    compondo o excesso + CDI para tras desde a ancora de 30/12/2021, este modulo devolve
    ~58.000 pontos em 20/05/2008 e ~44.000 em 26/01/2016, enquanto o Ibovespa real fechou
    perto de 73.500 e 37.500 nessas datas (numeros de memoria, conferir). O erro nao e so de
    escala: a forma da serie tambem difere. Consequencia pratica: no passado distante o
    numero de contratos dimensionado pelo nocional pode errar por dezenas de por cento. O
    retorno POR CONTRATO continua certo (ele vem do excesso, nao do nivel). Correcao devida:
    usar fechamentos reais do ^BVSP para o nivel e o NEFIN so para o excesso.
  - VALOR_PONTO_WIN = R$0,20 por ponto do mini-indice (o IND cheio e R$1,00). Conferir no
    contrato da B3, junto com o lote minimo (1 contrato) e o passo de cotacao (5 pontos,
    que este modulo IGNORA - nocional_win nao arredonda o nivel para o tick).
  - Margem, custo de rolagem, taxa de registro/emolumento e o spread entre o futuro e o
    indice a vista (base) NAO estao aqui. O futuro negocia com base positiva/negativa que
    se fecha no vencimento; tratar o futuro como "excesso puro" ignora essa base e o custo
    de rolar a cada dois meses. Isso pertence a quant/custos.py e ao backtest.
  - As datas de vencimento vem de calendario.vencimento_indice (regra "quarta mais proxima
    do dia 15 dos meses pares", tambem uma suposicao - ver o docstring de la).
  - A serie do NEFIN sofre revisao retroativa entre snapshots: o excesso usado num backtest
    so e reproduzivel citando o pin (attrs["pin"]), que este modulo propaga.
  - Yahoo (^BVSP): endpoint /v8/finance/chart nao e API documentada, pode mudar de formato,
    exigir cookie/crumb ou devolver 429. Os timestamps sao segundos epoch da ABERTURA da
    sessao; convertemos com fuso fixo -03:00 (o Brasil nao tem mais horario de verao desde
    2019, mas series anteriores a 2019 podem cair no dia errado se o Yahoo carimbar a
    abertura em horario de verao - conferir alguma data de janeiro antes de 2019).
  - Nada aqui e point-in-time no sentido de "so entra o que ja estava publicado": o nivel do
    indice e composto para tras a partir da ancora, entao a serie de nivel depende de dados
    posteriores a cada data. Isso e inofensivo para dimensionar o nocional (o nivel de t so
    usa retornos ate t, a menos de uma constante multiplicativa), mas a CONSTANTE vem do
    futuro em relacao ao inicio da amostra - mais um motivo para acertar NIVEL_ANCORA.

Convencoes (iguais as do resto do pacote): Series float com DatetimeIndex chamado "data",
attrs["fonte"] com a origem, entrada vazia devolve a mesma forma vazia, nada levanta
excecao por causa de rede (comum.http_get devolve None).

Uso: python3 -m quant.dados.mercado --patrimonio 100000 --contratos 1
"""
import argparse
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

from quant.comum import FUSO_BRT, http_get, log
from quant.dados import calendario, cdi, nefin

NIVEL_ANCORA = 104_822.0            # fechamento do Ibovespa em 30/12/2021 (SUPOSICAO: de
                                    # memoria, CONFERIR. Escala o nocional do hedge inteiro:
                                    # errar aqui e vies sistematico, nao ruido.)
DATA_ANCORA = date(2021, 12, 30)
VALOR_PONTO_WIN = 0.20              # R$ por ponto do mini-indice (IND cheio: 1.00)
VALOR_PONTO_IND = 1.00
COLUNA_FATOR_MERCADO = "Rm_minus_Rf"
JANELA_BETA = 60                    # pregoes (~3 meses) na janela do beta movel
MIN_PERIODOS_BETA = 40
DIAS_UTEIS_ANO = 252
DATA_INICIAL = date(2001, 1, 2)     # inicio dos fatores NEFIN
HOSTS_YAHOO = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
URL_YAHOO = ("https://{host}/v8/finance/chart/%5EBVSP"
             "?period1={ini}&period2={fim}&interval=1d")


# ─────────────────────────────────────────────────────────────
# Funcoes puras
# ─────────────────────────────────────────────────────────────
def _para_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return pd.Timestamp(d).date()


def _serie_vazia(nome):
    s = pd.Series(dtype=float, name=nome)
    s.index = pd.DatetimeIndex([], name="data")
    return s


def _eh_escalar(x):
    return not isinstance(x, (pd.Series, pd.DataFrame, dict, list, tuple, np.ndarray))


def _serie_attr(x, chave, padrao=None):
    """attrs.get tolerante: escalares e objetos sem attrs devolvem o padrao."""
    try:
        return x.attrs.get(chave, padrao)
    except AttributeError:
        return padrao


def _serie(x, nome="valor"):
    """Series float com DatetimeIndex "data", ordenada e sem datas repetidas.

    Aceita Series indexada por data, DataFrame (usa a coluna 'fec', ou 'data'+'fec', ou a
    ultima coluna), dict {data: valor} e None. Linhas com data ou valor invalido caem fora.
    Entrada vazia devolve a serie vazia com o mesmo schema. Os attrs da entrada (a
    procedencia: fonte, pin) sao preservados - pandas nao garante isso sozinho.
    """
    if x is None:
        return _serie_vazia(nome)
    if isinstance(x, pd.DataFrame):
        if x.shape[1] == 0:
            return _serie_vazia(nome)
        col = "fec" if "fec" in x.columns else [c for c in x.columns if c != "data"][-1]
        valores = pd.to_numeric(x[col], errors="coerce")
        idx = pd.to_datetime(x["data"], errors="coerce") if "data" in x.columns \
            else pd.to_datetime(x.index, errors="coerce")
        s = pd.Series(np.asarray(valores, dtype=float), index=pd.DatetimeIndex(idx))
    elif isinstance(x, pd.Series):
        s = pd.Series(pd.to_numeric(x, errors="coerce").values,
                      index=pd.DatetimeIndex(pd.to_datetime(x.index, errors="coerce")))
    else:
        s = pd.Series(x, dtype=float)
        s.index = pd.DatetimeIndex(pd.to_datetime(s.index, errors="coerce"))
    s = s[s.index.notna()]
    s = s[~s.index.duplicated(keep="last")].sort_index().astype(float)
    s.index = pd.DatetimeIndex(s.index, name="data")
    s.name = nome
    s.attrs.update(getattr(x, "attrs", None) or {})
    return s


def _indice_comum(valores):
    """Intersecao dos indices dos argumentos que sao Series/DataFrame; None se todos escalares."""
    idx = None
    for v in valores:
        if _eh_escalar(v):
            continue
        s = _serie(v)
        idx = s.index if idx is None else idx.intersection(s.index)
    return idx


def _expandir(v, idx, nome):
    """Escalar -> Series constante em idx; Series -> reindexada em idx. idx None -> float."""
    if idx is None:
        return float(v)
    if _eh_escalar(v):
        return pd.Series(float(v), index=idx, name=nome)
    return _serie(v, nome).reindex(idx)


def _alinhar(a, b, nome_a="a", nome_b="b"):
    """Duas Series na intersecao das datas (b pode ser escalar: vira constante)."""
    sa = _serie(a, nome_a)
    if _eh_escalar(b):
        return sa, pd.Series(float(b), index=sa.index, name=nome_b)
    sb = _serie(b, nome_b)
    idx = sa.index.intersection(sb.index)
    return sa.reindex(idx), sb.reindex(idx)


def _recorte(serie, ini=None, fim=None):
    """Recorte fechado [ini, fim] mantendo os attrs (procedencia) da serie original."""
    s = _serie(serie, serie.name if isinstance(serie, pd.Series) and serie.name else "valor")
    attrs = dict(s.attrs)
    if ini is not None:
        s = s[s.index >= pd.Timestamp(_para_date(ini))]
    if fim is not None:
        s = s[s.index <= pd.Timestamp(_para_date(fim))]
    s.attrs.update(attrs)
    return s


def retornos_ibov(ibov):
    """Retorno diario simples a partir da serie de NIVEL de fechamento do Ibovespa.

    Aceita o DataFrame (data, fec) do baixar_ibov_yahoo ou uma Series de niveis. Como o
    Ibovespa ja e indice de retorno total (reinveste os proventos da carteira teorica),
    isto E o retorno total: nao ha provento a somar por fora.
    """
    s = _serie(ibov, "ibov")
    if len(s) < 2:
        return _serie_vazia("ret_ibov")
    r = s.pct_change().dropna()
    r.name = "ret_ibov"
    r.index.name = "data"
    return r


def nivel_indice(excesso, cdi, nivel_ancora=NIVEL_ANCORA, data_ancora=DATA_ANCORA):
    """Serie do nivel do indice composta a partir de (1 + excesso + cdi) e ancorada num
    nivel conhecido em data_ancora.

    Necessaria porque o nocional do WIN e nivel x R$0,20: sem o nivel nao da para saber
    quantos contratos cabem no patrimonio nem quanto de beta cada contrato remove.

    excesso: Series diaria do excesso do mercado (excesso_mercado()).
    cdi:     Series diaria do CDI em decimal, OU um escalar (taxa constante). ATENCAO - este
             parametro sombreia o modulo quant.dados.cdi dentro desta funcao; e de proposito,
             a API pede o nome `cdi`.
    A composicao usa apenas as datas presentes NAS DUAS series (intersecao): um dia sem CDI
    nao entra, para nao inventar retorno.

    Ancoragem: nivel[data_ancora] == nivel_ancora exatamente. Se data_ancora nao for um dia
    da serie, usa o ultimo dia disponivel antes dela (attrs["data_ancora_efetiva"] registra
    qual foi). Se a serie comeca depois da ancora, ancora no primeiro dia e avisa no log -
    nesse caso o nivel esta deslocado por um fator constante e o nocional sai errado.

    O nivel de t so depende de retornos ate t a menos dessa constante multiplicativa; a
    constante, porem, vem de uma data que pode estar no futuro em relacao ao inicio da
    amostra. E, com o excesso do NEFIN, a serie e uma APROXIMACAO do Ibovespa, nao ele
    (ver as suposicoes no topo do modulo).
    """
    ex, taxa = _alinhar(excesso, cdi, "excesso", "cdi")
    total = (ex + taxa).astype(float).dropna()
    if len(total) == 0:
        return _serie_vazia("nivel")
    fator = (1.0 + total).cumprod()
    alvo = pd.Timestamp(_para_date(data_ancora))
    pos = int(fator.index.searchsorted(alvo, side="right")) - 1
    if pos < 0:
        log(f"mercado: serie comeca depois da ancora {alvo.date()}; ancorando no primeiro dia "
            f"({fator.index[0].date()}) - o nivel fica deslocado por uma constante")
        pos = 0
    nivel = (fator / float(fator.iloc[pos]) * float(nivel_ancora)).rename("nivel")
    nivel.index.name = "data"
    nivel.attrs.update({
        "fonte": _serie_attr(excesso, "fonte"),
        "nivel_ancora": float(nivel_ancora),
        "data_ancora": str(_para_date(data_ancora)),
        "data_ancora_efetiva": str(fator.index[pos].date()),
    })
    return nivel


def nocional_win(nivel, contratos=1, valor_ponto=VALOR_PONTO_WIN):
    """Valor nocional em R$ de `contratos` mini-indices com o indice em `nivel`.

    nocional = nivel x contratos x valor_ponto (WIN: R$0,20 por ponto; IND: R$1,00).
    Escalares devolvem float; qualquer Series devolve Series na intersecao das datas.
    Nao arredonda o nivel para o tick de 5 pontos nem cobra ajuste/margem.
    """
    idx = _indice_comum([nivel, contratos])
    nv = _expandir(nivel, idx, "nivel")
    ct = _expandir(contratos, idx, "contratos")
    if idx is None:
        return float(nv) * float(ct) * float(valor_ponto)
    out = (nv * ct * float(valor_ponto)).rename("nocional")
    out.index.name = "data"
    return out


def retorno_hedge(excesso, contratos, nivel, patrimonio, valor_ponto=VALOR_PONTO_WIN):
    """Retorno do hedge VENDIDO sobre o patrimonio: -(excesso) * nocional / patrimonio.

    contratos > 0 significa contratos VENDIDOS (o hedge de uma carteira comprada); um
    numero negativo devolve a ponta comprada. Aceita escalares ou Series alinhadas (a
    intersecao das datas manda).

    Por que o excesso e nao o retorno do indice: o futuro colateralizado paga indice - CDI.
    Vendido, o resultado sobre a margem e -(indice - CDI) = -excesso.

    ALINHAMENTO E RESPONSABILIDADE DE QUEM CHAMA: no dia t o nocional e o patrimonio que
    valem sao os do FECHAMENTO DE t-1 (a posicao ja estava montada quando o mercado andou).
    Passe nivel e patrimonio ja defasados (.shift(1)) se quiser essa convencao.
    patrimonio zero, negativo ou nao finito devolve NaN em vez de estourar.
    """
    idx = _indice_comum([excesso, contratos, nivel, patrimonio])
    ex = _expandir(excesso, idx, "excesso")
    ct = _expandir(contratos, idx, "contratos")
    nv = _expandir(nivel, idx, "nivel")
    pt = _expandir(patrimonio, idx, "patrimonio")
    noc = nocional_win(nv, ct, valor_ponto)
    if idx is None:
        if not np.isfinite(pt) or pt <= 0.0:
            return float("nan")
        return -float(ex) * float(noc) / float(pt)
    pt = pt.where(np.isfinite(pt) & (pt > 0.0))
    out = (-ex * noc / pt).rename("ret_hedge")
    out.index.name = "data"
    return out


def contratos_para_beta(beta_alvo, beta_carteira, patrimonio, nivel,
                        valor_ponto=VALOR_PONTO_WIN):
    """Quantos WIN vender para levar o beta da carteira de beta_carteira ate beta_alvo.

    contratos = (beta_carteira - beta_alvo) * patrimonio / (nivel * valor_ponto), arredondado
    para o inteiro mais proximo - o contrato e indivisivel, e e por isso que o hedge de uma
    carteira pequena so consegue beta em passos grossos (com o indice em 125.000 pontos, um
    WIN e R$25.000 de nocional).
    """
    noc = nocional_win(nivel, 1, valor_ponto)
    if _eh_escalar(noc):
        if not np.isfinite(noc) or noc <= 0:
            return 0
        return int(round((float(beta_carteira) - float(beta_alvo)) * float(patrimonio) / noc))
    bruto = (_expandir(beta_carteira, noc.index, "beta") - float(beta_alvo)) \
        * _expandir(patrimonio, noc.index, "patrimonio") / noc.where(noc > 0)
    return bruto.round().rename("contratos")


def beta_movel(retorno_carteira, excesso, janela=JANELA_BETA, min_periodos=MIN_PERIODOS_BETA):
    """Beta movel da carteira contra o excesso do mercado: cov(carteira, excesso)/var(excesso)
    na janela de `janela` pregoes, NaN ate haver `min_periodos` observacoes.

    E a estimativa mais crua possivel de proposito: ela e usada so para dimensionar o hedge,
    e um beta estimado com erro de 0,1 num hedge parcial custa pouco. Janela curta reage a
    mudanca de composicao da carteira; janela longa e mais estavel. Nao ha shrinkage nem
    correcao de nao-sincronismo (Dimson) - papel iliquido tem beta subestimado.
    """
    a, b = _alinhar(retorno_carteira, excesso, "carteira", "excesso")
    if len(a) == 0:
        return _serie_vazia("beta")
    cov = a.rolling(janela, min_periods=min_periodos).cov(b)
    var = b.rolling(janela, min_periods=min_periodos).var()
    beta = (cov / var.where(var > 0)).rename("beta")
    beta.index.name = "data"
    return beta


def parse_chart_yahoo(dados):
    """JSON do endpoint /v8/finance/chart -> DataFrame (data, fec). Nunca levanta.

    Formato esperado: {"chart": {"result": [{"timestamp": [epoch...], "indicators":
    {"quote": [{"close": [...]}]}}], "error": null}}. Fechamentos nulos (pregao sem dado)
    caem fora. Os timestamps sao a ABERTURA da sessao em epoch UTC; convertidos para o fuso
    -03:00 e truncados para a data (ver suposicoes no topo).
    """
    vazio = pd.DataFrame({"data": pd.Series(dtype="datetime64[ns]"), "fec": pd.Series(dtype=float)})
    if isinstance(dados, (str, bytes)):
        try:
            import json
            dados = json.loads(dados)
        except Exception:
            return vazio
    try:
        resultado = dados["chart"]["result"][0]
        ts = list(resultado["timestamp"])
        fec = list(resultado["indicators"]["quote"][0]["close"])
    except Exception:
        return vazio
    if not ts or len(ts) != len(fec):
        return vazio
    idx = pd.to_datetime(pd.Series(ts), unit="s", utc=True, errors="coerce")
    idx = idx.dt.tz_convert(FUSO_BRT).dt.tz_localize(None).dt.normalize()
    df = pd.DataFrame({"data": idx, "fec": pd.to_numeric(pd.Series(fec), errors="coerce")})
    df = df[df["data"].notna() & df["fec"].notna()]
    df = df.drop_duplicates(subset="data", keep="last").sort_values("data").reset_index(drop=True)
    return df


def comparar_fontes(excesso_nefin, ibov, cdi):
    """Confere a fonte 1 (NEFIN) contra a fonte 2 (Ibovespa - CDI) nas datas em comum.

    Devolve dict com dias, periodo, correlacao, media anualizada de cada uma e a diferenca
    (nefin - ibov) em p.p. ao ano. O que se espera de um par sadio: correlacao > 0,98 e
    diferenca de media anual dentro de ~1 p.p. (o NEFIN usa uma carteira de mercado ponderada
    por valor de TODAS as acoes elegiveis, nao a carteira teorica do Ibovespa, entao alguma
    diferenca e esperada e nao e bug). Sem datas em comum, devolve NaN em tudo.
    """
    ret = retornos_ibov(ibov)
    a, b = _alinhar(ret, cdi, "ret_ibov", "cdi")
    ex_ibov = (a - b).rename("excesso_ibov")
    x, y = _alinhar(excesso_nefin, ex_ibov, "excesso_nefin", "excesso_ibov")
    ok = x.notna() & y.notna()
    x, y = x[ok], y[ok]
    if len(x) == 0:
        return {"dias": 0, "ini": None, "fim": None, "correlacao": float("nan"),
                "media_aa_nefin": float("nan"), "media_aa_ibov": float("nan"),
                "dif_media_aa": float("nan"), "vol_aa_nefin": float("nan"),
                "vol_aa_ibov": float("nan")}
    media_n, media_i = float(x.mean()) * DIAS_UTEIS_ANO, float(y.mean()) * DIAS_UTEIS_ANO
    return {
        "dias": int(len(x)),
        "ini": str(x.index.min().date()), "fim": str(x.index.max().date()),
        "correlacao": float(x.corr(y)) if len(x) > 1 else float("nan"),
        "media_aa_nefin": media_n, "media_aa_ibov": media_i,
        "dif_media_aa": media_n - media_i,
        "vol_aa_nefin": float(x.std(ddof=1)) * np.sqrt(DIAS_UTEIS_ANO) if len(x) > 1 else float("nan"),
        "vol_aa_ibov": float(y.std(ddof=1)) * np.sqrt(DIAS_UTEIS_ANO) if len(y) > 1 else float("nan"),
    }


# ─────────────────────────────────────────────────────────────
# Fontes (disco e rede)
# ─────────────────────────────────────────────────────────────
def excesso_mercado(fatores=None, ibov=None, taxa_cdi=None):
    """Series diaria do excesso de retorno do mercado sobre o CDI.

    Fonte 1 (padrao): nefin.carregar_fatores()['Rm_minus_Rf'] - por definicao e o que um
    futuro de indice totalmente colateralizado paga. Fonte 2: uma serie de retorno total
    do Ibovespa menos o CDI, quando existir. attrs['fonte'] registra qual foi usada.

    fatores:   DataFrame do NEFIN ja carregado (ou Series de Rm_minus_Rf). None = carrega o
               ultimo snapshot local; sem snapshot, devolve a serie VAZIA e loga (nunca
               levanta) - rode nefin.baixar('fatores') com rede.
    ibov:      se dado, usa a fonte 2 (DataFrame (data, fec) ou Series de niveis).
    taxa_cdi:  CDI diario para descontar do Ibovespa. So e usado com `ibov`. None = pega de
               cdi.carregar(permitir_rede=False), para nao ir a rede sem pedir. Este e o
               unico argumento fora da assinatura original (excesso_mercado(fatores, ibov)):
               existe para que a fonte 2 nao busque o CDI por baixo dos panos, o que
               tornaria o resultado dependente do cache da maquina.
    """
    if ibov is not None:
        ret = retornos_ibov(ibov)
        if taxa_cdi is None:
            taxa_cdi = cdi.carregar(permitir_rede=False)
        if taxa_cdi is None:
            log("mercado: sem CDI para descontar do Ibovespa; excesso vazio")
            s = _serie_vazia("excesso_mercado")
            s.attrs["fonte"] = "indisponivel"
            return s
        a, b = _alinhar(ret, taxa_cdi, "ret_ibov", "cdi")
        s = (a - b).rename("excesso_mercado")
        s.index.name = "data"
        s.attrs["fonte"] = "ibov_menos_cdi"
        s.attrs["fonte_cdi"] = _serie_attr(taxa_cdi, "fonte")
        return s
    pin = None
    if fatores is None:
        try:
            fatores = nefin.carregar_fatores()
        except Exception as e:
            log(f"mercado: sem snapshot NEFIN ({type(e).__name__}); "
                f"rode nefin.baixar('fatores') - excesso vazio")
            s = _serie_vazia("excesso_mercado")
            s.attrs["fonte"] = "indisponivel"
            return s
    if isinstance(fatores, pd.DataFrame):
        pin = fatores.attrs.get("pin")
        if COLUNA_FATOR_MERCADO not in fatores.columns:
            log(f"mercado: DataFrame sem a coluna {COLUNA_FATOR_MERCADO}; excesso vazio")
            s = _serie_vazia("excesso_mercado")
            s.attrs["fonte"] = "indisponivel"
            return s
        fatores = fatores[COLUNA_FATOR_MERCADO]
    s = _serie(fatores, "excesso_mercado")
    s.attrs["fonte"] = "nefin"
    s.attrs["pin"] = pin
    s.attrs["avail_date"] = (pin or {}).get("avail_date")
    return s


def baixar_ibov_yahoo(ini=None, fim=None):
    """Conferencia opcional: ^BVSP pelo endpoint de chart do Yahoo. Devolve DataFrame
    (data, fec) ou None. NUNCA e dependencia: o padrao e o NEFIN.

    Tenta query1 e depois query2 (o mesmo servico atras de dois hosts). Sem rede, com 4xx
    ou com JSON fora do formato, devolve None e loga - nao levanta.
    """
    ini = _para_date(ini) or DATA_INICIAL
    fim = _para_date(fim) or date.today()
    p1 = int(datetime(ini.year, ini.month, ini.day, tzinfo=FUSO_BRT).timestamp())
    p2 = int(datetime(fim.year, fim.month, fim.day, tzinfo=FUSO_BRT).timestamp()) + 86400
    for host in HOSTS_YAHOO:
        r = http_get(URL_YAHOO.format(host=host, ini=p1, fim=p2), timeout=30, tentativas=2,
                     headers={"Accept": "application/json"})
        if r is None:
            continue
        try:
            bruto = r.json()
        except Exception:
            log(f"mercado: resposta do {host} nao e JSON")
            continue
        df = parse_chart_yahoo(bruto)
        if len(df):
            log(f"mercado: ^BVSP {len(df)} pregoes ({df['data'].min().date()}..{df['data'].max().date()})")
            return df
        log(f"mercado: {host} devolveu chart vazio")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Serie de mercado (excesso, nivel do indice) e mecanica do hedge em WIN")
    ap.add_argument("--ini", default=None, help="data inicial (AAAA-MM-DD)")
    ap.add_argument("--fim", default=None, help="data final (AAAA-MM-DD)")
    ap.add_argument("--patrimonio", type=float, default=100_000.0)
    ap.add_argument("--contratos", type=int, default=1)
    ap.add_argument("--beta-alvo", type=float, default=0.3, help="beta residual desejado")
    ap.add_argument("--yahoo", action="store_true",
                    help="compara com o ^BVSP do Yahoo (precisa de rede)")
    ap.add_argument("--sem-rede", action="store_true",
                    help="nao tenta baixar o CDI do BCB (usa cache ou o Risk_Free do NEFIN)")
    args = ap.parse_args(argv)

    ex = excesso_mercado()
    if len(ex) == 0:
        log("mercado: sem serie de excesso; rode nefin.baixar('fatores') com rede")
        return 1
    ex = _recorte(ex, args.ini, args.fim)
    taxa = cdi.carregar(args.ini, args.fim, permitir_rede=not args.sem_rede)
    if taxa is None:
        log("mercado: sem CDI (nem cache nem NEFIN); compondo o nivel so com o excesso (ERRADO)")
        taxa = 0.0
    nivel = nivel_indice(ex, taxa)
    ultimo = float(nivel.iloc[-1])
    print(f"excesso: fonte={ex.attrs.get('fonte')} pin={(ex.attrs.get('pin') or {}).get('sha256', '')[:12]} "
          f"{ex.index.min().date()}..{ex.index.max().date()} ({len(ex)} pregoes)")
    print(f"  media {ex.mean() * DIAS_UTEIS_ANO:+.2%} a.a., vol {ex.std(ddof=1) * np.sqrt(DIAS_UTEIS_ANO):.2%} a.a.")
    print(f"nivel: ancora {nivel.attrs['nivel_ancora']:,.0f} em {nivel.attrs['data_ancora_efetiva']} "
          f"(SUPOSICAO) -> {nivel.index[-1].date()} = {ultimo:,.0f} pontos")
    print(f"WIN: 1 contrato = {nocional_win(ultimo):,.2f} R$ de nocional "
          f"({nocional_win(ultimo) / args.patrimonio:.1%} de R$ {args.patrimonio:,.0f})")
    print(f"hedge de {args.contratos} contrato(s) no ultimo pregao: "
          f"{retorno_hedge(float(ex.iloc[-1]), args.contratos, ultimo, args.patrimonio):+.4%}")
    print(f"para beta {args.beta_alvo:.2f} com carteira beta 1,0: "
          f"{contratos_para_beta(args.beta_alvo, 1.0, args.patrimonio, ultimo)} contrato(s) vendido(s)")
    hoje = date.today()
    print(f"proximo vencimento de indice depois de {hoje}: "
          f"{calendario.proximo_vencimento_indice(hoje)}")
    if args.yahoo:
        ibov = baixar_ibov_yahoo(args.ini or DATA_INICIAL, args.fim)
        if ibov is None:
            log("mercado: Yahoo indisponivel; comparacao de fontes nao feita")
            return 0
        comp = comparar_fontes(ex, ibov, taxa)
        print(f"conferencia NEFIN x (Ibovespa - CDI): {comp['dias']} dias em comum "
              f"({comp['ini']}..{comp['fim']}), correlacao {comp['correlacao']:.4f}, "
              f"media {comp['media_aa_nefin']:+.2%} x {comp['media_aa_ibov']:+.2%} a.a. "
              f"(diferenca {comp['dif_media_aa']:+.2%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
