"""Operational boundary. Every response uses positive allowlists, including exports."""
from copy import deepcopy
from io import BytesIO
from flask import Blueprint,abort,jsonify,request,render_template,send_file,session
from openpyxl import Workbook
from private_store import transaction
from access import require,allowed,PERMISSIONS,initialize,write_user,public_user
from quoting import available,num,text,now,audit,matches
from inventory import component_available
bp=Blueprint('operational',__name__,url_prefix='/admin/operativo')
UNIT_KEYS=('group','index','room','quantity','detail','width_cm','height_cm','material','color','tube','side','drop','zocalo','chain','mount','guides','product_id')
BOM_KEYS=('id','curtain','name','quantity','unit','fabric','material_id','color_id','cut_width_cm','cut_height_cm','remnant_id','component_id')
STAGES=('pendiente','en fabricación','listo','entregado')
def select(data,keys):return {k:data[k] for k in keys if k in data}
def approved(s,ident):
    o=s['orders'].get(ident)
    if not o or o['status']!='aprobado':abort(404)
    return o
def safe_order(o,permissions):
    result=select(o,('id','number','customer','city','date','revision','technical_notes','manufacturing_status','manufacturing_revision'))
    result['units']=[dict(select(u,UNIT_KEYS),system=' · '.join(l['name'] for l in o['bom'] if l['curtain']==i+1 and l['name'].startswith('Sistema'))) for i,u in enumerate(o['units'])]
    if permissions['contacts']:result['contact']=o.get('contact','')
    if permissions['bom']:result['bom']=[select(l,BOM_KEYS) for l in o['bom']]
    return result
@bp.before_request
def login():
    if not session.get('admin_auth'):abort(401)
@bp.errorhandler(ValueError)
@bp.errorhandler(KeyError)
@bp.errorhandler(TypeError)
def invalid(e):return jsonify(error=str(e)),400
@bp.get('/')
def dashboard():return render_template('operational.html')
@bp.get('/api/state')
def state():
    from internal import config
    permissions={k:allowed(k) for k in PERMISSIONS}
    with transaction() as s:
        cfg=config(s);result=dict(permissions=permissions,stages=STAGES)
        if permissions['orders']:result['orders']=[safe_order(o,permissions) for o in s['orders'].values() if o['status']=='aprobado']
        if permissions['stock'] or permissions['remnants'] or permissions['stock_add'] or permissions['remnants_edit']:
            result['materials']=[dict(id=m['id'],name=m['name'],colors=[select(c,('id','name')) for c in m['colors'] if not c.get('deleted')]) for m in cfg['materials'] if not m.get('deleted')]
            result['components']=[select(c,('id','name','unit','category','minimum_qty')) for c in cfg['stock_components'] if not c.get('deleted')]
        result['lots']=[]
        for l in s['lots'].values():
            if not permissions['stock' if l['kind']=='rollo' else 'remnants']:continue
            result['lots'].append(dict(select(l,('id','kind','material_id','color_id','width_cm','length_m','location','origin','minimum_m','revision')),available=available(s,l)))
        result['component_lots']=[dict(select(l,('id','component_id','quantity','unit','location','origin','revision')),available=component_available(s,l)) for l in s.get('component_lots',{}).values()] if permissions['stock'] else []
        result['alerts']=[]
        if permissions['stock']:
            result['alerts']+=[l['id']+' · stock bajo' for l in result['lots'] if l['kind']=='rollo' and l['available']<=l.get('minimum_m',cfg['stock_min_m'])]
            for c in cfg['stock_components']:
                qty=sum(l['available'] for l in result['component_lots'] if l['component_id']==c['id'])
                if c.get('track_stock') and qty<=c.get('minimum_qty',0):result['alerts'].append(c['name']+' · stock bajo')
        return jsonify(result)
@bp.post('/api/lots')
def add_lot():
    data=request.get_json() or {};require('remnants_edit' if data.get('kind')=='retazo' else 'stock_add')
    from internal import create_lot
    create_lot()
    return jsonify(ok=True)
@bp.post('/api/lots/<ident>')
def edit_lot(ident):
    with transaction() as s:
        l=s['lots'].get(ident)
        if not l:abort(404)
        kind=l['kind']
    require('remnants_edit' if kind=='retazo' else 'stock_edit')
    from internal import edit_lot as adjust_lot
    adjust_lot(ident)
    return jsonify(ok=True)
@bp.post('/api/component-lots')
def add_component():
    require('stock_add')
    from internal import component_entry
    component_entry();return jsonify(ok=True)
@bp.post('/api/component-lots/<ident>')
def edit_component(ident):
    require('stock_edit')
    from internal import component_adjust
    component_adjust(ident);return jsonify(ok=True)
@bp.get('/api/orders/<ident>/bom.xlsx')
def export(ident):
    require('orders');require('bom');require('bom_export')
    from quote_exports import safe
    with transaction() as s:
        o=approved(s,ident);book=Workbook();sheet=book.active;sheet.title='Despiece'
        sheet.append(['Pedido',safe(o['number']),'Cliente',safe(o['customer'])])
        keys=['curtain','name','quantity','unit','cut_width_cm','cut_height_cm','remnant_id']
        sheet.append(['Cortina','Material','Cantidad física','Unidad','Ancho corte cm','Alto corte cm','Retazo'])
        for l in o['bom']:sheet.append([safe(l.get(k,'')) for k in keys])
        tech=book.create_sheet('Cortinas');tech.append(list(UNIT_KEYS))
        for u in o['units']:tech.append([safe(u.get(k,'')) for k in UNIT_KEYS])
        stream=BytesIO();book.save(stream);stream.seek(0)
        return send_file(stream,as_attachment=True,download_name=o['number']+'-despiece.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
@bp.post('/api/orders/<ident>/manufacturing')
def manufacturing(ident):
    require('orders');require('manufacturing');data=request.get_json() or {}
    if data.get('status') not in STAGES:raise ValueError('Estado de fabricación inválido')
    with transaction() as s:
        o=approved(s,ident)
        if data.get('revision',0)!=o.get('manufacturing_revision',0):abort(409)
        before=o.get('manufacturing_status','pendiente');o['manufacturing_status']=data['status'];o['manufacturing_revision']=o.get('manufacturing_revision',0)+1
        audit(s,'estado de fabricación',session['user'],order_id=ident,before=before,after=data['status'])
    return jsonify(ok=True)
@bp.post('/api/orders/<ident>/bom')
def edit_bom(ident):
    require('orders');require('bom');require('bom_edit');data=request.get_json() or {}
    from quoting import transition
    with transaction() as s:
        o=approved(s,ident)
        if data.get('revision')!=o['revision']:abort(409)
        changes=data.get('lines')
        if not isinstance(changes,list) or len(changes)!=len(o['bom']):raise ValueError('Conservá las líneas del despiece')
        original=deepcopy(o['bom']);byid={l['id']:l for l in o['bom']}
        if len({l.get('id') for l in changes})!=len(byid):raise ValueError('Líneas repetidas o inexistentes')
        clean=[]
        for change in changes:
            l=deepcopy(byid[change['id']])
            if l.get('fabric'):
                l['cut_width_cm']=num(change.get('cut_width_cm'),'Ancho corte',1,600)
                l['cut_height_cm']=num(change.get('cut_height_cm'),'Alto corte',1,1000)
                l['quantity']=l['cut_width_cm']*l['cut_height_cm']/10000
            else:l['quantity']=num(change.get('quantity'),'Cantidad',0,1e8)
            clean.append(l)
        # Reassign reservations atomically. Failure restores original BOM and reservations.
        transition(s,o,'presupuesto',session['user']);o['bom']=clean
        transition(s,o,'aprobado',session['user'])
        audit(s,'editar despiece operativo',session['user'],order_id=ident,before=original,after=clean)
    return jsonify(ok=True)
@bp.get('/api/orders/<ident>/remnants')
def compatible(ident):
    require('orders');require('bom');require('remnants')
    with transaction() as s:
        o=approved(s,ident)
        return jsonify({l['id']:[select(r,('id','width_cm','length_m','location')) for r in matches(s,l)] for l in o['bom'] if l.get('fabric')})
