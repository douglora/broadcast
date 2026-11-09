"""Onde ler cada lei e o JavaScript que tira o artigo da pagina no navegador do app, sem o trecho revogado (riscado).

O Planalto e a Receita recusam download por script (a conexao cai sem resposta, 27/10/2026): a leitura e no navegador
do app, em ritmo normal, sem contornar o bloqueio. Este arquivo nao baixa nada; diz onde ler e o que colar.

Uso (na raiz do repositorio):
    python3 ferramentas/local/lei.py --lista                  leis cadastradas, com o endereco
    python3 ferramentas/local/lei.py 9250                     endereco da Lei 9.250/1995
    python3 ferramentas/local/lei.py 9250 6-A 16-B            endereco + JavaScript que devolve os arts. 6-A e 16-B
    python3 ferramentas/local/lei.py cc --busca usufruto      endereco + JavaScript que lista os artigos que citam o termo

No app: preview_start {url} abre a lei numa aba; javascript_tool com o JavaScript impresso devolve o texto.
A skill contador le a regra assim antes de afirmar (lei lida, nao lembrada) e anota em REGRAS.md.
"""

from __future__ import annotations

import argparse
import json
import re

P = "https://www.planalto.gov.br/ccivil_03/"
RECEITA = "https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/"
LEIS = {
    "cc": ("Codigo Civil (Lei 10.406/2002)", P + "leis/2002/l10406compilada.htm"),
    "ctn": ("Codigo Tributario Nacional (Lei 5.172/1966)", P + "leis/l5172compilado.htm"),
    "6404": ("Lei 6.404/1976 (sociedades anonimas)", P + "leis/l6404consol.htm"),
    "7689": ("Lei 7.689/1988 (CSLL)", P + "leis/l7689.htm"),
    "8981": ("Lei 8.981/1995", P + "leis/l8981.htm"),
    "9249": ("Lei 9.249/1995 (IRPJ, dividendos, capital)", P + "leis/l9249.htm"),
    "9250": ("Lei 9.250/1995 (IRPF, retencao de dividendos e IRPFM)", P + "leis/l9250.htm"),
    "9430": ("Lei 9.430/1996 (lucro presumido)", P + "leis/l9430.htm"),
    "9718": ("Lei 9.718/1998 (PIS/COFINS cumulativo)", P + "leis/l9718compilada.htm"),
    "11033": ("Lei 11.033/2004 (renda fixa e isencoes da PF)", P + "_ato2004-2006/2004/lei/l11033.htm"),
    "11053": ("Lei 11.053/2004 (previdencia regressiva)", P + "_ato2004-2006/2004/lei/l11053.htm"),
    "12431": ("Lei 12.431/2011 (debentures incentivadas)", P + "_ato2011-2014/2011/lei/l12431.htm"),
    "13259": ("Lei 13.259/2016 (ganho de capital da PF)", P + "_ato2015-2018/2016/lei/l13259.htm"),
    "14754": ("Lei 14.754/2023 (fundos fechados e offshore)", P + "_ato2023-2026/2023/lei/l14754.htm"),
    "15270": ("Lei 15.270/2025 (dividendos e IRPFM)", P + "_ato2023-2026/2025/lei/L15270.htm"),
    "lcp224": ("Lei Complementar 224/2025 (corte de beneficios: JCP e presuncao do presumido)", P + "leis/lcp/lcp224.htm"),
    "cf": ("Constituicao Federal de 1988", P + "constituicao/constituicao.htm"),
    "lcp214": ("Lei Complementar 214/2025 (IBS, CBS e Imposto Seletivo)", P + "leis/lcp/lcp214.htm"),
    "lcp227": ("Lei Complementar 227/2026 (regras gerais do ITCMD, entre outras)", P + "leis/lcp/lcp227.htm"),
    "11482": ("Lei 11.482/2007 (tabela mensal do IRPF)", P + "_ato2007-2010/2007/lei/l11482.htm"),
    "8212": ("Lei 8.212/1991 (contribuicao ao INSS, pro-labore)", P + "leis/l8212cons.htm"),
    "d6306": ("Decreto 6.306/2007 (IOF, inclusive sobre aporte em VGBL)", P + "_ato2007-2010/2007/decreto/d6306.htm"),
    "d8426": ("Decreto 8.426/2015 (PIS/COFINS sobre receita financeira no lucro real)",
              P + "_ato2015-2018/2015/decreto/d8426.htm"),
    "dl1598": ("Decreto-Lei 1.598/1977 (receita bruta)", P + "decreto-lei/del1598.htm"),
    "in1700": ("IN RFB 1.700/2017 (IRPJ e CSLL; art. 216: presumido no resgate)", RECEITA + "81268"),
    "in1585": ("IN RFB 1.585/2015 (renda fixa e variavel; bolsa da pessoa fisica: arts. 37 e 56 a 82)", RECEITA + "67494"),
}

# a pagina da Receita monta por script: espera mais antes de ler
ESPERA_MS = {"planalto": 2500, "receita": 6000}

JS = r"""await new Promise(r => setTimeout(r, __ESPERA__));
(() => {
  const c = document.body.cloneNode(true);
  c.querySelectorAll('strike,s,del,[style*="line-through"]').forEach(e => e.remove());
  let t = [...c.querySelectorAll('p')].map(p => p.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n');
  const prox = /^Art\.?\s*\d/m;
  // pagina sem um paragrafo por artigo (a da Receita): texto da copia ja sem o riscado, montada fora da tela
  const aviso = prox.test(t) ? '' : '(sem paragrafo por artigo: texto corrido da pagina, ja sem o trecho riscado)\n';
  if (!prox.test(t)) {
    c.style.cssText = 'position:absolute;left:-99999px;top:0;width:900px';
    document.body.appendChild(c);
    t = c.innerText;
    c.remove();
  }
  const pedaco = (re) => {
    const m = re.exec(t);
    if (!m) return null;
    const fim = m.index + m[0].length, n = t.slice(fim).search(prox);
    return t.slice(m.index, n < 0 ? t.length : fim + n).trim();
  };
  const sem = s => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
  __CORPO__
})()"""

CORPO_ARTIGOS = r"""return aviso + __ARTS__.map(([a, re]) => '=== art. ' + a + ' ===\n'
    + (pedaco(re) || 'NAO ENCONTRADO (confira o numero ou use --busca)')).join('\n\n');"""

CORPO_BUSCA = r"""const alvo = sem(__TERMO__);
  const achados = t.split(/^(?=Art\.?\s*\d)/m).filter(p => sem(p).includes(alvo)).map(p => {
    const l = p.split('\n');
    return '--- ' + l[0].slice(0, 160) + '\n'
      + l.slice(1).filter(x => sem(x).includes(alvo)).slice(0, 8).map(x => '   ' + x.slice(0, 500)).join('\n');
  });
  return aviso + (achados.join('\n\n') || 'nenhum artigo cita ' + __TERMO__);"""


def padrao(art: str) -> str:
    """Regex (fonte, sem flags; vale em Python e em JavaScript com 'm') do cabecalho do artigo: 22, 1084, 6-A, 16-B."""
    m = re.fullmatch(r"(\d[\d.]*)\s*(?:-\s*([A-Za-z]))?", art.strip())
    if not m:
        raise SystemExit(f"artigo invalido: {art}")
    num = m.group(1).replace(".", "")
    num_re = num[:-3] + r"\.?" + num[-3:] if len(num) > 3 else num
    cauda = rf"\s*-\s*{m.group(2).upper()}\b" if m.group(2) else r"(?!\s*-\s*[A-Z]\b)"
    return rf"^Art\.?\s*{num_re}(?!\d)(?:\s*[º°o])?(?![º°o]){cauda}"


def js(url: str, artigos: list[str] | None = None, termo: str | None = None) -> str:
    """JavaScript para o javascript_tool da aba com a lei aberta: devolve os artigos pedidos ou os que citam o termo."""
    if termo:
        corpo = CORPO_BUSCA.replace("__TERMO__", json.dumps(termo, ensure_ascii=False))
    else:
        # regex literal, nao string: sem barra dupla para a colagem estragar
        arts = ", ".join(f"[{json.dumps(a)}, /{padrao(a)}/m]" for a in artigos or [])
        corpo = CORPO_ARTIGOS.replace("__ARTS__", f"[{arts}]")
    espera = ESPERA_MS["receita" if url.startswith(RECEITA) else "planalto"]
    return JS.replace("__ESPERA__", str(espera)).replace("__CORPO__", corpo)


def main() -> None:
    ap = argparse.ArgumentParser(description="Endereco oficial da lei e o JavaScript que extrai o artigo no navegador")
    ap.add_argument("lei", nargs="?", help="chave da lei (9250, cc, lcp227...): veja --lista")
    ap.add_argument("artigos", nargs="*", help="numeros dos artigos (22, 1084, 6-A, 16-B)")
    ap.add_argument("--busca", help="artigos que citam o termo (sem acento, sem caixa)")
    ap.add_argument("--lista", action="store_true")
    a = ap.parse_args()
    if a.lista or not a.lei:
        for k, (nome, url) in LEIS.items():
            print(f"{k:7s} {nome}\n        {url}")
        return
    chave = a.lei.lower().replace(".", "")
    if chave not in LEIS:
        raise SystemExit(f"lei nao cadastrada: {a.lei} (veja --lista)")
    nome, url = LEIS[chave]
    print(f"{nome}\n{url}")
    if a.artigos or a.busca:
        print("\n// cole no javascript_tool da aba aberta com preview_start {url}:\n")
        print(js(url, a.artigos, a.busca))


if __name__ == "__main__":
    main()
