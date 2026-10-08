"""
Leitura de fluxo (a "fita" e o livro de ofertas) para o robo de day trade.

DE ONDE VEM. O robo do MetaTrader (AutopilotFeed 1.3) grava, para os simbolos de
`autopilot_tape.txt`:
  - `autopilot_fita_AAAAMMDD.csv`: negocios somados por segundo e por preco, com o lado de
    quem AGREDIU (comprou a mercado ou vendeu a mercado). Linha:
        F;SIMBOLO;segundo;preco;vol_compra;vol_venda;vol_indef;negocios;maior_compra;maior_venda;idade_ms
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
    return {"simbolo": c[1], "seg": int(_f(c[2])), "preco": preco, "compra": _f(c[4]), "venda": _f(c[5]),
            "indef": _f(c[6]), "negocios": int(_f(c[7])), "maior_compra": _f(c[8]), "maior_venda": _f(c[9]),
            "idade_ms": _f(c[10]) if len(c) > 10 else 0.0}


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

    def __init__(self, simbolo, tick):
        self.simbolo = simbolo
        self.tick = float(tick)
        self.linhas = deque()                 # dicts de linha_da_fita, em ordem de segundo
        self.ultimo_seg = 0

    def acrescentar(self, linha):
        if linha is None or linha["simbolo"] != self.simbolo:
            return
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

    def absorcao(self, nivel, lado, segundos, ate=None, folga_ticks=1):
        """Mede a defesa de um nivel na janela.

        lado="compra": o nivel e um SUPORTE. Conta o volume de quem VENDEU a mercado em precos ate
        `folga_ticks` acima do nivel, e ve se o preco passou para baixo dele. Muita venda agredindo
        e o preco nao perdendo o nivel e o que o leitor de fluxo chama de absorcao (alguem esta
        comprando tudo o que vendem ali). lado="venda" e o espelho, para uma RESISTENCIA.
        Devolve {"agredido", "contra" (volume que foi a favor do nivel), "furou" (bool), "toques"}.
        """
        folga = folga_ticks * self.tick
        agredido = contra = 0.0
        furou = False
        segundos_no_nivel = set()
        for x in self._janela(segundos, ate):
            p = x["preco"]
            if lado == "compra":
                if p < nivel - 1e-9:
                    furou = True
                if nivel - 1e-9 <= p <= nivel + folga + 1e-9:
                    agredido += x["venda"]
                    contra += x["compra"]
                    segundos_no_nivel.add(x["seg"])
            else:
                if p > nivel + 1e-9:
                    furou = True
                if nivel - folga - 1e-9 <= p <= nivel + 1e-9:
                    agredido += x["compra"]
                    contra += x["venda"]
                    segundos_no_nivel.add(x["seg"])
        return {"agredido": agredido, "contra": contra, "furou": furou, "toques": len(segundos_no_nivel)}


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
