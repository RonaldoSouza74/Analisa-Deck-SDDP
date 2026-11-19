"""Monta a apresentação (PowerPoint .pptx) com os gráficos e números das etapas 1 a 10.

Roda depois do rodar_tudo.bat. Lê os PNGs e CSVs de <caso>\\resultados_uf e:
  - gera 2 gráficos próprios, só com dados do ano e sem a geração distribuída (dos CSVs do
    gargalo_cmo): mapa_vertimento_uf.png (mapa do Brasil por estado) e tecnologia_uf.png;
  - monta os slides na ordem: mensagem principal, método, quanto e onde, quando, por quê
    (gargalo x excesso), subsistemas, linhas, estados com mais vertimento, conclusões e anexo;
  - os títulos com números são calculados dos CSVs (nada digitado à mão); cada slide traz a
    fonte (arquivo de origem) no rodapé e um texto de apoio nas anotações do apresentador.
Slides cujo gráfico não existe são pulados (a lista sai no fim).

O mapa usa o contorno dos estados do IBGE (mapa_uf.json, nesta pasta) só para desenhar.

Uso:
  python apresentacao.py "<pasta do caso>" [--ano 2030] [--saida <pasta>]
Saída: <caso>\\resultados_uf\\apresentacao\\apresentacao_vertimento_<ano>.pptx

Requer numpy, matplotlib e python-pptx (python -m pip install python-pptx).
"""
import argparse
import collections
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graficos_uf import ORDEM_UF, TEXTO, TEXTO2, GRADE, FUNDO, plt, np            # noqa: E402

try:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt
except ImportError:
    sys.exit('ERRO: o pacote python-pptx não está instalado. No Prompt de Comando rode:\n'
             '    python -m pip install python-pptx')

AZUL = RGBColor(0x2a, 0x78, 0xd6)
ESCURO = RGBColor(0x1f, 0x29, 0x33)
CINZA = RGBColor(0x6b, 0x72, 0x80)
CLARO = RGBColor(0xf3, 0xf5, 0xf8)
COR_GARG, COR_EXC = '#e34948', '#8a8984'
TEC_COR = {'Eolica': '#2a78d6', 'Solar': '#eb6834', 'Biomassa': '#eda100', 'PCH': '#e87ba4'}
TEC_NOME = {'Eolica': 'Eólica', 'Solar': 'Solar centralizada', 'Biomassa': 'Biomassa', 'PCH': 'PCH'}
NOME_UF = {'AC': 'Acre', 'AL': 'Alagoas', 'AM': 'Amazonas', 'AP': 'Amapá', 'BA': 'Bahia', 'CE': 'Ceará',
           'DF': 'Distrito Federal', 'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão', 'MG': 'Minas Gerais',
           'MS': 'Mato Grosso do Sul', 'MT': 'Mato Grosso', 'PA': 'Pará', 'PB': 'Paraíba', 'PE': 'Pernambuco',
           'PI': 'Piauí', 'PR': 'Paraná', 'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte', 'RO': 'Rondônia',
           'RR': 'Roraima', 'RS': 'Rio Grande do Sul', 'SC': 'Santa Catarina', 'SE': 'Sergipe', 'SP': 'São Paulo',
           'TO': 'Tocantins'}


def br(x, casas=0):
    """Número no formato brasileiro (1.234,5)."""
    if x is None or x != x:
        return '–'
    t = f'{x:,.{casas}f}'
    return t.replace(',', 'X').replace('.', ',').replace('X', '.')


def ler_csv(caminho):
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------------
# números (todos dos CSVs das etapas)
# ----------------------------------------------------------------------------
def numeros(res):
    N = {}
    rows = ler_csv(os.path.join(res, 'gargalo_cmo', 'vertimento_causa_uf_mensal.csv'))
    if rows:
        g = collections.defaultdict(lambda: np.zeros(2))
        for r in rows:
            g[(r['uf'], r['fonte'])] += [fnum(r['gargalo_GWh']), fnum(r['excesso_sistema_GWh'])]
        N['uf'] = {f_: {u: g[(u, f_)] for u in ORDEM_UF if (u, f_) in g}
                   for f_ in ('renovavel', 'hidro_turbinavel')}
        for f_ in ('renovavel', 'hidro_turbinavel'):
            tot = sum(N['uf'][f_].values()) if N['uf'][f_] else np.zeros(2)
            N[f'tot_{f_}'] = tot
        ren = N['uf']['renovavel']
        N['ordem_uf'] = sorted(ren, key=lambda u: -ren[u].sum())
    rows = ler_csv(os.path.join(res, 'gargalo_cmo', 'vertimento_causa_uf_tecnologia.csv'))
    if rows:
        t = collections.defaultdict(float)
        for r in rows:
            if r['fonte'] == 'renovavel':
                t[(r['uf'], r['tecnologia'])] += fnum(r['gargalo_GWh']) + fnum(r['excesso_sistema_GWh'])
        N['tec'] = t
    rows = ler_csv(os.path.join(res, 'gargalo_subsistema', 'vertimento_causa_subsistema_mensal.csv'))
    if rows:
        s = collections.defaultdict(lambda: np.zeros(3))
        nomes = {}
        for r in rows:
            if r['mes'] == 'ano':
                s[r['subsistema']] += [fnum(r['gargalo_entre_subsistemas_GWh']), fnum(r['gargalo_dentro_subsistema_GWh']),
                                       fnum(r['excesso_sistema_GWh'])]
                nomes[r['subsistema']] = r['nome']
        N['sub'] = dict(s)
        N['sub_nome'] = nomes
        N['ordem_sub'] = sorted(s, key=lambda k: -s[k].sum())
    rows = ler_csv(os.path.join(res, 'analise_semana', 'resumo_util_fds.csv'))
    if rows:
        for r in rows:
            if r['uf'] == 'BR':
                N['fds'] = (fnum(r['vertimento_util_GWh_dia']), fnum(r['vertimento_fds_GWh_dia']))
    rows = ler_csv(os.path.join(res, 'gargalo_linhas', 'circuitos_no_limite.csv'))
    if rows:
        N['circ'] = sorted([r for r in rows if r['monitorado'] == '1'],
                           key=lambda r: -fnum(r['vertimento_gargalo_coincidente_GWh']))[:5]
        N['circ_sobre'] = [r for r in rows if r['monitorado'] != '1' and fnum(r['pct_horas_sobrecarga']) > 0]
    rows = ler_csv(os.path.join(res, 'gargalo_subsistema', 'intercambios_subsistemas.csv'))
    if rows:
        N['itc'] = sorted(rows, key=lambda r: -fnum(r['pct_horas_cmo_separado']))[:5]
    return N


# ----------------------------------------------------------------------------
# gráficos próprios
# ----------------------------------------------------------------------------
def mapa(N, saida, ano):
    arq = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapa_uf.json')
    if 'uf' not in N or not os.path.exists(arq):
        return None
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    geo = json.load(open(arq, encoding='utf-8'))['uf']
    ren = N['uf']['renovavel']
    tot = {u: ren[u].sum() if u in ren else 0.0 for u in geo}
    pct = {u: 100 * ren[u][0] / ren[u].sum() if u in ren and ren[u].sum() >= 10 else np.nan for u in geo}
    fig, axs = plt.subplots(1, 2, figsize=(15, 7.6))
    paineis = ((axs[0], tot, LinearSegmentedColormap.from_list('v', ['#f1f4f9', '#9cc3ee', '#2a78d6', '#123c73']),
                Normalize(0, max(tot.values()) or 1), 'Vertimento renovável no ano (GWh)', 'GWh'),
               (axs[1], pct, LinearSegmentedColormap.from_list('g', ['#f7efe9', '#f2a3a2', '#e34948', '#8a1c1b']),
                Normalize(0, max(50, np.nanmax(list(pct.values())) if np.isfinite(list(pct.values())).any() else 50)),
                '% do vertimento renovável por gargalo de transmissão', '%'))
    centro = {u: np.mean(np.vstack(max(p, key=len)), axis=0) for u, p in geo.items()}
    desloc = {'DF': (0.0, 0.0), 'SE': (0.9, -0.3), 'AL': (1.3, 0.1), 'PB': (1.9, -0.2), 'RN': (0.5, 0.4),
              'PE': (0.4, 0.0), 'ES': (1.0, -0.2), 'RJ': (0.6, -0.8), 'SC': (0.6, 0.0)}
    for ax, val, cmap, norm, titulo, un in paineis:
        polys, cores = [], []
        for u, partes in geo.items():
            v = val.get(u, np.nan)
            for parte in partes:
                polys.append(parte)
                cores.append(cmap(norm(v)) if v == v else '#e6e6e3')
        ax.add_collection(PolyCollection(polys, facecolors=cores, edgecolors=FUNDO, linewidths=0.8))
        for u, (x, y) in centro.items():
            dx, dy = desloc.get(u, (0, 0))
            v = val.get(u, np.nan)
            txt = u if v != v else (f'{u}\n{br(v)}' if un == 'GWh' and v >= 50 else
                                     (f'{u}\n{br(v)}%' if un == '%' else u))
            claro = v == v and norm(v) > 0.55
            ax.text(x + dx, y + dy, txt, ha='center', va='center', fontsize=7.5,
                    color='white' if claro else TEXTO, fontweight='bold' if v == v and norm(v) > 0.3 else 'normal')
        ax.set_xlim(-74.5, -34)
        ax.set_ylim(-34.5, 6)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(titulo, loc='left', fontsize=11)
        sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
        cb = fig.colorbar(sm, ax=ax, orientation='horizontal', fraction=0.035, pad=0.02, aspect=40)
        cb.outline.set_visible(False)
        cb.ax.tick_params(labelsize=8, colors=TEXTO2)
    fig.suptitle(f'Vertimento renovável por estado, {ano} (sem geração distribuída)', x=0.01, ha='left',
                 fontsize=14, fontweight='bold')
    fig.text(0.01, 0.01, 'Estado = UF da barra de conexão da usina. Média dos cenários. % por gargalo só para estados '
             'com 10 GWh ou mais (cinza = abaixo disso). Contorno dos estados: IBGE. Dados: gargalo_cmo.',
             fontsize=8, color=TEXTO2)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.9, bottom=0.08, wspace=0.04)
    nome = os.path.join(saida, 'mapa_vertimento_uf.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)
    return nome


def grafico_tecnologia(N, saida, ano):
    if 'tec' not in N or 'ordem_uf' not in N:
        return None
    t = N['tec']
    ufs = [u for u in N['ordem_uf'] if sum(t.get((u, k), 0) for k in TEC_COR) >= 1][::-1]
    if not ufs:
        return None
    fig, axs = plt.subplots(1, 2, figsize=(14, 0.34 * len(ufs) + 2))
    for ax, pct in zip(axs, (False, True)):
        esq = np.zeros(len(ufs))
        tot = np.array([sum(t.get((u, k), 0) for k in TEC_COR) for u in ufs])
        for k in TEC_COR:
            v = np.array([t.get((u, k), 0) for u in ufs])
            if pct:
                v = 100 * v / np.maximum(tot, 1e-9)
            ax.barh(range(len(ufs)), v, left=esq, color=TEC_COR[k], height=0.72, edgecolor=FUNDO, linewidth=1,
                    label=TEC_NOME[k])
            esq += v
        ax.set_yticks(range(len(ufs)), ufs)
        ax.grid(axis='x', color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        if pct:
            ax.set_xlim(0, 100)
            ax.set_title('Participação de cada tecnologia (%)', loc='left', fontsize=10)
        else:
            for k_, u in enumerate(ufs):
                ax.text(tot[k_], k_, f' {br(tot[k_])}', va='center', fontsize=8, color=TEXTO2)
            ax.set_xlim(0, tot.max() * 1.15)
            ax.set_title('Vertimento no ano (GWh, média dos cenários)', loc='left', fontsize=10)
            ax.legend(loc='lower right', fontsize=8, frameon=False)
    fig.suptitle(f'Vertimento renovável por estado e tecnologia, {ano} (sem geração distribuída)', x=0.01, ha='left',
                 fontsize=13, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    nome = os.path.join(saida, 'tecnologia_uf.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)
    return nome


# ----------------------------------------------------------------------------
# slides
# ----------------------------------------------------------------------------
def partes_imagem(cam, pasta_tmp, alvo=0.62, n_forcado=None):
    """Divide uma figura alta em partes de proporção ~alvo (altura/largura), cortando em faixas em branco
    entre os painéis. Devolve a lista de arquivos (a própria figura se não precisar dividir)."""
    from PIL import Image
    with Image.open(cam) as im:
        w, h = im.size
        if not n_forcado and h / w <= 0.95:
            return [cam]
        g = np.asarray(im.convert('L'), dtype=np.int16)
        n = n_forcado or max(2, min(int(np.ceil((h / w) / alvo)), 3))
        branca = (g.max(axis=1) - g.min(axis=1)) <= 3           # linha toda da mesma cor (sem desenho)
        cortes = [0]
        for k in range(1, n):
            ideal = int(h * k / n)
            ini, fim = max(cortes[-1] + 50, ideal - h // 4), min(h - 50, ideal + h // 4)
            # faixas contínuas em branco na janela; corta no meio da MAIS LARGA (espaço entre painéis)
            faixas, j = [], ini
            while j < fim:
                if branca[j]:
                    j0 = j
                    while j < fim and branca[j]:
                        j += 1
                    faixas.append((j - j0, -abs((j0 + j) // 2 - ideal), (j0 + j) // 2))
                j += 1
            cortes.append(int(max(faixas)[2]) if faixas else ideal)
        cortes.append(h)
        os.makedirs(pasta_tmp, exist_ok=True)
        nome = os.path.splitext(os.path.basename(cam))[0]
        out = []
        for k in range(n):
            arq = os.path.join(pasta_tmp, f'{nome}_parte{k + 1}.png')
            im.crop((0, cortes[k], w, cortes[k + 1])).save(arq)
            out.append(arq)
        return out


class Deck:
    def __init__(self, res, tmp):
        self.res, self.tmp = res, tmp
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)
        self.vazio = self.prs.slide_layouts[6]
        self.faltando = []
        self.n = 0

    def _texto(self, slide, x, y, w, h, texto, tam=14, cor=ESCURO, negrito=False, alinhar=None):
        caixa = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = caixa.text_frame
        tf.word_wrap = True
        linhas = texto if isinstance(texto, list) else [texto]
        for i, ln in enumerate(linhas):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = ln
            p.font.size = Pt(tam)
            p.font.color.rgb = cor
            p.font.bold = negrito
            if alinhar:
                p.alignment = alinhar
            if isinstance(texto, list):
                p.space_after = Pt(8)
        return caixa

    def _base(self, titulo, fonte=None, notas=None):
        s = self.prs.slides.add_slide(self.vazio)
        self.n += 1
        barra = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.12), Inches(7.5))
        barra.fill.solid()
        barra.fill.fore_color.rgb = AZUL
        barra.line.fill.background()
        self._texto(s, 0.45, 0.25, 12.4, 0.9, titulo, tam=24, negrito=True)
        rod = f'Fonte: {fonte}' if fonte else ''
        self._texto(s, 0.45, 7.05, 11.5, 0.35, rod, tam=9, cor=CINZA)
        self._texto(s, 12.3, 7.05, 0.8, 0.35, str(self.n), tam=9, cor=CINZA, alinhar=PP_ALIGN.RIGHT)
        if notas:
            s.notes_slide.notes_text_frame.text = notas
        return s

    def imagem(self, titulo, caminho_rel, notas=None, lateral=None, fonte=None, partes=None):
        """Slide com um gráfico. lateral = lista de frases mostradas à direita (para figuras altas)."""
        cam = caminho_rel if os.path.isabs(caminho_rel) else os.path.join(self.res, caminho_rel)
        if not os.path.exists(cam):
            self.faltando.append(caminho_rel)
            return False
        partes = partes_imagem(cam, os.path.join(self.tmp, 'partes'), n_forcado=partes)
        for k, parte in enumerate(partes):
            tit = titulo if len(partes) == 1 else f'{titulo} ({k + 1}/{len(partes)})'
            self._slide_imagem(tit, parte, fonte or caminho_rel.replace('/', '\\'), notas, lateral)
        return True

    def _slide_imagem(self, titulo, cam, fonte, notas, lateral):
        s = self._base(titulo, fonte, notas)
        from PIL import Image
        with Image.open(cam) as im:
            w_px, h_px = im.size
        x0, y0, wmax, hmax = 0.45, 1.2, 12.45, 5.8
        if lateral:
            wmax = 9.4
        esc = min(wmax / w_px, hmax / h_px)
        w, h = w_px * esc, h_px * esc
        x = x0 + (wmax - w) / 2 if not lateral else x0
        s.shapes.add_picture(cam, Inches(x), Inches(y0 + (hmax - h) / 2), Inches(w), Inches(h))
        if lateral:
            caixa = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x0 + w + 0.3), Inches(1.4), Inches(12.9 - (x0 + w + 0.3)), Inches(5.3))
            caixa.fill.solid()
            caixa.fill.fore_color.rgb = CLARO
            caixa.line.fill.background()
            self._texto(s, x0 + w + 0.5, 1.55, 12.6 - (x0 + w + 0.5), 5.0, lateral, tam=13)

    def secao(self, titulo, subtitulo=''):
        s = self.prs.slides.add_slide(self.vazio)
        self.n += 1
        fundo = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, self.prs.slide_width, self.prs.slide_height)
        fundo.fill.solid()
        fundo.fill.fore_color.rgb = AZUL
        fundo.line.fill.background()
        self._texto(s, 0.9, 2.7, 11.5, 1.2, titulo, tam=36, cor=RGBColor(255, 255, 255), negrito=True)
        if subtitulo:
            self._texto(s, 0.9, 3.8, 11.5, 1.0, subtitulo, tam=18, cor=RGBColor(0xdc, 0xe8, 0xf8))

    def texto(self, titulo, itens, fonte=None, notas=None):
        s = self._base(titulo, fonte, notas)
        self._texto(s, 0.7, 1.4, 12.0, 5.5, itens, tam=17)

    def numeros(self, titulo, cartoes, fonte=None, notas=None):
        """cartoes = lista de (número, descrição)."""
        s = self._base(titulo, fonte, notas)
        n = len(cartoes)
        col = 3 if n > 4 else n
        lin = int(np.ceil(n / col))
        w, h = 12.3 / col - 0.25, (5.4 / lin) - 0.25
        for i, (num, desc) in enumerate(cartoes):
            x, y = 0.5 + (i % col) * (w + 0.25), 1.35 + (i // col) * (h + 0.25)
            c = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
            c.fill.solid()
            c.fill.fore_color.rgb = CLARO
            c.line.fill.background()
            self._texto(s, x + 0.25, y + 0.2, w - 0.5, h * 0.5, num, tam=34, cor=AZUL, negrito=True)
            self._texto(s, x + 0.25, y + h * 0.52, w - 0.5, h * 0.45, desc, tam=13, cor=ESCURO)

    def capa(self, titulo, subtitulo, data):
        s = self.prs.slides.add_slide(self.vazio)
        self.n += 1
        fundo = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, self.prs.slide_width, self.prs.slide_height)
        fundo.fill.solid()
        fundo.fill.fore_color.rgb = ESCURO
        fundo.line.fill.background()
        faixa = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(2.45), Inches(1.2), Inches(0.09))
        faixa.fill.solid()
        faixa.fill.fore_color.rgb = AZUL
        faixa.line.fill.background()
        self._texto(s, 0.9, 2.7, 11.5, 1.5, titulo, tam=38, cor=RGBColor(255, 255, 255), negrito=True)
        self._texto(s, 0.9, 4.1, 11.5, 1.0, subtitulo, tam=18, cor=RGBColor(0xc8, 0xd3, 0xe0))
        self._texto(s, 0.9, 6.5, 11.5, 0.5, data, tam=12, cor=RGBColor(0xa0, 0xab, 0xb8))


def main():
    p = argparse.ArgumentParser(description='Monta a apresentação .pptx com os resultados.')
    p.add_argument('caso', help='pasta do caso SDDP (com resultados_uf dentro) ou a própria resultados_uf')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--saida')
    a = p.parse_args()
    res = a.caso if os.path.basename(os.path.normpath(a.caso)).lower() == 'resultados_uf' else \
        os.path.join(a.caso, 'resultados_uf')
    if not os.path.isdir(res):
        sys.exit(f'ERRO: não achei a pasta {res}. Rode antes o rodar_tudo.bat')
    saida = a.saida or os.path.join(res, 'apresentacao')
    os.makedirs(saida, exist_ok=True)
    ano = a.ano

    print('Lendo os números dos CSVs...')
    N = numeros(res)
    if 'uf' not in N:
        print('  AVISO: sem gargalo_cmo\\vertimento_causa_uf_mensal.csv (etapa 6): os números principais ficam de fora')
    print('Gerando o mapa e o gráfico de tecnologia...')
    arq_mapa = mapa(N, saida, ano)
    arq_tec = grafico_tecnologia(N, saida, ano)

    D = Deck(res, saida)
    ren = N.get('tot_renovavel', np.zeros(2))
    hid = N.get('tot_hidro_turbinavel', np.zeros(2))
    tot_ren = ren.sum()
    ordem = N.get('ordem_uf', [])
    top5 = ordem[:5]
    pct = (lambda a_, b_: 100 * a_ / b_ if b_ > 0 else 0)

    D.capa(f'Vertimento de energia renovável no SIN — {ano}',
           'Análise das saídas do SDDP (simulação horária com rede elétrica): quanto, onde, quando e por quê',
           datetime.date.today().strftime('%d/%m/%Y'))

    # mensagem principal
    cartoes = []
    if tot_ren > 0:
        cartoes.append((f'{br(tot_ren)} GWh', f'vertimento renovável em {ano} (sem geração distribuída)'))
        cartoes.append((f'{br(pct(ren[0], tot_ren))}%', 'do vertimento renovável ocorre com a usina atrás de um '
                                                        'gargalo de transmissão; o resto é excesso no sistema'))
    if hid.sum() > 0:
        cartoes.append((f'{br(hid.sum())} GWh', f'vertimento turbinável das hidrelétricas, '
                                                f'{br(pct(hid[0], hid.sum()))}% por gargalo'))
    if top5 and tot_ren > 0:
        s5 = sum(N['uf']['renovavel'][u].sum() for u in top5)
        cartoes.append((f'{br(pct(s5, tot_ren))}%', f'do vertimento renovável em 5 estados: {", ".join(top5)}'))
    if 'sub' in N:
        st = sum(N['sub'].values())
        cartoes.append((f'{br(pct(st[0], st.sum()))}%', 'do vertimento (renovável + hidro) com o subsistema inteiro '
                                                        'abaixo do CMO do SIN (gargalo entre subsistemas)'))
    if 'fds' in N:
        u_, f_ = N['fds']
        cartoes.append((f'{br(f_)} × {br(u_)}', 'GWh/dia de vertimento: fim de semana × dia útil'))
    if cartoes:
        D.numeros('Mensagem principal', cartoes, fonte='gargalo_cmo, gargalo_subsistema e analise_semana (CSVs)',
                  notas='Números calculados automaticamente dos CSVs das etapas. Ajuste o texto se quiser.')

    D.texto('Caso e método', [
        f'• Saídas horárias do SDDP para {ano} (simulação com rede elétrica, fluxo DC), média dos cenários.',
        '• Somente dados de entrada e saída do SDDP: vergnd, gergnd, envetu, cmgbus, businj, acline_flow, '
        'transformer_flow, interc, gerhid, gerter, demxba e os arquivos do deck (rede, usinas, carga).',
        '• Estado da usina = UF da barra de conexão; subsistema = o da barra (dbus.dat / sistem.dat).',
        '• A geração distribuída (MMGD/OMGD) fica fora do vertimento: na operação real ela não é cortada '
        '(no deck tem custo de corte 11 $/MWh, contra 10 das centralizadas).',
        '• Hora 1 = 00h–01h.'])
    D.texto('O que é o CMO e por que ele mostra o gargalo', [
        '• O CMO (custo marginal de operação) de uma barra é quanto custaria atender 1 MWh a mais de carga naquela '
        'barra, naquela hora. O SDDP calcula esse valor para cada barra (saída cmgbus).',
        '• Se nenhuma linha está no limite, a energia chega a qualquer barra pelo mesmo custo: o CMO é igual em todo o SIN.',
        '• Se uma linha chega ao limite, a energia de um lado não consegue passar para o outro. Do lado em que sobra '
        'energia, 1 MWh a mais não tem para onde ir e o CMO cai (fica perto de zero). Do outro lado, ele fica mais alto.',
        '• Por isso: se uma usina verte e o CMO da barra dela está ABAIXO do CMO do SIN, a energia dela está presa atrás '
        'de uma linha no limite → vertimento por GARGALO DE TRANSMISSÃO.',
        '• Se a usina verte e o CMO da barra dela é IGUAL ao do SIN (mesmo perto de zero), sobra energia no país inteiro '
        '→ vertimento por EXCESSO NO SISTEMA (falta de demanda).'],
        notas='CMO de cada barra: arquivo cmgbus do SDDP. Barra de cada usina: busconnection.dat e hydrounit??.dat.')
    D.texto('Como cada MW vertido é classificado', [
        '• A classificação é feita em cada hora, em cada cenário e para cada usina que verteu.',
        '• CMO do SIN = mediana do CMO de todas as barras do SIN (metade das barras acima, metade abaixo). Representa o '
        'preço do sistema sem ser puxado por poucas barras com valores extremos.',
        '• Por estado: CMO da barra da usina abaixo do CMO do SIN → GARGALO (vermelho); igual → EXCESSO (cinza).',
        '• Por subsistema: CMO do subsistema (mediana das barras do subsistema) abaixo do SIN → gargalo ENTRE '
        'subsistemas (vermelho): o subsistema inteiro está preso. Subsistema no preço do SIN, mas a barra da usina abaixo '
        'do subsistema → gargalo DENTRO do subsistema (laranja): só a rede perto da usina está no limite. Nenhum dos '
        'dois → EXCESSO (cinza).',
        '• "Abaixo" quer dizer mais de 1 $/MWh abaixo. Diferenças menores aparecem por perdas e arredondamentos e não '
        'indicam linha no limite; por isso são tratadas como preço igual.',
        '• A geração distribuída (MMGD/OMGD) fica fora: na operação real ela não é cortada.'])

    # A. quanto e onde
    D.secao('Quanto e onde', 'Vertimento por estado e tecnologia')
    if arq_mapa and top5 and tot_ren > 0:
        u1 = top5[0]
        D.imagem(f'{NOME_UF.get(u1, u1)} concentra {br(pct(N["uf"]["renovavel"][u1].sum(), tot_ren))}% do '
                 f'vertimento renovável; 5 estados somam '
                 f'{br(pct(sum(N["uf"]["renovavel"][u].sum() for u in top5), tot_ren))}%', arq_mapa,
                 fonte='apresentacao\\mapa_vertimento_uf.png (dados: gargalo_cmo\\vertimento_causa_uf_mensal.csv)',
                 notas='À esquerda, GWh vertidos no ano por estado; à direita, quanto desse vertimento ocorreu com a '
                       'barra da usina atrás de um gargalo de transmissão.')
    if arq_tec:
        D.imagem('Que tecnologia verte em cada estado', arq_tec,
                 fonte='apresentacao\\tecnologia_uf.png (dados: gargalo_cmo\\vertimento_causa_uf_tecnologia.csv)')

    # B. quando
    D.secao('Quando', 'Mês, hora do dia e tipo de dia')
    nota_e3 = 'Gráficos das etapas 3 e 4 (vertimento sem a geração distribuída; período escolhido na etapa 3).'
    D.imagem('Vertimento por mês e hora do dia', 'graficos/mapa_calor_vergnd_estados.png', notas=nota_e3)
    D.imagem('Perfil do vertimento por hora do dia, por estado', 'graficos/boxplot_vergnd_estados.png', notas=nota_e3)
    if 'fds' in N:
        u_, f_ = N['fds']
        tit = f'Fim de semana: {br(f_)} GWh/dia de vertimento, contra {br(u_)} GWh/dia em dia útil'
    else:
        tit = 'Dia útil × fim de semana'
    D.imagem(tit, 'analise_semana/resumo_util_fds.png', notas=nota_e3)
    D.imagem('Vertimento × carga líquida', 'analise_semana/carga_liquida_x_vertimento.png', notas=nota_e3)

    # C. por quê
    D.secao('Por quê', 'Gargalo de transmissão × excesso no sistema')
    if tot_ren > 0:
        tit = (f'{br(pct(ren[1], tot_ren))}% do vertimento renovável é por excesso no sistema; '
               f'{br(pct(ren[0], tot_ren))}% por gargalo de transmissão')
    else:
        tit = 'Gargalo de transmissão × excesso no sistema, por estado'
    D.imagem(tit, 'gargalo_cmo/gargalo_resumo.png')
    D.imagem('Em que horas cada estado está em gargalo', 'relacao_gargalo/ocorrencias_estados.png')
    D.imagem('Restrições de intercâmbio e elos CC no limite, mês a mês', 'gargalo_cmo/restricoes_ativas.png')
    D.imagem('Vertimento por causa × injeção líquida do estado', 'gargalo_linhas/injecao_x_vertimento_causa.png')

    # D. subsistemas
    D.secao('Subsistemas', 'CMO de cada subsistema × CMO do SIN e intercâmbio entre subsistemas')
    if 'sub' in N:
        st = sum(N['sub'].values())
        tit = (f'{br(pct(st[0], st.sum()))}% do vertimento é por gargalo entre subsistemas, '
               f'{br(pct(st[1], st.sum()))}% dentro do subsistema')
    else:
        tit = 'Vertimento por subsistema'
    D.imagem(tit, 'gargalo_subsistema/resumo_subsistemas.png')
    D.imagem('Vertimento por subsistema, mês a mês', 'gargalo_subsistema/mensal_subsistemas.png')
    tit = 'Ligações entre subsistemas: preço separado e circuitos no limite'
    if N.get('itc'):
        r = N['itc'][0]
        tit = (f'Ligação {r["de"]}–{r["para"]}: CMO separado em {br(fnum(r["pct_horas_cmo_separado"]), 1)}% das horas')
    D.imagem(tit, 'gargalo_subsistema/intercambios_subsistemas.png')
    ler_sub = ['Como ler', '• Barras: vertimento por tipo (vermelho = entre subsistemas, laranja = dentro do '
               'subsistema, cinza = excesso).', '• Azul abaixo do preto tracejado = subsistema preso.',
               '• Último painel: o circuito da ligação mais perto do limite (100% = no limite).']
    D.texto('Como ler o gráfico de cada subsistema', [
        'Todos os painéis têm a hora do dia no eixo x (1 = 00h–01h) e são médias de todos os dias e cenários do ano.',
        '1. Vertimento renovável por hora (MW médio): vermelho = entre subsistemas, laranja = dentro do subsistema, '
        'cinza = excesso.',
        '2. O mesmo para o vertimento turbinável das hidrelétricas.',
        '3. CMO por hora em todas as horas: subsistema (azul), SIN (preto tracejado) e subsistemas ligados (pontilhados).',
        '4 e 5. CMO só nos momentos em que houve vertimento, renovável e hidrelétrico, com peso pelo MW vertido: '
        'Σ(CMO × MW vertido) ÷ Σ MW vertido. Faixa rosa = subsistema abaixo do SIN. Uma hora pode mostrar diferença de '
        'CMO e quase nenhuma barra no painel 1: é o preço de poucos MW vertidos.',
        '6. Intercâmbio médio com cada subsistema ligado (MW; positivo = exporta).',
        '7. Carregamento do circuito mais carregado de cada ligação (% do limite físico; 100% = no limite).'])
    for k in N.get('ordem_sub', [])[:3]:
        v = N['sub'][k]
        D.imagem(f'Subsistema {k} ({N["sub_nome"].get(k, "")}): {br(v.sum())} GWh vertidos, '
                 f'{br(pct(v[0], v.sum()))}% entre subsistemas', f'gargalo_subsistema/por_subsistema/subsistema_{k}.png',
                 lateral=ler_sub)

    # E. onde está o gargalo na rede
    D.secao('Onde está o gargalo na rede', 'Linhas e transformadores no limite')
    tit = 'Circuitos com mais vertimento coincidente'
    if N.get('circ') and fnum(N['circ'][0]['vertimento_gargalo_coincidente_GWh']) > 0:
        r = N['circ'][0]
        tit = f'{r["nome"]} ({r["uf_de"]}–{r["uf_para"]}) é o circuito com mais vertimento coincidente'
    D.imagem(tit, 'gargalo_linhas/circuitos_vertimento.png')
    D.imagem('Circuitos mais tempo no limite', 'gargalo_linhas/circuitos_horas_no_limite.png')
    n_s = len(N.get('circ_sobre', []))
    D.imagem((f'{n_s} circuito não monitorado passa de 100% (o SDDP não o limita)' if n_s == 1 else
              f'{n_s} circuitos não monitorados passam de 100% (o SDDP não os limita)')
             if n_s else 'Circuitos não monitorados em sobrecarga',
             'gargalo_linhas/circuitos_sobrecarga_nao_monitorados.png')
    D.imagem('Margem de escoamento das barras, por estado', 'margem_barras/margem_resumo.png')

    # F. estados com mais vertimento
    D.secao('Estados com mais vertimento', ', '.join(top5) if top5 else '')
    D.texto('Como ler o gráfico de cada estado', [
        'Todos os painéis têm a hora do dia no eixo x (1 = 00h–01h) e são médias de todos os dias e cenários do ano.',
        '1. Vertimento renovável por hora (MW médio): vermelho = gargalo de transmissão, cinza = excesso no sistema.',
        '2. O mesmo para o vertimento turbinável das hidrelétricas.',
        '3. CMO por hora em todas as horas: estado (azul, mediana das barras do estado), SIN (preto tracejado) e os 3 '
        'estados com maior capacidade de divisa (pontilhados).',
        '4 e 5. CMO só nos momentos em que houve vertimento, renovável e hidrelétrico, com peso pelo MW vertido: '
        'barras das usinas que verteram (azul) × SIN e estados de divisa. Faixa rosa = barras abaixo do SIN.',
        '6. Carregamento das 4 linhas/trafos monitorados que mais limitam o estado (% do limite físico; 100% = no '
        'limite).',
        '7. Circuitos não monitorados acima de 100% (o SDDP não limita esses circuitos), se houver.'])
    ler_est = ['Como ler', '• Barras: vermelho = gargalo, cinza = excesso.',
               '• CMO: azul (estado ou barras das usinas) abaixo do SIN (preto tracejado) = gargalo.',
               '• Linhas: 100% tracejado = limite físico do deck.']
    ler_bal = ['Como ler', '• Abaixo da linha preta: consumido no estado.', '• Contorno roxo: exportado.',
               '• Hachurado no topo: vertido (vermelho = gargalo, cinza = excesso).']
    for i, u in enumerate(top5):
        v = N['uf']['renovavel'][u]
        D.imagem(f'{NOME_UF.get(u, u)}: {br(v.sum())} GWh de vertimento renovável, {br(pct(v[0], v.sum()))}% por '
                 'gargalo', f'gargalo_linhas/por_estado/estado_{u}.png', lateral=ler_est)
        D.imagem(f'{NOME_UF.get(u, u)}: o que estava gerando quando houve corte', f'balanco_uf/balanco_{u}.png',
                 lateral=ler_bal)
        if i == 0:
            D.imagem(f'{NOME_UF.get(u, u)}: vertimento, injeção, CMO e linhas por situação da hora',
                     f'relacao_gargalo/relacao_{u}.png')

    # fechamento
    conc = []
    if tot_ren > 0:
        conc.append(f'• Quanto: {br(tot_ren)} GWh de vertimento renovável em {ano} (sem GD)'
                    + (f' e {br(hid.sum())} GWh de vertimento turbinável.' if hid.sum() > 0 else '.'))
        conc.append(f'• Onde: {", ".join(top5)} concentram '
                    f'{br(pct(sum(N["uf"]["renovavel"][u].sum() for u in top5), tot_ren))}%.')
        conc.append(f'• Por quê: {br(pct(ren[1], tot_ren))}% é excesso no sistema (falta de demanda) e '
                    f'{br(pct(ren[0], tot_ren))}% gargalo de transmissão.')
    if 'fds' in N:
        conc.append(f'• Quando: fim de semana {br(N["fds"][1])} GWh/dia × dia útil {br(N["fds"][0])} GWh/dia.')
    if N.get('circ') and fnum(N['circ'][0]['vertimento_gargalo_coincidente_GWh']) > 0:
        conc.append('• Linhas: ' + '; '.join(f'{r["nome"]} ({r["uf_de"]}–{r["uf_para"]})' for r in N['circ'][:3]) + '.')
    conc.append('(Revise e complete estas conclusões.)')
    D.texto('Conclusões', conc, notas='Frases montadas a partir dos CSVs; ajuste a redação.')
    D.texto('Limitações', [
        '• Critério de gargalo: diferença de CMO maior que 1 $/MWh (opção --tolerancia).',
        '• Circuitos não monitorados não têm limite no SDDP: sobrecargas neles são gargalos que a simulação '
        'não representa.',
        '• A geração distribuída tem custo de corte no deck; aqui ela foi retirada das contas de vertimento.',
        '• A soma das capacidades dos circuitos de divisa não é a capacidade real de transferência.',
        '• Valores são médias dos cenários; os gráficos de caixa mostram a variação entre cenários.'])
    D.texto('Próximos passos', [
        '• Sensibilidades no deck: custo de corte da GD; monitorar os circuitos em sobrecarga.',
        '• Reforços nas ligações e circuitos que mais vezes ficam no limite.',
        '• Comparar com outros anos do horizonte.'])

    # anexo
    D.secao('Anexo', 'Gráficos por estado e por subsistema')
    for u in ordem[5:]:
        if N['uf']['renovavel'][u].sum() >= 10:
            v = N['uf']['renovavel'][u]
            D.imagem(f'{NOME_UF.get(u, u)}: {br(v.sum())} GWh, {br(pct(v[0], v.sum()))}% por gargalo',
                     f'gargalo_linhas/por_estado/estado_{u}.png', lateral=ler_est)
    for k in N.get('ordem_sub', [])[3:]:
        v = N['sub'][k]
        if v.sum() >= 1:
            D.imagem(f'Subsistema {k} ({N["sub_nome"].get(k, "")}): {br(v.sum())} GWh vertidos',
                     f'gargalo_subsistema/por_subsistema/subsistema_{k}.png', lateral=ler_sub)

    arq = os.path.join(saida, f'apresentacao_vertimento_{ano}.pptx')
    try:
        D.prs.save(arq)
    except PermissionError:
        sys.exit(f'ERRO: não consegui gravar {arq}. Ele está aberto no PowerPoint? Feche e rode de novo.')
    print(f'{D.n} slides.')
    if D.faltando:
        print(f'  AVISO: {len(D.faltando)} gráficos não encontrados (slides pulados): ' + ', '.join(D.faltando[:12]) +
              (' ...' if len(D.faltando) > 12 else ''))
    print(f'Fim. Apresentação: {arq}')


if __name__ == '__main__':
    main()
