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
  mapa_calor_<var>_estados.png média por mês (linhas) e hora do dia (colunas)
  injecao_x_vertimento.png     vertimento x injeção líquida, hora a hora, por
                               estado (precisa de businj e vergnd)
  vertimento_tecnologia.png    vertimento por estado e tecnologia (precisa de
                               vergnd_agente_mensal.csv)
  vertimento_uf_usina_x_barra.png  vertimento pela UF da barra de conexão x UF
                               do nome da usina (precisa de vergnd_agente_mensal.csv
                               e usinas_renovaveis_uf.csv)

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
    l1 = linhas[0].split(',')
    unidade = l1[3].strip()
    mes_ini, ano_ini = int(l1[5]), int(l1[6])
    cab = [c.strip() for c in linhas[3].split(',')]
    dados = np.loadtxt(linhas[4:], delimiter=',', ndmin=2)
    return dict(estagio=dados[:, 0].astype(int), cenario=dados[:, 1].astype(int),
                hora=dados[:, 2].astype(int), valores=dados[:, 3:], ufs=cab[3:], unidade=unidade,
                mes_ini=mes_ini, ano_ini=ano_ini)


def rotulo_estagio(d, e):
    m = d['mes_ini'] - 1 + e - 1
    return f'{MESES[m % 12]}/{str(d["ano_ini"] + m // 12)[2:]}'


MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']


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


def ler_limites(caminho):
    """limites_uf.csv (de limites_uf.py) -> {uf: (exportação MW, importação MW)}."""
    import csv
    if not caminho or not os.path.exists(caminho):
        return {}
    with open(caminho, encoding='utf-8-sig', newline='') as f:
        return {r['uf']: (float(r['limite_exportacao_MW']), float(r['limite_importacao_MW']))
                for r in csv.DictReader(f)}


def figura_estado(u, dados, saida, limites=None):
    vars_ = [v for v in ('gergnd', 'vergnd', 'businj', 'bus_inj') if v in dados and u in dados[v]['ufs']]
    fig, axs = plt.subplots(len(vars_), 1, figsize=(11, 3.2 * len(vars_)), sharex=True, squeeze=False)
    for ax, v in zip(axs[:, 0], vars_):
        d = dados[v]
        i = d['ufs'].index(u)
        caixas(ax, d, i, VARS[v]['cor'])
        if v.startswith('bus'):
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
            titulo = f'{VARS[v]["titulo"]} ({d["unidade"]}) — positivo = exporta'
            if limites and u in limites:
                exp, imp = limites[u]
                lo, hi = ax.get_ylim()
                lo, hi = min(lo, -imp), max(hi, exp)
                ax.set_ylim(lo - 0.10 * (hi - lo), hi + 0.10 * (hi - lo))
                for y, txt, va, dy in ((exp, f'limite de exportação: +{exp:,.0f} MW', 'top', -0.015),
                                       (-imp, f'limite de importação: −{imp:,.0f} MW', 'bottom', 0.015)):
                    ax.axhline(y, color=TEXTO, linewidth=1.3, linestyle='--')
                    ax.text(0.6, y + dy * (hi - lo), txt.replace(',', '.'), va=va, ha='left', fontsize=8.5,
                            color=TEXTO)
                titulo += ' · tracejado = capacidade dos circuitos de divisa (rede do SDDP)'
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


# ----------------------------------------------------------------------------
# Mapa de calor mês x hora
# ----------------------------------------------------------------------------
def _cmap_sequencial(cor):
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list('seq', [FUNDO, cor, '#3a1a08' if cor == '#eb6834' else '#06331f'])


def _cmap_divergente():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list('div', ['#b4302f', '#e34948', '#e9e8e4', '#2a78d6', '#164a8a'])


def matriz_mes_hora(d, i_uf):
    est = np.unique(d['estagio'])
    hd = hora_do_dia(d)
    M = np.zeros((len(est), 24))
    for k, e in enumerate(est):
        me = d['estagio'] == e
        x = d['valores'][me, i_uf]
        h = hd[me]
        M[k] = np.bincount(h, weights=x, minlength=24) / np.bincount(h, minlength=24)
    return est, M


def mapa_calor(var, d, saida):
    info = VARS[var]
    div = var.startswith('bus')
    cmap = _cmap_divergente() if div else _cmap_sequencial(info['cor'])
    fig, axs = plt.subplots(7, 4, figsize=(16, 24))
    axs = axs.ravel()
    ufs = [u for u in ORDEM_UF if u in d['ufs']]
    for k, u in enumerate(ufs):
        ax = axs[k]
        est, M = matriz_mes_hora(d, d['ufs'].index(u))
        if div:
            lim = max(abs(M).max(), 1e-9)
            im = ax.imshow(M, aspect='auto', cmap=cmap, vmin=-lim, vmax=lim, interpolation='nearest')
        else:
            im = ax.imshow(M, aspect='auto', cmap=cmap, vmin=0, vmax=max(M.max(), 1e-9),
                           interpolation='nearest')
        ax.set_yticks(range(len(est)), [rotulo_estagio(d, e) for e in est], fontsize=7)
        ax.set_xticks(range(0, 24, 2), [str(h) for h in range(1, 25, 2)], fontsize=7)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(f'{u}  ·  máx. {M.max():,.0f} MW'.replace(',', '.') if not div else
                     f'{u}  ·  {M.min():,.0f} a {M.max():,.0f} MW'.replace(',', '.'),
                     loc='left', fontsize=10, fontweight='bold')
        cb = fig.colorbar(im, ax=ax, fraction=0.05, pad=0.02)
        cb.ax.tick_params(labelsize=7)
        cb.outline.set_visible(False)
    for ax in axs[len(ufs):]:
        ax.axis('off')
    extra = ' (azul = exporta, vermelho = importa)' if div else ''
    fig.suptitle(f'{info["titulo"]}: média por mês e hora do dia, MW{extra} — {periodo(d)}',
                 x=0.01, ha='left', fontsize=14, fontweight='bold')
    fig.text(0.01, 0.005, 'Cada célula = média de todos os dias do mês e de todos os cenários. '
             'Hora 1 = 00h-01h. Cada estado tem sua própria escala de cor.', fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.01, 1, 0.98))
    nome = os.path.join(saida, f'mapa_calor_{var}_estados.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)
    return nome


# ----------------------------------------------------------------------------
# Injeção líquida x vertimento
# ----------------------------------------------------------------------------
def injecao_x_vertimento(dados, saida, n_estados=12):
    b = dados.get('businj') or dados.get('bus_inj')
    v = dados.get('vergnd')
    if b is None or v is None:
        return None
    if not (np.array_equal(b['estagio'], v['estagio']) and np.array_equal(b['hora'], v['hora'])
            and np.array_equal(b['cenario'], v['cenario'])):
        print('AVISO: businj e vergnd com horas diferentes; gráfico injeção x vertimento não gerado')
        return None
    tot = {u: v['valores'][:, i].sum() for i, u in enumerate(v['ufs'])}
    ufs = sorted([u for u in tot if tot[u] > 0 and u in b['ufs']], key=lambda u: -tot[u])[:n_estados]
    lin = int(np.ceil(len(ufs) / 4))
    fig, axs = plt.subplots(lin, 4, figsize=(16, 4.2 * lin), squeeze=False)
    axs = axs.ravel()
    linhas_tab = []
    for k, u in enumerate(ufs):
        ax = axs[k]
        x = b['valores'][:, b['ufs'].index(u)]
        y = v['valores'][:, v['ufs'].index(u)]
        hb = ax.hexbin(x, y, gridsize=45, bins='log', cmap=_cmap_sequencial('#2a78d6'), mincnt=1,
                       linewidths=0)
        # média do vertimento por faixa de injeção
        faixas = np.linspace(x.min(), x.max(), 26)
        idx = np.clip(np.digitize(x, faixas) - 1, 0, 24)
        cnt = np.bincount(idx, minlength=25)
        med = np.bincount(idx, weights=y, minlength=25) / np.maximum(cnt, 1)
        ok = cnt >= 20
        cx = (faixas[:-1] + faixas[1:]) / 2
        ax.plot(cx[ok], med[ok], color=VARS['vergnd']['cor'], linewidth=2, label='média do vertimento')
        ax.axvline(0, color=TEXTO2, linewidth=0.8)
        p95 = np.percentile(x, 95)
        ax.axvline(p95, color=TEXTO2, linewidth=0.8, linestyle=':')
        # parcela do vertimento que ocorre quando a injeção está nos 10% mais altos
        p90 = np.percentile(x, 90)
        frac = 100 * y[x >= p90].sum() / max(y.sum(), 1e-9)
        corr = np.corrcoef(x, y)[0, 1] if y.std() > 0 and x.std() > 0 else float('nan')
        linhas_tab.append((u, frac, corr))
        ax.set_title(f'{u}  ·  {frac:.0f}% do vertim. no top 10% de injeção  ·  r = {corr:.2f}'.replace('.', ','),
                     loc='left', fontsize=9.5, fontweight='bold')
        ax.set_xlabel('Injeção líquida do estado (MW)  →  exporta')
        ax.set_ylabel('Vertimento (MW)')
        ax.grid(color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        if k == 0:
            ax.legend(loc='upper left', fontsize=8, frameon=False)
    for ax in axs[len(ufs):]:
        ax.axis('off')
    fig.suptitle(f'Vertimento × injeção líquida, hora a hora — {len(ufs)} estados com mais vertimento, {periodo(v)}',
                 x=0.01, ha='left', fontsize=14, fontweight='bold')
    fig.text(0.01, 0.005, 'Cor = quantidade de horas (escala log). Linha laranja = vertimento médio por faixa de '
             'injeção. Linha pontilhada = injeção no percentil 95. Vertimento crescendo junto com a injeção até '
             'uma "parede" vertical indica limite de exportação (transmissão).', fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.015, 1, 0.97))
    nome = os.path.join(saida, 'injecao_x_vertimento.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)
    with open(os.path.join(saida, 'injecao_x_vertimento.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,pct_vertimento_com_injecao_no_top10pct,correlacao_injecao_vertimento\n')
        for u, fr, c in linhas_tab:
            f.write(f'{u},{fr:.1f},{c:.3f}\n')
    return nome


# ----------------------------------------------------------------------------
# A partir do arquivo por usina (<var>_agente_mensal.csv)
# ----------------------------------------------------------------------------
TEC_ORDEM = ['Eolica', 'Solar', 'GD Solar', 'Biomassa', 'PCH', 'Outras GD']
TEC_COR = {'Eolica': '#2a78d6', 'Solar': '#eb6834', 'GD Solar': '#1baf7a', 'Biomassa': '#eda100',
           'PCH': '#e87ba4', 'Outras GD': '#6250d6'}
TEC_NOME = {'Eolica': 'Eólica', 'Solar': 'Solar centralizada', 'GD Solar': 'GD solar',
            'Biomassa': 'Biomassa', 'PCH': 'PCH', 'Outras GD': 'Outras GD'}


def ler_agente(caminho):
    import csv
    with open(caminho, encoding='utf-8-sig', newline='') as f:
        primeira = f.readline()
        f.seek(0)
        sep = ';' if primeira.count(';') > primeira.count(',') else ','
        linhas = list(csv.reader(f, delimiter=sep))
    cab = linhas[0]
    tot = [float(r[-1].replace(',', '.') if sep == ';' else r[-1]) for r in linhas[1:]]
    return [dict(zip(cab, r), total=t) for r, t in zip(linhas[1:], tot)], cab[-1]


def vertimento_tecnologia(pasta, saida):
    arq = os.path.join(pasta, 'vergnd_agente_mensal.csv')
    if not os.path.exists(arq):
        return None
    usinas, col = ler_agente(arq)
    fator = 1 / 1000 if col.startswith('total_MWh') else 1  # MWh -> GWh
    soma = {}
    for u in usinas:
        soma.setdefault(u['uf'], {}).setdefault(u['tecnologia'], 0.0)
        soma[u['uf']][u['tecnologia']] += u['total'] * fator
    tot = {uf: sum(v.values()) for uf, v in soma.items()}
    ufs = sorted([uf for uf in tot if tot[uf] >= 1], key=lambda uf: tot[uf])
    tecs = [t for t in TEC_ORDEM if any(soma[uf].get(t, 0) > 0 for uf in ufs)]
    fig, axs = plt.subplots(1, 2, figsize=(14, 0.34 * len(ufs) + 2))
    for ax, pct in zip(axs, (False, True)):
        esq = np.zeros(len(ufs))
        for t in tecs:
            v = np.array([soma[uf].get(t, 0) for uf in ufs])
            if pct:
                v = 100 * v / np.array([tot[uf] for uf in ufs])
            ax.barh(range(len(ufs)), v, left=esq, color=TEC_COR[t], height=0.72,
                    edgecolor=FUNDO, linewidth=1, label=TEC_NOME[t])
            esq += v
        ax.set_yticks(range(len(ufs)), ufs)
        ax.grid(axis='x', color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        if not pct:
            for k, uf in enumerate(ufs):
                ax.text(tot[uf], k, f' {tot[uf]:,.0f}'.replace(',', '.'), va='center', fontsize=8, color=TEXTO2)
            ax.set_title('Vertimento no período (GWh, média dos cenários)', loc='left', fontsize=10)
        else:
            ax.set_xlim(0, 100)
            ax.set_title('Participação de cada tecnologia no vertimento do estado (%)', loc='left', fontsize=10)
    axs[0].legend(loc='lower right', fontsize=8, frameon=False)
    fig.suptitle('Vertimento renovável por estado e tecnologia (UF da barra de conexão)', x=0.01, ha='left',
                 fontsize=13, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    nome = os.path.join(saida, 'vertimento_tecnologia.png')
    fig.savefig(nome, dpi=130)
    plt.close(fig)
    with open(os.path.join(saida, 'vertimento_tecnologia.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,' + ','.join(tecs) + ',total_GWh\n')
        for uf in reversed(ufs):
            f.write(uf + ',' + ','.join(f'{soma[uf].get(t, 0):.1f}' for t in tecs) + f',{tot[uf]:.1f}\n')
    return nome


def vertimento_uf_usina_x_barra(pasta, saida, tabelas):
    import csv
    arq = os.path.join(pasta, 'vergnd_agente_mensal.csv')
    tab = os.path.join(tabelas, 'usinas_renovaveis_uf.csv')
    if not (os.path.exists(arq) and os.path.exists(tab)):
        return None
    with open(tab, encoding='utf-8-sig', newline='') as f:
        primeira = f.readline()
        f.seek(0)
        sep = ';' if primeira.count(';') > primeira.count(',') else ','
        uf_nome = {r['nome_usina']: r['uf_nome_usina'] for r in csv.DictReader(f, delimiter=sep)}
    usinas, col = ler_agente(arq)
    fator = 1 / 1000 if col.startswith('total_MWh') else 1
    barra, nome, fluxo = {}, {}, {}
    for u in usinas:
        ub, un = u['uf'], uf_nome.get(u['usina'], u['uf'])
        g = u['total'] * fator
        barra[ub] = barra.get(ub, 0) + g
        nome[un] = nome.get(un, 0) + g
        if ub != un and g > 0:
            fluxo[(un, ub)] = fluxo.get((un, ub), 0) + g
    ufs = sorted([x for x in set(barra) | set(nome) if max(barra.get(x, 0), nome.get(x, 0)) >= 1],
                 key=lambda x: barra.get(x, 0))
    y = np.arange(len(ufs))
    fig, axs = plt.subplots(1, 2, figsize=(14, 0.36 * len(ufs) + 2),
                            gridspec_kw=dict(width_ratios=[1.3, 1]))
    ax = axs[0]
    ax.barh(y + 0.19, [barra.get(x, 0) for x in ufs], height=0.36, color='#2a78d6', label='UF da barra de conexão')
    ax.barh(y - 0.19, [nome.get(x, 0) for x in ufs], height=0.36, color='#eb6834', label='UF do nome da usina')
    ax.set_yticks(y, ufs)
    ax.grid(axis='x', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc='lower right', fontsize=8, frameon=False)
    ax.set_title('Vertimento no período (GWh, média dos cenários)', loc='left', fontsize=10)
    ax = axs[1]
    dif = [barra.get(x, 0) - nome.get(x, 0) for x in ufs]
    ax.barh(y, dif, color=['#2a78d6' if d >= 0 else '#eb6834' for d in dif], height=0.6)
    ax.axvline(0, color=TEXTO2, linewidth=0.8)
    for k, d in enumerate(dif):
        if abs(d) >= 0.5:
            ax.text(d, k, f' {d:+,.0f} '.replace(',', '.'), va='center', ha='left' if d >= 0 else 'right',
                    fontsize=8, color=TEXTO2)
    ax.set_yticks(y, ufs)
    ax.grid(axis='x', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title('Diferença barra − usina (GWh): azul = recebe vertimento de usinas de outros estados',
                 loc='left', fontsize=9)
    movido = sum(fluxo.values())
    total = sum(barra.values())
    fig.suptitle(f'Vertimento pela UF da barra × UF da usina — {movido:,.0f} GWh ({100 * movido / max(total, 1e-9):.1f}%) '
                 f'mudam de estado'.replace(',', 'X').replace('.', ',').replace('X', '.'),
                 x=0.01, ha='left', fontsize=13, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    nome_arq = os.path.join(saida, 'vertimento_uf_usina_x_barra.png')
    fig.savefig(nome_arq, dpi=130)
    plt.close(fig)
    with open(os.path.join(saida, 'vertimento_uf_usina_x_barra.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf_usina,uf_barra,vertimento_GWh\n')
        for (a, b), g in sorted(fluxo.items(), key=lambda z: -z[1]):
            f.write(f'{a},{b},{g:.2f}\n')
    return nome_arq


def main():
    p = argparse.ArgumentParser(description='Box plots por UF das saídas do SDDP.')
    p.add_argument('pasta', help='pasta resultados_uf com os *_uf_horario.csv')
    p.add_argument('--saida', help='pasta dos gráficos (padrão: <pasta>\\graficos)')
    p.add_argument('--estagios', nargs=2, type=int, metavar=('INICIAL', 'FINAL'))
    p.add_argument('--limites', help='limites_uf.csv gerado por limites_uf.py (padrão: procura na pasta)')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)),
                   help='pasta com usinas_renovaveis_uf.csv (padrão: pasta deste script)')
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
        print('Mapa de calor:', mapa_calor(v, d, saida))
    r = injecao_x_vertimento(dados, saida)
    if r:
        print('Injeção x vertimento:', r)
    arq_lim = a.limites or next((c for c in (os.path.join(a.pasta, 'limites_uf.csv'),
                                             os.path.join(a.tabelas, 'limites_uf.csv')) if os.path.exists(c)), None)
    limites = ler_limites(arq_lim)
    print('Limites de exportação/importação:', arq_lim if limites else 'não encontrados (gráficos sem as linhas)')
    ufs = sorted(set(u for d in dados.values() for u in d['ufs']),
                 key=lambda u: ORDEM_UF.index(u) if u in ORDEM_UF else 99)
    for u in ufs:
        figura_estado(u, dados, saida, limites)
    print(f'Gráficos por estado: {len(ufs)} arquivos estado_<UF>.png')
    r = ranking(dados, saida)
    if r:
        print('Ranking:', r)
    r = vertimento_tecnologia(a.pasta, saida)
    print('Vertimento por tecnologia:', r or 'vergnd_agente_mensal.csv não encontrado, gráfico não gerado')
    r = vertimento_uf_usina_x_barra(a.pasta, saida, a.tabelas)
    print('UF da usina x UF da barra:', r or 'vergnd_agente_mensal.csv ou usinas_renovaveis_uf.csv não encontrado')
    print('Fim. Gráficos em', saida)


if __name__ == '__main__':
    main()
