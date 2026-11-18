"""Authenticated internal workflow, using the existing Flask application."""
from copy import deepcopy
import os
from io import BytesIO
import json
import uuid
from flask import Blueprint, abort, jsonify, render_template, request, send_file, session,current_app
from itsdangerous import URLSafeTimedSerializer,BadSignature
from private_store import transaction
from inventory import ensure_inventory,validate_inventory_catalogue,reconcile_prices,component_available
from storage import load_catalog
from quoting import (COLUMNS, defaults, validate_config, quote_order, commercial_rows,
    num, text, money, now, audit, available, matches, stock_warnings, transition, apply_price_choice)

bp = Blueprint('internal',__name__,url_prefix='/admin/interno')


def actor():
    return session.get('user','dueño')


def owner():
    if session.get('role','owner') != 'owner':
        abort(403)


def config(state):
    if state['config'] is None:
        state['config'] = defaults(load_catalog())
    state['config'].setdefault('happy_markup_pct',10)
    ensure_inventory(state,state['config'])
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
    return render_template('internal.html',is_owner=session.get('role','owner')=='owner',demo_stock=os.environ.get('BARON_DEMO_STOCK')=='1')


@bp.get('/api/state')
def state_api():
    with transaction() as state:
        cfg = config(state)
        orders = [{k:o.get(k) for k in ('id','number','customer','city','date','status','total','revision','updated_at')} for o in state['orders'].values()]
        lots = [dict(l,available_m=available(state,l)) for l in state['lots'].values()]
        components=[dict(l,available_qty=component_available(state,l)) for l in state['component_lots'].values()]
        return jsonify(config=cfg,orders=orders,lots=lots,component_lots=components,movements=state['movements'][-200:],
                       columns=COLUMNS,preferences=state['preferences'].get(actor(),list(COLUMNS)))


@bp.post('/api/preview')
def preview():
    data = body()
    with transaction() as state:
        cfg = config(state)
        old=order_in(state,data['id']) if data.get('id') else None
        same=old and data.get('groups')==old['groups'] and float(data.get('discount_pct',0))==old['discount_pct']
        order = quote_order(data,old['price_snapshot'] if same and not data.get('reprice') else cfg)
        if old:
            order['happy_rate_snapshot']=old.get('happy_rate_snapshot',cfg['happy_markup_pct']) if not data.get('reprice') else cfg['happy_markup_pct']
            apply_price_choice(order,old.get('price_choice','normal'))
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
            if old:
                order['happy_rate_snapshot']=old.get('happy_rate_snapshot',cfg['happy_markup_pct']) if not data.get('reprice') else cfg['happy_markup_pct']
                apply_price_choice(order,old.get('price_choice','normal'))
        order['mentirita']=data.get('mentirita') is True
        order.setdefault('happy_rate_snapshot',cfg['happy_markup_pct'])
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


@bp.post('/api/orders/<ident>/price-choice')
def price_choice(ident):
    data=body()
    with transaction() as state:
        order=order_in(state,ident,data.get('revision',-1))
        if order['status']!='presupuesto':
            raise ValueError('Volvé a Presupuesto antes de modificar el precio')
        choice=data.get('choice')
        if choice not in ('happy','normal'):
            raise ValueError('Elegí carita feliz o precio normal')
        if choice==order.get('price_choice','normal'):
            return jsonify(order=order,rows=commercial_rows(order),warnings=[],unchanged=True)
        before=deepcopy(order)
        order.setdefault('happy_rate_snapshot',config(state)['happy_markup_pct'])
        apply_price_choice(order,choice)
        order['revision']+=1
        order['updated_at']=now()
        audit(state,'ajuste comercial',actor(),order_id=ident,before=before,choice=choice,after=order)
        return jsonify(order=order,rows=commercial_rows(order),warnings=[],unchanged=False)


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
        unchanged=order['status']==data.get('status')
        transition(state,order,data.get('status'),actor())
        return jsonify(order=order,rows=commercial_rows(order),warnings=[],unchanged=unchanged)


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
            if not fabric and line.get('component_id'):
                component=next((c for c in config(state)['stock_components'] if c['id']==line['component_id'] and c.get('active',True) and not c.get('deleted')),None)
                if not component or component['unit']!=item['unit']:raise ValueError('Insumo o unidad del despiece inválidos')
                item['component_id']=component['id']
            clean.append(item)
        # Exactly one fabric allocation per curtain; cannot bypass stock by deleting it.
        if sorted(l['curtain'] for l in clean if l.get('fabric')) != [i+1 for i,u in enumerate(order['units']) if u.get('material_id')]:
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
        if not m or m.get('deleted') or data.get('color_id') not in [c['id'] for c in m['colors'] if not c.get('deleted')]:
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
        validate_inventory_catalogue(cfg)
        old={c['id']:c for c in state['config']['stock_components']}
        for c in cfg['stock_components']:
            if c['id'] in old and c['unit']!=old[c['id']]['unit'] and any(l['component_id']==c['id'] for l in state['component_lots'].values()):
                raise ValueError('El insumo tiene stock: para cambiar de unidad, creá otro artículo')
        reconcile_prices(state['config'],cfg)
        audit(state,'configuración',actor(),before=state['config'],after=cfg)
        state['config']=cfg
    return jsonify(ok=True)


@bp.post('/api/component-lots')
def component_entry():
    data=body()
    with transaction() as state:
        cfg=config(state)
        c=next((c for c in cfg['stock_components'] if c['id']==data.get('component_id') and c.get('active',True) and not c.get('deleted')),None)
        if not c:raise ValueError('Elegí un insumo activo')
        qty=num(data.get('quantity'),'Cantidad de entrada',0.000001,1e8)
        lot=dict(id='ins-lote-'+uuid.uuid4().hex[:12],component_id=c['id'],quantity=qty,unit=c['unit'],location=text(data.get('location',''),150),origin=text(data.get('origin',''),200),revision=1)
        state['component_lots'][lot['id']]=lot;c['track_stock']=True
        state['movements'].append(dict(at=now(),actor=actor(),event='entrada',lot_id=lot['id'],quantity=qty,unit=lot['unit']))
        audit(state,'entrada de insumo',actor(),lot=lot)
        return jsonify(lot=lot)


@bp.post('/api/component-lots/<ident>')
def component_adjust(ident):
    data=body()
    with transaction() as state:
        config(state)
        lot=state['component_lots'].get(ident)
        if not lot:abort(404)
        if data.get('revision')!=lot['revision']:abort(409,description='El lote cambió; recargá antes de ajustar')
        reason=text(data.get('reason',''),300)
        if not reason:raise ValueError('Indicá el motivo del ajuste')
        qty=num(data.get('quantity'),'Cantidad',0,1e8)
        reserved=lot['quantity']-component_available(state,lot)
        if qty<reserved:raise ValueError('La cantidad no puede ser menor a la reserva vigente')
        before=deepcopy(lot);lot.update(quantity=qty,location=text(data.get('location',''),150),revision=lot['revision']+1)
        state['movements'].append(dict(at=now(),actor=actor(),event='ajuste',lot_id=ident,quantity=qty-before['quantity'],unit=lot['unit'],reason=reason))
        audit(state,'ajuste de insumo',actor(),before=before,after=lot,reason=reason)
        return jsonify(lot=lot)


@bp.get('/api/inventory/export')
def inventory_export():
    from inventory_excel import export_inventory
    scope=request.args.get('scope','todo');template=request.args.get('template')=='1'
    with transaction() as state:
        config(state)
        raw=export_inventory(state,scope,template)
    return send_file(BytesIO(raw),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',as_attachment=True,
                     download_name=('plantilla-' if template else '')+'baron-'+scope+'.xlsx')


def inventory_signer():
    return URLSafeTimedSerializer(current_app.secret_key,salt='baron-inventory-import-v1')


@bp.post('/api/inventory/import/preview')
def inventory_import_preview():
    owner()
    from inventory_excel import read_inventory,apply_inventory,fingerprint
    file=request.files.get('file')
    if not file:raise ValueError('Seleccioná un archivo Excel')
    scope=request.form.get('scope','todo')
    rows=read_inventory(file.read(3_000_001),file.filename or '',scope)
    with transaction() as state:
        config(state);before=fingerprint(state)
        simulated=deepcopy(state)
        changes=apply_inventory(simulated,rows,actor())
        token=inventory_signer().dumps(dict(rows=rows,fingerprint=before,actor=actor()))
    return jsonify(token=token,changes=changes[:200],count=len(changes),truncated=len(changes)>200)


@bp.post('/api/inventory/import/commit')
def inventory_import_commit():
    owner()
    from inventory_excel import apply_inventory,fingerprint
    try:plan=inventory_signer().loads(body().get('token',''),max_age=3600)
    except BadSignature:raise ValueError('La vista previa venció o es inválida. Volvé a subir el Excel')
    if plan.get('actor')!=actor():abort(403)
    with transaction() as state:
        config(state)
        if plan['fingerprint']!=fingerprint(state):abort(409,description='El stock o catálogo cambió. Generá otra vista previa antes de aplicar')
        before=dict(config=deepcopy(state['config']),lots=deepcopy(state['lots']),component_lots=deepcopy(state['component_lots']))
        changes=apply_inventory(state,plan['rows'],actor())
        audit(state,'importar Excel',actor(),before=before,changes=changes)
    return jsonify(ok=True,count=len(changes))


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
