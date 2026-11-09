"""PDF leve, sem o Chrome: texto na Helvetica padrao do PDF (nao embute fonte), linhas, retangulos e imagem PNG
(paleta, cinza ou RGB, sem transparencia). Documento simples como o DARF sai com poucos KB, o que deixa o anexo do
e-mail pequeno. Coordenadas em pontos a partir do canto de cima da pagina, como no HTML do relatorio; o texto e
posicionado pela linha de base.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from .relatorio import _larg


def _png(dados: bytes) -> dict:
    """PNG -> imagem do PDF sem recodificar: os blocos IDAT ja sao Flate com o preditor do PNG."""
    if dados[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('nao e PNG')
    i, idat, paleta, ihdr = 8, b'', b'', None
    while i < len(dados):
        n, tipo = struct.unpack('>I4s', dados[i:i + 8])
        corpo = dados[i + 8:i + 8 + n]
        if tipo == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', corpo)
        elif tipo == b'PLTE':
            paleta = corpo
        elif tipo == b'IDAT':
            idat += corpo
        i += 12 + n
    larg, alt, bits, cor, _, _, entrelacado = ihdr
    if entrelacado or cor not in (0, 2, 3):
        raise ValueError('PNG entrelacado ou com transparencia: use paleta, cinza ou RGB')
    if cor == 3:
        espaco = b'[/Indexed /DeviceRGB %d <%s>]' % (len(paleta) // 3 - 1, paleta.hex().encode())
    else:
        espaco = b'/DeviceGray' if cor == 0 else b'/DeviceRGB'
    canais = 3 if cor == 2 else 1
    dic = (b'/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent %d '
           b'/Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors %d /BitsPerComponent %d /Columns %d >>'
           % (larg, alt, espaco, bits, canais, bits, larg))
    return {'dic': dic, 'dados': idat}


def _pdf_txt(txt: str) -> bytes:
    s = str(txt).encode('cp1252', 'replace')   # WinAnsiEncoding: cobre os acentos do portugues, ª e º
    return s.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')


class Pagina:
    def __init__(self, larg: float, alt: float):
        self.larg, self.alt = larg, alt
        self.ops: list[bytes] = []
        self.imagens: list[dict] = []

    def texto(self, x: float, base: float, txt: str, pt: float = 9, negrito: bool = False, anc: str = 'e') -> None:
        """anc: 'e' esquerda, 'd' direita (x e a borda direita), 'c' centro."""
        w = _larg(txt, pt, negrito)
        x = x - w if anc == 'd' else x - w / 2 if anc == 'c' else x
        self.ops.append(b'BT /F%d %.2f Tf %.2f %.2f Td (%s) Tj ET' % (2 if negrito else 1, pt, x, self.alt - base,
                                                                    _pdf_txt(txt)))

    def linha(self, x0: float, y0: float, x1: float, y1: float, larg: float = 1.0) -> None:
        self.ops.append(b'%.2f w %.2f %.2f m %.2f %.2f l S' % (larg, x0, self.alt - y0, x1, self.alt - y1))

    def retangulo(self, x: float, y: float, w: float, h: float, larg: float = 1.0) -> None:
        self.ops.append(b'%.2f w %.2f %.2f %.2f %.2f re S' % (larg, x, self.alt - y - h, w, h))

    def imagem(self, png: bytes, x: float, y: float, w: float, h: float) -> None:
        """A mesma imagem desenhada duas vezes (o brasao das duas vias) entra uma vez so no arquivo."""
        k = next((i for i, im in enumerate(self.imagens, 1) if im['png'] == png), None)
        if k is None:
            self.imagens.append({**_png(png), 'png': png})
            k = len(self.imagens)
        self.ops.append(b'q %.2f 0 0 %.2f %.2f %.2f cm /Im%d Do Q' % (w, h, x, self.alt - y - h, k))


def gravar(paginas: list[Pagina], destino: Path, titulo: str = '') -> Path:
    """Monta o arquivo: catalogo, paginas, as duas Helveticas (normal e negrito) e as imagens de cada pagina."""
    objs: list[bytes] = [b'', b'']           # 1 catalogo e 2 arvore de paginas, preenchidos no fim
    objs.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    objs.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')
    kids = []
    for pg in paginas:
        xo = b''
        for k, im in enumerate(pg.imagens, 1):
            objs.append(b'<< %s /Length %d >>\nstream\n' % (im['dic'], len(im['dados'])) + im['dados'] + b'\nendstream')
            xo += b'/Im%d %d 0 R ' % (k, len(objs))
        corpo = zlib.compress(b'\n'.join(pg.ops), 9)
        objs.append(b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(corpo) + corpo + b'\nendstream')
        conteudo = len(objs)
        objs.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R /Resources << /Font '
                    b'<< /F1 3 0 R /F2 4 0 R >> /XObject << %s>> >> >>' % (pg.larg, pg.alt, conteudo, xo))
        kids.append(b'%d 0 R' % len(objs))
    objs[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objs[1] = b'<< /Type /Pages /Kids [%s] /Count %d >>' % (b' '.join(kids), len(kids))
    info = b''
    if titulo:
        objs.append(b'<< /Title (%s) /Producer (contador_bolsa) >>' % _pdf_txt(titulo))
        info = b' /Info %d 0 R' % len(objs)
    saida = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    pos = []
    for n, o in enumerate(objs, 1):
        pos.append(len(saida))
        saida += b'%d 0 obj\n' % n + o + b'\nendobj\n'
    xref = len(saida)
    saida += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    saida += b''.join(b'%010d 00000 n \n' % p for p in pos)
    saida += b'trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, info, xref)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(bytes(saida))
    return destino
