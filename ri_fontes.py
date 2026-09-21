# Onde cada companhia publica o release de resultados no proprio site de RI.
#
# O coletor (coletar_dados.py) usa este mapa como fonte de releases quando o
# indice IPE da CVM falha ou atrasa (em 20/09/2026 o ipe_cia_aberta_2026
# passou a responder 404 e o historico parou no 3T25). A central de resultados
# do RI e a fonte primaria do release; o IPE da CVM vira conferencia.
#
# Chaves sempre presentes em cada ticker:
#   empresa      nome da companhia
#   central      central de resultados em portugues (melhor URL encontrada)
#   alternativas lista de URLs alternativas (ingles, legado), pode ser vazia
#   plataforma   "mz" | "riweb" | "proprio" | "desconhecida"
#                mz      documentos servidos por api.mziq.com/mzfilemanager/v2/d/<mz_id>/<uuid>
#                        ou filemanager-cdn.mziq.com/published/<mz_id>/<arquivo>
#                riweb   dominio com 'riweb' ou links /Download.aspx
#                proprio site da propria companhia, sem MZ nem RiWeb
#   mz_id        primeiro uuid depois de /mzfilemanager/v2/d/ (str) ou None
#   observacao   texto livre curto: onde o id foi visto, o que foi inferido
#
# Chave opcional:
#   lista        lista de URLs (JSON ou HTML) que devolvem a listagem de documentos
#                quando a central e montada por JavaScript (o HTML vem sem link).
#                O coletor tenta essas rotas antes de sondar a pagina; a arvore
#                do JSON e percorrida e todo campo com url/titulo vira candidato.
#
# Regras de preenchimento (busca web em 20/09/2026):
# - mz_id so entra quando visto numa URL real de documento da propria
#   companhia em resultado de busca; nunca inventado.
# - "central PT inferida" = a busca so indexou a pagina em ingles; a URL em
#   portugues segue o padrao do tema MZ (raiz = PT, /en/ = EN, slugs
#   traduzidos: financial-information -> informacoes-financeiras,
#   investor-information -> informacoes-aos-investidores,
#   results-center -> central-de-resultados). O padrao foi conferido em
#   sites irmaos indexados (ri.tenda.com, ri.bnb.gov.br, ri.brb.com.br,
#   ri.ceb.com.br). O coletor deve tentar 'central' e depois 'alternativas'.
# - Sem acentos neste arquivo.

RI_FONTES = {
    # ---- grupo 'construcao' (pares.py) ----------------------------------
    "DIRR3": {
        "empresa": "Direcional Engenharia",
        "central": "https://ri.direcional.com.br/informacoes-financeiras/central-de-resultados/",
        "alternativas": [
            "https://ri.direcional.com.br/en/financial-information/results-center/",
            "https://ri.direcional.com.br/listresultados.aspx?idCanal=wK6Cfmgdm9M0YQJtvN9JVQ%3D%3D",
        ],
        "plataforma": "mz",
        "mz_id": "ada9bc2c-f7d0-4359-9eaf-851b679ab788",
        "observacao": (
            "mz_id visto em ITRs, DFs, 'Resultados Direcional' e 'Divulgacao de "
            "Resultados 3T24' da Direcional em api.mziq.com. O id "
            "60f49a2d-bd8c-4fd9-95ab-bdf833097a83 foi checado e pertence a "
            "Energisa (EMT, notas ANEEL, newsletters): NAO usar para DIRR3. "
            "Central PT inferida do tema MZ; EN confirmada; terceira URL e o "
            "legado .aspx."
        ),
    },
    "CURY3": {
        "empresa": "Cury Construtora e Incorporadora",
        "central": "https://ri.cury.net/informacoes-aos-investidores/central-de-resultados/",
        "alternativas": [
            "https://ri.cury.net/en/investor-information/results-center/",
        ],
        "plataforma": "mz",
        "mz_id": "702b9586-4f10-4a79-a7e6-232ce8803136",
        "observacao": (
            "mz_id visto em 'RELEASE DE RESULTADOS' 4T24, '3Q22 EARNINGS RELEASE', "
            "previas operacionais 1Q26/4Q25 e ITR da Cury em api.mziq.com. "
            "Central PT inferida (investor-information -> "
            "informacoes-aos-investidores); EN confirmada."
        ),
    },
    "TEND3": {
        "empresa": "Construtora Tenda",
        "central": "https://ri.tenda.com/informacoes-financeiras/central-de-resultados",
        "alternativas": [
            "https://ri.tenda.com/en/financial-information/results-center",
            "https://ri.tenda.com/en/financial-information/results/",
        ],
        "plataforma": "proprio",
        "mz_id": None,
        "observacao": (
            "Site proprio: PDFs em ri.tenda.com/docs/<Nome>-<AAAA-MM-DD>-<hash>.pdf "
            "(ex. Press-release-Tenda-2025-12-31-8BpGhFtk.pdf, "
            "Tenda-2025-03-31-FKJqWfmB.pdf). Central PT e EN confirmadas em busca. "
            "Sem MZ."
        ),
    },
    "PLPL3": {
        "empresa": "Plano & Plano Desenvolvimento Imobiliario",
        "central": "https://ri.planoeplano.com.br/informacoes-financeiras/central-de-resultados/",
        "alternativas": [
            "https://ri.planoeplano.com.br/en/financial-information/results-center/",
        ],
        "plataforma": "mz",
        "mz_id": "dd0335cb-6079-40d0-95fc-fbcb3fa580ef",
        "observacao": (
            "mz_id visto em 'EARNING RESULTS 2Q25/3Q25 ... PLPL3', 'RESULTADOS 1o "
            "TRIMESTRE' 2026 e previa operacional 2026 em api.mziq.com. "
            "Central PT inferida do tema MZ; EN confirmada."
        ),
    },
    "MRVE3": {
        "empresa": "MRV Engenharia e Participacoes",
        "central": "https://ri.mrv.com.br/informacoes-financeiras/central-de-resultados/",
        "alternativas": [
            "https://ri.mrv.com.br/en/financial-information/results-center/",
            "https://ri.mrv.com.br/default.aspx",
        ],
        "plataforma": "mz",
        "mz_id": "4b56353d-d5d9-435f-bf63-dcbf0a6c25d5",
        "observacao": (
            "mz_id visto em 'EARNINGS RELEASE 3Q25', '2Q26 OPERATIONAL PREVIEW', "
            "ITR e releases historicos da MRV em api.mziq.com. Central PT "
            "inferida (paginas PT sem /en/ existem no dominio, ex. "
            "/servicos-aos-investidores/calendario-de-eventos/); EN confirmada. "
            "Espelho do release 2T26: static.poder360.com.br/uploads/2026/08/MRV-2-tri-2026.pdf."
        ),
    },
    "CYRE3": {
        "empresa": "Cyrela Brazil Realty",
        "central": "https://ri.cyrela.com.br/informacoes-financeiras/central-de-resultados/",
        "alternativas": [
            "https://ri.cyrela.com.br/en/financial-information/results-center/",
            "https://cyrela.globalri.com.br/pt/central-de-resultados",
        ],
        "plataforma": "mz",
        "mz_id": "d7617e78-1c42-4341-83ae-a1faa8569ca8",
        "observacao": (
            "mz_id visto em 'Release de Resultados 2T26 CYRE3 CYRE4 (13/08/2026)' "
            "e previas operacionais da Cyrela em api.mziq.com. Central PT "
            "inferida do tema MZ; EN confirmada; terceira URL e a central antiga "
            "(globalri)."
        ),
    },
    "EZTC3": {
        "empresa": "EZTEC Empreendimentos e Participacoes",
        "central": "https://ri.eztec.com.br/central-de-resultados/",
        "alternativas": [
            "https://ri.eztec.com.br/en/results-center/",
            "http://ri.eztec.com.br/eztec2009/web/conteudo_pt.asp?conta=28&idioma=0&tipo=26864",
        ],
        "plataforma": "mz",
        "mz_id": "653fada3-cbcd-4015-9a94-2149f610a321",
        "observacao": (
            "mz_id visto em 'EARNINGS RELEASE', teleconferencias, DFs e "
            "apresentacao institucional da EZTEC em api.mziq.com e "
            "filemanager-cdn.mziq.com. Central PT inferida (EN e "
            "/en/results-center/, sem segmento intermediario); EN confirmada; "
            "terceira URL e o legado ASP 'Resultados Financeiros'."
        ),
    },
    # ---- demais tickers da B3 ja presentes no branch dados ---------------
    "AMER3": {
        "empresa": "Americanas",
        "central": "https://ri.americanas.io/informacoes-aos-investidores/central-de-resultados/",
        "alternativas": [
            "https://ri.americanas.io/en/investor-information/results-center/",
        ],
        "plataforma": "mz",
        "mz_id": "347dba24-05d2-479e-a775-2ea8677c50f2",
        "observacao": (
            "mz_id 347dba24 e o da Americanas S.A. (ITR, 'Divulgacao de Resultado "
            "2025', documentos da recuperacao judicial) em api.mziq.com; o id "
            "941b74a9-5cce-4537-ba90-97973226b3f3 e o legado da Lojas Americanas "
            "(LASA). Central PT inferida; EN confirmada."
        ),
    },
    "BBAS3": {
        "empresa": "Banco do Brasil",
        "central": "https://ri.bb.com.br/informacoes-financeiras/central-de-resultados/",
        "alternativas": [
            "https://ri.bb.com.br/en/financial-information/results-center/",
        ],
        "plataforma": "mz",
        "mz_id": "5760dff3-15e1-4962-9e81-322a0b3d0bbd",
        "observacao": (
            "mz_id visto em 'Analise do Desempenho' 2T26/1T26/4T25, 'Sumario do "
            "Resultado' e DFs do BB em api.mziq.com. O release do BB se chama "
            "'Analise do Desempenho' (mais 'Sumario do Resultado'). Central PT "
            "inferida; EN confirmada."
        ),
    },
    "BBDC4": {
        "empresa": "Banco Bradesco",
        "central": "https://www.bradescori.com.br/informacoes-ao-mercado/central-de-resultados/",
        "alternativas": [
            "https://www.bradescori.com.br/en/market-information/results-center/",
            "https://www.bradescori.com.br/siteBradescoRI/Paginas/informacoesaomercado/91_Informacoes-ao-mercado.aspx",
        ],
        "plataforma": "mz",
        "mz_id": "80f2e993-0a30-421a-9470-a4d5c8ad5e9f",
        "observacao": (
            "mz_id visto em 'Relatorio de Analise Economica e Financeira' (4T25, "
            "1T26, 2T22) em api.mziq.com e filemanager-cdn.mziq.com. O release do "
            "Bradesco se chama 'Relatorio de Analise Economica e Financeira'. "
            "Central PT inferida (market-information -> informacoes-ao-mercado); "
            "EN confirmada; terceira URL e o legado .aspx."
        ),
    },
    "BHIA3": {
        "empresa": "Grupo Casas Bahia",
        "central": "https://ri.grupocasasbahia.com.br/informacoes-financeiras/central-de-resultados/",
        "alternativas": [
            "https://ri.grupocasasbahia.com.br/en/financial-information/results-center/",
        ],
        "plataforma": "mz",
        "mz_id": "ce9bff9f-fb19-49b9-9588-c4c6b7052c9c",
        "observacao": (
            "mz_id visto em 'RESULTADOS 1T26', 'Destaques dos Resultados do 4T25 e "
            "2025', release 4T24 e DFs do Grupo Casas Bahia em api.mziq.com. "
            "Central PT inferida; EN confirmada."
        ),
    },
    "BPAC11": {
        "empresa": "Banco BTG Pactual",
        "central": "https://ri.btgpactual.com/principais-informacoes/central-de-resultados",
        "alternativas": [
            "https://ri.btgpactual.com/en/principais-informacoes/central-de-resultados",
            "https://ri.btgpactual.com/noticias/",
        ],
        "plataforma": "mz",
        "mz_id": "0afe1b62-e299-4dec-a938-763ebc4e2c11",
        "observacao": (
            "mz_id visto em 'BTG Pactual - Divulgacao de Resultados' em "
            "api.mziq.com. A URL confirmada em busca e a com /en/ e slug em "
            "portugues (principais-informacoes/central-de-resultados); a PT sem "
            "/en/ e inferida. Releases tambem saem como noticia em "
            "/noticias/divulgacao-dos-resultados-<periodo>/."
        ),
    },
    "ITUB4": {
        "empresa": "Itau Unibanco Holding",
        "central": "https://www.itau.com.br/relacoes-com-investidores/resultados-e-relatorios/central-de-resultados/",
        "alternativas": [
            "https://www.itau.com.br/relacoes-com-investidores/en/results-and-reports/results-center/",
            "https://www.itau.com.br/relacoes-com-investidores/resultados-e-relatorios/",
        ],
        "plataforma": "proprio",
        "mz_id": None,
        "observacao": (
            "Site proprio (itau.com.br/relacoes-com-investidores). EN e "
            "/resultados-e-relatorios/ confirmadas em busca; central PT inferida "
            "delas. Release = 'Analise Gerencial da Operacao' + DFs completas. "
            "Sem MZ."
        ),
    },
    "MGLU3": {
        "empresa": "Magazine Luiza",
        "central": "https://ri.magazineluiza.com.br/ListResultados/Central-de-Resultados?linguagem=pt",
        "alternativas": [
            "https://ri.magazineluiza.com.br/listresultados.aspx?idCanal=0WX0bwP76pYcZvx+vXUnvg%3D%3D",
            "https://ri.magazineluiza.com.br/Default.aspx",
        ],
        "plataforma": "proprio",
        "mz_id": None,
        "observacao": (
            "Plataforma .aspx propria: central PT confirmada em busca; downloads "
            "em /Download/<slug>?linguagem=pt (ex. Apresentacao-Resultado-2T26); "
            "segunda URL e a central legada. Sem MZ."
        ),
    },
    "PETR4": {
        "empresa": "Petroleo Brasileiro (Petrobras)",
        "central": "https://www.investidorpetrobras.com.br/resultados-e-comunicados/central-de-resultados/",
        "alternativas": [
            "https://www.investidorpetrobras.com.br/en/results-and-announcements/results-center/",
            "https://www.investidorpetrobras.com.br/resultados-e-comunicados/",
        ],
        "plataforma": "mz",
        "mz_id": "25fdf098-34f5-4608-b7fa-17d60b2de47d",
        "observacao": (
            "mz_id visto em 'Desempenho financeiro da Petrobras no 4T23/1T24/4T21' "
            "e relatorio da administracao em api.mziq.com. O release da Petrobras "
            "se chama 'Desempenho Financeiro'. /resultados-e-comunicados/ PT "
            "confirmada; central PT inferida; EN confirmada."
        ),
    },
    "SANB11": {
        "empresa": "Banco Santander (Brasil)",
        "central": "https://www.santander.com.br/ri/resultados-e-relatorios/divulgacao-de-resultados/",
        "alternativas": [
            "https://www.santander.com.br/ri/en/results-and-reports/earnings-results/",
            "https://www.santander.com.br/ri/resultados",
        ],
        "plataforma": "proprio",
        "mz_id": None,
        "observacao": (
            "Site proprio (santander.com.br/ri), conteudo carregado por "
            "JavaScript. Central PT e EN confirmadas em busca. Sem MZ."
        ),
    },
    "VALE3": {
        "empresa": "Vale",
        "central": "https://www.vale.com/announcements-results-presentations-and-reports",
        "alternativas": [
            "https://saladeimprensa.vale.com/announcements-results-presentations-and-reports",
            "https://www.vale.com/pt/investidores/-/categories",
            "https://ri-vale.mz-sites.com/en/information-to-the-market/financial-statements/",
        ],
        "plataforma": "mz",
        "mz_id": "2c1e0dd9-31eb-4dc0-ab4d-844683600488",
        "observacao": (
            "mz_id visto em filemanager-cdn.mziq.com/published/<mz_id>/"
            "..._release_6m26_pt.pdf ('RELEASE DE RESULTADOS 2T26'). Site principal "
            "vale.com (Liferay; PT em /pt/), pagina de comunicados/resultados "
            "confirmada em busca; saladeimprensa.vale.com serve a mesma pagina em "
            "PT; ri-vale.mz-sites.com e o site no tema MZ."
        ),
    },
    "WEGE3": {
        "empresa": "WEG",
        "central": "https://ri.weg.net/informacoes-financeiras/central-de-resultados/",
        "alternativas": [
            "https://ri.weg.net/en/financial-information/results-center/",
        ],
        "plataforma": "mz",
        "mz_id": "50c1bd3e-8ac6-42d9-884f-b9d69f690602",
        "observacao": (
            "mz_id visto em 'RELEASE DE RESULTADOS 3T 2025 / 1T 2025 / 2T 2026', "
            "DFs 2025 e comunicados da WEG S.A. em api.mziq.com. Central PT "
            "inferida; EN confirmada."
        ),
    },
}

CHAVES = ("empresa", "central", "alternativas", "plataforma", "mz_id", "observacao")
PLATAFORMAS = ("mz", "riweb", "proprio", "desconhecida")


def fonte(ticker):
    """Devolve o dicionario de RI do ticker ou None quando nao mapeado."""
    return RI_FONTES.get(str(ticker).upper().strip())


def validar():
    """Confere o esquema; levanta AssertionError com o ticker errado."""
    for tk, v in RI_FONTES.items():
        assert set(v) == set(CHAVES), tk
        assert isinstance(v["alternativas"], list), tk
        assert v["plataforma"] in PLATAFORMAS, tk
        assert v["mz_id"] is None or isinstance(v["mz_id"], str), tk
        assert v["central"].startswith("http"), tk
    return len(RI_FONTES)


if __name__ == "__main__":
    print(validar(), "tickers")
