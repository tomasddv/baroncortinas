"""Shared catalogue and physical inventory for hardware and custom products."""
from copy import deepcopy
import os
import uuid
from quoting import num, text, money, now, audit

CATEGORIES=['caño','cadena','sistema','zócalo','guía','soporte','accesorio','otro']
UNITS=['m','m²','unidad','par']
QUANTITY_MODES=['fijo','ancho_m','alto_m','area_m2','perimetro_m']
PRICE_MODES=['roller','materiales','m2','metro_ancho','fijo']


def default_products():
    return [dict(id='roller',name='Roller',calculation='roller',price_value=0,
        requires_fabric=True,extra_height_cm=0,fabric_width_multiplier=1,recipes=[],active=True)]


def ensure_inventory(state,cfg):
    state.setdefault('component_lots',{})
    cfg.setdefault('products',default_products())
    for m in cfg['materials']:m.setdefault('deleted',False)
    for p in cfg['products']:p.setdefault('deleted',False)
    if 'stock_components' not in cfg:
        entries=[]
        for tube,rule in cfg['tubes'].items():
            entries.append(dict(id='tubo-'+tube,name='Caño '+tube,category='caño',unit='m',unit_cost=rule['price_m'],pricing_key='tube:'+tube))
        for tube in ['32','42']:
            entries.append(dict(id='sistema-'+tube,name='Sistema '+tube,category='sistema',unit='unidad',unit_cost=cfg['tubes'][tube]['system_price'],pricing_key='system:'+tube))
        entries.append(dict(id='guias',name='Guías',category='guía',unit='m',unit_cost=cfg['guides_price_m'],pricing_key='guides'))
        for kind,category,unit in [('chain','cadena','unidad'),('zocalo','zócalo','m'),('mount','soporte','unidad')]:
            for name,price in cfg['extras'][kind].items():
                entries.append(dict(id='ins-'+uuid.uuid4().hex[:12],name=name,category=category,unit=unit,unit_cost=price,pricing_key=kind+':'+name))
        entries.extend([dict(id='cadena-plastica',name='Cadena plástica',category='cadena',unit='m',unit_cost=0),
                        dict(id='soportes',name='Soportes',category='soporte',unit='par',unit_cost=0),
                        dict(id='zocalo',name='Zócalo',category='zócalo',unit='m',unit_cost=0)])
        for item in entries:item.update(active=True,minimum_qty=5,track_stock=False)
        cfg['stock_components']=entries
    linked={c.get('pricing_key') for c in cfg['stock_components']}
    for kind,category,unit in [('chain','cadena','unidad'),('zocalo','zócalo','m'),('mount','soporte','unidad')]:
        for name,price in cfg['extras'][kind].items():
            key=kind+':'+name
            if key not in linked:
                cfg['stock_components'].append(dict(id='ins-'+uuid.uuid4().hex[:12],name=name,category=category,unit=unit,unit_cost=price,pricing_key=key,active=True,minimum_qty=0,track_stock=False))
                linked.add(key)
    for c in cfg['stock_components']:c.setdefault('deleted',False)
    if os.environ.get('BARON_DEMO_STOCK')=='1' and not state.get('hardware_demo_seeded'):
        for item in cfg['stock_components']:
            ident='DEMO-INS-'+item['id']
            if ident not in state['component_lots']:
                qty=100 if item['unit']=='m' else 50
                state['component_lots'][ident]=dict(id=ident,component_id=item['id'],quantity=qty,
                    unit=item['unit'],location='PRUEBA · STOCK FICTICIO',origin='Carga ficticia de insumos',revision=1,demo=True)
                state['movements'].append(dict(at=now(),actor='sistema-demo',event='entrada ficticia',lot_id=ident,quantity=qty,unit=item['unit']))
            item['track_stock']=True
        state['hardware_demo_seeded']=now()
        audit(state,'cargar insumos ficticios','sistema-demo',count=len(cfg['stock_components']))


def validate_inventory_catalogue(cfg):
    cfg.setdefault('products',default_products())
    cfg.setdefault('stock_components',[])
    component_ids=set()
    for c in cfg['stock_components']:
        if c['id'] in component_ids:raise ValueError('Código de insumo repetido')
        component_ids.add(c['id']);text(c['id'],100)
        c['name']=text(c['name'],100)
        if not c['name']:raise ValueError('Ingresá el nombre del insumo')
        if c['category'] not in CATEGORIES or c['unit'] not in UNITS:raise ValueError('Categoría o unidad de insumo inválida')
        c['unit_cost']=num(c['unit_cost'],'Costo del insumo')
        c['minimum_qty']=num(c.get('minimum_qty',0),'Mínimo de stock')
        if c.get('deleted'):c['active']=False
    products=set()
    for p in cfg['products']:
        if p['id'] in products:raise ValueError('Código de producto repetido')
        products.add(p['id']);text(p['id'],100)
        p['name']=text(p['name'],100)
        if not p['name']:raise ValueError('Ingresá el nombre del producto')
        if p['calculation'] not in PRICE_MODES or (p['calculation']=='roller' and p['id']!='roller'):raise ValueError('Regla de producto inválida')
        p['price_value']=num(p.get('price_value',0),'Precio base del producto')
        p['extra_height_cm']=num(p.get('extra_height_cm',0),'Extra de alto',0,300)
        p['fabric_width_multiplier']=num(p.get('fabric_width_multiplier',1),'Multiplicador de tela',0.01,10)
        for r in p.get('recipes',[]):
            if r['component_id'] not in component_ids or r['mode'] not in QUANTITY_MODES:raise ValueError('Receta con insumo o regla inválidos')
            r['factor']=num(r.get('factor',1),'Factor de insumo',0,10000)
        if p.get('deleted'):p['active']=False
    if 'roller' not in products:raise ValueError('Conservá el modelo Roller; podés desactivarlo si no lo usás')


def reconcile_prices(previous,cfg):
    old={c['id']:c for c in previous.get('stock_components',[])}
    for c in cfg.get('stock_components',[]):
        key=c.get('pricing_key','')
        if not key:continue
        before=old.get(c['id'],{})
        changed=c['unit_cost']!=before.get('unit_cost',c['unit_cost'])
        if key.startswith('tube:'):
            target=cfg['tubes'][key.split(':',1)[1]];field='price_m'
        elif key.startswith('system:'):
            size=key.split(':',1)[1];target=cfg['tubes'][size];field='system_price'
        elif key=='guides':target=cfg;field='guides_price_m'
        elif ':' in key:
            kind,name=key.split(':',1)
            if kind not in cfg['extras'] or name not in cfg['extras'][kind]:continue
            target=cfg['extras'][kind];field=name
        else:continue
        if changed:target[field]=c['unit_cost']
        else:c['unit_cost']=target[field]


def component_available(state,lot):
    reserved=sum(r.get('quantity',0) for r in state['reservations'] if r.get('kind')=='insumo' and r['lot_id']==lot['id'] and r['status']=='reservado')
    return round(lot['quantity']-reserved,6)


def reserve_component(state,line,order,actor):
    cfg=state['config'];item=next((c for c in cfg.get('stock_components',[]) if c['id']==line.get('component_id')),None)
    if not item or not item.get('track_stock'):return
    if not item.get('active',True) or item.get('deleted'):raise ValueError('Insumo no disponible: '+item['name'])
    need=num(line['quantity'],'Cantidad de insumo')
    lots=[l for l in state.get('component_lots',{}).values() if l['component_id']==item['id'] and l['unit']==line['unit']]
    if sum(component_available(state,l) for l in lots)+1e-6<need:raise ValueError('Stock insuficiente de '+item['name'])
    for lot in lots:
        qty=min(need,component_available(state,lot))
        if qty<=0:continue
        state['reservations'].append(dict(id=uuid.uuid4().hex,kind='insumo',order_id=order['id'],line_id=line['id'],
            lot_id=lot['id'],quantity=qty,unit=lot['unit'],status='reservado',at=now()))
        lot['revision']+=1
        state['movements'].append(dict(at=now(),actor=actor,event='reserva',lot_id=lot['id'],order_id=order['id'],quantity=qty,unit=lot['unit']))
        need=round(need-qty,6)
        if need<=0:break


def generic_unit(raw,product,cfg,index):
    w=num(raw.get('width_cm'),'Ancho',1,600);h=num(raw.get('height_cm'),'Alto',1,600)
    lines=[];material=None;color=None;cut_w=w;cut_h=h
    def add(name,quantity,unit,price,**kwargs):
        lines.append(dict(id=f'{index}-custom-{len(lines)}',curtain=index+1,name=name,quantity=quantity,unit=unit,unit_cost=price,subtotal=money(quantity*price),**kwargs))
    if product.get('requires_fabric',True):
        material=next((m for m in cfg['materials'] if m['id']==raw.get('material_id') and m.get('active',True) and not m.get('deleted')),None)
        if not material:raise ValueError('Elegí una tela activa para '+product['name'])
        color=next((c for c in material['colors'] if c['id']==raw.get('color_id') and not c.get('deleted')),None)
        if not color:raise ValueError('Elegí un color válido')
        cut_w=w*product.get('fabric_width_multiplier',1);cut_h=h+product.get('extra_height_cm',0)
        if cut_w>material['roll_width_cm']:raise ValueError('El ancho de corte del producto supera el ancho de tela; revisá su regla')
        physical=cut_w*cut_h/10000
        billed=max(cfg['min_billable_m2'],physical) if material['price_unit']=='m2' else max(cfg['min_linear_m'],cut_h/100)
        rate=color.get('price_override',material['price'])
        add(material['name']+' / '+color['name'],physical,'m²',rate,fabric=True,material_id=material['id'],color_id=color['id'],cut_width_cm=cut_w,cut_height_cm=cut_h,billable_quantity=billed,price_unit=material['price_unit'])
        lines[-1]['subtotal']=money(billed*rate)
    components={c['id']:c for c in cfg.get('stock_components',[])}
    for recipe in product.get('recipes',[]):
        c=components.get(recipe['component_id'])
        if not c or not c.get('active',True) or c.get('deleted'):raise ValueError('Hay un insumo inactivo en la receta de '+product['name'])
        base={'fijo':1,'ancho_m':w/100,'alto_m':h/100,'area_m2':w*h/10000,'perimetro_m':2*(w+h)/100}[recipe['mode']]
        add(c['name'],round(base*recipe.get('factor',1),6),c['unit'],c['unit_cost'],component_id=c['id'])
    mode=product['calculation'];rate=product.get('price_value',0)
    base=sum(l['subtotal'] for l in lines) if mode=='materiales' else rate*({'m2':w*h/10000,'metro_ancho':w/100,'fijo':1}[mode])
    price=money(base*(1+cfg['markup_pct']/100)*(1+cfg['tax_pct']/100))
    if price<=0:raise ValueError('Configurá un precio o receta para '+product['name'])
    unit=dict(group=raw['group'],index=raw['index'],product_id=product['id'],room=text(raw.get('room',''),100),detail=product['name'],width_cm=w,height_cm=h,
        material=material['name'] if material else '',material_id=material['id'] if material else '',color=color['name'] if color else '',color_id=color['id'] if color else '',
        unit_price=price,quantity=1,subtotal=price,cut_width_cm=cut_w,cut_height_cm=cut_h)
    return unit,lines
