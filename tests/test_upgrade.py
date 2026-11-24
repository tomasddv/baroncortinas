from copy import deepcopy
from io import BytesIO
import zipfile
import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from werkzeug.security import check_password_hash
from app import app
from private_store import transaction,backup_table,engine
from sqlalchemy import select
from test_internal import client,draft,save,post
from access import PERMISSIONS


def collaborator(owner,permissions=None):
    body=dict(username='operario',name='Operario',password='clave-operaria-segura',enabled=True,permissions=permissions or ['orders','stock','stock_add','stock_edit'])
    r=post(owner,'/users',body);assert r.status_code==200,r.data
    with transaction() as s:
        u=s['users']['operario'];assert check_password_hash(u['password_hash'],body['password']);version=u['version']
    c=app.test_client()
    with c.session_transaction() as session:session.update(admin_auth=True,csrf='op-csrf',user='operario',role='staff',version=version)
    return c

def op(c,path,body):return c.post('/admin/operativo/api'+path,json=body,headers={'X-CSRF-Token':'op-csrf'})

def approve(client):
    post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco',length_m=50))
    o=save(client,draft(1));r=post(client,'/orders/'+o['id']+'/status',dict(status='aprobado',revision=o['revision'],confirm=True));assert r.status_code==200
    return r.json['order']

def test_collaborator_boundary_and_export(client):
    o=approve(client);unapproved=save(client,draft(1));c=collaborator(client,list(PERMISSIONS))
    r=c.get('/admin/operativo/api/state');assert r.status_code==200
    data=r.json;assert [x['id'] for x in data['orders']]==[o['id']]
    forbidden=('unit_cost','unit_price','subtotal','price_snapshot','payments','price_value','total','password_hash','markup','normal_total')
    def inspect(value):
        if isinstance(value,dict):
            assert not set(value).intersection(forbidden),value
            for v in value.values():inspect(v)
        if isinstance(value,list):
            for v in value:inspect(v)
    inspect(data)
    for path in ['/admin/interno/','/admin/interno/api/state','/admin/interno/api/backup','/admin/interno/api/users','/admin/interno/api/orders/'+o['id'],
      '/admin/interno/api/orders/'+o['id']+'/export/bom','/admin/interno/api/orders/'+o['id']+'/export/pdf','/admin/interno/api/inventory/export','/api/config','/admin/exportar']:
        assert c.get(path).status_code==403,path
    assert op(c,'/orders/'+unapproved['id']+'/manufacturing',dict(status='listo')).status_code==404
    raw=c.get('/admin/operativo/api/orders/'+o['id']+'/bom.xlsx');assert raw.status_code==200
    book=load_workbook(BytesIO(raw.data));assert book.sheetnames==['Despiece','Cortinas']
    for ws in book:
        assert ws.sheet_state=='visible'
        for row in ws:
            for cell in row:assert not any(k in str(cell.value).lower() for k in ['precio','costo','margen','importe','unit_price','subtotal'])
    with zipfile.ZipFile(BytesIO(raw.data)) as z:
        for name in z.namelist():assert b'price_snapshot' not in z.read(name)

def test_live_permissions_and_stock_audit(client):
    c=collaborator(client)
    r=op(c,'/component-lots',dict(component_id='tubo-32',quantity=12,origin='Recepción operario'));assert r.status_code==200,r.data
    assert op(c,'/component-lots',dict(component_id='no-existe',quantity=10)).status_code==400
    assert op(c,'/component-lots',dict(component_id='tubo-32',quantity=-1)).status_code==400
    assert c.post('/admin/interno/api/config',json={},headers={'X-CSRF-Token':'op-csrf'}).status_code==403
    with transaction() as s:
        m=s['stock_history'][-1];assert m['actor']=='operario' and m['before']==0 and m['after']==12 and m['delta']==12
    r=post(client,'/users',dict(username='operario',name='Operario',enabled=False,permissions=[]));assert r.status_code==200
    assert c.get('/admin/operativo/api/state').status_code in (401,302)
    c=collaborator(client,['orders'])
    assert op(c,'/component-lots',dict(component_id='tubo-32',quantity=1)).status_code==403
    assert c.get('/admin/operativo/api/state').json['component_lots']==[]

def test_manual_government_notes_and_preservation(client):
    old=save(client,draft(1));before=deepcopy(old)
    data=draft(1);data['groups'].append(dict(quantity=2,base=dict(product_id='manual',detail='Caño de aluminio',unit_price=1234.56,width_cm='',height_cm='',material='',color=''),attributes=[],units=[],customize=False))
    data.update(notes='Instalación incluida.\nGarantía de un año.',government=True,government_total=100000.01)
    o=save(client,data)
    assert o['total']==100000.01 and sum(int(round(u['subtotal']*100)) for u in o['units'])==10000001
    assert o['payments']=={'TOTAL PRESUPUESTO':100000.01} and len(o['bom'])==3
    assert sum(1 for u in o['units'] if u.get('manual'))==2
    raw=client.get('/admin/interno/api/orders/'+o['id']+'/export/pdf').data
    reader=PdfReader(BytesIO(raw));content=''.join(p.extract_text() for p in reader.pages)
    assert 'TOTAL PRESUPUESTO' in content and 'Garantía' in content
    assert not any(k in content for k in ['Transferencia','Tarjeta','Efectivo','Descuento'])
    book=load_workbook(BytesIO(client.get('/admin/interno/api/orders/'+o['id']+'/export/xlsx').data));values=str(list(book.active.values))
    assert 'TOTAL PRESUPUESTO' in values and 'Garantía' in values and 'Transferencia' not in values
    assert client.get('/admin/interno/api/orders/'+old['id']).json['order']==before
    ordinary=save(client,data|{'government':False});assert set(ordinary['payments'])=={'Transferencia','Efectivo','Tarjeta'}
    assert ordinary['total']==old['total']+2469.12

def test_operational_edit_reservations_and_manufacturing(client):
    o=approve(client);c=collaborator(client,list(PERMISSIONS))
    state=c.get('/admin/operativo/api/state').json;safe=state['orders'][0];lines=safe['bom'];lines[0]['cut_height_cm']=210
    r=op(c,'/orders/'+o['id']+'/bom',dict(revision=o['revision'],lines=lines));assert r.status_code==200,r.data
    with transaction() as s:
        order=s['orders'][o['id']];assert order['total']==o['total']
        reserved=sum(r.get('length_m',0) for r in s['reservations'] if r['status']=='reservado');assert reserved==2.1
    assert op(c,'/orders/'+o['id']+'/manufacturing',dict(status='en fabricación',revision=0)).status_code==200
    assert op(c,'/orders/'+o['id']+'/manufacturing',dict(status='listo',revision=0)).status_code==409

def test_backup_before_migration_and_owner_login(client,monkeypatch):
    client.get('/admin/interno/api/state')
    with engine().connect() as conn:assert conn.execute(select(backup_table.c.payload)).first() is not None
    monkeypatch.setenv('ADMIN_PASSWORD','clave-dueno-segura')
    monkeypatch.setenv('ADMIN_USERNAME','dueno')
    c=app.test_client();c.get('/admin/login')
    with c.session_transaction() as session:csrf=session['csrf']
    r=c.post('/admin/login',data=dict(username='dueno',password='clave-dueno-segura',csrf=csrf));assert r.status_code==302
    assert c.get('/admin/interno/api/state').status_code==200
    with transaction() as s:assert check_password_hash(s['users']['dueno']['password_hash'],'clave-dueno-segura')


def test_multi_page_template_geometry_and_preview(client):
    import pymupdf
    body=draft(1);body['groups']=[dict(quantity=1,base=body['groups'][0]['base']|{'room':f'LUGAR{i:02}'}) for i in range(40)]
    body['notes']='CONDICIONES ESPECIALES\n'+'Entrega e instalación coordinadas con el cliente. '*60
    o=save(client,body);root='/admin/interno/api/orders/'+o['id']
    raw=client.get(root+'/export/pdf').data
    with pymupdf.open(stream=raw,filetype='pdf') as doc:
        assert len(doc)>1
        markers=[]
        for page in doc:
            for word in page.get_text('words'):
                if word[4].startswith('LUGAR'):
                    markers.append(word[4]);assert 190<word[1]<660
            assert 'Ambiente' in page.get_text() or 'CONDICIONES' in page.get_text() or 'coordinadas' in page.get_text()
        assert len(markers)==40
    preview=client.get(root+'/preview')
    assert preview.headers['X-Frame-Options']=='SAMEORIGIN'
    assert b'frame-ancestors' not in preview.data
    assert client.get(root+'/preview/1.png').data.startswith(b'\x89PNG')

def test_password_reset_contact_permissions_and_persistence(client):
    o=approve(client)
    with transaction() as s:s['orders'][o['id']].update(contact='contacto-privado',notes='importe-confidencial',technical_notes='Fabricar sin girar la trama')
    c=collaborator(client,['orders','bom'])
    data=c.get('/admin/operativo/api/state').data
    assert b'contacto-privado' not in data and b'importe-confidencial' not in data and b'Fabricar sin girar' in data
    assert c.get('/admin/operativo/api/orders/'+o['id']+'/bom.xlsx').status_code==403
    post(client,'/users',dict(username='operario',password='clave-nueva-12345',permissions=['orders','bom','contacts'],enabled=True))
    assert c.get('/admin/operativo/api/state').status_code in (302,401)
    fresh=app.test_client();fresh.get('/admin/login')
    with fresh.session_transaction() as se:csrf=se['csrf']
    assert fresh.post('/admin/login',data=dict(username='operario',password='clave-nueva-12345',csrf=csrf)).status_code==302
    assert fresh.get('/admin/operativo/api/state').json['orders'][0]['contact']=='contacto-privado'
    from private_store import _engines
    for eng in list(_engines.values()):eng.dispose()
    assert fresh.get('/admin/operativo/api/state').json['orders'][0]['number']==o['number']


def test_owner_rename_keeps_identity_password_and_revokes_old_session(client,monkeypatch):
    from werkzeug.security import generate_password_hash
    from access import initialize
    monkeypatch.setenv('ADMIN_USERNAME','LUCAS')
    hashed=generate_password_hash('misma-clave-1234')
    with transaction() as s:
        s['users']['dueno']=dict(id='owner-persistente',username='dueno',role='owner',name='Dueño',password_hash=hashed,version=3,enabled=True,permissions=list(PERMISSIONS))
    stale=app.test_client()
    with stale.session_transaction() as se:se.update(admin_auth=True,role='owner',user='dueno',version=3,csrf='stale')
    assert stale.get('/admin/interno/api/state').status_code==302
    with transaction() as s:
        assert 'dueno' not in s['users']
        u=s['users']['LUCAS'];assert u['id']=='owner-persistente' and u['password_hash']==hashed and u['version']==4
        initialize(s);assert s['users']['LUCAS']['version']==4
    fresh=app.test_client();fresh.get('/admin/login')
    with fresh.session_transaction() as se:csrf=se['csrf']
    assert fresh.post('/admin/login',data=dict(username='LUCAS',password='misma-clave-1234',csrf=csrf)).status_code==302
    assert fresh.get('/admin/interno/api/state').status_code==200

def test_curtain_completion_atomic_idempotent_and_reopen(client):
    post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco',length_m=50))
    o=save(client,draft(2));post(client,'/orders/'+o['id']+'/status',dict(status='aprobado',revision=o['revision'],confirm=True))
    c=collaborator(client,list(PERMISSIONS));path='/orders/'+o['id']+'/curtains/1/completion'
    with transaction() as s:before=deepcopy({k:s[k] for k in ['lots','reservations','movements']})
    r=op(c,path,dict(done=True,revision=0));assert r.status_code==200
    assert op(c,path,dict(done=True,revision=0)).json['unchanged'] is True
    with transaction() as s:
        assert {k:s[k] for k in before}==before
        assert s['orders'][o['id']]['curtain_progress']['1']['actor']=='operario'
        assert s['orders'][o['id']]['manufacturing_status']=='en fabricación'
    data=c.get('/admin/operativo/api/state').json['orders'][0]
    assert data['curtain_progress']['1']['done'] and not data['curtain_progress']['2']['done']
    lines=data['bom'];lines[0]['cut_height_cm']=220
    assert op(c,'/orders/'+o['id']+'/bom',dict(lines=lines,revision=data['revision'])).status_code==400
    assert op(c,path,dict(done=False,revision=1)).status_code==400
    assert op(c,path,dict(done=False,revision=0,confirm=True)).status_code==409
    assert op(c,path,dict(done=False,revision=1,confirm=True)).status_code==200
    assert op(c,path,dict(done=True,revision=1)).status_code==409
    assert op(c,path,dict(done=True,revision=2)).status_code==200
    assert op(c,'/orders/'+o['id']+'/curtains/2/completion',dict(done=True,revision=0)).status_code==200
    with transaction() as s:assert s['orders'][o['id']]['manufacturing_status']=='listo'
    # Completed physical units cannot be silently modified from the owner's editor either.
    stored=client.get('/admin/interno/api/orders/'+o['id']).json['order']
    post(client,'/orders/'+o['id']+'/status',dict(status='presupuesto',revision=stored['revision'],confirm=True))
    stored=client.get('/admin/interno/api/orders/'+o['id']).json['order']
    body=draft(2);body.update(id=o['id'],revision=stored['revision']);body['groups'][0]['base']['height_cm']=210
    assert post(client,'/orders',body).status_code==400
    duplicate=post(client,'/orders/'+o['id']+'/duplicate',{}).json['order']
    assert duplicate['curtain_progress']=={} and duplicate['manufacturing_status']=='pendiente'

def test_completion_permissions_and_single_curtain_export(client):
    o=approve(client);c=collaborator(client,['orders','bom','bom_export'])
    assert op(c,'/orders/'+o['id']+'/curtains/1/completion',dict(done=True,revision=0)).status_code==403
    raw=c.get('/admin/operativo/api/orders/'+o['id']+'/bom.xlsx?curtain=1')
    assert raw.status_code==200
    book=load_workbook(BytesIO(raw.data));assert len(list(book['Cortinas'].values))==2
    assert c.get('/admin/operativo/api/orders/'+o['id']+'/bom.xlsx?curtain=2').status_code==400


def test_revoked_session_post_returns_to_login_without_executing(client):
    c=collaborator(client,['orders'])
    post(client,'/users',dict(username='operario',enabled=False,permissions=[]))
    response=c.post('/admin/salir',data={'csrf':'op-csrf'})
    assert response.status_code==303 and response.location.endswith('/admin/login')
    assert c.get(response.location).status_code==200

def test_stale_login_form_gets_fresh_token_and_never_authenticates(client):
    c=app.test_client();c.get('/admin/login')
    r=c.post('/admin/login',data=dict(username='LUCAS',password='anything',csrf='expired-token'))
    assert r.status_code==303
    with c.session_transaction() as se:assert not se.get('admin_auth')
    assert c.get(r.location).status_code==200
    with c.session_transaction() as se:assert se.get('csrf')

def test_staff_root_routes_to_operational_not_forbidden(client):
    c=collaborator(client,['orders'])
    r=c.get('/');assert r.status_code==302 and r.location.endswith('/admin/operativo/')
    assert c.get('/admin/interno/api/state').status_code==403
