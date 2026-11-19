"""Balanço por estado e por subsistema nas horas de vertimento: o que estava gerando quando houve corte.

Para cada estado, hora e cenário do ano:
  renovável gerada  (gergnd_uf_horario.csv, da etapa 1)
  hidro gerada      (gerhid, por usina -> estado pela barra)
  térmica gerada    (gerter, por usina -> estado pela barra)
  carga             (demxba, por barra -> estado; igual em todos os cenários)
  injeção líquida   (businj_uf_horario.csv, da etapa 1)
  outros            = injeção - (renovável + hidro + térmica - carga): baterias, déficit e
                      arredondamentos (deve ser pequeno)
  vertimento        por gargalo e por excesso no sistema (gargalo_cmo, etapa 6)

e classifica cada hora do estado: com vertimento por gargalo / só com vertimento por
excesso (falta de demanda) / sem vertimento.

Hidrelétricas e térmicas ligadas à rede pelas unidades geradoras (hydrounit??.dat,
thermunit??.dat) entram pela barra das unidades.

Uso:
  python balanco_uf.py "<pasta do caso>" [--ano 2030]
Precisa: gerhid, gerter e demxba (.hdr/.bin) na pasta do caso; chidro??.dat, ctermi??.dat,
hydrounit??.dat e thermunit??.dat do deck; e, em <caso>\\resultados_uf, os resultados das
etapas 1 (gergnd/businj_uf_horario.csv) e 6 (gargalo_cmo).
Por subsistema (barras do subsistema), usa também gergnd/businj_subsistema_horario.csv (etapa 1)
e o vertimento entre/dentro/excesso do gargalo_subsistema (etapa 9).
Saída: <caso>\\resultados_uf\\balanco_uf (estados) e <caso>\\resultados_uf\\balanco_subsistema
"""
import argparse
import collections
import csv
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import mes_ano, ids_subsistemas                             # noqa: E402
from gargalo_cmo import abrir, bloco, ler_tab                                     # noqa: E402
from gargalo_linhas import ler_horario_sddp, serie_ano, _caixas                   # noqa: E402
from graficos_uf import ORDEM_UF, REGIAO_DA_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402

COR = {'ren': '#1baf7a', 'hid': '#2a78d6', 'ter': '#eda100', 'out': '#8a8984',
       'garg': '#e34948', 'exc': '#c3c2b7', 'carga': TEXTO, 'inj': '#6250d6'}
ROT = {'ren': 'renovável gerada', 'hid': 'hidrelétrica', 'ter': 'termelétrica', 'out': 'outros (baterias, déficit)',
       'garg': 'vertimento por gargalo', 'exc': 'vertimento por excesso', 'carga': 'carga do estado',
       'inj': 'injeção líquida'}
SIT = [('garg', 'horas com vertimento por GARGALO'), ('exc', 'horas só com vertimento por EXCESSO (falta de demanda)'),
       ('sem', 'horas SEM vertimento')]


def barras_por_unidades(caso, cadastro, unidades):
    """Usinas ligadas pelas unidades geradoras: nome da usina -> lista de códigos de barra."""
    nomes = {}
    for arq in glob.glob(os.path.join(caso, f'{cadastro}??.dat')):
        sis = arq[-6:-4]
        with open(arq, encoding='latin-1') as f:
            for ln in f:
                if ln[:4].strip().isdigit():
                    nomes[(sis, int(ln[:4]))] = ln[5:17].strip()
    out = collections.defaultdict(list)
    for arq in glob.glob(os.path.join(caso, f'{unidades}??.dat')):
        sis = re.search(rf'{unidades}(..)\.dat$', arq).group(1)
        with open(arq, encoding='latin-1', newline='') as f:
            for r in csv.reader(f):
                if not r or r[0].startswith(('$', '!')):
                    continue
                try:
                    n = nomes.get((sis, int(r[2])))
                    if n:
                        out[n].append(int(r[3]))
                except (ValueError, IndexError):
                    continue
    return out


def main():
    p = argparse.ArgumentParser(description='Balanço por estado nas horas de vertimento.')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--saida')
    a = p.parse_args()
    res = os.path.join(a.caso, 'resultados_uf')
    saida = a.saida or os.path.join(res, 'balanco_uf')
    os.makedirs(saida, exist_ok=True)

    print('Abrindo as saídas do SDDP...')
    hid, ter, dem = abrir(a.caso, 'gerhid'), abrir(a.caso, 'gerter'), abrir(a.caso, 'demxba')
    for h in (ter, dem):
        if h['horas'] != hid['horas']:
            sys.exit(f'ERRO: {h["nome"]} tem horas diferentes do gerhid (rodadas diferentes?)')
    estagios = [e for e in range(hid['n_estagios']) if mes_ano(hid, e)[1] == a.ano]
    if not estagios:
        sys.exit(f'ERRO: a rodada não tem estágios de {a.ano}')
    n_cen = hid['n_cen']

    # --- resultados das etapas anteriores ---------------------------------------
    def csv_h(nome, obrigatorio=True):
        c = os.path.join(res, nome)
        if os.path.exists(c):
            return ler_horario_sddp(c)
        if obrigatorio:
            sys.exit(f'ERRO: não achei {nome} em {res}. Rode antes as etapas anteriores.')
        return None

    # --- usina/barra -> estado e subsistema ----------------------------------------
    barras = [b for b in ler_tab(os.path.join(a.tabelas, 'barras_uf.csv')) if b['rede'] == 'CA']
    nome_sigla, ordem_sub = ids_subsistemas(a.caso)
    sig = (lambda x: nome_sigla.get(x.upper(), x[:2].upper()) if x else '??')
    conex = collections.defaultdict(list)
    for r in ler_tab(os.path.join(a.tabelas, 'conexoes_usinas_uf.csv')):
        conex[(r['tipo_usina'], r['nome_usina'])].append(int(r['barra']))
    unid = {'H': barras_por_unidades(a.caso, 'chidro', 'hydrounit'),
            'T': barras_por_unidades(a.caso, 'ctermi', 'thermunit')}
    subs_barras = {sig(b['subsistema']) for b in barras}
    grupos = [dict(chave='uf', itens=list(ORDEM_UF), cod={int(b['codigo']): b['uf'] for b in barras},
                   nome={b['nome']: b['uf'] for b in barras}, artigo='do estado', rot='estado',
                   titulo=lambda u: f'{u} ({REGIAO_DA_UF.get(u, "")})', saida=saida,
                   ren='gergnd_uf_horario.csv', inj=('businj_uf_horario.csv', 'bus_inj_uf_horario.csv'),
                   causas=[('garg', os.path.join('gargalo_cmo', 'vertimento_gargalo_uf_horario.csv'),
                            '#e34948', 'vertimento por gargalo'),
                           ('exc', os.path.join('gargalo_cmo', 'vertimento_excesso_uf_horario.csv'),
                            '#c3c2b7', 'vertimento por excesso')],
                   csv='balanco_situacao_uf.csv'),
              dict(chave='subsistema', itens=[x for x in ordem_sub if x in subs_barras] +
                   sorted(subs_barras - set(ordem_sub)),
                   cod={int(b['codigo']): sig(b['subsistema']) for b in barras},
                   nome={b['nome']: sig(b['subsistema']) for b in barras}, artigo='do subsistema', rot='subsistema',
                   titulo=lambda u: f'Subsistema {u} ({nome_sub.get(u, "")})',
                   saida=os.path.join(res, 'balanco_subsistema'),
                   ren='gergnd_subsistema_horario.csv', inj=('businj_subsistema_horario.csv',
                                                            'bus_inj_subsistema_horario.csv'),
                   causas=[('entre', os.path.join('gargalo_subsistema',
                                                  'vertimento_gargalo_entre_subsistemas_horario.csv'),
                            '#e34948', 'vertimento por gargalo entre subsistemas'),
                           ('dentro', os.path.join('gargalo_subsistema',
                                                   'vertimento_gargalo_dentro_subsistema_horario.csv'),
                            '#eb6834', 'vertimento por gargalo dentro do subsistema'),
                           ('exc', os.path.join('gargalo_subsistema', 'vertimento_excesso_subsistema_horario.csv'),
                            '#c3c2b7', 'vertimento por excesso')],
                   csv='balanco_situacao_subsistema.csv')]
    nome_sub = {v: k for k, v in nome_sigla.items()}

    def indicadora(h, tipo, G):
        itens = G['itens']
        M = np.zeros((h['n_agentes'], len(itens)))
        sem = []
        for i, n in enumerate(h['nomes']):
            cods = [c for c in (conex.get((tipo, n)) or unid[tipo].get(n, [])) if c in G['cod']]
            if cods:
                u = collections.Counter(G['cod'][c] for c in cods).most_common(1)[0][0]
                if u in itens:
                    M[i, itens.index(u)] = 1
            else:
                sem.append(n)
        if sem and G['chave'] == 'uf':
            print(f'  AVISO: {len(sem)} usinas de {h["nome"]} sem barra (ficam fora do balanço): '
                  f'{", ".join(sem[:10])}{" ..." if len(sem) > 10 else ""}')
        return M

    ativos = []
    for G in grupos:
        G['dados'] = {'ren': csv_h(G['ren'], G['chave'] == 'uf'),
                      'inj': next((d for d in (csv_h(n_, False) for n_ in G['inj']) if d), None)}
        if G['dados']['inj'] is None and G['chave'] == 'uf':
            sys.exit(f'ERRO: não achei {G["inj"][0]} em {res}. Rode antes a etapa 1.')
        for k, arq, _, _ in G['causas']:
            G['dados'][k] = csv_h(arq, G['chave'] == 'uf')
        falta = [k for k, v in G['dados'].items() if v is None]
        if falta:
            print(f'  AVISO: balanço por {G["rot"]} não gerado: faltam ' +
                  ', '.join(G['ren'] if k == 'ren' else G['inj'][0] if k == 'inj' else
                            dict((c[0], c[1]) for c in G['causas'])[k] for k in falta) +
                  ' (rode de novo as etapas 1 e 9)')
            continue
        G['M'] = {'hid': indicadora(hid, 'H', G), 'ter': indicadora(ter, 'T', G)}
        Md = np.zeros((dem['n_agentes'], len(G['itens'])))
        for i, n in enumerate(dem['nomes']):
            if G['nome'].get(n) in G['itens']:
                Md[i, G['itens'].index(G['nome'][n])] = 1
        G['M']['carga'] = Md
        G['agg'] = {k: {} for k in ('hid', 'ter', 'carga')}
        os.makedirs(G['saida'], exist_ok=True)
        ativos.append(G)

    # --- leitura das saídas (uma vez, para estados e subsistemas) ------------------------
    t0 = time.time()
    for e in estagios:
        D = bloco(dem, e, 0) * 1000.0                                  # carga (MW), igual nos cenários
        for c in range(n_cen):
            Hh, Tt = bloco(hid, e, c) * 1000.0, bloco(ter, e, c) * 1000.0
            for G in ativos:
                G['agg']['hid'][(e, c)] = Hh @ G['M']['hid']
                G['agg']['ter'][(e, c)] = Tt @ G['M']['ter']
                G['agg']['carga'][(e, c)] = D @ G['M']['carga']
        print(f'  {MESES[mes_ano(hid, e)[0] - 1]}/{a.ano} ok - {time.time() - t0:.0f} s')

    for G in ativos:
        balanco_grupo(G, estagios, n_cen, a.ano)
    print('Fim. Arquivos em', ', '.join(G['saida'] for G in ativos))


def balanco_grupo(G, estagios, n_cen, ano):
    """Gráficos e CSV do balanço para cada estado ou subsistema (G = configuração do grupo)."""
    itens, agg, artigo = G['itens'], G['agg'], G['artigo']
    causas = [c[0] for c in G['causas']]
    garg_c = [c for c in causas if c != 'exc']
    cor = dict(COR, **{c[0]: c[2] for c in G['causas']})
    rot_c = dict(ROT, **{c[0]: c[3] for c in G['causas']}, carga=f'carga {artigo}')
    saida = G['saida']

    def serie(chave, u):
        if chave in agg:
            return serie_ano(agg[chave], estagios, n_cen, itens.index(u))[0]
        dic, cols = G['dados'][chave]
        return serie_ano(dic, estagios, n_cen, cols.index(u))[0] if u in cols else None

    resumo = []
    for uf in itens:
        chaves = ('ren', 'hid', 'ter', 'carga', 'inj') + tuple(causas)
        S = {k: serie(k, uf) for k in chaves}
        if S['hid'] is None or S['ren'] is None or S['inj'] is None:
            continue
        S = {k: (v if v is not None else np.zeros_like(S['hid'])) for k, v in S.items()}
        n = min(len(v) for v in S.values())
        S = {k: np.nan_to_num(v[:n]) for k, v in S.items()}
        _, hd, est = serie_ano(agg['hid'], estagios, n_cen, itens.index(uf))
        hd, est = hd[:n], est[:n]
        S['out'] = S['inj'] - (S['ren'] + S['hid'] + S['ter'] - S['carga'])
        S['gargtot'] = sum(S[c] for c in garg_c)
        sit = {'garg': S['gargtot'] > 1}
        sit['exc'] = ~sit['garg'] & (S['exc'] > 1)
        sit['sem'] = ~sit['garg'] & ~sit['exc']
        for s_, _ in SIT:
            m = sit[s_]
            nh = m.sum()
            linha = {G['chave']: uf, 'situacao': s_, 'pct_horas': round(100 * nh / n, 2)}
            for k in ('ren', 'hid', 'ter', 'out', 'carga', 'inj') + tuple(causas) + ('gargtot',):
                linha[f'{k}_MW_medio'] = round(float(S[k][m].mean()), 1) if nh else ''
                linha[f'{k}_GWh_ano'] = round(float(S[k][m].sum()) / n_cen / 1000, 2)
            resumo.append(linha)
        if S['gargtot'].sum() + S['exc'].sum() <= 0:
            continue

        horas = np.arange(1, 25)
        fig = plt.figure(figsize=(16, 13.5))
        gs = fig.add_gridspec(3, 3, height_ratios=[1.15, 1, 1], hspace=0.5, wspace=0.18)
        ax = fig.add_subplot(gs[0, :])

        def empilhado(ax, m, larg=0.8, legenda=False):
            base = np.zeros(24)
            # horas sem nenhum caso ficam em branco (NaN), em vez de aparecer como zero
            media = lambda v: np.array([v[m & (hd == h)].mean() if (m & (hd == h)).any() else np.nan for h in range(24)])
            topo_ger = None
            for k in ('hid', 'ter', 'ren') + tuple(causas):
                if k == causas[0]:
                    topo_ger = base.copy()                          # topo da geração (sem o vertimento)
                y = media(S[k])
                ax.bar(horas, np.nan_to_num(y), bottom=base, width=larg, color=cor[k], edgecolor=FUNDO, linewidth=0.6,
                       label=rot_c[k] if legenda else None, hatch='//' if k in causas else None)
                base += np.nan_to_num(y)
            carga = media(S['carga'])
            ok = np.isfinite(carga)
            # faixa entre a carga e o topo da geração: o que sai (ou o que entra, se faltar geração)
            exp_ = np.where(ok, np.maximum(topo_ger - np.nan_to_num(carga), 0), 0)
            imp_ = np.where(ok, np.maximum(np.nan_to_num(carga) - topo_ger, 0), 0)
            for alt, base_, estilo in ((exp_, np.nan_to_num(carga), '-'), (imp_, topo_ger, '--')):
                tem = alt > 1e-6
                if tem.any():
                    ax.bar(horas[tem], alt[tem], bottom=base_[tem], width=larg + 0.06, color='none',
                           edgecolor=COR['inj'], linewidth=1.8, linestyle=estilo)
            ax.plot(horas, carga, color=COR['carga'], linewidth=2, marker='o', markersize=3,
                    label=f'carga {artigo} (abaixo dela: consumido no {G["rot"]})' if legenda else None)
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
            ax.set_xticks(horas, [str(h) if h % 2 else '' for h in horas])
            ax.set_xlim(0.4, 24.6)
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
        empilhado(ax, np.ones(n, bool), legenda=True)
        ax.set_title('Média de todas as horas do ano (MW): geração por fonte empilhada; abaixo da linha preta = '
                     f'consumido no {G["rot"]}; contorno roxo = exportado; hachurado no topo = vertido', loc='left',
                     fontsize=10)
        ax.set_ylabel('MW')
        from matplotlib.patches import Patch
        hs_, ls_ = ax.get_legend_handles_labels()
        hs_ += [Patch(facecolor='none', edgecolor=COR['inj'], linewidth=1.8, label='exportado (geração − carga)'),
                Patch(facecolor='none', edgecolor=COR['inj'], linewidth=1.8, linestyle='--',
                      label='importado (carga − geração)')]
        ax.legend(handles=hs_, loc='upper left', fontsize=8, frameon=False, ncol=4, bbox_to_anchor=(0, -0.1))
        rot_sit = {'garg': 'horas com vertimento por GARGALO' + (' (entre ou dentro)' if len(garg_c) > 1 else ''),
                   'exc': 'horas só com vertimento por EXCESSO (falta de demanda)', 'sem': 'horas SEM vertimento'}
        for j, (s_, _) in enumerate(SIT):
            ax = fig.add_subplot(gs[1, j])
            empilhado(ax, sit[s_], larg=0.75)
            m_ = sit[s_]
            curto = {'garg': 'gargalo', 'entre': 'entre', 'dentro': 'dentro', 'exc': 'excesso'}
            if s_ != 'sem' and m_.any():
                med = '; vertido em média: ' + ', '.join(
                    f'{curto[c]} ' + f'{S[c][m_].mean():,.0f}'.replace(',', '.') + ' MW' for c in causas)
            else:
                med = ''
            ax.set_title(f'{rot_sit[s_]}\n(' + f'{100 * m_.mean():.1f}'.replace('.', ',') + f'% das horas{med})',
                         loc='left', fontsize=8.5)
            if j == 0:
                ax.set_ylabel('MW médio')
        for j, (k, rot) in enumerate((('ter', 'Termelétrica gerada'), ('hid', 'Hidrelétrica gerada'),
                                      ('out', 'Outros: baterias, déficit e diferenças'))):
            ax = fig.add_subplot(gs[2, j])
            for s_, cor_, off in (('garg', COR['garg'], -0.27), ('exc', '#8a8984', 0.0), ('sem', '#2a78d6', 0.27)):
                grupos_ = [S[k][sit[s_] & (hd == h)] for h in range(24)]
                ok = [i for i, g_ in enumerate(grupos_) if len(g_)]
                if ok:
                    _caixas(ax, [grupos_[i] for i in ok], horas[ok] + off, cor_, 0.24)
            ax.set_xticks(horas, [str(h) if h % 2 else '' for h in horas])
            ax.set_xlim(0.4, 24.6)
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.set_title(f'{rot} (MW), conforme a situação da hora', loc='left', fontsize=9)
            ax.set_xlabel('Hora do dia')
            if j == 0:
                ax.set_ylabel('MW')
        fig.legend(handles=[Patch(facecolor=COR['garg'] + '55', edgecolor=COR['garg'],
                                  label='horas com vertimento por gargalo'),
                            Patch(facecolor='#8a898455', edgecolor='#8a8984', label='horas só com vertimento por excesso'),
                            Patch(facecolor='#2a78d655', edgecolor='#2a78d6', label='horas sem vertimento')],
                   loc='lower right', ncol=3, fontsize=8.5, frameon=False, bbox_to_anchor=(0.99, 0.325))
        res_ = S['out']
        fig.suptitle(f'{G["titulo"](uf)} — balanço {artigo} nas horas de vertimento, {ano}',
                     x=0.01, ha='left', fontsize=13, fontweight='bold')
        fig.text(0.01, 0.006, f'Médias e caixas com todas as horas do ano e os {n_cen} cenários. "Outros" = injeção − '
                 f'(renovável + hidro + térmica − carga): baterias, déficit e diferenças (média {res_.mean():.0f} MW, '
                 f'95% entre {np.percentile(res_, 2.5):.0f} e {np.percentile(res_, 97.5):.0f} MW).\nVertimento sem a geração '
                 f'distribuída (MMGD/OMGD). Hora "com gargalo" = mais de 1 MW de vertimento por gargalo somado {artigo}: '
                 'quando é pouco, o hachurado quase não aparece (ver o MW médio no título de cada painel).',
                 fontsize=7.5, color=TEXTO2)
        fig.subplots_adjust(left=0.05, right=0.99, top=0.94, bottom=0.06)
        fig.savefig(os.path.join(saida, f'balanco_{uf}.png'), dpi=115)
        plt.close(fig)

    with open(os.path.join(saida, G['csv']), 'w', encoding='utf-8-sig', newline='') as f:
        if resumo:
            w = csv.DictWriter(f, fieldnames=list(resumo[0].keys()))
            w.writeheader()
            w.writerows(resumo)

    # resumo: hidro e térmica nas horas com vertimento por gargalo e por excesso
    por = collections.defaultdict(dict)
    for r in resumo:
        por[r[G['chave']]][r['situacao']] = r
    tot_v = (lambda u: por[u]['garg']['gargtot_GWh_ano'] + por[u]['exc']['exc_GWh_ano'])
    lista = [u for u in itens if u in por and tot_v(u) >= (50 if G['chave'] == 'uf' else 1)]
    if lista:
        lista = sorted(lista, key=tot_v)
        fig, axs = plt.subplots(1, 2, figsize=(16, 0.42 * len(lista) + 2.4))
        y = np.arange(len(lista))
        for ax, (s_, rot) in zip(axs, SIT[:2]):
            ver = np.array([por[u][s_]['gargtot_GWh_ano' if s_ == 'garg' else 'exc_GWh_ano'] for u in lista])
            te = np.array([por[u][s_]['ter_GWh_ano'] for u in lista])
            hi = np.array([por[u][s_]['hid_GWh_ano'] for u in lista])
            ax.barh(y + 0.27, ver, height=0.26, color=COR['garg'] if s_ == 'garg' else COR['exc'], edgecolor='#8a8984',
                    label='vertimento por gargalo' if s_ == 'garg' else 'vertimento por excesso')
            ax.barh(y, te, height=0.26, color=COR['ter'], label='termelétrica gerada nessas horas')
            ax.barh(y - 0.27, hi, height=0.26, color=COR['hid'], label='hidrelétrica gerada nessas horas')
            ax.set_yticks(y, lista)
            ax.set_xlabel('GWh no ano (média dos cenários)')
            ax.set_title(rot, loc='left', fontsize=10)
            ax.grid(axis='x', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.legend(loc='lower right', fontsize=8, frameon=False)
        fig.suptitle(f'Vertimento × geração hidrelétrica e termelétrica {artigo} nas mesmas horas, {ano}',
                     x=0.01, ha='left', fontsize=13, fontweight='bold')
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        fig.savefig(os.path.join(saida, 'balanco_resumo.png'), dpi=130)
        plt.close(fig)


if __name__ == '__main__':
    main()
