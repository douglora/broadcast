"""Boletim Diario do Mercado da B3 (BDI): coleta, resumo e sinais.

Roda no GitHub Actions (a sessao do Claude na nuvem nao alcanca a B3) e grava em
`boletim_b3/` no branch `dados`. A sessao le com `python3 mesa.py boletim`.

    python boletim_b3.py --saida dados_branch/boletim_b3

Modulos:
  b3.py      rotas do aplicativo do BDI e da API de download (sem cadastro)
  coleta.py  o que se busca de cada pregao e o que fica gravado
  resumo.py  numeros com fonte e data, cruzados com o livro, e os sinais
  render.py  resumo.md, a leitura pronta para a sessao colar
"""

FONTE = "B3, Boletim Diario do Mercado (arquivos.b3.com.br/bdi)"
