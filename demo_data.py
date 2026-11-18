"""Explicit, one-time fictitious inventory for the separate preview only."""
from copy import deepcopy
from private_store import transaction
from quoting import defaults, now, audit
from storage import load_catalog

DEMO_VERSION='stock-ficticio-v1'


def prepare_demo():
    with transaction() as state:
        if state.get('demo_seed',{}).get('version')==DEMO_VERSION:
            return 0
        # Retain the complete previous private state before any additive changes.
        state['before_demo_stock_v1']=deepcopy(state)
        if state['config'] is None:
            state['config']=defaults(load_catalog())
        cfg=state['config']
        created=0
        for material in cfg['materials']:
            if not material.get('active',True) or material.get('family') not in ('sunscreen','blackout','traslucida'):
                continue
            if not material.get('colors'):
                material['colors']=[{'id':'demo-blanco','name':'Blanco (DEMO)','hex':'#f6f4ee'},
                                    {'id':'demo-gris','name':'Gris (DEMO)','hex':'#909090'}]
            for color in material['colors']:
                width=material.get('roll_width_cm',280)
                samples=[('rollo',width,50),('rollo',width,50),
                         ('retazo',min(width,160),2.3),('retazo',min(width,220),2.8),
                         ('retazo',min(width,100),1.2)]
                for i,(kind,w,length) in enumerate(samples,1):
                    ident=f'DEMO-{material["id"]}-{color["id"]}-{i}'
                    if ident in state['lots']:
                        continue
                    lot=dict(id=ident,kind=kind,material_id=material['id'],color_id=color['id'],
                        width_cm=w,length_m=length,location='PRUEBA · STOCK FICTICIO',
                        origin='Datos ficticios para probar BARÓN. No representan existencias reales.',
                        minimum_m=5 if kind=='rollo' else 0,status='disponible',revision=1,demo=True)
                    state['lots'][ident]=lot
                    state['movements'].append(dict(at=now(),actor='sistema-demo',event='entrada ficticia',
                        lot_id=ident,length_m=length))
                    created+=1
        # Preserve older workflow data while presenting only the two requested states.
        for order in state['orders'].values():
            old=order['status']
            if old not in ('presupuesto','aprobado'):
                order['legacy_status']=old
                order['status']='presupuesto' if old=='cancelado' else 'aprobado'
                order['revision']+=1
                order['updated_at']=now()
                audit(state,'simplificar estado anterior', 'sistema-demo',order_id=order['id'],before=old,after=order['status'])
        state['demo_seed']=dict(version=DEMO_VERSION,at=now(),created_lots=created)
        audit(state,'cargar stock ficticio','sistema-demo',created_lots=created)
    print(f'Stock DEMO inicializado: {created} lotes ficticios. Pedidos y existencias previas conservados.',flush=True)
    return created
