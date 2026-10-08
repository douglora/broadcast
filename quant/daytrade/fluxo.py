"""
Leitura de fluxo (a "fita" e o livro de ofertas) para o robo de day trade.

DE ONDE VEM. O robo do MetaTrader (AutopilotFeed 1.3) grava, para os simbolos de
`autopilot_tape.txt`:
  - `autopilot_fita_AAAAMMDD.csv`: negocios somados por segundo e por preco, com o lado de
    quem AGREDIU (comprou a mercado ou vendeu a mercado). Linha:
        F;SIMBOLO;segundo;preco;vol_compra;vol_venda;vol_indef;negocios;maior_compra;maior_venda;idade_ms;
          compra_media;venda_media;compra_grande;venda_grande
    Os quatro ultimos separam o volume por TAMANHO DO NEGOCIO: "media" soma so negocios de 10
    contratos ou mais, "grande" so os de 50 ou mais. Quem le fluxo no contrato cheio descarta o
    lote minimo (5 contratos, "lote de robo") e chama 50 de lote de instituicao.
  - `autopilot_livro.csv`: a foto do livro de ofertas, do melhor preco para o pior:
        L;SIMBOLO;C;preco;qtd;...;V;preco;qtd;...

O QUE ESTE MODULO ENTREGA. As medidas que um leitor de fluxo olha, em numero:
  - agressao compradora e vendedora numa janela, e o saldo entre elas (o "delta");
  - quanto se negociou em cada preco, por lado agressor (onde houve briga);
  - ABSORCAO num nivel: muita agressao contra o nivel e o preco nao passa;
  - o maior lote que agrediu em cada lado;
  - o tamanho das ofertas paradas nos primeiros niveis do livro.

O QUE ELE NAO TEM, e nao ha como ter por aqui: QUEM e a corretora de cada negocio. O
MetaTrader nao entrega esse codigo. Toda leitura que depende de "a XP esta comprando" fica
de fora; o que sobra e a leitura por preco, volume e lado agressor.

Tudo aqui e conta sobre listas: o teste entrega linhas escritas a mao.
"""
import os
from collections import deque

PASTA_MT5 = os.path.expanduser(os.environ.get(
    "QUANT_MT5_FILES",
    "~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Files"))
ARQ_TAPE = "autopilot_tape.txt"
ARQ_LIVRO = "autopilot_livro.csv"
PREFIXO_FITA = "autopilot_fita_"
JANELA_MAXIMA_S = 3 * 3600          # quanto de fita cada simbolo guarda na memoria


def _f(x, padrao=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return padrao


def linha_da_fita(texto):
    """'F;SIMBOLO;seg;preco;vc;vv;vn;neg;mc;mv;idade' -> dict, ou None se a linha nao serve."""
    c = texto.strip().split(";")
    if len(c) < 10 or c[0] != "F":
        return None
    preco = _f(c[3])
    if preco <= 0:
        return None
    d = {"simbolo": c[1], "seg": int(_f(c[2])), "preco": preco, "compra": _f(c[4]), "venda": _f(c[5]),
         "indef": _f(c[6]), "negocios": int(_f(c[7])), "maior_compra": _f(c[8]), "maior_venda": _f(c[9]),
         "idade_ms": _f(c[10]) if len(c) > 10 else 0.0}
    if len(c) >= 15:                         # fita que separa o tamanho do negocio
        d.update(compra_media=_f(c[11]), venda_media=_f(c[12]), compra_grande=_f(c[13]), venda_grande=_f(c[14]))
    return d


def ler_livro(texto):
    """Foto do livro -> {simbolo: {"compra": [(preco, qtd)...], "venda": [(preco, qtd)...]}}.
    Foto sem '#FIM' (o MetaTrader estava gravando) e ignorada: devolve {}."""
    linhas = [x.strip() for x in (texto or "").splitlines() if x.strip()]
    if len(linhas) < 2 or not linhas[0].startswith("#LIVRO") or linhas[-1] != "#FIM":
        return {}
    fora = {}
    for ln in linhas[1:-1]:
        c = ln.split(";")
        if len(c) < 4 or c[0] != "L":
            continue
        lados, lado = {"C": [], "V": []}, None
        i = 2
        while i < len(c):
            if c[i] in ("C", "V"):
                lado = c[i]
                i += 1
                continue
            if lado and i + 1 < len(c):
                p, q = _f(c[i]), _f(c[i + 1])
                if p > 0 and q > 0:
                    lados[lado].append((p, q))
            i += 2
        fora[c[1]] = {"compra": lados["C"], "venda": lados["V"]}
    return fora


class Fita:
    """A fita de UM simbolo na memoria, com as medidas por janela."""

    def __init__(self, simbolo, tick, sem_lote_de_robo=False):
        self.simbolo = simbolo
        self.tick = float(tick)
        self.linhas = deque()                 # dicts de linha_da_fita, em ordem de segundo
        self.ultimo_seg = 0
        # True = le o contrato CHEIO como ele: a agressao so conta negocios de 10 contratos ou mais
        # (o lote de 5 e de robo) e os de 50 ou mais ficam marcados como lote de instituicao.
        self.sem_lote_de_robo = bool(sem_lote_de_robo)
        self.separa_tamanho = False           # vira True quando chega a primeira linha com os campos de tamanho

    def acrescentar(self, linha):
        if linha is None or linha["simbolo"] != self.simbolo:
            return
        if "compra_media" in linha:
            self.separa_tamanho = True
            if self.sem_lote_de_robo:
                linha = dict(linha, compra=linha["compra_media"], venda=linha["venda_media"])
        linha.setdefault("compra_grande", 0.0)
        linha.setdefault("venda_grande", 0.0)
        self.linhas.append(linha)
        self.ultimo_seg = max(self.ultimo_seg, linha["seg"])
        limite = self.ultimo_seg - JANELA_MAXIMA_S
        while self.linhas and self.linhas[0]["seg"] < limite:
            self.linhas.popleft()

    def _janela(self, segundos, ate=None):
        ate = self.ultimo_seg if ate is None else int(ate)
        ini = ate - int(segundos)
        return [x for x in self.linhas if ini < x["seg"] <= ate]

    def agressao(self, segundos, ate=None):
        """Volume de quem comprou a mercado, de quem vendeu a mercado, e o saldo, na janela."""
        j = self._janela(segundos, ate)
        c = sum(x["compra"] for x in j)
        v = sum(x["venda"] for x in j)
        total = c + v
        return {"compra": c, "venda": v, "saldo": c - v, "total": total,
                "fracao_compra": (c / total) if total > 0 else None,
                "compra_grande": sum(x["compra_grande"] for x in j), "venda_grande": sum(x["venda_grande"] for x in j),
                "negocios": sum(x["negocios"] for x in j),
                "maior_compra": max((x["maior_compra"] for x in j), default=0.0),
                "maior_venda": max((x["maior_venda"] for x in j), default=0.0),
                "minimo": min((x["preco"] for x in j), default=None),
                "maximo": max((x["preco"] for x in j), default=None),
                "ultimo": j[-1]["preco"] if j else None}

    def por_preco(self, segundos, ate=None):
        """{preco: {"compra", "venda"}} na janela: onde se negociou e quem agrediu em cada preco."""
        fora = {}
        for x in self._janela(segundos, ate):
            d = fora.setdefault(x["preco"], {"compra": 0.0, "venda": 0.0})
            d["compra"] += x["compra"]
            d["venda"] += x["venda"]
        return fora

    def volume_tipico(self, segundos, janelas=20, ate=None):
        """Mediana do volume agredido em janelas seguidas do mesmo tamanho: a regua do que e "muito" hoje.

        A leitura de fluxo fala em agressao "forte" sem dar numero. O numero muda de dia para dia
        e de hora para hora; a mediana das ultimas janelas e a referencia que acompanha o proprio dia.
        Devolve None enquanto nao houver pelo menos 5 janelas com negocio.
        """
        ate = self.ultimo_seg if ate is None else int(ate)
        vals = []
        for k in range(1, int(janelas) + 1):
            a = self.agressao(segundos, ate - k * int(segundos))
            if a["total"] > 0:
                vals.append(a["total"])
        if len(vals) < 5:
            return None
        vals.sort()
        return vals[len(vals) // 2]

    def amplitude_tipica(self, segundos=60, janelas=15, ate=None):
        """Mediana do vai-e-vem (maximo menos minimo) em janelas seguidas: a "frequencia" do mercado hoje.
        Ele calibra o tamanho do stop por isso: dia que anda muito pede stop mais longo. None sem 5 janelas."""
        ate = self.ultimo_seg if ate is None else int(ate)
        vals = []
        for k in range(int(janelas)):
            a = self.agressao(segundos, ate - k * int(segundos))
            if a["maximo"] is not None:
                vals.append(a["maximo"] - a["minimo"])
        if len(vals) < 5:
            return None
        vals.sort()
        return vals[len(vals) // 2]

    def corrida(self, segundos, ate=None):
        """O movimento que terminou num extremo, dentro da janela.

        {"alta": {"extremo", "seg_extremo", "origem", "tamanho"}, "baixa": {...}} ou None sem negocio.
        "alta": o preco mais alto da janela, a ULTIMA vez em que ele foi negociado, e o preco mais baixo
        visto ANTES dele (de onde a corrida saiu). "baixa" e o espelho.
        """
        j = self._janela(segundos, ate)
        if not j:
            return None
        fora = {}
        for nome, melhor, pior in (("alta", max, min), ("baixa", min, max)):
            extremo = melhor(x["preco"] for x in j)
            i_ext = max(i for i, x in enumerate(j) if x["preco"] == extremo)
            antes = [x["preco"] for x in j[:i_ext + 1]]
            origem = pior(antes)
            fora[nome] = {"extremo": extremo, "seg_extremo": j[i_ext]["seg"], "origem": origem, "tamanho": abs(extremo - origem)}
        return fora

    def testes(self, nivel, lado, segundos, ate=None, zona_ticks=1, afasta_ticks=3):
        """Quantas vezes o preco foi ao nivel na janela. Um teste so conta de novo depois de o preco
        se afastar `afasta_ticks` do nivel. lado="compra": nivel e suporte (o preco vem de cima)."""
        zona, afasta = zona_ticks * self.tick + 1e-9, afasta_ticks * self.tick - 1e-9
        n, fora = 0, True
        for x in self._janela(segundos, ate):
            d = (x["preco"] - nivel) if lado == "compra" else (nivel - x["preco"])
            if d <= zona:
                if fora:
                    n, fora = n + 1, False
            elif d >= afasta:
                fora = True
        return n

    def absorcao(self, nivel, lado, segundos, ate=None, folga_ticks=1, tolerancia_ticks=0):
        """Mede a defesa de um nivel na janela.

        lado="compra": o nivel e um SUPORTE. Conta o volume de quem VENDEU a mercado em precos ate
        `folga_ticks` acima do nivel, e ve se o preco passou para baixo dele. Muita venda agredindo
        e o preco nao perdendo o nivel e o que o leitor de fluxo chama de absorcao (alguem esta
        comprando tudo o que vendem ali). lado="venda" e o espelho, para uma RESISTENCIA.
        `tolerancia_ticks`: quantos ticks alem do nivel ainda nao contam como perder o nivel.
        Devolve {"agredido", "contra" (volume que foi a favor do nivel), "furou" (bool), "toques",
        "rodadas_grandes" (segundos em que um lote de instituicao bateu contra o nivel), "agredido_grande"}.
        """
        folga, tol = folga_ticks * self.tick, tolerancia_ticks * self.tick
        agredido = contra = grande = 0.0
        furou = False
        segundos_no_nivel, segundos_grandes = set(), set()
        for x in self._janela(segundos, ate):
            p = x["preco"]
            if lado == "compra":
                if p < nivel - tol - 1e-9:
                    furou = True
                if nivel - tol - 1e-9 <= p <= nivel + folga + 1e-9:
                    agredido += x["venda"]
                    contra += x["compra"]
                    segundos_no_nivel.add(x["seg"])
                    if x["venda_grande"] > 0:
                        grande += x["venda_grande"]
                        segundos_grandes.add(x["seg"])
            else:
                if p > nivel + tol + 1e-9:
                    furou = True
                if nivel - folga - 1e-9 <= p <= nivel + tol + 1e-9:
                    agredido += x["compra"]
                    contra += x["venda"]
                    segundos_no_nivel.add(x["seg"])
                    if x["compra_grande"] > 0:
                        grande += x["compra_grande"]
                        segundos_grandes.add(x["seg"])
        return {"agredido": agredido, "contra": contra, "furou": furou, "toques": len(segundos_no_nivel),
                "rodadas_grandes": len(segundos_grandes), "agredido_grande": grande}


class Leitor:
    """Le a fita do dia aos poucos (pela posicao no arquivo) e a foto do livro."""

    def __init__(self, pasta=PASTA_MT5, dia=None):
        self.pasta = pasta
        self.dia = dia                         # "AAAAMMDD"
        self.posicao = 0
        self.resto = ""

    def arquivo_da_fita(self):
        return os.path.join(self.pasta, f"{PREFIXO_FITA}{self.dia}.csv")

    def novas_linhas(self):
        """Linhas da fita gravadas desde a ultima leitura. Linha pela metade fica para a proxima."""
        caminho = self.arquivo_da_fita()
        try:
            tamanho = os.path.getsize(caminho)
        except OSError:
            return []
        if tamanho < self.posicao:              # arquivo recomecou
            self.posicao, self.resto = 0, ""
        if tamanho == self.posicao:
            return []
        with open(caminho, "r", encoding="latin-1", errors="ignore") as f:
            f.seek(self.posicao)
            texto = self.resto + f.read()
            self.posicao = f.tell()
        partes = texto.split("\n")
        self.resto = partes.pop()               # o que veio sem quebra de linha ainda nao terminou
        return [x for x in (linha_da_fita(p) for p in partes) if x is not None]

    def livro(self):
        try:
            with open(os.path.join(self.pasta, ARQ_LIVRO), "r", encoding="latin-1", errors="ignore") as f:
                return ler_livro(f.read())
        except OSError:
            return {}

    def pedir(self, simbolos):
        """Diz ao robo do MetaTrader de quais simbolos gravar fita e livro."""
        caminho = os.path.join(self.pasta, ARQ_TAPE)
        texto = "\n".join(sorted(set(simbolos))) + "\n"
        try:
            atual = open(caminho, "r", encoding="latin-1").read()
        except OSError:
            atual = None
        if atual != texto:
            with open(caminho + ".tmp", "w", encoding="latin-1") as f:
                f.write(texto)
            os.replace(caminho + ".tmp", caminho)
        return caminho
