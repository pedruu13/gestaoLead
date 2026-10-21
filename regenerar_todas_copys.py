#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para regenerar todas as copys dos leads existentes no banco de dados
para o novo modelo consultivo (com triagem de recepção/agendamento, foco na necessidade
digital percebida do nicho, e 3 variações: consultiva, direta e curiosidade).
"""

import sys
import os
import time
import json
import sqlite3
import argparse

# Adiciona o diretório atual ao path para importar as funções do app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import (
    DB_NAME,
    load_config,
    gerar_copy_inteligente,
    update_lead_ai,
    extrair_apenas_numeros,
    eh_celular_valido,
    formatar_whatsapp,
    is_social_or_directory,
)

def eh_mercado_internacional(lead):
    tel = extrair_apenas_numeros(lead.get("telefone", ""))
    if tel and not tel.startswith("55"):
        return True
    local = (lead.get("bairro", "") or "").lower()
    intl_keywords = [
        "usa", "fl", "ny", "tx", "ca", "london", "uk", "portugal", 
        "lisbon", "spain", "madrid", "italy", "milan", "netherlands", 
        "amsterdam", "united states", "florida", "miami", "orlando"
    ]
    return any(k in local for k in intl_keywords)

def montar_dados_raw(lead):
    return {
        "Nome": lead.get("nome", "") or "",
        "Nicho": lead.get("nicho", "") or "",
        "Categoria Maps": lead.get("nicho", "") or "",
        "Bairro": lead.get("bairro", "") or "",
        "Nota Maps": lead.get("nota", "") or "",
        "Qtd Avaliacoes": lead.get("avaliacoes", "0") or "0",
        "Telefone": lead.get("telefone", "") or "",
        "E-mail Encontrado": lead.get("email", "") or "",
        "Instagram": lead.get("instagram", "") or "",
        "Facebook": lead.get("facebook", "") or "",
        "LinkedIn": lead.get("linkedin", "") or "",
        "Link Inicial": lead.get("link_inicial", "") or "",
        "Google Maps": lead.get("google_maps", "") or "",
        "Prompt Prototipo": lead.get("prompt_design", "") or "",
    }

def regenerar_copys(forcar_todas=True, pausa_segundos=1.2):
    print("=" * 65)
    print(" REGENERAÇÃO DE COPYS PARA O NOVO MODELO CONSULTIVO")
    print("=" * 65)
    
    config = load_config()
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM leads ORDER BY data_adicao DESC")
    leads = [dict(ix) for ix in c.fetchall()]
    conn.close()
    
    total = len(leads)
    print(f"[*] Total de leads encontrados no banco: {total}")
    if total == 0:
        print("[!] Nenhum lead cadastrado para atualizar.")
        return

    leads_para_processar = []
    for lead in leads:
        copies = lead.get("copies_pitch")
        # Se forcar_todas é True, processa todos. Caso contrário, apenas os que não tem copies_pitch válidas
        if forcar_todas:
            leads_para_processar.append(lead)
        else:
            tem_versoes = False
            if copies:
                try:
                    parsed = json.loads(copies) if isinstance(copies, str) else copies
                    tem_versoes = bool(parsed.get("consultiva") and parsed.get("direta") and parsed.get("curiosidade"))
                except Exception:
                    tem_versoes = False
            if not tem_versoes:
                leads_para_processar.append(lead)
                
    total_proc = len(leads_para_processar)
    print(f"[*] Leads a processar nesta execução: {total_proc}")
    print(f"[*] Pausa configurada entre chamadas: {pausa_segundos}s")
    print("-" * 65)
    
    atualizados = 0
    via_ia = 0
    via_contingencia = 0
    erros = 0
    
    for idx, lead in enumerate(leads_para_processar, 1):
        place_id = lead.get("place_id")
        nome = lead.get("nome", "Sem nome")
        is_intl = eh_mercado_internacional(lead)
        dados_raw = montar_dados_raw(lead)
        
        try:
            resultado_ia = gerar_copy_inteligente(dados_raw, config, is_intl=is_intl)
            copy_texto = resultado_ia.get("mensagem", "")
            analise_ia = resultado_ia.get("analise", "")
            estrategia_ia = resultado_ia.get("estrategia", "")
            versoes = resultado_ia.get("versoes", {})
            gerada_ia = resultado_ia.get("gerada_por_ia", False)
            
            # Recalcula o link do WhatsApp com a nova copy codificada
            tel_raw = lead.get("telefone", "")
            numeros_whats = extrair_apenas_numeros(tel_raw)
            whats_link_final = ""
            if numeros_whats and eh_celular_valido(numeros_whats):
                whats_link_final = formatar_whatsapp(numeros_whats, copy_texto)
            else:
                whats_link_final = lead.get("whatsapp_link", "")
                
            update_lead_ai(
                place_id,
                copy_texto,
                analise_ia,
                estrategia_ia,
                whats_link_final,
                versoes,
            )
            
            atualizados += 1
            if gerada_ia:
                via_ia += 1
                tipo = "Gemini IA"
            else:
                via_contingencia += 1
                tipo = "Modelo Consultivo Setorial"
                
            print(f"[{idx}/{total_proc}] OK: {nome[:32]:<32} | {tipo} | 3 variações salvas")
            
            if pausa_segundos > 0 and idx < total_proc:
                time.sleep(pausa_segundos)
                
        except Exception as e:
            erros += 1
            print(f"[{idx}/{total_proc}] ERRO em {nome}: {e}")
            
    print("=" * 65)
    print(" RESUMO DA REGENERAÇÃO:")
    print(f" - Total atualizados: {atualizados}")
    print(f" - Gerados via Gemini: {via_ia}")
    print(f" - Gerados via Modelo Consultivo Setorial: {via_contingencia}")
    print(f" - Erros: {erros}")
    print("=" * 65)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regenerar copys dos leads para o novo modelo")
    parser.add_argument("--todas", action="store_true", default=True, help="Regenerar todas as copys mesmo as que já possuem variações")
    parser.add_argument("--so-antigos", dest="todas", action="store_false", help="Apenas leads que ainda não possuem as 3 variações")
    parser.add_argument("--pausa", type=float, default=1.0, help="Segundos de pausa entre leads para evitar rate limit (padrão: 1.0s)")
    args = parser.parse_args()
    
    regenerar_copys(forcar_todas=args.todas, pausa_segundos=args.pausa)
