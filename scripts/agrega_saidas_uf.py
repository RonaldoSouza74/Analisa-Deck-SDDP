"""Agrega por UF (estado) as saídas binárias do SDDP (.hdr + .bin).

Lê os arquivos grandes aos poucos (sem carregar tudo na memória) e gera CSVs
pequenos, prontos para o Excel:

  <var>_uf_horario.csv        cenário x hora, uma coluna por UF
  <var>_uf_mensal.csv         cenário (e média) x mês x UF [x tecnologia]
  <var>_agente_mensal.csv     cada usina/barra x mês, média dos cenários

Variáveis procuradas na pasta do caso (as que existirem):
  gergnd  geração renovável      (por usina renovável)
  vergnd  vertimento renovável   (por usina renovável)
  businj / bus_inj  injeção líquida por barra CA
  bus_losses        perdas por barra CA

Uso:
  python agrega_saidas_uf.py "C:\\caminho\\da\\pasta\\do\\caso"

Opções:
  --tabelas PASTA   onde estão barras_uf.csv e usinas_renovaveis_uf.csv
                    (padrão: a mesma pasta deste script)
  --saida PASTA     onde gravar os CSVs (padrão: <caso>\\resultados_uf)
  --uf-usina nome   usa a UF do nome da usina em vez da UF da barra de conexão
  --arquivos A B    processa só estes arquivos (ex.: --arquivos gergnd vergnd)

Requer Python 3 e numpy.
"""
import argparse
import csv
import os
import struct
import sys
import time

try:
    import numpy as np
except ImportError:
    sys.exit('ERRO: o pacote numpy não está instalado. Rode:  python -m pip install numpy')

VARIAVEIS = ['gergnd', 'vergnd', 'businj', 'bus_inj', 'bus_losses']
MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
DIAS_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


# ----------------------------------------------------------------------------
# Leitura do cabeçalho .hdr (formato binário PSR, registros estilo Fortran)
# ----------------------------------------------------------------------------
def ler_hdr(caminho):
    b = open(caminho, 'rb').read()
    pos = 0

    def registro():
        nonlocal pos
        n = struct.unpack_from('<i', b, pos)[0]
        dado = b[pos + 4:pos + 4 + n]
        if b[pos + 4 + n:pos + 8 + n] != b[pos:pos + 4]:
            raise ValueError(f'{caminho}: cabeçalho em formato inesperado (posição {pos})')
        pos += 8 + n
        return dado

    versao = struct.unpack('<i', registro())[0]
    r = registro()
    (estagio_ini, n_estagios, n_cenarios, n_agentes, varia_cenario, varia_bloco,
     discret_hora, tipo_estagio, mes_ini, ano_ini) = struct.unpack_from('<10i', r, 0)
    unidade = r[40:47].decode('latin-1').strip()
    tam_nome = struct.unpack_from('<i', r, 47)[0]

    horas = None
    if len(b) - pos != n_agentes * (tam_nome + 8):
        r = registro()
        horas = list(struct.unpack('<%di' % (len(r) // 4), r))  # horas acumuladas por estágio
    nomes = [registro().decode('latin-1').strip() for _ in range(n_agentes)]
    if pos != len(b):
        raise ValueError(f'{caminho}: sobraram {len(b) - pos} bytes no cabeçalho')

    if horas is None or len(horas) != n_estagios + 1:
        raise ValueError(f'{caminho}: este script trata apenas saídas horárias '
                         f'(não achei a tabela de horas por estágio)')
    return dict(versao=versao, n_estagios=n_estagios, n_cenarios=n_cenarios,
                n_agentes=n_agentes, varia_cenario=varia_cenario, varia_bloco=varia_bloco,
                tipo_estagio=tipo_estagio, mes_ini=mes_ini, ano_ini=ano_ini,
                unidade=unidade, horas=horas, nomes=nomes)


def mes_ano(h, estagio):
    """Mês e ano do estágio (0 = primeiro), para estágios mensais."""
    m = h['mes_ini'] - 1 + estagio
    return m % 12 + 1, h['ano_ini'] + m // 12


# ----------------------------------------------------------------------------
# Tabelas de UF
# ----------------------------------------------------------------------------
def ler_tabela(caminho):
    with open(caminho, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def num(x):
    """Número com vírgula decimal (Excel em português)."""
    return ('%.3f' % x).replace('.', ',')


def escrever_csv(caminho, cabecalho, linhas):
    with open(caminho, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(cabecalho)
        w.writerows(linhas)


# ----------------------------------------------------------------------------
# Processamento de uma variável
# ----------------------------------------------------------------------------
def processar(var, caso, saida, usinas, barras, uf_usina):
    hdr = ler_hdr(os.path.join(caso, var + '.hdr'))
    arq_bin = os.path.join(caso, var + '.bin')
    if not os.path.exists(arq_bin):
        print(f'  [{var}] AVISO: {var}.hdr existe, mas {var}.bin não. Pulando.')
        return

    n_est, n_ag, unidade = hdr['n_estagios'], hdr['n_agentes'], hdr['unidade']
    n_cen = hdr['n_cenarios'] if hdr['varia_cenario'] else 1
    total_h = hdr['horas'][-1]
    esperado = total_h * n_cen * n_ag * 4
    tamanho = os.path.getsize(arq_bin)
    print(f'  [{var}] {n_ag} agentes, {n_est} estágios ({total_h} horas), {n_cen} cenários, '
          f'unidade {unidade}, {tamanho / 1e9:.2f} GB')
    if tamanho != esperado:
        sys.exit(f'ERRO em {var}: o .bin tem {tamanho} bytes, mas o .hdr indica {esperado}.\n'
                 f'Copie esta mensagem e envie para análise.')

    # --- agente -> UF (e tecnologia, para usinas) ----------------------------
    nomes = hdr['nomes']
    if var in ('gergnd', 'vergnd'):
        tab = {u['nome_usina']: u for u in usinas}
        col_uf = 'uf_nome_usina' if uf_usina == 'nome' else 'uf_barra'
        uf_ag = [tab[n][col_uf] if n in tab else '??' for n in nomes]
        tec_ag = [tab[n]['tecnologia'] if n in tab else '??' for n in nomes]
        tipo_agente = 'usina'
    else:
        tab = {b['nome']: b for b in barras}
        uf_ag = [tab[n]['uf'] if n in tab else '??' for n in nomes]
        tec_ag = None
        tipo_agente = 'barra'
    sem_uf = sum(1 for u in uf_ag if u == '??')
    if sem_uf:
        print(f'  [{var}] AVISO: {sem_uf} agentes sem UF na tabela (somados como "??")')

    ufs = sorted(set(uf_ag))
    M_uf = np.zeros((n_ag, len(ufs)))
    for i, u in enumerate(uf_ag):
        M_uf[i, ufs.index(u)] = 1
    if tec_ag:
        grupos = sorted(set(zip(uf_ag, tec_ag)))
        M_grp = np.zeros((n_ag, len(grupos)))
        for i, g in enumerate(zip(uf_ag, tec_ag)):
            M_grp[i, grupos.index(g)] = 1
    else:
        grupos, M_grp = [(u,) for u in ufs], M_uf

    # Energia (GWh por hora) vira MWh; potência (MW) fica em MW
    energia = unidade.upper().startswith(('GWH', 'MWH'))
    fator = 1000.0 if unidade.upper().startswith('GWH') else 1.0
    un_saida = 'MWh' if energia else unidade

    dados = np.memmap(arq_bin, dtype='<f4', mode='r')
    f_hora = open(os.path.join(saida, f'{var}_uf_horario.csv'), 'w', encoding='utf-8-sig', newline='')
    w_hora = csv.writer(f_hora, delimiter=';')
    w_hora.writerow(['cenario', 'data_hora'] + [f'{u} ({un_saida})' for u in ufs])

    mensal = np.zeros((n_cen, n_est, len(grupos)))   # soma (energia) ou média (MW)
    agente = np.zeros((n_est, n_ag))                  # média dos cenários
    inicio = time.time()
    for e in range(n_est):
        h0, h1 = hdr['horas'][e], hdr['horas'][e + 1]
        nh = h1 - h0
        mes, ano = mes_ano(hdr, e)
        rotulos = [f'{ano}-{mes:02d}-{h // 24 + 1:02d} {h % 24:02d}:00' for h in range(nh)]
        bloco = dados[h0 * n_cen * n_ag:h1 * n_cen * n_ag].reshape(n_cen, nh, n_ag)
        for c in range(n_cen):
            x = np.asarray(bloco[c], dtype=np.float64) * fator        # horas x agentes
            por_uf = x @ M_uf
            for h in range(nh):
                w_hora.writerow([c + 1, rotulos[h]] + [num(v) for v in por_uf[h]])
            red = x.sum(axis=0) if energia else x.mean(axis=0)        # por agente no mês
            mensal[c, e] = red @ M_grp
            agente[e] += red / n_cen
        dec = time.time() - inicio
        print(f'  [{var}] estágio {e + 1}/{n_est} ({MESES[mes - 1]}/{ano}) ok - {dec:.0f} s')
    f_hora.close()

    # --- mensal por UF (e tecnologia) ---------------------------------------
    medida = 'energia_MWh' if energia else f'media_{un_saida}'
    cab = ['cenario', 'ano', 'mes', 'uf'] + (['tecnologia'] if tec_ag else []) + [medida]
    linhas = []
    for c in list(range(n_cen)) + ['media']:
        valores = mensal.mean(axis=0) if c == 'media' else mensal[c]
        for e in range(n_est):
            mes, ano = mes_ano(hdr, e)
            for g, grp in enumerate(grupos):
                linhas.append([c + 1 if c != 'media' else 'media', ano, mes, *grp, num(valores[e, g])])
    escrever_csv(os.path.join(saida, f'{var}_uf_mensal.csv'), cab, linhas)

    # --- por agente, média dos cenários -------------------------------------
    cols = [f'{MESES[mes_ano(hdr, e)[0] - 1]}/{mes_ano(hdr, e)[1]}' for e in range(n_est)]
    cab = [tipo_agente, 'uf'] + (['tecnologia'] if tec_ag else []) + cols + ['total' if energia else 'media']
    linhas = []
    for i, n in enumerate(nomes):
        v = agente[:, i]
        tot = v.sum() if energia else (v * np.diff(hdr['horas'])).sum() / total_h
        linhas.append([n, uf_ag[i]] + ([tec_ag[i]] if tec_ag else []) + [num(x) for x in v] + [num(tot)])
    escrever_csv(os.path.join(saida, f'{var}_agente_mensal.csv'), cab, linhas)

    # --- checagem: perfil da solar no 1º dia (deve ser zero à noite) --------
    if tec_ag and 'Solar' in tec_ag:
        idx = [i for i, t in enumerate(tec_ag) if t == 'Solar']
        dia = np.asarray(dados[:24 * n_cen * n_ag].reshape(n_cen, 24, n_ag)[0][:, idx], dtype=np.float64)
        perfil = dia.sum(axis=1) * fator
        txt = ' '.join(f'{h:02d}h:{v:.0f}' for h, v in enumerate(perfil))
        print(f'  [{var}] checagem - solar centralizada, 1º dia, cenário 1 ({un_saida}): {txt}')
        with open(os.path.join(saida, 'checagem.txt'), 'a', encoding='utf-8') as f:
            f.write(f'{var} solar 1o dia cenario 1 ({un_saida}): {txt}\n')
    print(f'  [{var}] concluído em {time.time() - inicio:.0f} s')


def main():
    p = argparse.ArgumentParser(description='Agrega saídas do SDDP por UF.')
    p.add_argument('caso', help='pasta com os arquivos .hdr/.bin do SDDP')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--saida')
    p.add_argument('--uf-usina', choices=['barra', 'nome'], default='barra')
    p.add_argument('--arquivos', nargs='+')
    a = p.parse_args()

    caso = os.path.abspath(a.caso)
    saida = a.saida or os.path.join(caso, 'resultados_uf')
    os.makedirs(saida, exist_ok=True)
    for t in ('barras_uf.csv', 'usinas_renovaveis_uf.csv'):
        if not os.path.exists(os.path.join(a.tabelas, t)):
            sys.exit(f'ERRO: não achei {t} em {a.tabelas}. Coloque-o na mesma pasta do script.')
    usinas = ler_tabela(os.path.join(a.tabelas, 'usinas_renovaveis_uf.csv'))
    barras = ler_tabela(os.path.join(a.tabelas, 'barras_uf.csv'))

    variaveis = a.arquivos or [v for v in VARIAVEIS if os.path.exists(os.path.join(caso, v + '.hdr'))]
    if not variaveis:
        sys.exit(f'ERRO: nenhum arquivo .hdr de {VARIAVEIS} encontrado em {caso}')
    print(f'Pasta do caso: {caso}\nResultados em: {saida}\nArquivos: {", ".join(variaveis)}')
    if os.path.exists(os.path.join(saida, 'checagem.txt')):
        os.remove(os.path.join(saida, 'checagem.txt'))
    for v in variaveis:
        processar(v, caso, saida, usinas, barras, a.uf_usina)
    print('Fim. Arquivos gerados em', saida)


if __name__ == '__main__':
    main()
