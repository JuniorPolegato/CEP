#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pygtk
pygtk.require("2.0")
import gtk
import threading

import httplib
import urllib
import json
import re

oo = float("infinity")

class Projeto(object):
    def __init__(self, *args, **kargs):
        ui = gtk.Builder()
        ui.add_from_file('consulta_cep.ui')
        ui.connect_signals(self)
        ui.get_object('eventbox1').modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color("Royal Blue"))
        self.pb_cep         = ui.get_object('pb_cep')
        self.pb_cep_total   = ui.get_object('pb_cep_total')
        self.ed_cep_inicial = ui.get_object('ed_cep_inicial')
        self.ed_cep_final   = ui.get_object('ed_cep_final')
        self.ls_dados       = ui.get_object('ls_dados')
        self.jn_principal   = ui.get_object('jn_principal')
        self.bt_localizar   = ui.get_object('bt_localizar')
        self.bt_limpar      = ui.get_object('bt_limpar')
        self.bt_copiar      = ui.get_object('bt_copiar')

        self.sessao_cep_iniciada = False
        self.terminar = False
        self.ed_cep_inicial.props.text = '14.120'
        self.ed_cep_final.props.text = '14.150'
        self.con_maps = None
        self.lock = threading.Lock()

    def requerer_cep(self, cep):
        if not self.sessao_cep_iniciada:
            self.iniciar_sessao_cep()

        progresso = 0
        self.pb_cep.set_fraction(progresso)
        c = cep[:2] + '.' + cep[2:5] + ('-' + cep[5:] if len(cep) > 5 else '')
        self.pb_cep.set_text("%s - %i%%" % (c, progresso * 100))
        while gtk.events_pending():
            gtk.main_iteration()

        self.headers_cep['Referer'] = 'http://www.buscacep.correios.com.br/servicos/dnec/menuAction.do?Metodo=menuCep'
        dados = "CEP=%s&Metodo=listaLogradouro&TipoConsulta=cep&StartRow=1&EndRow=10" % str(cep)
        con = httplib.HTTPConnection('www.buscacep.correios.com.br')
        con.request('POST', '/servicos/dnec/consultaLogradouroAction.do', dados, self.headers_cep)
        resp = con.getresponse()
        html = resp.read().decode(self.charset_cep)
        p = html.find('<?xml ')
        html = html[p:html.find('</table>', p) + 8]
        cookie = ''
        for header in resp.getheaders():
            if header[0].lower() == "set-cookie":
                cookie += (header[1] + ';').split(';', 1)[0] + ';'
        partes = html.split('onclick="javascript:detalharCep(')[1:]
        if len(partes) == 0:
            return
        self.headers_cep['Cookie'] = cookie
        self.headers_cep['Referer'] = "http://www.buscacep.correios.com.br/servicos/dnec/consultaLogradouroAction.do"
        passo = 1./len(partes)
        for parte in partes:
            posicao, tipo = [int(x) for x in parte.split(')', 1)[0].replace("'", '').split(',')]
            dados = "Metodo=detalhe&Posicao=%i&TipoCep=%i&CEP=" % (posicao, tipo)
            con.request('POST', '/servicos/dnec/detalheCEPAction.do', dados, self.headers_cep)
            resp = con.getresponse()
            html = resp.read().decode(self.charset_cep)
            if tipo == 2:
                p = html.find('>Logradouro:</td>') + 1
            elif tipo == 1:
                p = html.find('>Localidade:</td>') + 1
            elif tipo == 6:
                p = html.find('>Unidade:</td>') + 1
            elif tipo == 5:
                p = html.find('>Cliente:</td>') + 1
            else:
                print 'Tipo %i desconhecido' % tipo
                raw_input()
            html = html[p:html.find('</table>', p) + 8].replace('\r', '').replace('\n', ' ')
            html = re.sub(r'[ \t]*(?=<)|(?=>)[ \t]*', '', html)
            html = re.sub(r'</td></tr></table>', '', html)
            dados = [re.split(r'</td><td[^>]*>', par) for par in html.split('</td></tr><tr><td class="label">')]
            dados = zip(*dados)[1]
            if tipo == 2: # Logradouro
                infos = dados[0].split(' - ')
                logradouro = infos[0]
                lado = 'ambos'
                inicio = 0
                fim = 999999
                print dados[3], infos
                for info in infos[1:]:
                    if info[:5] == 'lado ':
                        lado = info[5:]
                    elif info[:3] == 'de ':
                        if ' a ' in info:
                            inicio, fim = info[3:].split(' a ', 1)
                            inicio = int(inicio.split('/')[0])
                            fim = int(fim.split('/')[-1])
                        else:
                            inicio = int(info[3:].split(' ', 1)[0].split('/')[0])
                    elif info[:4] == u'até ':
                        fim = int(info[4:].split('/')[-1])
                    else:
                        logradouro += ' - ' + info
                linha = self.ls_dados.append([logradouro, lado, inicio, fim, dados[1], dados[2].split('/')[0], dados[2].split('/')[1], dados[3], '', '', oo, oo])
            elif tipo == 1: # Localidade
                linha = self.ls_dados.append(['', '', 0, 999999, '', dados[0], dados[1], dados[2], '', '', oo, oo])
            elif tipo in (5, 6): # Unidade ou Cliente
                caixa_postal = re.sub(r'<[^>]*>', '', dados[5]) if len(dados) > 5 else ''
                linha = self.ls_dados.append([dados[1], 'ambos', 0, 999999, dados[2], dados[3].split('/')[0], dados[3].split('/')[1], dados[4], dados[0], caixa_postal, oo, oo])
            threading.Thread(target = self.lat_lng, args = (linha,)).start()

            progresso += passo
            self.pb_cep.set_fraction(progresso if progresso < 1 else 1)
            self.pb_cep.set_text("%s - %i%%" % (cep, progresso * 100))
            while gtk.events_pending():
                gtk.main_iteration()
            if self.terminar:
                break

        con.close()

    def iniciar_sessao_cep(self):
        self.headers_cep = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux i686; rv:10.0.3) Gecko/20100101 Firefox/10.0.3', # Iceweasel/10.0.3',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-br,pt;q=0.8,en-us;q=0.5,en;q=0.3',
            'DNT': '1',
            'Connection': 'keep-alive'
        }
        con = httplib.HTTPConnection('www.buscacep.correios.com.br')
        con.request('GET', '/servicos/dnec/menuAction.do?Metodo=menuCep', None, self.headers_cep)
        resp = con.getresponse()
        cookie = ''
        charset = ''
        for header in resp.getheaders():
            if header[0].lower() == "set-cookie":
                cookie += (header[1] + ';').split(';', 1)[0] + ';'
            if header[0].lower() == "content-type":
                charset = [x.split('=')[1] for x in header[1].split(';') if x.split('=')[0] == 'charset']
                charset = 'ISO-8859-1' if len(charset) == 0 else charset[0]
        html = resp.read()
        self.headers_cep['Cookie'] = cookie
        self.headers_cep['Content-Type'] = 'application/x-www-form-urlencoded'
        con.close()
        self.charset_cep = charset
        self.sessao_cep_iniciada = True

    def ao_clicar_bt_localizar(self, botao):
        if self.bt_localizar.get_label() == "gtk-stop":
            self.bt_localizar.set_label("gtk-find")
            self.terminar = True
            self.bt_limpar.set_sensitive(True)
            self.bt_copiar.set_sensitive(True)
            return
        self.bt_localizar.set_label("gtk-stop")
        self.bt_limpar.set_sensitive(False)
        self.bt_copiar.set_sensitive(False)
        self.terminar = False
        cep_inicial = re.sub('[^0-9]', '', self.ed_cep_inicial.props.text)[:8]
        cep_final = re.sub('[^0-9]', '', self.ed_cep_final.props.text)[:8]
        if len(cep_inicial) < 5:
            d = gtk.MessageDialog(self.jn_principal, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_OK, "CEP inical inválido!")
            d.run()
            d.destroy()
            del d
            return
        if len(cep_final) < 5:
            d = gtk.MessageDialog(self.jn_principal, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_OK, "CEP final inválido!")
            d.run()
            d.destroy()
            del d
            return
        if cep_final < cep_inicial:
            self.requerer_cep(cep_inicial)
        else:
            cep_atual = cep_inicial
            inicio = cep_inicial + '0' * (8 - len(cep_inicial))
            fim = cep_final + '0' * (8 - len(cep_final))
            formatar = "%0" + str(len(cep_atual)) + "i"
            faixa = inicio[:2] + '.' + inicio[2:5] + '-' + inicio[5:] + ' à ' + fim[:2] + '.' + fim[2:5] + '-' + fim[5:] + ' - '
            fim, inicio = int(fim), int(inicio)
            intervalo = fim - inicio
            self.pb_cep_total.set_fraction(0)
            self.pb_cep_total.set_text(faixa + '0%')
            while gtk.events_pending():
                gtk.main_iteration()
            while cep_atual <= cep_final:
                self.requerer_cep(cep_atual)
                atual = float(cep_atual + '0' * (8 - len(cep_atual))) - inicio
                progresso = atual / intervalo if intervalo else 1.
                self.pb_cep_total.set_fraction(progresso if progresso < 1. else 1.)
                self.pb_cep_total.set_text("%s%i%%" % (faixa, progresso * 100))
                while gtk.events_pending():
                    gtk.main_iteration()
                cep_atual = formatar % (int(cep_atual) + 1)
                if self.terminar:
                    break
        self.bt_localizar.set_label("gtk-find")
        self.bt_limpar.set_sensitive(True)
        self.bt_copiar.set_sensitive(True)


    def lat_lng(self, linha):
        self.lock.acquire()
        response = None
        try:
            busca = urllib.quote_plus(
                        (
                            self.ls_dados[linha][0] + ' - '
                            if self.ls_dados[linha][0] else ''
                        ) +
                        self.ls_dados[linha][5] + ' - ' +
                        self.ls_dados[linha][6] + ' - Brasil')
            if not self.con_maps:
                self.con_maps = httplib.HTTPConnection('maps.googleapis.com')
            self.con_maps.request('GET', '/maps/api/geocode/json?address=' + busca + '&sensor=false')
            response = self.con_maps.getresponse()
            if response.status != 200:
                raise Exception('Response Error')
            result = json.loads(response.read())['results'][0]
            if 'partial_match' in result and result['partial_match']:
                busca = urllib.quote_plus(
                            self.ls_dados[linha][5] + ' - '
                            + self.ls_dados[linha][6] + ' - Brasil')
                response = None
                self.con_maps.request('GET', '/maps/api/geocode/json?address=' + busca + '&sensor=false')
                response = self.con_maps.getresponse()
                if response.status != 200:
                    raise Exception('Response Error')
                result = json.loads(response.read())['results'][0]
            lat = result['geometry']['location']['lat']
            lng = result['geometry']['location']['lng']
            self.ls_dados[linha][-2] = lat
            self.ls_dados[linha][-1] = lng
        except Exception as e:
            print e
            if response:
                print response.status, response.reason
                print response.getheaders()
                print response.read()
        self.lock.release()

    def ao_clicar_sair(self, *args):
        self.terminar = True
        gtk.main_quit()

    def ao_clicar_bt_limpar(self, *args):
        self.bt_limpar.set_sensitive(False)
        self.bt_copiar.set_sensitive(False)
        self.ls_dados.clear()

    def ao_clicar_bt_copiar(self, *args):
        csv = 'Logradouro\tLado\tNº de\tNº até\tBairro\tCidade\tUF\tCEP\tUnidade/Cliente\tCaixa Postal\tLatitude\tLongitude\n'
        csv += '\n'.join(['\t'.join([str(c) for c in l]) for l in self.ls_dados]) + '\n'
        gtk.clipboard_get().set_text(csv)
        d = gtk.MessageDialog(self.jn_principal, 0, gtk.MESSAGE_INFO, gtk.BUTTONS_OK, "Dados copiados para a área de transferência!")
        d.run()
        d.destroy()
        del d

if  __name__ == "__main__":
    gtk.threads_init()
    projeto = Projeto()
    gtk.main()
