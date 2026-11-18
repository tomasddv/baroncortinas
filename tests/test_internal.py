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


def test_two_status_workflow_reserves_and_releases_without_consuming(client):
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
    o=status('aprobado',o); o=status('aprobado',o)
    with transaction() as s:
        assert s['lots'][lot['id']]['length_m']==50
        assert len([r for r in s['reservations'] if r['status']=='reservado'])==3
    r=post(client,'/orders/'+o['id']+'/status',dict(status='fabricación',revision=o['revision'],confirm=True))
    assert r.status_code==400
    o=status('presupuesto',o)
    with transaction() as s: assert s['lots'][lot['id']]['length_m']==50


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


@pytest.mark.parametrize('field,value',[('name','   '),('family','desconocida'),('hex','rojo')])
def test_configuration_rejects_invalid_material_fields(client,field,value):
    cfg=client.get('/admin/interno/api/state').json['config']
    changed=deepcopy(cfg)
    target=changed['materials'][0]['colors'][0] if field=='hex' else changed['materials'][0]
    target[field]=value
    assert post(client,'/config',dict(config=changed,previous=cfg)).status_code==400
    assert client.get('/admin/interno/api/state').json['config']==cfg


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


def test_stale_stock_adjustment_cannot_override_reservation(client):
    lot=post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco')).json['lot']
    o=save(client,draft(1))
    for target in ('aprobado',):
        r=post(client,'/orders/'+o['id']+'/status',dict(status=target,revision=o['revision'],confirm=True))
        assert r.status_code==200
        o=r.json['order']
    r=post(client,'/lots/'+lot['id'],dict(revision=lot['revision'],width_cm=280,length_m=50,reason='Ajuste desde pantalla desactualizada'))
    assert r.status_code==409
    with transaction() as s: assert s['lots'][lot['id']]['length_m']==50


def test_margin_changes_only_client_dimensions_and_exports(client):
    body=draft(1);body['mentirita']=True
    o=save(client,body)
    regular=quote_order(draft(1),defaults(load_catalog()))
    assert o['total']==regular['total']
    assert o['units'][0]['width_cm']==150 and o['units'][0]['height_cm']==180
    assert o['bom'][0]['cut_width_cm']==150 and o['bom'][0]['cut_height_cm']==200
    row=commercial_rows(o)[0]
    assert row['width_cm']==160 and row['height_cm']==190
    prefix='/admin/interno/api/orders/'+o['id']+'/export/'
    commercial=load_workbook(BytesIO(client.get(prefix+'xlsx').data)).active
    assert commercial['D6'].value==160 and commercial['E6'].value==190
    assert 'margen' in commercial['B4'].value
    technical=load_workbook(BytesIO(client.get(prefix+'bom').data))
    assert technical['Cortinas']['E2'].value==150 and technical['Cortinas']['F2'].value==180
    document=''.join(p.extract_text() for p in PdfReader(BytesIO(client.get(prefix+'pdf').data)).pages)
    assert '10 cm de margen' in document


def test_happy_choice_is_reversible_idempotent_and_preserves_stock(client):
    post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco'))
    o=save(client);base=o['total'];original_bom=deepcopy(o['bom'])
    def choose(choice,order):
        r=post(client,'/orders/'+order['id']+'/price-choice',dict(choice=choice,revision=order['revision']))
        assert r.status_code==200,r.data
        return r.json
    result=choose('happy',o);happy=result['order']
    assert happy['total']==base*1.1 and happy['happy_adjustment_pct']==10
    assert happy['bom']==original_bom
    repeated=choose('happy',happy)
    assert repeated['unchanged'] and repeated['order']['total']==happy['total']
    assert repeated['order']['revision']==happy['revision']
    saved=post(client,'/orders',dict(draft(),id=happy['id'],revision=happy['revision'])).json['order']
    assert choose('happy',saved)['order']['total']==happy['total']
    normal=choose('normal',saved)['order']
    assert normal['total']==base
    assert all(u['unit_price']==u['normal_unit_price'] for u in normal['units'])
    with transaction() as s:
        assert not s['reservations']
        assert all(l['length_m']==50 for l in s['lots'].values())
    approved=post(client,'/orders/'+normal['id']+'/status',dict(status='aprobado',revision=normal['revision'],confirm=True)).json['order']
    with transaction() as s:count=len(s['reservations'])
    repeated_status=post(client,'/orders/'+normal['id']+'/status',dict(status='aprobado',revision=approved['revision'],confirm=True))
    assert repeated_status.json['unchanged']
    with transaction() as s:assert len(s['reservations'])==count
    assert post(client,'/orders/'+normal['id']+'/price-choice',dict(choice='happy',revision=approved['revision'])).status_code==400


def test_happy_rate_is_configurable_and_historical(client):
    old=save(client,draft(1))
    cfg=client.get('/admin/interno/api/state').json['config']
    changed=deepcopy(cfg);changed['happy_markup_pct']=17
    assert post(client,'/config',dict(config=changed,previous=cfg)).status_code==200
    new=save(client,draft(1))
    for o,pct in [(old,10),(new,17)]:
        result=post(client,'/orders/'+o['id']+'/price-choice',dict(choice='happy',revision=o['revision']))
        assert result.status_code==200
        assert result.json['order']['happy_adjustment_pct']==pct
    changed['happy_markup_pct']=-1
    current=client.get('/admin/interno/api/state').json['config']
    assert post(client,'/config',dict(config=changed,previous=current)).status_code==400


def test_demo_stock_is_additive_persistent_and_not_replenished(client):
    from demo_data import prepare_demo
    old=save(client,draft(1))
    actual=post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco',length_m=7)).json['lot']
    created=prepare_demo()
    assert created>0
    with transaction() as s:
        assert s['orders'][old['id']]['total']==old['total']
        assert s['lots'][actual['id']]['length_m']==7
        assert s['before_demo_stock_v1']['orders'][old['id']]['total']==old['total']
        demos=[l for l in s['lots'].values() if l.get('demo')]
        assert len(demos)==created
        assert any(l['kind']=='retazo' and l['width_cm']>=150 and l['length_m']>=2 for l in demos)
        sample=demos[0]['id']
        s['lots'][sample]['length_m']=4
    assert prepare_demo()==0
    with app.test_client() as another:
        with another.session_transaction() as session:
            session.update(admin_auth=True,csrf='test-csrf')
        data=another.get('/admin/interno/api/state').json
        assert old['id'] in [o['id'] for o in data['orders']]
        assert next(l for l in data['lots'] if l['id']==sample)['length_m']==4
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
