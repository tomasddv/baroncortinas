"""Roller domain: explicit Excel rules, group inheritance, snapshots and stock."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import math
import re
import uuid

ATTRIBUTES = {'material_id', 'color_id', 'side', 'drop', 'tube', 'room'}
COLUMNS = {'room': 'Ambiente', 'quantity': 'Cant.', 'detail': 'Detalle', 'width_cm': 'Ancho',
           'height_cm': 'Alto', 'material': 'Tela', 'color': 'Color', 'unit_price': 'Precio', 'subtotal': 'Subtotal'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def num(value, label, low=0, high=1e9):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + ': ingresá un número válido')
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f'{label}: valor permitido entre {low} y {high}')
    return n


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def text(value, limit=200):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Texto inválido o demasiado largo')
    return value.strip()


def defaults(catalog):
    # BARÓN Hoja1 B7:B16, B19:D22. 42 uses supplier label 41.
    materials = []
    for ident, name, family, price in [('excel-screen', 'Screen BARÓN', 'sunscreen', 23650),
            ('excel-blackout', 'Blackout BARÓN', 'blackout', 23650),
            ('excel-traslucida', 'Traslúcida BARÓN', 'traslucida', 16000)]:
        # Colours are inherited from existing inventory/catalogue, not invented.
        colors = next((deepcopy(m['colors']) for m in catalog['materials'] if m['family'] == family), [])
        materials.append(dict(id=ident, name=name, family=family, price=price, price_unit='m2',
                              roll_width_cm=280, colors=colors, active=True, source='BARÓN Hoja1 B7:B9'))
    # Preserve all original materials with their own rates and widths.
    materials.extend(deepcopy(catalog['materials']))
    return {'materials': materials, 'tubes': {
        '32': {'extra_cm': 20, 'price_m': 37400, 'system_price': 36000},
        '42': {'extra_cm': 30, 'price_m': 41800, 'system_price': 42000},
        '45': {'extra_cm': 35, 'price_m': 49280, 'system_price': 42000},
        '58': {'extra_cm': 40, 'price_m': 62900, 'system_price': 42000}},
        'guides_price_m': 25000, 'min_billable_m2': 0, 'min_linear_m': 0,
        'width_reduction_cm': 0, 'stock_min_m': 5, 'markup_pct': 0, 'tax_pct': 0,
        'payments': {'Transferencia': 0, 'Efectivo': 0, 'Tarjeta': 0},
        'extras': {'zocalo': {}, 'chain': {}, 'mount': {}},
        'brand': deepcopy(catalog['settings']), 'confirmed': False,
        'note': 'Base BARÓN sin recargos. Validar mínimo, IVA, pagos y equivalencia 41/42 antes de emitir.'}


def validate_config(cfg):
    if not isinstance(cfg, dict) or set(cfg.get('tubes', {})) != {'32','42','45','58'}:
        raise ValueError('Configuración de caños incompleta')
    for tube in cfg['tubes'].values():
        for k in ('extra_cm', 'price_m', 'system_price'):
            tube[k] = num(tube[k], k, 0, 1e8)
    for k in ('guides_price_m','min_billable_m2','min_linear_m','width_reduction_cm','stock_min_m','markup_pct','tax_pct'):
        cfg[k] = num(cfg[k], k, 0, 1000 if k.endswith('pct') else 1e8)
    if cfg['width_reduction_cm'] > 20:
        raise ValueError('Reducción de ancho máxima 20 cm')
    if not isinstance(cfg.get('payments'), dict) or set(cfg['payments']) != {'Transferencia','Efectivo','Tarjeta'}:
        raise ValueError('Configurá los tres medios de pago')
    cfg['payments'] = {text(k,40): num(v,k,-100,1000) for k,v in cfg['payments'].items()}
    ids = set()
    for m in cfg['materials']:
        if m['id'] in ids:
            raise ValueError('Identificador de tela duplicado')
        ids.add(m['id'])
        text(m['id'],100)
        m['name']=text(m['name'],100)
        if not m['name']:
            raise ValueError('Ingresá el nombre de cada tela')
        if m.get('family') not in ('blackout','sunscreen','traslucida','tela'):
            raise ValueError('Tipo de tela inválido')
        m['price'] = num(m['price'],'Precio tela')
        m['roll_width_cm'] = num(m['roll_width_cm'],'Ancho rollo',20,600)
        if m['price_unit'] not in ('m2','metro_lineal'):
            raise ValueError('Unidad de tela inválida')
        seen = set()
        for c in m['colors']:
            text(c['id'],100)
            c['name']=text(c['name'],100)
            if not c['name']:
                raise ValueError('Ingresá el nombre de cada color')
            if c.get('hex') and not re.fullmatch(r'#[a-fA-F0-9]{6}',c['hex']):
                raise ValueError('Muestra de color inválida')
            if c['id'] in seen:
                raise ValueError('Color duplicado')
            seen.add(c['id'])
            if 'price_override' in c:
                c['price_override'] = num(c['price_override'],'Precio por color')
    for field in ('zocalo','chain','mount'):
        for name, rate in cfg['extras'][field].items():
            text(name,100); num(rate, 'Adicional')
    if not isinstance(cfg.get('brand'),dict):
        raise ValueError('Datos del comercio inválidos')
    cfg['confirmed'] = cfg.get('confirmed') is True
    return cfg


def resolve_groups(groups):
    if not isinstance(groups, list) or not 1 <= len(groups) <= 50:
        raise ValueError('Agregá entre 1 y 50 grupos')
    result = []
    for gi, group in enumerate(groups):
        qty = num(group.get('quantity',1),'Cantidad',1,100)
        if int(qty) != qty:
            raise ValueError('Cantidad entera requerida')
        fields = group.get('attributes',[]) if group.get('customize') is True else []
        if not isinstance(fields,list) or set(fields) - ATTRIBUTES:
            raise ValueError('Atributos de personalización inválidos')
        base = group.get('base')
        if not isinstance(base,dict):
            raise ValueError('Configuración base inválida')
        overrides = group.get('units', [])
        if not isinstance(overrides,list):
            raise ValueError('Variantes inválidas')
        for ui in range(int(qty)):
            unit = deepcopy(base)
            override = overrides[ui] if ui < len(overrides) else {}
            if not isinstance(override,dict):
                raise ValueError('Variante inválida')
            # Unselected fields NEVER influence inherited values.
            unit.update({k: override[k] for k in fields if k in override})
            result.append(dict(unit, group=gi, index=ui))
    if len(result) > 300:
        raise ValueError('Máximo 300 cortinas por pedido')
    return result


def quote_order(body, cfg):
    from datetime import date
    for key in ('date','valid_until'):
        value=body.get(key,'')
        if value:
            try:
                date.fromisoformat(value)
            except (ValueError,TypeError):
                raise ValueError('Fecha inválida: '+key)
    if body.get('date') and body.get('valid_until') and body['valid_until'] < body['date']:
        raise ValueError('La vigencia no puede ser anterior a la fecha del presupuesto')
    groups = deepcopy(body.get('groups'))
    units, bom = [], []
    for i, raw in enumerate(resolve_groups(groups)):
        w = num(raw.get('width_cm'),'Ancho',30,600)
        h = num(raw.get('height_cm'),'Alto',30,600)
        tube = str(raw.get('tube','32'))
        if tube not in cfg['tubes']:
            raise ValueError('Caño inválido')
        rule = cfg['tubes'][tube]
        material = next((m for m in cfg['materials'] if m['id']==raw.get('material_id') and m.get('active',True)),None)
        if not material:
            raise ValueError('Tela no disponible')
        if material.get('family') not in ('sunscreen','blackout','traslucida'):
            raise ValueError('Este cotizador admite Roller; conservá las telas tradicionales para su módulo específico')
        color = next((c for c in material['colors'] if c['id']==raw.get('color_id')),None)
        if not color:
            raise ValueError('Color no válido para la tela elegida')
        side, drop = raw.get('side','Derecha'), raw.get('drop','Detrás')
        if side not in ('Derecha','Izquierda') or drop not in ('Detrás','Delante'):
            raise ValueError('Mando o caída inválidos')
        cut_w, cut_h = w-cfg['width_reduction_cm'], h+rule['extra_cm']
        if cut_w <= 0 or cut_w > material['roll_width_cm']:
            raise ValueError('El ancho de corte supera el ancho nominal de la tela')
        physical_area = cut_w*cut_h/10000
        billed = max(cfg['min_billable_m2'],physical_area) if material['price_unit']=='m2' else max(cfg['min_linear_m'],cut_h/100)
        rate = color.get('price_override',material['price'])
        def line(name, quantity, unit, price, **extra):
            return dict(id=f'{i}-{len(bom)}', curtain=i+1, name=name, quantity=quantity, unit=unit,
                        unit_cost=price, subtotal=money(quantity*price), **extra)
        lines = [line(material['name']+' / '+color['name'], physical_area,'m²',rate,
                      fabric=True, material_id=material['id'], color_id=color['id'],
                      cut_width_cm=cut_w, cut_height_cm=cut_h, billable_quantity=billed,
                      price_unit=material['price_unit'])]
        # Physical usage and billable usage are explicitly separate.
        lines[0]['subtotal'] = money(billed*rate)
        bom.extend(lines)
        for name, q, unit, price in [('Caño '+tube,w/100,'m',rule['price_m']),
                                     ('Sistema '+('41 (42)' if tube!='32' else '32'),1,'unidad',rule['system_price'])]:
            bom.append(line(name,q,unit,price))
        if raw.get('guides') is True:
            bom.append(line('Guías (criterio BARÓN: alto × tarifa)',h/100,'m',cfg['guides_price_m']))
        options = {}
        for field, label in [('zocalo','Zócalo'),('chain','Cadena'),('mount','Soportes')]:
            name = text(raw.get(field,''),100)
            options[field] = name
            if name:
                if name not in cfg['extras'][field]:
                    raise ValueError(label+': configurá el precio del adicional')
                bom.append(line(label+' '+name,w/100 if field=='zocalo' else 1,'m' if field=='zocalo' else 'unidad',float(cfg['extras'][field][name])))
        cost = money(sum(l['subtotal'] for l in bom if l['curtain']==i+1))
        price = money(cost*(1+cfg['markup_pct']/100)*(1+cfg['tax_pct']/100))
        units.append(dict(group=raw['group'], index=raw['index'], room=text(raw.get('room',''),100),
            detail='Roller '+material['name']+' · caño '+tube+' · '+side+' · '+drop,
            width_cm=w,height_cm=h,material=material['name'], material_id=material['id'],color=color['name'],
            color_id=color['id'],tube=tube,side=side,drop=drop,**options,guides=raw.get('guides') is True,
            unit_price=price,quantity=1,subtotal=price,cut_width_cm=cut_w,cut_height_cm=cut_h))
    discount = num(body.get('discount_pct',0),'Descuento',0,100)
    subtotal = money(sum(u['subtotal'] for u in units))
    total = money(subtotal*(1-discount/100))
    return dict(groups=groups,units=units,bom=bom,subtotal=subtotal,total=total,discount_pct=discount,
        payments={k:money(total*(1+v/100)) for k,v in cfg['payments'].items()},
        customer=text(body.get('customer',''),150),city=text(body.get('city',''),150),
        date=text(body.get('date',''),10),valid_until=text(body.get('valid_until',''),10),
        notes=text(body.get('notes',''),2000),price_snapshot=deepcopy(cfg))


def commercial_rows(order):
    rows = {}
    for u in order['units']:
        key = tuple(str(u.get(k,'')) for k in ('room','detail','width_cm','height_cm','material','color','unit_price','zocalo','chain','mount','guides'))
        if key not in rows:
            rows[key] = {k:u[k] for k in COLUMNS}
            rows[key]['quantity'] = 0
            rows[key]['subtotal'] = 0
        rows[key]['quantity'] += 1
        rows[key]['subtotal'] = money(rows[key]['subtotal']+u['unit_price'])
    return list(rows.values())


def audit(state, action, actor, **details):
    state['audit'].append(dict(at=now(),action=action,actor=actor,**deepcopy(details)))


def available(state, lot):
    reserved = sum(r['length_m'] for r in state['reservations'] if r['lot_id']==lot['id'] and r['status']=='reservado')
    return round(lot['length_m']-reserved,6)


def matches(state, line):
    return sorted([l for l in state['lots'].values() if l['kind']=='retazo' and l['status']=='disponible'
        and l['material_id']==line['material_id'] and l['color_id']==line['color_id']
        and l['width_cm']>=line['cut_width_cm'] and available(state,l)*100>=line['cut_height_cm']],
        key=lambda l:l['width_cm']*l['length_m']*100-line['cut_width_cm']*line['cut_height_cm'])


def stock_warnings(state, order, cfg):
    simulated = deepcopy(state)
    warnings = []
    try:
        reserve(simulated,dict(order,id='preview'), 'simulación')
    except ValueError as exc:
        warnings.append(str(exc))
    for lot in state['lots'].values():
        if lot['kind']=='rollo' and available(state,lot)<=lot.get('minimum_m',cfg['stock_min_m']):
            warnings.append('Poco stock: '+lot['id']+' ('+str(available(state,lot))+' m libres)')
    return warnings


def reserve(state, order, actor):
    for line in order['bom']:
        if not line.get('fabric'):
            continue
        candidates = [l for l in state['lots'].values() if l['kind']=='rollo' and l['status']=='disponible'
            and l['material_id']==line['material_id'] and l['color_id']==line['color_id']
            and l['width_cm']>=line['cut_width_cm'] and available(state,l)*100+1e-6>=line['cut_height_cm']]
        if line.get('remnant_id'):
            candidates = [l for l in matches(state,line) if l['id']==line['remnant_id']]
        if not candidates:
            raise ValueError('Stock insuficiente para '+line['name']+'; cargá existencias o elegí un retazo compatible en Despiece')
        lot = min(candidates,key=lambda l:available(state,l))
        length = line['cut_height_cm']/100
        state['reservations'].append(dict(id=uuid.uuid4().hex,order_id=order['id'],line_id=line['id'],
            lot_id=lot['id'],length_m=length,status='reservado',at=now()))
        if lot['kind']=='retazo':
            lot['status']='reservado'
        lot['revision']=lot.get('revision',1)+1
        state['movements'].append(dict(at=now(),actor=actor,lot_id=lot['id'],order_id=order['id'],event='reserva',length_m=length))


def transition(state, order, target, actor):
    current = order['status']
    if target not in ('presupuesto','aprobado'):
        raise ValueError('Elegí Presupuesto o Aprobado')
    if current == target:
        return
    allowed = {'presupuesto':{'aprobado'},'aprobado':{'presupuesto'}}
    if target not in allowed.get(current,set()):
        raise ValueError('Transición de estado no permitida')
    if target=='presupuesto' and any(r['order_id']==order['id'] and r['status']=='consumido' for r in state['reservations']):
        raise ValueError('Este pedido ya tiene consumo. Duplicalo para un nuevo trabajo; no se vuelve a descontar.')
    if target=='aprobado':
        reserve(state,order,actor)
    for r in state['reservations']:
        if r['order_id']!=order['id'] or r['status']!='reservado':
            continue
        lot = state['lots'][r['lot_id']]
        if target=='presupuesto':
            r['status']='liberado'
            lot['status']='disponible'
            event='liberación'
        else:
            continue
        lot['revision']=lot.get('revision',1)+1
        state['movements'].append(dict(at=now(),actor=actor,lot_id=lot['id'],order_id=order['id'],event=event,length_m=r['length_m']))
    order['status']=target
    order['revision']+=1
    order['updated_at']=now()
    audit(state,'estado',actor,order_id=order['id'],before=current,after=target)
