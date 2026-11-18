from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
import zipfile
import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from app import app
from storage import load_catalog
from private_store import transaction
from quoting import defaults, quote_order, resolve_groups, commercial_rows, matches


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///'+str(tmp_path/'test.sqlite'))
    app.config.update(TESTING=True)
    with app.test_client() as c:
        with c.session_transaction() as s:
            s.update(admin_auth=True, csrf='test-csrf', user='test-owner', role='owner')
        yield c


def draft(qty=3):
    return dict(customer='Cliente de prueba', city='Trelew', date='2026-11-18', valid_until='2026-12-01',
        groups=[dict(quantity=qty, customize=False, attributes=[], units=[], base=dict(
            material_id='excel-screen', color_id='blanco', width_cm=150, height_cm=180, tube='32', room='Living'))])


def post(c, path, data):
    return c.post('/admin/interno/api'+path, json=data, headers={'X-CSRF-Token': 'test-csrf'})


def save(c, data=None):
    r=post(c, '/orders', data or draft())
    assert r.status_code==200, r.data
    return r.json['order']


@pytest.mark.parametrize('tube,extra,rate,system', [('32',.2,37400,36000), ('42',.3,41800,42000), ('45',.35,49280,42000), ('58',.4,62900,42000)])
@pytest.mark.parametrize('material,price', [('excel-screen',23650), ('excel-blackout',23650), ('excel-traslucida',16000)])
def test_excel_formula(tube, extra, rate, system, material, price):
    cfg=defaults(load_catalog())
    next(m for m in cfg['materials'] if m['id']==material)['colors']=[dict(id='test', name='Test')]
    body=draft(1); body['groups'][0]['base'].update(tube=tube, material_id=material, color_id='test')
    q=quote_order(body,cfg)
    assert q['total']==round(1.5*(1.8+extra)*price+system+1.5*rate,2)
    assert q['units'][0]['height_cm']==180
    assert q['units'][0]['cut_height_cm']==180+extra*100


def test_variants_and_ignored_overrides():
    body=draft(); g=body['groups'][0]
    g['units']=[{},dict(color_id='beige',width_cm=999),{}]
    assert all(u['color_id']=='blanco' for u in resolve_groups(body['groups']))
    g.update(customize=True,attributes=['color_id'])
    units=resolve_groups(body['groups'])
    assert [u['color_id'] for u in units]==['blanco','beige','blanco']
    assert all(u['width_cm']==150 for u in units)
    cfg=defaults(load_catalog()); cfg['materials'][0]['colors'][1]['price_override']=30000
    q=quote_order(body,cfg)
    assert q['units'][1]['unit_price']!=q['units'][0]['unit_price']
    assert sorted(r['quantity'] for r in commercial_rows(q))==[1,2]
    g['attributes']=[]
    assert all(u['color_id']=='blanco' for u in resolve_groups(body['groups']))


def test_snapshot_and_revisions(client):
    o=save(client)
    with transaction() as s: s['config']['materials'][0]['price']=999999
    get=client.get('/admin/interno/api/orders/'+o['id']).json['order']
    assert get['total']==o['total']
    update=dict(draft(),id=o['id'],revision=o['revision'],notes='Nueva nota')
    assert post(client,'/orders',update).json['order']['total']==o['total']
    assert post(client,'/orders',update).status_code==409


def test_stock_lifecycle_and_cancel(client):
    lot=post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco')).json['lot']
    o=save(client)
    with transaction() as s:
        assert s['lots'][lot['id']]['length_m']==50
        assert not s['reservations']
    def status(target,o):
        r=post(client,'/orders/'+o['id']+'/status',dict(status=target,revision=o['revision'],confirm=True))
        assert r.status_code==200,r.data
        return r.json['order']
    o=status('aprobado',o)
    with transaction() as s:
        assert len(s['reservations'])==3
        assert s['lots'][lot['id']]['length_m']==50
    o=status('presupuesto',o)
    with transaction() as s: assert all(r['status']=='liberado' for r in s['reservations'])
    o=status('aprobado',o); o=status('fabricación',o); o=status('fabricación',o)
    with transaction() as s: assert s['lots'][lot['id']]['length_m']==44
    o=status('cancelado',o)
    with transaction() as s: assert s['lots'][lot['id']]['length_m']==44


def test_insufficient_rolls_atomic(client):
    post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco',length_m=3))
    o=save(client)
    r=post(client,'/orders/'+o['id']+'/status',dict(status='aprobado',revision=1,confirm=True))
    assert r.status_code==400
    with transaction() as s:
        assert s['reservations']==[]
        assert s['orders'][o['id']]['status']=='presupuesto'


def test_remnants_no_rotation_reserved_and_best_fit(client):
    lots=[]
    for w,h in [(160,2.1),(200,3),(200,1.6),(140,3)]:
        lots.append(post(client,'/lots',dict(kind='retazo',material_id='excel-screen',color_id='blanco',width_cm=w,length_m=h)).json['lot'])
    o=save(client,draft(1)); line=o['bom'][0]
    with transaction() as s:
        assert [l['id'] for l in matches(s,line)]==[lots[0]['id'],lots[1]['id']]
    line['remnant_id']=lots[0]['id']
    r=post(client,'/orders/'+o['id']+'/bom',dict(lines=o['bom'],revision=1))
    assert r.status_code==200,r.data
    o=r.json['order']
    assert post(client,'/orders/'+o['id']+'/status',dict(status='aprobado',revision=o['revision'],confirm=True)).status_code==200
    with transaction() as s:
        assert lots[0]['id'] not in [l['id'] for l in matches(s,line)]


def test_bom_price_separation_and_fabric_required(client):
    o=save(client,draft(1)); o['bom'][1]['unit_cost']=1
    r=post(client,'/orders/'+o['id']+'/bom',dict(lines=o['bom'],revision=1))
    assert r.status_code==200
    assert r.json['order']['total']==o['total']
    lines=[l for l in r.json['order']['bom'] if not l.get('fabric')]
    assert post(client,'/orders/'+o['id']+'/bom',dict(lines=lines,revision=2)).status_code==400


def test_exports_real_consistent_and_safe(client):
    body=draft(); body['customer']='=HYPERLINK("bad")'; o=save(client,body)
    prefix='/admin/interno/api/orders/'+o['id']+'/export/'
    x=load_workbook(BytesIO(client.get(prefix+'xlsx').data))
    assert x.active['B2'].data_type=='s'
    assert any(c.value==o['total'] for row in x.active for c in row)
    b=load_workbook(BytesIO(client.get(prefix+'bom').data))
    assert b.sheetnames==['Despiece','Cortinas','Resumen']
    p=client.get(prefix+'pdf'); assert p.data.startswith(b'%PDF')
    content=''.join(pg.extract_text() for pg in PdfReader(BytesIO(p.data)).pages)
    assert 'PRESUPUESTO' in content and '180' in content
    assert 'Costo' not in content and 'consumo' not in content
    assert client.get(prefix+'jpg').data.startswith(b'\xff\xd8')
    assert client.get(prefix+'png').data.startswith(b'\x89PNG')


def test_multipage_exports(client):
    body=draft(1); body['groups']=[deepcopy(body['groups'][0]) for _ in range(45)]
    for i,g in enumerate(body['groups']): g['base']['room']='Ambiente '+str(i)
    o=save(client,body); prefix='/admin/interno/api/orders/'+o['id']+'/export/'
    p=PdfReader(BytesIO(client.get(prefix+'pdf').data)); assert len(p.pages)>1
    r=client.get(prefix+'jpg'); assert r.mimetype=='application/zip'
    assert len(zipfile.ZipFile(BytesIO(r.data)).namelist())==len(p.pages)


def test_private_routes_csrf_and_staff(client):
    assert client.post('/admin/interno/api/orders',json=draft()).status_code==403
    with client.session_transaction() as s: s['role']='staff'
    assert post(client,'/config',{}).status_code==403
    assert client.get('/admin/exportar').status_code==403
    assert client.get('/admin/interno/api/backup').status_code==403
    with client.session_transaction() as s: s.clear()
    for path in ['/api/cotizar','/api/armar-pedido','/api/verificar']:
        assert client.post(path,json={}).status_code==401
    for path in ['/admin/interno/api/state','/admin/interno/api/backup','/admin/simulador']:
        assert client.get(path).status_code==302


def test_concurrent_stock_and_numbering(client):
    post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco',length_m=2))
    def worker(i):
        with app.test_client() as c:
            with c.session_transaction() as s: s.update(admin_auth=True,csrf='test-csrf')
            o=save(c,draft(1))
            r=post(c,'/orders/'+o['id']+'/status',dict(status='aprobado',revision=1,confirm=True))
            return o['number'],r.status_code
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(worker,range(4)))
    assert len({r[0] for r in results})==4
    assert sum(r[1]==200 for r in results)==1


def test_config_preferences_and_billable_minimum(client):
    cfg=client.get('/admin/interno/api/state').json['config']
    changed=deepcopy(cfg);changed['min_billable_m2']=4
    assert post(client,'/config',dict(config=changed,previous=cfg)).status_code==200
    assert post(client,'/config',dict(config=changed,previous=cfg)).status_code==409
    o=save(client,draft(1))
    assert o['bom'][0]['quantity']==3
    assert o['bom'][0]['billable_quantity']==4
    assert o['bom'][0]['subtotal']==94600
    assert post(client,'/preferences',dict(columns=['material','color','subtotal'])).status_code==200
    assert client.get('/admin/interno/api/state').json['preferences']==['material','color','subtotal']
    assert post(client,'/preferences',dict(columns=['unit_cost'])).status_code==400
    with client.session_transaction() as s:s['user']='otro'
    assert len(client.get('/admin/interno/api/state').json['preferences'])==9


def test_reprice_explicit_and_invalid_inputs(client):
    o=save(client,draft(1))
    with transaction() as s:s['config']['materials'][0]['price']=30000
    data=dict(draft(1),id=o['id'],revision=o['revision'])
    assert post(client,'/preview',data).json['order']['total']==o['total']
    data['reprice']=True
    changed=post(client,'/preview',data).json['order']['total']
    assert changed>o['total']
    assert post(client,'/orders',data).json['order']['total']==changed
    data=draft(1);data['valid_until']='2026-02-31'
    assert post(client,'/preview',data).status_code==400


def test_stale_stock_adjustment_cannot_restore_consumed_fabric(client):
    lot=post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco')).json['lot']
    o=save(client,draft(1))
    for target in ('aprobado','fabricación'):
        r=post(client,'/orders/'+o['id']+'/status',dict(status=target,revision=o['revision'],confirm=True))
        assert r.status_code==200
        o=r.json['order']
    r=post(client,'/lots/'+lot['id'],dict(revision=lot['revision'],width_cm=280,length_m=50,reason='Ajuste desde pantalla desactualizada'))
    assert r.status_code==409
    with transaction() as s: assert s['lots'][lot['id']]['length_m']==48
    data=draft(1);data['groups'][0]['base']['width_cm']=500
    assert post(client,'/preview',data).status_code==400


@pytest.mark.skipif(not os.environ.get('TEST_POSTGRES_URL'),reason='Requires PostgreSQL test service')
def test_postgres_locking(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['TEST_POSTGRES_URL'])
    with transaction() as s: s['sequence']=0
    def increment(_):
        with transaction() as s: s['sequence']+=1
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(increment,range(24)))
    with transaction() as s: assert s['sequence']==24
