"""Quais linhas e transformadores ficam no limite nas horas com vertimento por gargalo.

Usa os fluxos do SDDP (acline_flow e transformer_flow) e os limites da rede do deck
(Rating das linhas em dcirc/mcirc, Rn dos transformadores em dtrans/mtrans, situação em
circstatus/transtatus) no ano analisado.

Para cada hora e cenário:
  carregamento = |fluxo| / limite;
  NO LIMITE    = circuito MONITORADO com carregamento >= 99% (opção --carregamento);
                 o lado "preso" é a barra de custo marginal (cmgbus) mais baixo; se a
                 diferença de custo marginal entre as duas barras passa da tolerância, o
                 limite está separando preços (gargalo efetivo);
  SOBRECARGA   = circuito NÃO monitorado com carregamento > 100% (o SDDP não limita esses
                 circuitos: é um gargalo que a simulação não representa).

Para cada circuito no limite também soma o vertimento por gargalo (de gargalo_cmo.py) do
estado do lado preso, nas horas em que o circuito estava no limite. Como vários circuitos
podem estar no limite na mesma hora, esse valor indica coincidência, não é uma divisão
exclusiva do vertimento entre os circuitos.

Antes, rode gargalo_cmo.py (ele grava vertimento_gargalo_uf_horario.csv).

Uso:
  python gargalo_linhas.py "<pasta do caso>" [--ano 2030] [--carregamento 99] [--tolerancia 1]
Padrão de saída: <pasta do caso>\\resultados_uf\\gargalo_linhas
"""
import argparse
import collections
import csv
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import mes_ano, ids_subsistemas                           # noqa: E402
from limites_uf import ler, situacao, em_operacao, SEM_LIMITE                   # noqa: E402
from limites_uf import num as numero                                            # noqa: E402
from gargalo_cmo import abrir, bloco, ler_tab                                   # noqa: E402
from graficos_uf import ORDEM_UF, REGIAO_DA_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402

COR_LIM, COR_SOBRE = '#e34948', '#eda100'
FRAC_POUCO = 0.02    # horas com vertimento < 2% da maior hora do dia: CMO no momento do vertimento apagado


def circuitos_do_ano(caso, ano):
    """{('linha'|'trafo', nome): dict(codigo, de, para, limite, mon, opera)} na rede de 1/1 do ano."""
    data = datetime.date(ano, 1, 1)
    out = {}

    def montar(tipo, base_arq, mod_arq, st_arq, i_lim_base, i_mon_base, i_lim_mod, i_exist, i_desat,
               i_emg_base=None, i_emg_mod=None):
        elem = {}
        for r in ler(os.path.join(caso, base_arq)):
            elem[int(r[0])] = dict(nome=r[1].strip(), de=int(r[2]), para=int(r[3]), exist=int(r[i_exist]),
                                   desat=int(r[i_desat]), limite=numero(r[i_lim_base]),
                                   emergencia=numero(r[i_emg_base]) if i_emg_base is not None and len(r) > i_emg_base
                                   else float('nan'),
                                   mon=int(r[i_mon_base]) if len(r) > i_mon_base and r[i_mon_base] else 0)
        for r in sorted(ler(os.path.join(caso, mod_arq)), key=lambda r: (int(r[2]), int(r[1]), int(r[0]))):
            if datetime.date(int(r[2]), int(r[1]), int(r[0])) > data:
                continue
            e = elem.setdefault(int(r[3]), dict(nome=r[4].strip(), mon=0))
            e.update(de=int(r[5]), para=int(r[6]), exist=int(r[7]), desat=int(r[8]), limite=numero(r[i_lim_mod]))
            if i_emg_mod is not None and len(r) > i_emg_mod:
                e['emergencia'] = numero(r[i_emg_mod])
        st = situacao(os.path.join(caso, st_arq), data)
        for cod, e in elem.items():
            e['codigo'] = cod
            e['opera'] = e.get('exist', 1) == 0 and e.get('desat', 0) == 0 and em_operacao(st, cod)
            out[(tipo, e['nome'])] = e

    montar('linha', 'dcirc.dat', 'mcirc.dat', 'circstatus_b004m.dat', 11, 14, 12, 6, 7, 12, 13)   # Rating/EmergencyRating
    montar('trafo', 'dtrans.dat', 'mtrans.dat', 'transtatus_b004m.dat', 14, 28, 14, 7, 8, 15, 15)  # Rn/Re
    return out


def ler_horario_sddp(caminho):
    """CSV no formato do SDDP -> {(estágio, cenário): matriz horas x UF} e lista de UFs."""
    with open(caminho, encoding='latin-1') as f:
        linhas = f.readlines()
    ufs = [c.strip() for c in linhas[3].split(',')][3:]
    dados = np.atleast_2d(np.genfromtxt(linhas[4:], delimiter=','))
    out = {}
    for (e, c) in sorted({(int(a), int(b)) for a, b in dados[:, :2]}):
        m = (dados[:, 0] == e) & (dados[:, 1] == c)
        bloco_ = dados[m]
        out[(e - 1, c - 1)] = bloco_[np.argsort(bloco_[:, 2])][:, 3:]
    return out, ufs


CORES_CIRC = ['#2a78d6', '#eb6834', '#1baf7a', '#6250d6']      # paleta categórica (ordem fixa)
COR_EXC, COR_INJ_SEM = '#8a8984', '#2a78d6'


def quantil_hist(hist, q, NB, PASSO):
    """hist: [24, NB] -> quantil q (0-1) do carregamento em % para cada hora."""
    out = np.full(24, np.nan)
    for h in range(24):
        n = hist[h].sum()
        if n:
            acum = np.cumsum(hist[h])
            b = int(np.searchsorted(acum, q * n))
            out[h] = 100 * min(b, NB - 1) * PASSO          # início da faixa (100% aparece como 100%)
    return out


def serie_ano(dic, estagios, n_cen, j):
    """Junta, para a coluna j, as matrizes horárias {(estágio, cenário): horas x UF} do ano."""
    vals, hd, mes = [], [], []
    for e in estagios:
        for c in range(n_cen):
            M = dic.get((e, c))
            if M is None:
                continue
            vals.append(M[:, j])
            hd.append(np.arange(M.shape[0]) % 24)
            mes.append(np.full(M.shape[0], e))
    if not vals:
        return None, None, None
    return np.concatenate(vals), np.concatenate(hd), np.concatenate(mes)


def _caixas(ax, dados, pos, cor, larg):
    ax.boxplot(dados, positions=pos, widths=larg, whis=(5, 95), showfliers=False, showmeans=True,
               patch_artist=True, manage_ticks=False,
               boxprops=dict(facecolor=cor + '55', edgecolor=cor, linewidth=0.9),
               whiskerprops=dict(color=cor, linewidth=0.9), capprops=dict(color=cor, linewidth=0.9),
               medianprops=dict(color=TEXTO, linewidth=1.3),
               meanprops=dict(marker='D', markersize=3, markerfacecolor=TEXTO, markeredgecolor=FUNDO))


def figura_estado(uf, linhas_perfil, top_m, top_n, pasta, a, NB, PASSO, horas):
    """Gráfico único por estado, todos os painéis com a hora do dia (1 a 24) no eixo x e CMO em $/MWh."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    lin = sorted(linhas_perfil, key=lambda r: int(r['hora']))

    def col(nome):
        return np.array([float(r[nome]) if r.get(nome) not in (None, '') else np.nan for r in lin])
    COR_EST = '#2a78d6'
    CORES_VIZ = ['#eb6834', '#1baf7a', '#eda100']
    n_pain = 6 + (1 if top_n else 0)
    fig, axs = plt.subplots(n_pain, 1, figsize=(15, 2.5 * n_pain + 1.3), sharex=True)
    LEG = dict(loc='upper left', bbox_to_anchor=(1.01, 1.0), borderaxespad=0, frameon=False, fontsize=8)
    # 1 e 2) vertimento por causa
    for ax, f_, rot in ((axs[0], 'ren', 'renovável (sem GD)'), (axs[1], 'hid', 'hidrelétrico (vertimento turbinável)')):
        gg, xx = np.nan_to_num(col(f'vert_{f_}_gargalo_MW')), np.nan_to_num(col(f'vert_{f_}_excesso_MW'))
        ax.bar(horas, gg, color=COR_LIM, width=0.75, edgecolor=FUNDO, linewidth=0.8)
        ax.bar(horas, xx, bottom=gg, color=COR_EXC, width=0.75, edgecolor=FUNDO, linewidth=0.8)
        tot = (gg + xx).sum()
        pct = 100 * gg.sum() / tot if tot > 0 else 0
        if tot <= 0:
            ax.set_ylim(0, 1)
            ax.set_yticks([0])
            ax.text(0.5, 0.5, f'sem vertimento {rot.split(" ")[0]} no estado', ha='center', va='center',
                    color=TEXTO2, transform=ax.transAxes)
        ax.set_title(f'Vertimento {rot} médio por hora (MW) — {pct:.0f}% por gargalo'.replace('.', ','),
                     loc='left', fontsize=10)
        ax.set_ylabel('MW')
    # 3) CMO do SIN, do estado e dos vizinhos (todas as horas)
    viz = []
    for k in range(1, 4):
        v = lin[0].get(f'vizinho{k}_uf') if lin else ''
        if v:
            cap = float(lin[0].get(f'vizinho{k}_capacidade_divisa_MW') or 0)
            viz.append((k, v, f'{cap:,.0f}'.replace(',', '.')))

    def linhas_cmo(ax, c_est, rot_est, c_sin, rot_sin, sufixo_viz, ok=None):
        """ok: horas com vertimento suficiente; as demais ficam apagadas (preço pouco representativo)."""
        series = [(c_est, dict(color=COR_EST, linewidth=2.6, marker='o', markersize=3.5, label=rot_est, zorder=5)),
                  (c_sin, dict(color=TEXTO, linewidth=2, linestyle='--', marker='o', markersize=3, label=rot_sin,
                               zorder=4))]
        for i, (k, v, cap) in enumerate(viz):
            # por cima e pontilhado: aparece mesmo quando coincide com o estado ou com o SIN
            series.append((col(f'vizinho{k}_cmo{sufixo_viz}'), dict(color=CORES_VIZ[i], linewidth=2.2, linestyle=':',
                                                                    marker='s', markersize=4,
                                                                    label=f'{v}\n(divisa {cap} MW)', zorder=6)))
        for y_, kw in series:
            if ok is None or ok.all():
                ax.plot(horas, y_, **kw)
            else:
                ax.plot(horas, y_, **dict(kw, label=None, alpha=0.22, markersize=2))
                ax.plot(horas, np.where(ok, y_, np.nan), **kw)
        ax.set_ylabel('$/MWh')
        if ok is not None and not ok.all():
            h_, l_ = ax.get_legend_handles_labels()
            h_.append(Line2D([], [], color=TEXTO2, alpha=0.3, linewidth=2, marker='o', markersize=2))
            l_.append(f'horas com pouco vertimento\n(< {100 * FRAC_POUCO:.0f}% da maior hora):\npreço pouco representativo')
            ax.legend(h_, l_, **LEG)
        else:
            ax.legend(**LEG)
    linhas_cmo(axs[2], col('cmo_estado'), f'{uf} (mediana de todas\nas barras do estado)', col('cmo_sin'),
               'SIN (mediana de todas\nas barras do país)', '')
    axs[2].set_title(f'CMO médio por hora ($/MWh) — todas as horas do ano: {uf}, SIN e os 3 estados com maior '
                     f'capacidade de divisa com {uf}', loc='left', fontsize=10)
    # 4 e 5) CMO nas barras das usinas no momento em que verteram x SIN e vizinhos nos mesmos momentos
    for ax, f_, rot in ((axs[3], 'ren', 'renováveis'), (axs[4], 'hid', 'hidrelétricas')):
        cu, cs = col(f'cmo_usinas_{f_}_que_verteram'), col(f'cmo_sin_quando_{f_}_verteu')
        ax.set_title(f'CMO no momento em que as {rot} do estado verteram ($/MWh, ponderado pelo MW vertido) — '
                     'azul abaixo do SIN = gargalo', loc='left', fontsize=10)
        if np.isfinite(cu).any():
            vt = np.nan_to_num(col(f'vert_{f_}_gargalo_MW')) + np.nan_to_num(col(f'vert_{f_}_excesso_MW'))
            ok = vt >= FRAC_POUCO * vt.max() if vt.max() > 0 else np.ones(24, bool)
            linhas_cmo(ax, cu, f'barras das {rot}\nque verteram', cs, 'SIN nesses\nmesmos momentos',
                       f'_quando_{f_}_verteu', ok=ok)
            ax.fill_between(horas, cu, cs, where=ok & np.isfinite(cu) & np.isfinite(cs) & (cu < cs - a.tolerancia),
                            color=COR_LIM, alpha=0.12, linewidth=0)
        else:
            ax.set_yticks([])
            ax.text(0.5, 0.5, f'sem vertimento das {rot} no estado', ha='center', va='center', color=TEXTO2,
                    transform=ax.transAxes)

    # 6 e 7) carregamento das linhas
    def painel_circ(ax, lista, titulo):
        for i, d in enumerate(lista):
            cor = CORES_CIRC[i % len(CORES_CIRC)]
            ax.plot(horas, quantil_hist(d['hist'], 0.5, NB, PASSO), color=cor, linewidth=2)
            ax.plot(horas, quantil_hist(d['hist'], 0.95, NB, PASSO), color=cor, linewidth=1, linestyle=':')
        ax.axhline(100, color=TEXTO, linewidth=1.2, linestyle='--')
        ax.set_ylabel('% do limite')
        ax.set_title(titulo, loc='left', fontsize=9.5)
        tot_h = lista[0]['hist'].sum() if lista else 1
        hand = []
        for i, d in enumerate(lista):
            lim_txt = f'{d["lim"]:,.0f}'.replace(',', '.')
            extra = (f'\n{100 * d["hlim"] / tot_h:.1f}% das horas no limite\nlado preso: {d["lado"]}'.replace('.', ',')
                     if d['hlim'] else
                     (f'\n{100 * d["hsob"] / tot_h:.1f}% das horas acima de 100%'.replace('.', ',') if d['hsob'] else ''))
            hand.append(Line2D([], [], color=CORES_CIRC[i % 4], linewidth=2,
                               label=f'{d["nome"][:30]}\n({d["ufs"]}, limite {lim_txt} MW){extra}'))
        hand.append(Line2D([], [], color=TEXTO2, linewidth=1, linestyle=':', label='pontilhado = 95% das horas abaixo'))
        ax.legend(handles=hand, **dict(LEG, fontsize=7))
    ax = axs[5]
    if top_m:
        painel_circ(ax, top_m, 'Carregamento das principais linhas/trafos MONITORADOS do estado (% do limite físico do '
                               'deck; cheia = mediana, tracejado = 100%)')
    else:
        ax.text(0.5, 0.5, 'nenhum circuito monitorado com limite ligado ao estado', ha='center', va='center',
                color=TEXTO2, transform=ax.transAxes)
    if top_n:
        painel_circ(axs[6], top_n, 'Circuitos NÃO monitorados do estado acima de 100% (o SDDP não limita esses '
                                   'circuitos)')
    for ax in axs:
        ax.grid(axis='y', color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_xticks(horas, [str(h) for h in horas], fontsize=7.5)
        ax.tick_params(labelbottom=True)
        ax.set_xlim(0.4, 24.6)
    axs[-1].set_xlabel('Hora do dia (1 = 00h-01h)')
    fig.legend(handles=[Patch(color=COR_LIM, label='vertimento por gargalo de transmissão'),
                        Patch(color=COR_EXC, label='vertimento por excesso no sistema (falta de demanda)')],
               loc='upper left', ncol=2, fontsize=9, frameon=False, bbox_to_anchor=(0.005, 1 - 0.42 / fig.get_figheight()))
    fig.suptitle(f'{uf} ({REGIAO_DA_UF.get(uf, "")}) — vertimento, CMO e linhas por hora do dia, {a.ano}', x=0.01,
                 y=1 - 0.12 / fig.get_figheight(), ha='left', fontsize=13, fontweight='bold')
    fig.text(0.01, 0.004, 'Médias de todas as horas do ano e de todos os cenários, por hora do dia. Gargalo = CMO da barra '
             f'da usina mais de {a.tolerancia:g} $/MWh abaixo do CMO do SIN na mesma hora e cenário. Vertimento sem a geração '
             'distribuída (MMGD/OMGD).',
             fontsize=7.5, color=TEXTO2)
    fig.subplots_adjust(left=0.055, right=0.78, top=1 - 0.95 / fig.get_figheight(), bottom=0.75 / fig.get_figheight(),
                        hspace=0.5)
    fig.savefig(os.path.join(pasta, f'estado_{uf}.png'), dpi=115)
    plt.close(fig)


def graficos_horarios(a, saida, estagios, n_cen, ref, elems, acc, linhas, NB, PASSO):
    """Gráfico padronizado por estado (estado_<UF>.png) e dispersão injeção x vertimento por causa."""
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    pasta_g = a.gargalo or os.path.join(a.caso, 'resultados_uf', 'gargalo_cmo')
    dados = {}
    for chave, arq in (('garg', 'vertimento_gargalo_uf_horario.csv'), ('exc', 'vertimento_excesso_uf_horario.csv'),
                       ('dif', 'cmo_diferenca_uf_horario.csv')):
        cam = os.path.join(pasta_g, arq)
        dados[chave] = ler_horario_sddp(cam) if os.path.exists(cam) else ({}, [])
    cam_inj = next((os.path.join(a.caso, 'resultados_uf', n) for n in ('businj_uf_horario.csv', 'bus_inj_uf_horario.csv')
                    if os.path.exists(os.path.join(a.caso, 'resultados_uf', n))), None)
    dados['inj'] = ler_horario_sddp(cam_inj) if cam_inj else ({}, [])
    if not dados['garg'][1]:
        print('  AVISO: sem os arquivos horários do gargalo_cmo; gráficos horários por estado não gerados')
        return
    if not cam_inj:
        print('  AVISO: sem businj_uf_horario.csv em resultados_uf (etapa 1); painel de injeção fica de fora')
    pasta = os.path.join(saida, 'por_estado')
    os.makedirs(pasta, exist_ok=True)
    horas = np.arange(1, 25)
    dispersao = {}
    perfil = {}
    cam_p = os.path.join(pasta_g, 'perfil_horario_uf.csv')
    if os.path.exists(cam_p):
        with open(cam_p, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                perfil.setdefault(r['uf'], []).append(r)
    else:
        print(f'  AVISO: não achei {cam_p}; rode antes o gargalo_cmo.py (versão atual). Gráficos por estado não gerados')

    for uf in ORDEM_UF:
        ser = {}
        for chave in ('garg', 'exc', 'dif', 'inj'):
            dic, ufs_ = dados[chave]
            ser[chave] = serie_ano(dic, estagios, n_cen, ufs_.index(uf)) if uf in ufs_ else (None, None, None)
        g, hd, est = ser['garg']
        x = ser['exc'][0]
        if g is None or x is None or (np.nansum(g) + np.nansum(x)) <= 0:
            continue
        # circuitos do estado: monitorados (mais vertimento do lado preso no estado, mais horas no limite,
        # maior carregamento) e não monitorados com sobrecarga
        cand_m, cand_n = [], []
        for tipo, E in elems.items():
            A = acc[tipo]
            for k in E['com_lim']:
                if uf not in (E['ufde'][k], E['ufpa'][k]):
                    continue
                hist = A['hist'][E['pos_lim'][k]]
                p95 = quantil_hist(hist, 0.95, NB, PASSO)
                lado = ORDEM_UF[int(A['lado_baixo'][k][:len(ORDEM_UF)].argmax())] if A['lado_baixo'][k].sum() else ''
                info = dict(tipo=tipo, k=k, nome=E['info'][k]['nome'], ufs=f'{E["ufde"][k]}-{E["ufpa"][k]}',
                            hlim=A['h_lim'][k].sum(), hsob=A['h_sobre'][k].sum(), p95max=np.nanmax(p95),
                            vert=A['vert'][k] if lado == uf else 0.0, lado=lado, hist=hist, lim=E['lim'][k])
                (cand_m if E['mon'][k] else cand_n).append(info)
        cand_m.sort(key=lambda d: (d['vert'], d['hlim'], d['p95max']), reverse=True)
        cand_n = sorted([d for d in cand_n if d['hsob'] > 0], key=lambda d: (d['hsob'], d['p95max']), reverse=True)
        top_m, top_n = cand_m[:4], cand_n[:3]
        inj = ser['inj'][0]
        if inj is not None:
            dispersao[uf] = (inj, g, x)
        P = perfil.get(uf)
        if P is None:
            continue
        figura_estado(uf, P, top_m, top_n, pasta, a, NB, PASSO, horas)

    # dispersão: injeção líquida x vertimento por causa, estados com mais vertimento
    if dispersao:
        tops = sorted(dispersao, key=lambda u: -(np.nansum(dispersao[u][1]) + np.nansum(dispersao[u][2])))[:6]
        fig, axs = plt.subplots(len(tops), 2, figsize=(13, 3.3 * len(tops) + 0.8), squeeze=False)
        for i, uf in enumerate(tops):
            inj, g, x = dispersao[uf]
            for j_, (v, cor, nome) in enumerate(((g, COR_LIM, 'por gargalo'), (x, COR_EXC, 'por excesso no sistema'))):
                ax = axs[i, j_]
                ok = v > 1
                cmap = LinearSegmentedColormap.from_list('seq', [FUNDO, cor, TEXTO])
                if ok.sum() > 10 and len(np.unique(np.round(inj[ok]))) > 20 and len(np.unique(np.round(v[ok]))) > 20:
                    ax.hexbin(inj[ok], v[ok], gridsize=40, bins='log', mincnt=1, cmap=cmap, linewidths=0)
                elif ok.any():
                    ax.scatter(inj[ok], v[ok], s=12, color=cor, alpha=0.5, edgecolor='none')
                else:
                    ax.text(0.5, 0.5, f'sem horas com vertimento {nome}', ha='center', va='center', color=TEXTO2,
                            transform=ax.transAxes)
                    ax.set_xticks([])
                    ax.set_yticks([])
                ax.axvline(0, color=TEXTO2, linewidth=0.8)
                ax.set_title(f'{uf} — vertimento {nome} × injeção líquida ({100 * ok.mean():.1f}% das horas com '
                             f'vertimento)'.replace('.', ','), loc='left', fontsize=9.5)
                ax.set_xlabel('Injeção líquida do estado (MW, positivo = exporta)')
                ax.set_ylabel('Vertimento (MW)')
                ax.grid(color=GRADE, linewidth=0.6)
                ax.set_axisbelow(True)
        fig.suptitle(f'Vertimento por causa × injeção líquida do estado, hora a hora, {a.ano}', x=0.01, ha='left',
                     fontsize=13, fontweight='bold')
        fig.text(0.01, 0.004, 'Cor = quantidade de horas (escala log), só horas com vertimento > 1 MW. Gargalo com '
                 'injeção alta = estado exportando no limite da rede; excesso com injeção baixa = falta de demanda.',
                 fontsize=7.5, color=TEXTO2)
        fig.tight_layout(rect=(0, 0.015, 1, 1 - 0.55 / fig.get_figheight()))
        fig.savefig(os.path.join(saida, 'injecao_x_vertimento_causa.png'), dpi=120)
        plt.close(fig)


def main():
    p = argparse.ArgumentParser(description='Linhas e transformadores no limite nas horas com vertimento.')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--carregamento', type=float, default=99.0, help='%% do limite para considerar "no limite"')
    p.add_argument('--tolerancia', type=float, default=1.0, help='diferença de custo marginal ($/MWh)')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--gargalo', help='pasta com vertimento_gargalo_uf_horario.csv (padrão: '
                                     '<caso>\\resultados_uf\\gargalo_cmo)')
    p.add_argument('--saida')
    p.add_argument('--top', type=int, default=30, help='quantos circuitos mostrar nos gráficos')
    a = p.parse_args()
    saida = a.saida or os.path.join(a.caso, 'resultados_uf', 'gargalo_linhas')
    os.makedirs(saida, exist_ok=True)
    lim_frac = a.carregamento / 100

    print('Abrindo as saídas do SDDP...')
    fl = {'linha': abrir(a.caso, 'acline_flow'), 'trafo': abrir(a.caso, 'transformer_flow', obrigatorio=False)}
    cmg = abrir(a.caso, 'cmgbus')
    ref = fl['linha']
    for h in [fl['trafo'], cmg]:
        if h is not None and (h['horas'] != ref['horas'] or h['n_cen'] != ref['n_cen']):
            sys.exit(f'ERRO: {h["nome"]} tem horas/cenários diferentes do acline_flow (rodadas diferentes?)')
    estagios = [e for e in range(ref['n_estagios']) if mes_ano(ref, e)[1] == a.ano]
    if not estagios:
        sys.exit(f'ERRO: a rodada não tem estágios de {a.ano}')
    n_cen = ref['n_cen']

    arq_g = os.path.join(a.gargalo or os.path.join(a.caso, 'resultados_uf', 'gargalo_cmo'),
                         'vertimento_gargalo_uf_horario.csv')
    if os.path.exists(arq_g):
        G, ufs_g = ler_horario_sddp(arq_g)
        print('Vertimento por gargalo:', arq_g)
    else:
        G, ufs_g = {}, []
        print(f'  AVISO: não achei {arq_g}; rode antes o gargalo_cmo.py. Sigo sem o vertimento coincidente.')

    lista_uf = list(ORDEM_UF) + ['??']
    iuf = {u: i for i, u in enumerate(lista_uf)}
    g_col = np.array([ufs_g.index(u) if u in ufs_g else -1 for u in lista_uf])   # UF -> coluna em G
    barras = [b for b in ler_tab(os.path.join(a.tabelas, 'barras_uf.csv')) if b['rede'] == 'CA']
    uf_cod = {int(b['codigo']): b['uf'] for b in barras}
    nome_cod = {int(b['codigo']): b['nome'] for b in barras}
    nome_sigla, ordem_sub = ids_subsistemas(a.caso)
    sub_cod = {int(b['codigo']): nome_sigla.get(b['subsistema'].upper(), b['subsistema'][:2].upper()) if b['subsistema']
               else '??' for b in barras}
    col_cmg = {n: i for i, n in enumerate(cmg['nomes'])}
    circ = circuitos_do_ano(a.caso, a.ano)

    # --- elementos de cada arquivo de fluxo ---------------------------------------
    elems = {}
    for tipo, h in fl.items():
        if h is None:
            continue
        info = []
        faltam = 0
        for n in h['nomes']:
            c = circ.get((tipo, n))
            if c is None:
                faltam += 1
                info.append(None)
                continue
            info.append(c)
        if faltam:
            print(f'  AVISO: {faltam} {tipo}s de {h["nome"]} sem cadastro no deck (ignorados)')
        lim = np.array([c['limite'] if c and c['opera'] and 0 < c['limite'] < SEM_LIMITE else np.nan for c in info])
        mon = np.array([bool(c and c['mon'] == 1) for c in info])
        cde = np.array([col_cmg.get(nome_cod.get(c['de'], ''), -1) if c else -1 for c in info])
        cpa = np.array([col_cmg.get(nome_cod.get(c['para'], ''), -1) if c else -1 for c in info])
        ufde = [uf_cod.get(c['de'], '??') if c else '??' for c in info]
        ufpa = [uf_cod.get(c['para'], '??') if c else '??' for c in info]
        subde = [sub_cod.get(c['de'], '??') if c else '??' for c in info]
        subpa = [sub_cod.get(c['para'], '??') if c else '??' for c in info]
        elems[tipo] = dict(h=h, info=info, lim=lim, mon=mon, cde=cde, cpa=cpa, ufde=ufde, ufpa=ufpa,
                           subde=subde, subpa=subpa,
                           ide=np.array([iuf.get(u, iuf['??']) for u in ufde]),
                           ipa=np.array([iuf.get(u, iuf['??']) for u in ufpa]))
        print(f'  {h["nome"]}: {len(info)} {tipo}s, {np.isfinite(lim).sum()} com limite, '
              f'{int((mon & np.isfinite(lim)).sum())} monitorados')

    # --- acumuladores ---------------------------------------------------------------
    acc = {}
    for tipo, E in elems.items():
        n = len(E['info'])
        acc[tipo] = dict(h_lim=np.zeros((n, 12)), h_sep=np.zeros(n), h_sobre=np.zeros((n, 12)),
                         cmax=np.zeros(n), vert=np.zeros(n), lado_baixo=np.zeros((n, len(lista_uf))))
    NB, PASSO = 61, 0.025                       # faixas de carregamento: 0-150% de 2,5 em 2,5% + acima de 150%
    for tipo, E in elems.items():
        E['com_lim'] = np.nonzero(np.isfinite(E['lim']))[0]
        acc[tipo]['hist'] = np.zeros(len(E['com_lim']) * 24 * NB, dtype=np.int64)
    horas_mes = np.zeros(12)
    uf_garg_horas = collections.Counter()      # UF -> horas com vertimento por gargalo
    uf_garg_com_linha = collections.Counter()  # UF -> horas com vertimento por gargalo e algum circuito da UF no limite
    t0 = time.time()
    for e in estagios:
        m = mes_ano(ref, e)[0] - 1
        for c in range(n_cen):
            P = bloco(cmg, e, c)
            Gb = G.get((e, c))
            nh = P.shape[0]
            horas_mes[m] += nh
            uf_com_limite = np.zeros((nh, len(lista_uf)), dtype=bool)
            for tipo, E in elems.items():
                F = np.abs(bloco(E['h'], e, c))
                car = F / E['lim']                                    # NaN onde não há limite
                A = acc[tipo]
                with np.errstate(invalid='ignore'):
                    A['cmax'] = np.fmax(A['cmax'], np.nanmax(np.where(np.isfinite(car), car, -np.inf), axis=0))
                    no_lim = (car >= lim_frac) & E['mon']
                    sobre = (car > 1.0) & ~E['mon']
                A['h_lim'][:, m] += no_lim.sum(axis=0)
                A['h_sobre'][:, m] += sobre.sum(axis=0)
                cl = car[:, E['com_lim']]
                faixa = np.minimum((cl / PASSO).astype(np.int64), NB - 1)
                hd_ = (np.arange(nh) % 24)[:, None]
                plano = ((np.arange(cl.shape[1])[None, :] * 24 + hd_) * NB + faixa).ravel()
                A['hist'] += np.bincount(plano, minlength=A['hist'].size)
                hh, kk = np.nonzero(no_lim)
                if len(hh):
                    pde = np.where(E['cde'][kk] >= 0, P[hh, np.clip(E['cde'][kk], 0, None)], np.nan)
                    ppa = np.where(E['cpa'][kk] >= 0, P[hh, np.clip(E['cpa'][kk], 0, None)], np.nan)
                    sep = np.abs(pde - ppa) > a.tolerancia
                    np.add.at(A['h_sep'], kk[sep], 1)
                    baixo = np.where(pde <= ppa, E['ide'][kk], E['ipa'][kk])      # UF do lado preso
                    np.add.at(A['lado_baixo'], (kk, baixo), 1)
                    uf_com_limite[hh, E['ide'][kk]] = True
                    uf_com_limite[hh, E['ipa'][kk]] = True
                    if Gb is not None:
                        gc = g_col[baixo]
                        ok = sep & (gc >= 0)
                        np.add.at(A['vert'], kk[ok], Gb[hh[ok], gc[ok]])
            if Gb is not None:
                for j, uf in enumerate(ufs_g):
                    tem = Gb[:, j] > 1e-6
                    uf_garg_horas[uf] += int(tem.sum())
                    if uf in iuf:
                        uf_garg_com_linha[uf] += int((tem & uf_com_limite[:, iuf[uf]]).sum())
        print(f'  {MESES[m]}/{a.ano} ok - {time.time() - t0:.0f} s')

    n_horas = horas_mes.sum()
    for tipo, E in elems.items():
        acc[tipo]['hist'] = acc[tipo]['hist'].reshape(len(E['com_lim']), 24, NB)
        E['pos_lim'] = {k: i for i, k in enumerate(E['com_lim'])}
    # --- CSV --------------------------------------------------------------------------
    linhas = []
    for tipo, E in elems.items():
        A = acc[tipo]
        for k, cinfo in enumerate(E['info']):
            if cinfo is None or not np.isfinite(E['lim'][k]):
                continue
            hl, hs = A['h_lim'][k].sum(), A['h_sobre'][k].sum()
            if hl == 0 and hs == 0:
                continue
            lado = lista_uf[int(A['lado_baixo'][k].argmax())] if A['lado_baixo'][k].sum() else ''
            sub_lado = (E['subde'][k] if lado == E['ufde'][k] else E['subpa'][k]) if lado else ''
            linhas.append(dict(tipo='linha' if tipo == 'linha' else 'transformador', nome=cinfo['nome'],
                               codigo=cinfo['codigo'], uf_de=E['ufde'][k], uf_para=E['ufpa'][k],
                               sub_de=E['subde'][k], sub_para=E['subpa'][k], sub_lado_preso=sub_lado,
                               limite_MW=E['lim'][k], monitorado=int(E['mon'][k]),
                               pct_horas_no_limite=100 * hl / n_horas,
                               pct_horas_separando_precos=100 * A['h_sep'][k] / n_horas,
                               pct_horas_sobrecarga=100 * hs / n_horas, carregamento_max_pct=100 * A['cmax'][k],
                               uf_lado_preso=lado, vertimento_gargalo_coincidente_GWh=A['vert'][k] / n_cen / 1000,
                               meses=[100 * A['h_lim'][k][mm] / max(horas_mes[mm], 1) for mm in range(12)],
                               meses_sobre=[100 * A['h_sobre'][k][mm] / max(horas_mes[mm], 1) for mm in range(12)]))
    cab = ['tipo', 'nome', 'codigo', 'uf_de', 'uf_para', 'limite_MW', 'monitorado', 'pct_horas_no_limite',
           'pct_horas_separando_precos', 'pct_horas_sobrecarga', 'carregamento_max_pct', 'uf_lado_preso',
           'vertimento_gargalo_coincidente_GWh', 'sub_de', 'sub_para', 'sub_lado_preso']
    with open(os.path.join(saida, 'circuitos_no_limite.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(cab + [f'pct_horas_no_limite_{MESES[mm]}' for mm in range(12)] +
                   [f'pct_horas_sobrecarga_{MESES[mm]}' for mm in range(12)])
        for l_ in sorted(linhas, key=lambda l_: (-l_['vertimento_gargalo_coincidente_GWh'], -l_['pct_horas_no_limite'],
                                                  -l_['pct_horas_sobrecarga'])):
            w.writerow([round(l_[k], 3) if isinstance(l_[k], float) else l_[k] for k in cab] +
                       [round(x, 2) for x in l_['meses']] + [round(x, 2) for x in l_['meses_sobre']])
    with open(os.path.join(saida, 'gargalos_por_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['uf', 'circuitos_monitorados_no_limite', 'circuitos_nao_monitorados_sobrecarga',
                    'horas_com_vertimento_por_gargalo', 'pct_dessas_horas_com_circuito_da_uf_no_limite'])
        for uf in ORDEM_UF:
            nl = sum(1 for l_ in linhas if l_['monitorado'] and l_['pct_horas_no_limite'] > 0 and uf in (l_['uf_de'], l_['uf_para']))
            ns = sum(1 for l_ in linhas if not l_['monitorado'] and l_['pct_horas_sobrecarga'] > 0 and uf in (l_['uf_de'], l_['uf_para']))
            hg = uf_garg_horas.get(uf, 0)
            w.writerow([uf, nl, ns, hg, round(100 * uf_garg_com_linha.get(uf, 0) / hg, 1) if hg else ''])

    # --- gráficos -----------------------------------------------------------------------
    POR_PAGINA = 20

    def barras_top(sel, chave, titulo, rot_x, cor, arquivo, extra, onde='', pasta=None, top=None, rotulo=None):
        """Barras (valor do ano) + mapa de calor (% das horas de cada mês), 20 circuitos por figura.
        top=None: todos os circuitos de sel. Devolve a lista de arquivos (arquivo.png, arquivo_2.png, ...)."""
        from matplotlib.colors import LinearSegmentedColormap
        import textwrap
        sel = sorted(sel, key=lambda l_: l_[chave], reverse=True)
        if top:
            sel = sel[:top]
        if not sel:
            return []
        rotulo = rotulo or (lambda l_: f'{l_["uf_de"]}-{l_["uf_para"]}')
        mk = 'meses' if 'sobre' not in arquivo else 'meses_sobre'
        vmax = max(max(max(l_[mk]) for l_ in sel), 1)
        xmax = max(l_[chave] for l_ in sel)
        cmap = LinearSegmentedColormap.from_list('seq', [FUNDO, cor, '#3a1010'])
        paginas = [sel[i:i + POR_PAGINA] for i in range(0, len(sel), POR_PAGINA)]
        base_arq, ext = os.path.splitext(arquivo)
        saidas_ = []
        for p_, pag in enumerate(paginas):
            pag = pag[::-1]                   # o maior fica em cima (barh desenha de baixo para cima)
            fig, axs = plt.subplots(1, 2, figsize=(17, 0.42 * len(pag) + 2.2), gridspec_kw=dict(width_ratios=[1, 1.25]))
            y = np.arange(len(pag))
            ax = axs[0]
            ax.barh(y, [l_[chave] for l_ in pag], color=cor, height=0.7)
            for k, l_ in enumerate(pag):
                ax.text(l_[chave], k, '  ' + extra(l_), va='center', fontsize=8.5, color=TEXTO2)
            ax.set_yticks(y, [f'{l_["nome"][:34]} ({rotulo(l_)})' for l_ in pag], fontsize=9)
            ax.set_ylim(-0.5, len(pag) - 0.5)             # mesma escala vertical do mapa de calor ao lado
            ax.set_xlim(0, xmax * 1.02)                   # mesma escala em todas as páginas
            ax.set_xlabel(rot_x)
            ax.grid(axis='x', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            sub = titulo.split(' — ', 1)[1] if ' — ' in titulo else rot_x
            ax.set_title('\n'.join(textwrap.wrap(sub[0].upper() + sub[1:], 70)), loc='left', fontsize=10)
            ax = axs[1]
            Mx = np.array([l_[mk] for l_ in pag])
            # origin='lower': linha 0 embaixo, na mesma ordem das barras do painel da esquerda
            im = ax.imshow(Mx, aspect='auto', cmap=cmap, vmin=0, vmax=vmax, interpolation='nearest', origin='lower')
            for i in range(Mx.shape[0]):
                for j in range(12):
                    if horas_mes[j] and Mx[i, j] >= 0.5:
                        ax.text(j, i, f'{Mx[i, j]:.0f}', ha='center', va='center', fontsize=8,
                                color=FUNDO if Mx[i, j] > 0.6 * vmax else TEXTO)
            ax.set_yticks([])
            ax.set_xticks(range(12), MESES)
            for sp in ax.spines.values():
                sp.set_visible(False)
            cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
            cb.outline.set_visible(False)
            ax.set_title('% das horas de cada mês (média dos cenários)', loc='left', fontsize=10)
            parte = f' — parte {p_ + 1} de {len(paginas)}' if len(paginas) > 1 else ''
            fig.suptitle(f'{titulo.split(" —")[0]}{onde}, {a.ano}{parte}', x=0.01, ha='left', fontsize=13,
                         fontweight='bold')
            fig.tight_layout(rect=(0, 0, 1, 1 - 0.5 / fig.get_figheight()))
            destino = os.path.join(pasta or saida, f'{base_arq}{"" if p_ == 0 else f"_{p_ + 1}"}{ext}')
            fig.savefig(destino, dpi=130)
            plt.close(fig)
            saidas_.append(destino)
        return saidas_

    fmt_lim = (lambda x: (f'{x:.1f}'.replace('.', ',') if x < 10 else f'{x:,.0f}'.replace(',', '.')))
    mon_lim = [l_ for l_ in linhas if l_['monitorado'] and l_['pct_horas_no_limite'] > 0]
    sobre = [l_ for l_ in linhas if not l_['monitorado'] and l_['pct_horas_sobrecarga'] > 0]

    def tres_graficos(m_sel, s_sel, onde='', pasta=None, prefixo='', top=-1, rotulo=None, lado='uf_lado_preso'):
        k_ = dict(onde=onde, pasta=pasta, top=a.top if top == -1 else top, rotulo=rotulo)
        barras_top([l_ for l_ in m_sel if l_['vertimento_gargalo_coincidente_GWh'] > 0],
                   'vertimento_gargalo_coincidente_GWh',
                   'Circuitos monitorados no limite com mais vertimento por gargalo — vertimento por gargalo do estado do '
                   'lado preso nas horas em que o circuito estava no limite', 'GWh no ano (média dos cenários)', COR_LIM,
                   f'{prefixo}circuitos_vertimento.png',
                   lambda l_: (f'{l_["pct_horas_no_limite"]:.1f}% das horas no limite'.replace('.', ',') +
                               f' · lado preso: {l_[lado]}'), **k_)
        barras_top(m_sel, 'pct_horas_no_limite',
                   f'Circuitos monitorados mais tempo no limite (≥ {a.carregamento:g}% do limite)',
                   '% das horas do ano', COR_LIM, f'{prefixo}circuitos_horas_no_limite.png',
                   lambda l_: f'limite {fmt_lim(l_["limite_MW"])} MW · lado preso: {l_[lado]}', **k_)
        barras_top(s_sel, 'pct_horas_sobrecarga',
                   'Circuitos NÃO monitorados acima de 100% do limite — gargalos que o SDDP não limita',
                   '% das horas do ano', COR_SOBRE, f'{prefixo}circuitos_sobrecarga_nao_monitorados.png',
                   lambda l_: f'máx. {l_["carregamento_max_pct"]:.0f}% · limite {fmt_lim(l_["limite_MW"])} MW', **k_)

    tres_graficos(mon_lim, sobre)                                        # Brasil (os --top primeiros)
    # por estado e por subsistema: TODOS os circuitos com uma ponta no estado/subsistema (20 por figura)
    p_uf = os.path.join(saida, 'circuitos_por_estado')
    p_sub = os.path.join(saida, 'circuitos_por_subsistema')
    os.makedirs(p_uf, exist_ok=True)
    os.makedirs(p_sub, exist_ok=True)
    for uf in ORDEM_UF:
        f_ = (lambda l_: uf in (l_['uf_de'], l_['uf_para']))
        tres_graficos([l_ for l_ in mon_lim if f_(l_)], [l_ for l_ in sobre if f_(l_)], onde=f' — {uf}', pasta=p_uf,
                      prefixo=f'{uf}_', top=None)
    subs = [x for x in ordem_sub] + sorted({x for l_ in linhas for x in (l_['sub_de'], l_['sub_para'])}
                                           - set(ordem_sub) - {'??'})
    rot_sub = (lambda l_: f'{l_["sub_de"]}-{l_["sub_para"]}, {l_["uf_de"]}-{l_["uf_para"]}')
    for sb in subs:
        f_ = (lambda l_: sb in (l_['sub_de'], l_['sub_para']))
        tres_graficos([l_ for l_ in mon_lim if f_(l_)], [l_ for l_ in sobre if f_(l_)], onde=f' — subsistema {sb}',
                      pasta=p_sub, prefixo=f'{sb}_', top=None, rotulo=rot_sub, lado='sub_lado_preso')

    graficos_horarios(a, saida, estagios, n_cen, ref, elems, acc, linhas, NB, PASSO)

    print(f'Circuitos monitorados que chegaram ao limite: {len(mon_lim)}')
    print(f'Circuitos não monitorados com sobrecarga: '
          f'{sum(1 for l_ in linhas if not l_["monitorado"] and l_["pct_horas_sobrecarga"] > 0)}')
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
