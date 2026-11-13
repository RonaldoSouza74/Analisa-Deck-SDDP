"""Margem de escoamento por barra: injeção do SDDP x capacidade dos circuitos monitorados.

Para cada barra CA:
  capacidade = soma dos limites (Rating das linhas, Rn dos transformadores) dos circuitos
               MONITORADOS (FlagMonitored = 1) em operação no ano, ligados à barra, mais a
               capacidade dos conversores CA->CC ligados a ela (elos de corrente contínua);
  sem limite = barra sem nenhum circuito monitorado, ou com algum circuito monitorado de
               limite 99999 (sem limite no deck) -> conta como COM margem;
  SEM margem = barra em que a injeção líquida do SDDP (businj, positivo = barra exporta)
               supera a capacidade em pelo menos uma hora de um cenário do ano;
  COM margem = as demais.

Depois agrega por estado, hora a hora e cenário a cenário, a injeção e a capacidade das
barras de cada grupo e faz os gráficos.

Lê o businj.bin direto do disco, em duas passadas (classificação e agregação).

Uso:
  python margem_barras.py "<pasta do caso>" [--tabelas <pasta com barras_uf.csv>]
                          [--saida <pasta>] [--ano 2030]
Padrão de saída: <pasta do caso>\\resultados_uf\\margem_barras

Saídas:
  barras_margem.csv                   cada barra: capacidade, injeção máxima/média, horas acima
                                      do limite e classificação
  margem_limites_uf.csv               por estado: nº de barras e capacidade de cada grupo
  businj_sem_margem_uf_horario.csv    injeção agregada das barras sem margem (formato do SDDP)
  businj_com_margem_uf_horario.csv    idem, barras com margem e com limite
  businj_sem_limite_uf_horario.csv    idem, barras sem limite no deck (contam como com margem)
  margem_<UF>.png / margem_BR.png     por estado: injeção agregada (box plot por hora) e
                                      capacidade agregada, barras sem margem x com margem
  margem_resumo.png                   resumo por estado

Requer numpy e matplotlib; usa agrega_saidas_uf.py, graficos_uf.py e limites_uf.py (mesma pasta).
"""
import argparse
import collections
import csv
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import ler_hdr, mes_ano, num                         # noqa: E402
from limites_uf import ler, situacao, em_operacao, SEM_LIMITE              # noqa: E402
from limites_uf import num as numero                                       # noqa: E402
from graficos_uf import ORDEM_UF, REGIAO_DA_UF, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402

COR_SEM, COR_COM, COR_LIVRE = '#e34948', '#2a78d6', '#8a8984'


# ----------------------------------------------------------------------------
# Capacidade por barra
# ----------------------------------------------------------------------------
def capacidade_barras(caso, ano):
    data = datetime.date(ano, 1, 1)
    cap = collections.defaultdict(float)
    n_mon = collections.Counter()
    ilimitada = set()
    n_total = collections.Counter()

    def aplicar(base, mods, idx):
        """Aplica as alterações (mcirc/mtrans) com data <= 1/1 do ano; mantém o FlagMonitored."""
        for r in sorted(mods, key=lambda r: (int(r[2]), int(r[1]), int(r[0]))):
            if datetime.date(int(r[2]), int(r[1]), int(r[0])) > data:
                continue
            e = base.setdefault(int(r[3]), dict(mon=0))
            e.update(de=int(r[5]), para=int(r[6]), exist=int(r[7]), desat=int(r[8]), rating=numero(r[idx]))

    circ = {int(r[0]): dict(de=int(r[2]), para=int(r[3]), exist=int(r[6]), desat=int(r[7]), rating=numero(r[11]),
                            mon=int(r[14]) if len(r) > 14 and r[14] else 0)
            for r in ler(os.path.join(caso, 'dcirc.dat'))}
    aplicar(circ, ler(os.path.join(caso, 'mcirc.dat')), 12)
    trf = {int(r[0]): dict(de=int(r[2]), para=int(r[3]), exist=int(r[7]), desat=int(r[8]), rating=numero(r[14]),
                           mon=int(r[28]) if len(r) > 28 and r[28] else 0)
           for r in ler(os.path.join(caso, 'dtrans.dat'))}
    aplicar(trf, ler(os.path.join(caso, 'mtrans.dat')), 14)
    for elems, arq_st in ((circ, 'circstatus_b004m.dat'), (trf, 'transtatus_b004m.dat')):
        st = situacao(os.path.join(caso, arq_st), data)
        for cod, e in elems.items():
            if e.get('exist', 1) != 0 or e.get('desat', 0) != 0 or not em_operacao(st, cod):
                continue
            for b in (e['de'], e['para']):
                n_total[b] += 1
                if e['mon'] == 1:
                    n_mon[b] += 1
                    if e['rating'] >= SEM_LIMITE:
                        ilimitada.add(b)
                    else:
                        cap[b] += e['rating']
    # conversores CA->CC (elos de corrente contínua): capacidade de exportação da barra CA
    conv = {}
    for r in ler(os.path.join(caso, 'dcnvlcc.dat')):
        conv[int(r[0])] = dict(ac=int(r[2]), exist=int(r[8]), desat=int(r[9]), acdc=numero(r[16]))
    for r in ler(os.path.join(caso, 'mcnvlcc.dat')):
        if datetime.date(int(r[2]), int(r[1]), int(r[0])) <= data:
            conv[int(r[3])] = dict(ac=int(r[5]), exist=int(r[8]), desat=int(r[9]), acdc=numero(r[16]))
    n_conv = collections.Counter()
    for c in conv.values():
        if c['exist'] == 0 and c['desat'] == 0 and c['acdc'] > 0:
            cap[c['ac']] += c['acdc']
            n_mon[c['ac']] += 1
            n_conv[c['ac']] += 1
    return cap, n_mon, n_total, ilimitada, n_conv


# ----------------------------------------------------------------------------
def estagios_do_ano(hdr, ano):
    return [e for e in range(hdr['n_estagios']) if mes_ano(hdr, e)[1] == ano]


def blocos(hdr, arq_bin, estagios):
    """Gera (estágio, cenário, matriz horas x barras) lendo o .bin aos poucos."""
    n_ag = hdr['n_agentes']
    n_cen = hdr['n_cenarios'] if hdr['varia_cenario'] else 1
    dados = np.memmap(arq_bin, dtype='<f4', mode='r')
    for e in estagios:
        h0, h1 = hdr['horas'][e], hdr['horas'][e + 1]
        bloco = dados[h0 * n_cen * n_ag:h1 * n_cen * n_ag].reshape(n_cen, h1 - h0, n_ag)
        for c in range(n_cen):
            yield e, c, np.asarray(bloco[c], dtype=np.float64)


def escrever_horario(caminho, hdr, ufs, linhas_por_estagio):
    """CSV no formato do SDDP (3 linhas de cabeçalho + Mês,Cenários,Hora,UFs)."""
    n_col = 3 + len(ufs)
    vazio = [''] * n_col
    with open(caminho, 'w', encoding='latin-1', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow((['Varies per block?       ', 2, 'Unit    ', 'MW     ', hdr['tipo_estagio'], hdr['mes_ini'],
                     hdr['ano_ini']] + vazio)[:n_col])
        w.writerow((['Varies per sequence?    ', 1] + vazio)[:n_col])
        w.writerow((['# of agents             ', len(ufs)] + vazio)[:n_col])
        w.writerow(['Mês', 'Cenários', 'Hora'] + [u.ljust(12) for u in ufs])
        for e, c, M in linhas_por_estagio:
            for h in range(M.shape[0]):
                w.writerow([e + 1, c + 1, h + 1] + [num(v) for v in M[h]])


# ----------------------------------------------------------------------------
# Gráficos
# ----------------------------------------------------------------------------
def _caixas_hora(ax, x, hd, cor, off=0.0, largura=0.6):
    grupos = [x[hd == h] for h in range(24)]
    ax.boxplot(grupos, positions=np.arange(1, 25) + off, widths=largura, whis=(5, 95), showfliers=False,
               showmeans=True, patch_artist=True, manage_ticks=False,
               boxprops=dict(facecolor=cor + '55', edgecolor=cor, linewidth=1),
               whiskerprops=dict(color=cor, linewidth=1), capprops=dict(color=cor, linewidth=1),
               medianprops=dict(color=TEXTO, linewidth=1.5),
               meanprops=dict(marker='D', markersize=3.5, markerfacecolor=TEXTO, markeredgecolor=FUNDO))


def _linha_limite(ax, y, rotulo):
    ax.axhline(y, color=TEXTO, linewidth=1.3, linestyle='--')
    lo, hi = ax.get_ylim()
    lo, hi = min(lo, 0, y), max(hi, y)
    ax.set_ylim(lo - 0.08 * (hi - lo), hi + 0.12 * (hi - lo))
    ax.text(0.6, y + 0.015 * (hi - lo), rotulo.replace(',', '.'), va='bottom', ha='left', fontsize=8.5, color=TEXTO)


def figura_uf(nome, serie, hd, lim, saida, ano):
    """serie: dict grupo -> vetor horário (todas as horas x cenários) da injeção agregada."""
    fig, axs = plt.subplots(2, 1, figsize=(11, 7.6), sharex=True)
    ax = axs[0]
    n, capg = lim['n_sem'], lim['cap_sem']
    if n:
        _caixas_hora(ax, serie['sem'], hd, COR_SEM)
        _linha_limite(ax, capg, f'capacidade agregada: {capg:,.0f} MW')
        pct = 100 * (serie['sem'] > capg).mean()
        ax.set_title(f'Barras SEM margem de escoamento ({n} barras) — injeção agregada (MW) · '
                     f'acima da capacidade agregada em {pct:.1f}% das horas'.replace('.', ','),
                     loc='left', fontsize=10)
    else:
        ax.text(0.5, 0.5, 'nenhuma barra sem margem', ha='center', va='center', color=TEXTO2,
                transform=ax.transAxes)
        ax.set_title('Barras SEM margem de escoamento (0 barras)', loc='left', fontsize=10)
    ax = axs[1]
    nc, capc, nl = lim['n_com'], lim['cap_com'], lim['n_livre']
    if nc:
        _caixas_hora(ax, serie['com'], hd, COR_COM, off=-0.18 if nl else 0, largura=0.34 if nl else 0.6)
    if nl:
        _caixas_hora(ax, serie['livre'], hd, COR_LIVRE, off=0.18 if nc else 0, largura=0.34 if nc else 0.6)
    if nc:
        _linha_limite(ax, capc, f'capacidade agregada das {nc} barras com limite: {capc:,.0f} MW')
    ax.set_title(f'Barras COM margem de escoamento — azul: {nc} barras com limite · cinza: {nl} barras sem limite '
                 f'no deck (injeção agregada, MW)', loc='left', fontsize=10)
    for a in axs:
        a.axhline(0, color=TEXTO2, linewidth=0.8)
        a.grid(axis='y', color=GRADE, linewidth=0.6)
        a.set_axisbelow(True)
        a.set_ylabel('MW')
        a.set_xticks(range(1, 25), [str(h) if h % 2 else '' for h in range(1, 25)])
        a.set_xlim(0.3, 24.7)
    axs[-1].set_xlabel('Hora do dia')
    titulo = 'Brasil' if nome == 'BR' else f'{nome} ({REGIAO_DA_UF.get(nome, "")})'
    fig.suptitle(f'{titulo} — margem de escoamento das barras, {ano}', x=0.01, ha='left', fontsize=13,
                 fontweight='bold')
    fig.text(0.01, 0.005, 'Capacidade da barra = soma dos limites dos circuitos monitorados ligados a ela. Sem margem = '
             'injeção acima da capacidade em ao menos 1 hora de 1 cenário. Caixa: 25-75%, bigodes 5-95%, '
             'losango = média.', fontsize=7.5, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(os.path.join(saida, f'margem_{nome}.png'), dpi=130)
    plt.close(fig)


def figura_resumo(lims, maxinj, saida, ano):
    ufs = [u for u in ORDEM_UF if u in lims]
    ufs = sorted(ufs, key=lambda u: lims[u]['n_sem'])
    y = np.arange(len(ufs))
    fig, axs = plt.subplots(1, 2, figsize=(16, 0.36 * len(ufs) + 2.2))
    ax = axs[0]
    a = np.array([lims[u]['n_sem'] for u in ufs])
    b = np.array([lims[u]['n_com'] for u in ufs])
    c = np.array([lims[u]['n_livre'] for u in ufs])
    ax.barh(y, a, color=COR_SEM, height=0.7, label='sem margem', edgecolor=FUNDO, linewidth=1)
    ax.barh(y, b, left=a, color=COR_COM, height=0.7, label='com margem (com limite)', edgecolor=FUNDO, linewidth=1)
    ax.barh(y, c, left=a + b, color=COR_LIVRE, height=0.7, label='sem limite no deck', edgecolor=FUNDO,
            linewidth=1)
    for k, u in enumerate(ufs):
        ax.text(a[k] + b[k] + c[k], k, f'  {a[k]} sem margem', va='center', fontsize=7.5, color=TEXTO2)
    ax.set_yticks(y, ufs)
    ax.set_xlabel('Número de barras')
    ax.legend(loc='lower right', fontsize=8, frameon=False)
    ax.set_title('Barras por grupo', loc='left', fontsize=10)
    ax = axs[1]
    capv = np.array([lims[u]['cap_sem'] for u in ufs]) / 1000
    injv = np.array([maxinj.get(u, 0) for u in ufs]) / 1000
    ax.barh(y + 0.19, capv, height=0.36, color=COR_COM, label='capacidade agregada')
    ax.barh(y - 0.19, injv, height=0.36, color=COR_SEM, label='injeção agregada máxima (hora x cenário)')
    ax.set_yticks(y, ufs)
    ax.set_xlabel('GW')
    ax.legend(loc='lower right', fontsize=8, frameon=False)
    ax.set_title('Barras SEM margem: capacidade x injeção máxima agregadas', loc='left', fontsize=10)
    for a_ in axs:
        a_.grid(axis='x', color=GRADE, linewidth=0.6)
        a_.set_axisbelow(True)
    fig.suptitle(f'Margem de escoamento das barras por estado, {ano}', x=0.01, ha='left', fontsize=13,
                 fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(os.path.join(saida, 'margem_resumo.png'), dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description='Margem de escoamento por barra (injeção x capacidade).')
    p.add_argument('caso', help='pasta do caso: businj.hdr/.bin (ou bus_inj) e arquivos de rede do deck')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--saida')
    p.add_argument('--ano', type=int, default=2030)
    a = p.parse_args()
    saida = a.saida or os.path.join(a.caso, 'resultados_uf', 'margem_barras')
    os.makedirs(saida, exist_ok=True)

    nome = next((n for n in ('businj', 'bus_inj') if os.path.exists(os.path.join(a.caso, n + '.hdr'))), None)
    if not nome:
        sys.exit(f'ERRO: não achei businj.hdr (nem bus_inj.hdr) em {a.caso}')
    hdr = ler_hdr(os.path.join(a.caso, nome + '.hdr'))
    arq_bin = os.path.join(a.caso, nome + '.bin')
    n_ag = hdr['n_agentes']
    n_cen = hdr['n_cenarios'] if hdr['varia_cenario'] else 1
    if os.path.getsize(arq_bin) != hdr['horas'][-1] * n_cen * n_ag * 4:
        sys.exit(f'ERRO: o tamanho de {nome}.bin não bate com o {nome}.hdr')
    estagios = estagios_do_ano(hdr, a.ano)
    if not estagios:
        sys.exit(f'ERRO: {nome} não tem estágios do ano {a.ano}')
    print(f'{nome}: {n_ag} barras, {n_cen} cenários, estágios {estagios[0] + 1} a {estagios[-1] + 1} ({a.ano})')

    with open(os.path.join(a.tabelas, 'barras_uf.csv'), encoding='utf-8-sig', newline='') as f:
        tab = list(csv.DictReader(f))
    por_nome = {b['nome']: b for b in tab}
    cap, n_mon, n_total, ilimitada, n_conv = capacidade_barras(a.caso, a.ano)

    # vetores por agente
    info = []
    for n in hdr['nomes']:
        b = por_nome.get(n)
        if b is None or b['rede'] != 'CA':
            info.append(None)                 # barra CC ou desconhecida: fora da análise
            continue
        cod = int(b['codigo'])
        livre = cod in ilimitada or n_mon[cod] == 0
        info.append(dict(codigo=cod, nome=n, uf=b['uf'], tipo=b['tipo'], tensao=b['tensao_kv'],
                         cap=float('inf') if livre else cap[cod], livre=livre, n_mon=n_mon[cod],
                         n_total=n_total[cod], n_conv=n_conv[cod]))
    ca = np.array([i is not None for i in info])
    capv = np.array([i['cap'] if i else np.inf for i in info])
    print(f'Barras CA: {ca.sum()} | sem limite no deck: {sum(1 for i in info if i and i["livre"])} | '
          f'fora da análise (CC/sem cadastro): {(~ca).sum()}')

    # --- passada 1: máximo, média e horas acima do limite ---------------------
    t0 = time.time()
    mx = np.full(n_ag, -np.inf)
    soma = np.zeros(n_ag)
    acima = np.zeros(n_ag, dtype=np.int64)
    n_h = 0
    for e, c, X in blocos(hdr, arq_bin, estagios):
        mx = np.maximum(mx, X.max(axis=0))
        soma += X.sum(axis=0)
        acima += (X > capv).sum(axis=0)
        n_h += X.shape[0]
        if c == n_cen - 1:
            m, y = mes_ano(hdr, e)
            print(f'  passada 1: {m:02d}/{y} ok - {time.time() - t0:.0f} s')
    media = soma / n_h

    grupo = []
    for k, i in enumerate(info):
        if i is None:
            grupo.append(None)
        elif i['livre']:
            grupo.append('livre')
        elif mx[k] > i['cap']:
            grupo.append('sem')
        else:
            grupo.append('com')
    with open(os.path.join(saida, 'barras_margem.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['codigo', 'nome', 'uf', 'tipo', 'tensao_kv', 'classificacao', 'capacidade_MW',
                    'circuitos_monitorados', 'circuitos_total', 'conversores_cc', 'injecao_max_MW',
                    'injecao_media_MW', 'horas_acima_capacidade', 'pct_horas_acima'])
        rot = {'sem': 'sem margem', 'com': 'com margem', 'livre': 'sem limite no deck (com margem)'}
        for k, i in enumerate(info):
            if i is None:
                continue
            w.writerow([i['codigo'], i['nome'], i['uf'], i['tipo'], i['tensao'], rot[grupo[k]],
                        '' if i['livre'] else round(i['cap'], 1), i['n_mon'], i['n_total'], i['n_conv'],
                        round(mx[k], 2), round(media[k], 2), int(acima[k]), round(100 * acima[k] / n_h, 3)])

    # --- passada 2: agregação por estado e grupo -----------------------------
    ufs = [u for u in ORDEM_UF if any(i and i['uf'] == u for i in info)]
    cols = [(u, g) for u in ufs for g in ('sem', 'com', 'livre')]
    M = np.zeros((n_ag, len(cols)))
    for k, i in enumerate(info):
        if i is not None:
            M[k, cols.index((i['uf'], grupo[k]))] = 1
    series = {g: [] for g in ('sem', 'com', 'livre')}
    linhas = {g: [] for g in ('sem', 'com', 'livre')}
    t0 = time.time()
    for e, c, X in blocos(hdr, arq_bin, estagios):
        Y = X @ M                                                  # horas x (UF, grupo)
        for g in ('sem', 'com', 'livre'):
            idx = [j for j, (u, gg) in enumerate(cols) if gg == g]
            linhas[g].append((e, c, Y[:, idx]))
            series[g].append(Y[:, idx])
        if c == n_cen - 1:
            m, y = mes_ano(hdr, e)
            print(f'  passada 2: {m:02d}/{y} ok - {time.time() - t0:.0f} s')
    for g, rot in (('sem', 'sem_margem'), ('com', 'com_margem'), ('livre', 'sem_limite')):
        escrever_horario(os.path.join(saida, f'businj_{rot}_uf_horario.csv'), hdr, ufs, linhas[g])

    # limites por estado
    lims = {}
    for u in ufs:
        ks = [k for k, i in enumerate(info) if i and i['uf'] == u]
        lims[u] = dict(n_sem=sum(1 for k in ks if grupo[k] == 'sem'),
                       cap_sem=sum(info[k]['cap'] for k in ks if grupo[k] == 'sem'),
                       n_com=sum(1 for k in ks if grupo[k] == 'com'),
                       cap_com=sum(info[k]['cap'] for k in ks if grupo[k] == 'com'),
                       n_livre=sum(1 for k in ks if grupo[k] == 'livre'))
    lims['BR'] = {k: sum(lims[u][k] for u in ufs) for k in lims[ufs[0]]}
    with open(os.path.join(saida, 'margem_limites_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['uf', 'barras_sem_margem', 'capacidade_sem_margem_MW', 'barras_com_margem',
                    'capacidade_com_margem_MW', 'barras_sem_limite'])
        for u in ufs + ['BR']:
            L = lims[u]
            w.writerow([u, L['n_sem'], round(L['cap_sem']), L['n_com'], round(L['cap_com']), L['n_livre']])

    # --- gráficos ------------------------------------------------------------
    S = {g: np.vstack(series[g]) for g in series}                    # (horas x cenários) x UF
    hd = np.concatenate([np.arange(Y.shape[0]) % 24 for _, _, Y in linhas['sem']])
    maxinj = {}
    for j, u in enumerate(ufs):
        serie = {g: S[g][:, j] for g in S}
        maxinj[u] = serie['sem'].max() if lims[u]['n_sem'] else 0
        figura_uf(u, serie, hd, lims[u], saida, a.ano)
    figura_uf('BR', {g: S[g].sum(axis=1) for g in S}, hd, lims['BR'], saida, a.ano)
    figura_resumo({u: lims[u] for u in ufs}, maxinj, saida, a.ano)

    L = lims['BR']
    print(f'Brasil: {L["n_sem"]} barras sem margem, {L["n_com"]} com margem, {L["n_livre"]} sem limite no deck')
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
