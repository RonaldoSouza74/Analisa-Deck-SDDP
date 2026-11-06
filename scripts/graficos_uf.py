"""Gráficos box plot por UF a partir dos CSV horários de agrega_saidas_uf.py.

Para cada hora do dia (eixo x), o box plot mostra a distribuição dos valores em
todos os dias do período e todos os cenários (ex.: 365 dias x 10 cenários =
3.650 valores por hora). Caixa = 25% a 75%, linha = mediana, bigodes = 5% a 95%,
losango = média.

Gera, na pasta de saída:
  boxplot_<var>_estados.png    os 27 estados num painel só (escala própria em cada)
  estado_<UF>.png              por estado: geração, vertimento e injeção, um
                               gráfico embaixo do outro (os que existirem)
  ranking_estados.png          vertimento médio anual por estado (e % da
                               geração renovável disponível, se houver gergnd)

Uso:
  python graficos_uf.py "C:\\...\\resultados_uf"
  python graficos_uf.py "C:\\...\\resultados_uf" --estagios 2 13

Requer numpy e matplotlib.
"""
import argparse
import os
import sys

try:
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError as e:
    sys.exit(f'ERRO: falta o pacote {e.name}. Rode:  python -m pip install numpy matplotlib')

VARS = {
    'gergnd': dict(titulo='Geração renovável', cor='#1baf7a'),
    'vergnd': dict(titulo='Vertimento renovável', cor='#eb6834'),
    'businj': dict(titulo='Injeção líquida nas barras', cor='#2a78d6'),
    'bus_inj': dict(titulo='Injeção líquida nas barras', cor='#2a78d6'),
}
REGIOES = [('Norte', ['AC', 'AM', 'AP', 'PA', 'RO', 'RR', 'TO']),
           ('Nordeste', ['AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE']),
           ('Centro-Oeste', ['DF', 'GO', 'MS', 'MT']),
           ('Sudeste', ['ES', 'MG', 'RJ', 'SP']),
           ('Sul', ['PR', 'RS', 'SC'])]
ORDEM_UF = [u for _, us in REGIOES for u in us]
REGIAO_DA_UF = {u: r for r, us in REGIOES for u in us}

TEXTO, TEXTO2, GRADE, FUNDO = '#0b0b0b', '#52514e', '#e5e4df', '#fcfcfb'
plt.rcParams.update({
    'font.size': 9, 'axes.edgecolor': GRADE, 'axes.labelcolor': TEXTO2,
    'xtick.color': TEXTO2, 'ytick.color': TEXTO2, 'axes.titlecolor': TEXTO,
    'figure.facecolor': FUNDO, 'axes.facecolor': FUNDO, 'savefig.facecolor': FUNDO,
    'axes.spines.top': False, 'axes.spines.right': False,
})


def ler_horario(caminho):
    """Lê um CSV no formato do SDDP: 3 linhas de cabeçalho + Mês,Cenários,Hora,..."""
    with open(caminho, encoding='latin-1') as f:
        linhas = f.readlines()
    unidade = linhas[0].split(',')[3].strip()
    cab = [c.strip() for c in linhas[3].split(',')]
    dados = np.loadtxt(linhas[4:], delimiter=',', ndmin=2)
    return dict(estagio=dados[:, 0].astype(int), cenario=dados[:, 1].astype(int),
                hora=dados[:, 2].astype(int), valores=dados[:, 3:], ufs=cab[3:], unidade=unidade)


def hora_do_dia(d):
    return (d['hora'] - 1) % 24          # 0 = primeira hora do dia (00h-01h)


def caixas(ax, d, i_uf, cor):
    hd = hora_do_dia(d)
    grupos = [d['valores'][hd == h, i_uf] for h in range(24)]
    bp = ax.boxplot(grupos, positions=range(1, 25), widths=0.6, whis=(5, 95), showfliers=False,
                    showmeans=True, patch_artist=True,
                    boxprops=dict(facecolor=cor + '55', edgecolor=cor, linewidth=1),
                    whiskerprops=dict(color=cor, linewidth=1), capprops=dict(color=cor, linewidth=1),
                    medianprops=dict(color=TEXTO, linewidth=1.5),
                    meanprops=dict(marker='D', markersize=3.5, markerfacecolor=TEXTO,
                                   markeredgecolor=FUNDO))
    ax.set_xticks(range(1, 25), [str(h) if h % 2 else '' for h in range(1, 25)])
    ax.set_xlim(0.3, 24.7)
    ax.grid(axis='y', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    return bp


def energia_media_anual(d, i_uf):
    """GWh no período, média dos cenários (valores horários em MW)."""
    n_cen = len(np.unique(d['cenario']))
    return d['valores'][:, i_uf].sum() / n_cen / 1000


def periodo(d):
    e = np.unique(d['estagio'])
    return f'estágios {e.min()} a {e.max()}, {len(np.unique(d["cenario"]))} cenários'


def legenda_box(fig):
    fig.text(0.01, 0.005, 'Caixa: 25% a 75% · linha: mediana · losango: média · bigodes: 5% a 95%. '
             'Hora 1 = 00h-01h. Valores de todos os dias do período e todos os cenários.',
             fontsize=8, color=TEXTO2)


def painel_estados(var, d, saida):
    info = VARS[var]
    fig, axs = plt.subplots(7, 4, figsize=(16, 22))
    axs = axs.ravel()
    ufs = [u for u in ORDEM_UF if u in d['ufs']]
    for k, u in enumerate(ufs):
        ax = axs[k]
        i = d['ufs'].index(u)
        if not np.any(d['valores'][:, i]):
            ax.text(0.5, 0.5, 'sem valores', ha='center', va='center', color=TEXTO2, transform=ax.transAxes)
            ax.set_xticks([]); ax.set_yticks([])
        else:
            caixas(ax, d, i, info['cor'])
            if var.startswith('bus'):
                ax.axhline(0, color=TEXTO2, linewidth=0.8)
        tot = energia_media_anual(d, i)
        sub = f'{tot:,.0f} GWh'.replace(',', '.') if not var.startswith('bus') else REGIAO_DA_UF[u]
        ax.set_title(f'{u}  ·  {sub}', loc='left', fontsize=10, fontweight='bold')
    for ax in axs[len(ufs):]:
        ax.axis('off')
    unid = d['unidade']
    extra = ' (positivo = estado exporta)' if var.startswith('bus') else ''
    fig.suptitle(f'{info["titulo"]} por hora do dia, {unid}{extra} — {periodo(d)}',
                 x=0.01, ha='left', fontsize=14, fontweight='bold', color=TEXTO)
    legenda_box(fig)
    fig.tight_layout(rect=(0, 0.012, 1, 0.98))
    nome = os.path.join(saida, f'boxplot_{var}_estados.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)
    return nome


def figura_estado(u, dados, saida):
    vars_ = [v for v in ('gergnd', 'vergnd', 'businj', 'bus_inj') if v in dados and u in dados[v]['ufs']]
    fig, axs = plt.subplots(len(vars_), 1, figsize=(11, 3.2 * len(vars_)), sharex=True, squeeze=False)
    for ax, v in zip(axs[:, 0], vars_):
        d = dados[v]
        i = d['ufs'].index(u)
        caixas(ax, d, i, VARS[v]['cor'])
        if v.startswith('bus'):
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
            titulo = f'{VARS[v]["titulo"]} ({d["unidade"]}) — positivo = exporta'
        else:
            titulo = f'{VARS[v]["titulo"]} ({d["unidade"]}) — {energia_media_anual(d, i):,.0f} GWh no período'.replace(',', '.')
        ax.set_title(titulo, loc='left', fontsize=10)
        ax.set_ylabel(d['unidade'])
    axs[-1, 0].set_xlabel('Hora do dia')
    d0 = dados[vars_[0]]
    fig.suptitle(f'{u} ({REGIAO_DA_UF.get(u, "")}) — {periodo(d0)}', x=0.01, ha='left',
                 fontsize=13, fontweight='bold')
    legenda_box(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    nome = os.path.join(saida, f'estado_{u}.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)


def ranking(dados, saida):
    if 'vergnd' not in dados:
        return None
    v = dados['vergnd']
    ver = {u: energia_media_anual(v, i) for i, u in enumerate(v['ufs'])}
    ufs = sorted([u for u in ver if ver[u] > 0], key=lambda u: ver[u])
    g = dados.get('gergnd')
    n = 2 if g else 1
    fig, axs = plt.subplots(1, n, figsize=(6 * n, 0.32 * len(ufs) + 1.5), squeeze=False)
    ax = axs[0, 0]
    y = range(len(ufs))
    ax.barh(y, [ver[u] for u in ufs], color=VARS['vergnd']['cor'], height=0.7)
    for k, u in enumerate(ufs):
        ax.text(ver[u], k, f' {ver[u]:,.0f}'.replace(',', '.'), va='center', fontsize=8, color=TEXTO2)
    ax.set_yticks(list(y), ufs)
    ax.set_title('Vertimento no período (GWh, média dos cenários)', loc='left', fontsize=10)
    ax.grid(axis='x', color=GRADE, linewidth=0.6); ax.set_axisbelow(True)
    if g:
        ger = {u: energia_media_anual(g, i) for i, u in enumerate(g['ufs'])}
        pct = {u: 100 * ver[u] / (ver[u] + ger.get(u, 0)) for u in ufs}
        ax = axs[0, 1]
        ax.barh(y, [pct[u] for u in ufs], color=VARS['vergnd']['cor'], height=0.7)
        for k, u in enumerate(ufs):
            ax.text(pct[u], k, f' {pct[u]:.1f}%'.replace('.', ','), va='center', fontsize=8, color=TEXTO2)
        ax.set_yticks(list(y), ufs)
        ax.set_title('Vertimento / (geração + vertimento), %', loc='left', fontsize=10)
        ax.grid(axis='x', color=GRADE, linewidth=0.6); ax.set_axisbelow(True)
    fig.suptitle(f'Vertimento renovável por estado — {periodo(v)}', x=0.01, ha='left',
                 fontsize=13, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    nome = os.path.join(saida, 'ranking_estados.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)
    return nome


def main():
    p = argparse.ArgumentParser(description='Box plots por UF das saídas do SDDP.')
    p.add_argument('pasta', help='pasta resultados_uf com os *_uf_horario.csv')
    p.add_argument('--saida', help='pasta dos gráficos (padrão: <pasta>\\graficos)')
    p.add_argument('--estagios', nargs=2, type=int, metavar=('INICIAL', 'FINAL'))
    a = p.parse_args()
    saida = a.saida or os.path.join(a.pasta, 'graficos')
    os.makedirs(saida, exist_ok=True)

    dados = {}
    for v in VARS:
        arq = os.path.join(a.pasta, f'{v}_uf_horario.csv')
        if os.path.exists(arq):
            print(f'Lendo {arq} ...')
            d = ler_horario(arq)
            if a.estagios:
                m = (d['estagio'] >= a.estagios[0]) & (d['estagio'] <= a.estagios[1])
                if not m.any():
                    sys.exit(f'ERRO: nenhum dado dos estágios {a.estagios} em {arq}')
                d = {k: (x[m] if isinstance(x, np.ndarray) else x) for k, x in d.items()}
            dados[v] = d
    if not dados:
        sys.exit(f'ERRO: nenhum *_uf_horario.csv encontrado em {a.pasta}')

    for v, d in dados.items():
        print('Gráfico com todos os estados:', painel_estados(v, d, saida))
    ufs = sorted(set(u for d in dados.values() for u in d['ufs']),
                 key=lambda u: ORDEM_UF.index(u) if u in ORDEM_UF else 99)
    for u in ufs:
        figura_estado(u, dados, saida)
    print(f'Gráficos por estado: {len(ufs)} arquivos estado_<UF>.png')
    r = ranking(dados, saida)
    if r:
        print('Ranking:', r)
    print('Fim. Gráficos em', saida)


if __name__ == '__main__':
    main()
