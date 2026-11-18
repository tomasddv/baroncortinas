"""Authenticated internal workflow, using the existing Flask application."""
from copy import deepcopy
from io import BytesIO
import json
import uuid
from flask import Blueprint, abort, jsonify, render_template, request, send_file, session
from private_store import transaction
from storage import load_catalog
from quoting import (COLUMNS, defaults, validate_config, quote_order, commercial_rows,
    num, text, money, now, audit, available, matches, stock_warnings, transition)

bp = Blueprint('internal',__name__,url_prefix='/admin/interno')


def actor():
    return session.get('user','dueño')


def owner():
    if session.get('role','owner') != 'owner':
        abort(403)


def config(state):
    if state['config'] is None:
        state['config'] = defaults(load_catalog())
    return state['config']


def body():
    value = request.get_json(silent=True)
    if not isinstance(value,dict):
        raise ValueError('Datos JSON inválidos')
    return value


def order_in(state, ident, revision=None):
    order = state['orders'].get(ident)
    if not order:
        abort(404)
    if revision is not None and revision != order['revision']:
        abort(409, description='Otro usuario modificó el pedido. Volvé a abrirlo antes de guardar.')
    return order


@bp.errorhandler(ValueError)
@bp.errorhandler(KeyError)
@bp.errorhandler(TypeError)
def invalid(exc):
    return jsonify(error=str(exc)),400


@bp.get('')
@bp.get('/')
def workspace():
    return render_template('internal.html',is_owner=session.get('role','owner')=='owner')


@bp.get('/api/state')
def state_api():
    with transaction() as state:
        cfg = config(state)
        orders = [{k:o.get(k) for k in ('id','number','customer','city','date','status','total','revision','updated_at')} for o in state['orders'].values()]
        lots = [dict(l,available_m=available(state,l)) for l in state['lots'].values()]
        return jsonify(config=cfg,orders=orders,lots=lots,movements=state['movements'][-200:],
                       columns=COLUMNS,preferences=state['preferences'].get(actor(),list(COLUMNS)))


@bp.post('/api/preview')
def preview():
    data = body()
    with transaction() as state:
        cfg = config(state)
        old=order_in(state,data['id']) if data.get('id') else None
        same=old and data.get('groups')==old['groups'] and float(data.get('discount_pct',0))==old['discount_pct']
        order = quote_order(data,old['price_snapshot'] if same and not data.get('reprice') else cfg)
        return jsonify(order=order,rows=commercial_rows(order),warnings=stock_warnings(state,order,cfg))


@bp.post('/api/orders')
def save_order():
    data = body()
    with transaction() as state:
        cfg = config(state)
        old = order_in(state,data['id'],data.get('revision')) if data.get('id') else None
        if old and 'revision' not in data:
            abort(409)
        if old and old['status']!='presupuesto':
            raise ValueError('Volvé a presupuesto para editar. Los pedidos con consumo se duplican para un nuevo trabajo.')
        # Unchanged group saves retain quoted prices even after catalogue updates.
        same = old and data.get('groups')==old['groups'] and float(data.get('discount_pct',0))==old['discount_pct']
        if same and not data.get('reprice'):
            order = deepcopy(old)
            for key,limit in [('customer',150),('city',150),('date',10),('valid_until',10),('notes',2000)]:
                order[key]=text(data.get(key,''),limit)
        else:
            order = quote_order(data,cfg)
        if not order['customer']:
            raise ValueError('Ingresá el cliente')
        if not old:
            state['sequence']+=1
        ident = old['id'] if old else uuid.uuid4().hex
        order.update(id=ident,number=old['number'] if old else f'BAR-{state["sequence"]:06d}',
                     status='presupuesto',revision=old['revision']+1 if old else 1,
                     created_at=old['created_at'] if old else now(),updated_at=now())
        state['orders'][ident]=order
        audit(state,'guardar pedido',actor(),order_id=ident,before=old,after=order)
        return jsonify(order=order,rows=commercial_rows(order),warnings=stock_warnings(state,order,cfg))


@bp.get('/api/orders/<ident>')
def get_order(ident):
    with transaction() as state:
        order=order_in(state,ident)
        return jsonify(order=order,rows=commercial_rows(order),warnings=stock_warnings(state,order,config(state)),
                       audit=[a for a in state['audit'] if a.get('order_id')==ident],
                       reservations=[r for r in state['reservations'] if r['order_id']==ident])


@bp.post('/api/orders/<ident>/duplicate')
def duplicate(ident):
    with transaction() as state:
        old=order_in(state,ident)
        order=deepcopy(old)
        state['sequence']+=1
        new_id=uuid.uuid4().hex
        order.update(id=new_id,number=f'BAR-{state["sequence"]:06d}',status='presupuesto',revision=1,created_at=now(),updated_at=now())
        # A duplicate is a new job: no stock allocations or inherited remnant selection.
        for line in order['bom']:
            line.pop('remnant_id',None)
        state['orders'][new_id]=order
        audit(state,'duplicar',actor(),order_id=new_id,source=ident)
        return jsonify(order=order,rows=commercial_rows(order),warnings=[])


@bp.post('/api/orders/<ident>/status')
def status(ident):
    data=body()
    if data.get('confirm') is not True:
        raise ValueError('Confirmá el cambio de estado y sus movimientos de stock')
    with transaction() as state:
        order=order_in(state,ident,data.get('revision',-1))
        transition(state,order,data.get('status'),actor())
        return jsonify(order=order,rows=commercial_rows(order),warnings=[])


@bp.post('/api/orders/<ident>/bom')
def save_bom(ident):
    data=body()
    with transaction() as state:
        order=order_in(state,ident,data.get('revision',-1))
        if order['status']!='presupuesto':
            raise ValueError('Editá el despiece antes de aprobar o liberar reservas')
        lines=data.get('lines')
        if not isinstance(lines,list) or not 1<=len(lines)<=3000:
            raise ValueError('Despiece inválido')
        originals={l['id']:l for l in order['bom']}
        clean=[]
        for index,line in enumerate(lines):
            fabric=line.get('fabric') is True
            previous=originals.get(line.get('id'),{})
            if fabric != bool(previous.get('fabric')):
                raise ValueError('Las líneas físicas de tela se conservan; modificá sus medidas o el grupo')
            item=dict(id=str(index)+'-'+uuid.uuid4().hex[:8],name=text(line['name'],200),
                      curtain=int(num(line['curtain'],'Cortina',1,len(order['units']))),
                      quantity=num(line['quantity'],'Cantidad'),unit=text(line['unit'],20),
                      unit_cost=num(line['unit_cost'],'Costo'))
            if fabric:
                item.update(fabric=True,material_id=previous['material_id'],color_id=previous['color_id'],
                    cut_width_cm=num(line['cut_width_cm'],'Ancho de corte',1,600),
                    cut_height_cm=num(line['cut_height_cm'],'Alto de corte',1,1000),
                    billable_quantity=num(line.get('billable_quantity',previous['billable_quantity']),'Cantidad facturable'),price_unit=previous['price_unit'])
                item['quantity']=item['cut_width_cm']*item['cut_height_cm']/10000
                if line.get('remnant_id'):
                    if line['remnant_id'] not in [l['id'] for l in matches(state,item)]:
                        raise ValueError('Retazo incompatible o ya reservado')
                    item['remnant_id']=line['remnant_id']
            item['subtotal']=money(item.get('billable_quantity',item['quantity'])*item['unit_cost'])
            clean.append(item)
        # Exactly one fabric allocation per curtain; cannot bypass stock by deleting it.
        if sorted(l['curtain'] for l in clean if l.get('fabric')) != list(range(1,len(order['units'])+1)):
            raise ValueError('Conservá una línea física de tela por cortina')
        audit(state,'editar despiece',actor(),order_id=ident,before=order['bom'],after=clean)
        order['bom']=clean
        order['revision']+=1
        order['updated_at']=now()
        return jsonify(order=order,rows=commercial_rows(order),warnings=stock_warnings(state,order,config(state)))


@bp.get('/api/orders/<ident>/remnants')
def remnant_search(ident):
    with transaction() as state:
        order=order_in(state,ident)
        return jsonify({l['id']:matches(state,l) for l in order['bom'] if l.get('fabric')})


@bp.post('/api/lots')
def create_lot():
    data=body()
    with transaction() as state:
        cfg=config(state)
        m=next((m for m in cfg['materials'] if m['id']==data.get('material_id')),None)
        if not m or data.get('color_id') not in [c['id'] for c in m['colors']]:
            raise ValueError('Tela o color inválidos')
        kind=data.get('kind')
        if kind not in ('rollo','retazo'):
            raise ValueError('Tipo de existencia inválido')
        lot=dict(id=uuid.uuid4().hex[:12],kind=kind,material_id=m['id'],color_id=data['color_id'],
            width_cm=num(data.get('width_cm',280),'Ancho',1,600),
            length_m=num(data.get('length_m',50),'Largo',0.001,10000),
            location=text(data.get('location',''),150),origin=text(data.get('origin',''),200),
            minimum_m=num(data.get('minimum_m',cfg['stock_min_m']),'Mínimo',0,10000),status='disponible',revision=1)
        state['lots'][lot['id']]=lot
        state['movements'].append(dict(at=now(),actor=actor(),event='entrada',lot_id=lot['id'],length_m=lot['length_m']))
        audit(state,'entrada',actor(),lot=lot)
        return jsonify(lot=lot)


@bp.post('/api/lots/<ident>')
def edit_lot(ident):
    data=body()
    with transaction() as state:
        lot=state['lots'].get(ident)
        if not lot:
            abort(404)
        if data.get('revision') != lot.get('revision',1):
            abort(409,description='El lote cambió. Recargá antes de ajustar.')
        if any(r['lot_id']==ident and r['status']=='reservado' for r in state['reservations']):
            raise ValueError('Liberá las reservas antes de ajustar este lote')
        before=deepcopy(lot)
        reason=text(data.get('reason',''),300)
        if not reason:
            raise ValueError('Indicá el motivo del ajuste')
        lot['length_m']=num(data['length_m'],'Largo',0,10000)
        lot['width_cm']=num(data['width_cm'],'Ancho',1,600)
        lot['location']=text(data.get('location',''),150)
        lot['minimum_m']=num(data.get('minimum_m',lot['minimum_m']),'Mínimo',0,10000)
        lot['status']='disponible' if lot['length_m'] else 'consumido'
        lot['revision']=lot.get('revision',1)+1
        state['movements'].append(dict(at=now(),actor=actor(),event='ajuste',lot_id=ident,length_m=lot['length_m']-before['length_m'],reason=reason))
        audit(state,'ajuste',actor(),before=before,after=lot,reason=reason)
        return jsonify(lot=lot)


@bp.post('/api/config')
def save_config():
    owner()
    data=body()
    cfg=validate_config(data.get('config'))
    with transaction() as state:
        # Compare the exact previous config to avoid silently overwriting another owner edit.
        if data.get('previous') != config(state):
            abort(409,description='La configuración cambió. Recargá antes de guardar.')
        audit(state,'configuración',actor(),before=state['config'],after=cfg)
        state['config']=cfg
    return jsonify(ok=True)


@bp.post('/api/preferences')
def preferences():
    columns=body().get('columns')
    if not isinstance(columns,list) or not columns or set(columns)-COLUMNS.keys():
        raise ValueError('Seleccioná columnas comerciales válidas')
    with transaction() as state:
        state['preferences'][actor()]=columns
    return jsonify(ok=True)


@bp.get('/api/backup')
def backup():
    owner()
    with transaction() as state:
        return send_file(BytesIO(json.dumps(state,ensure_ascii=False,indent=2).encode()),mimetype='application/json',
                         as_attachment=True,download_name='baron-respaldo-privado.json')


@bp.get('/api/orders/<ident>/export/<kind>')
def export(ident,kind):
    from quote_exports import export_file
    with transaction() as state:
        order=order_in(state,ident)
        columns=state['preferences'].get(actor(),list(COLUMNS))
        content,mime,extension=export_file(order,columns,kind,[r for r in state['reservations'] if r['order_id']==ident])
        return send_file(BytesIO(content),mimetype=mime,as_attachment=True,download_name=order['number']+'.'+extension)
