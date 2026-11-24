"""Inventory deltas, recorded inside the same transaction as the change."""
from copy import deepcopy
from datetime import datetime,timezone
from flask import has_request_context,session

def record_changes(state,before):
    actor=session.get('user','sistema') if has_request_context() else 'sistema'
    history=state.setdefault('stock_history',[])
    cfg=state.get('config') or {};materials={m['id']:m for m in cfg.get('materials',[])};components={c['id']:c for c in cfg.get('stock_components',[])}
    for collection,qtykey in [('lots','length_m'),('component_lots','quantity')]:
        for ident,lot in state.get(collection,{}).items():
            old=before.get(collection,{}).get(ident)
            if old==lot:continue
            qty=lot[qtykey];previous=old.get(qtykey,0) if old else 0
            # Reservation changes carry revisions but no physical stock delta.
            if old and all(lot.get(k)==old.get(k) for k in (qtykey,'width_cm','location','minimum_m','origin')):continue
            m=materials.get(lot.get('material_id'),{});c=components.get(lot.get('component_id'),{})
            color=next((x['name'] for x in m.get('colors',[]) if x['id']==lot.get('color_id')),'')
            recent=next((x for x in reversed(state['movements']) if x.get('lot_id')==ident),{})
            history.append(dict(at=datetime.now(timezone.utc).isoformat(timespec='seconds'),actor=actor,lot_id=ident,
                article=c.get('name') or m.get('name') or ident,material=m.get('name',''),color=color,
                before=previous,delta=round(qty-previous,6),after=qty,unit=lot.get('unit','m'),
                kind=lot.get('kind','insumo'),event=recent.get('event','ajuste'),reason=recent.get('reason') or lot.get('origin','')))
