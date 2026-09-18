"""Livro monitorado: coleta, sinais e render que rodam no GitHub Actions.

A sessao do Claude na nuvem nao alcanca as fontes de mercado; este pacote roda
no runner (internet aberta), grava JSON e Markdown no branch `dados` (pasta
`livro/`) e a sessao apenas le e narra.

    python -m livro.rodar --modo fechamento --saida dados_branch/livro
"""

import os

VERSAO = "0.1.0"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(RAIZ, "config")
