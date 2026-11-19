"""Despachante do executável analisa.exe (um só programa para todas as ferramentas).

Uso interno (chamado pelos rodar_*.bat, o usuário não digita isto):
  analisa <ferramenta> [argumentos]
  analisa com_log <arquivo_log> <ferramenta> [argumentos]   (roda e grava tudo no log)

As ferramentas são os módulos agrega_saidas_uf, limites_uf, graficos_uf, etc.
"""
import datetime
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agrega_saidas_uf                                                           # noqa: E402
import analise_semana_carga                                                       # noqa: E402
import apresentacao                                                               # noqa: E402
import apresentacao_detalhada                                                     # noqa: E402
import balanco_uf                                                                 # noqa: E402
import barras_uf                                                                  # noqa: E402
import exemplo_cmo                                                                # noqa: E402
import gargalo_cmo                                                                # noqa: E402
import gargalo_linhas                                                             # noqa: E402
import gargalo_subsistema                                                         # noqa: E402
import graficos_uf                                                                # noqa: E402
import limites_uf                                                                 # noqa: E402
import margem_barras                                                              # noqa: E402
import relacao_gargalo                                                            # noqa: E402

FERRAMENTAS = {m.__name__: m for m in (
    agrega_saidas_uf, limites_uf, graficos_uf, analise_semana_carga, margem_barras,
    gargalo_cmo, gargalo_linhas, relacao_gargalo, gargalo_subsistema, balanco_uf,
    apresentacao, apresentacao_detalhada, exemplo_cmo, barras_uf)}


class _Tee:
    """Escreve ao mesmo tempo na tela e no arquivo de log."""

    def __init__(self, tela, arquivo):
        self.tela, self.arquivo = tela, arquivo

    def write(self, texto):
        try:
            self.tela.write(texto)
        except UnicodeEncodeError:
            self.tela.write(texto.encode('ascii', 'replace').decode('ascii'))
        self.arquivo.write(texto)
        self.tela.flush()
        self.arquivo.flush()

    def flush(self):
        self.tela.flush()
        self.arquivo.flush()


def _rodar(nome, args):
    mod = FERRAMENTAS.get(nome)
    if mod is None:
        sys.exit(f'ferramenta desconhecida: {nome} (opções: {", ".join(sorted(FERRAMENTAS))})')
    sys.argv = [nome] + list(args)
    if nome == 'barras_uf':                 # único que não usa argparse
        mod.main(args[0], args[1])
    else:
        mod.main()


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit('uso: analisa <ferramenta> [argumentos]')
    if a[0] == 'com_log':
        if len(a) < 3:
            sys.exit('uso: analisa com_log <log> <ferramenta> [argumentos]')
        log, nome, resto = a[1], a[2], a[3:]
        pasta = os.path.dirname(os.path.abspath(log))
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        with open(log, 'a', encoding='utf-8') as f:
            tela_out, tela_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = _Tee(tela_out, f), _Tee(tela_err, f)
            inicio = datetime.datetime.now()
            print(f'[{inicio:%d/%m/%Y %H:%M:%S}] {nome} {" ".join(resto)}')
            codigo = 0
            try:
                _rodar(nome, resto)
            except SystemExit as e:
                if isinstance(e.code, int):
                    codigo = e.code
                elif e.code is None:
                    codigo = 0
                else:
                    print(e.code, file=sys.stderr)
                    codigo = 1
            except Exception:
                traceback.print_exc()
                codigo = 1
            fim = datetime.datetime.now()
            print(f'[{fim:%d/%m/%Y %H:%M:%S}] fim ({"ok" if codigo == 0 else "ERRO"}, '
                  f'{(fim - inicio).total_seconds() / 60:.1f} min)\n')
            sys.stdout, sys.stderr = tela_out, tela_err
        sys.exit(codigo)
    _rodar(a[0], a[1:])


if __name__ == '__main__':
    main()
