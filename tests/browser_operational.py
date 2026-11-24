from pathlib import Path
import os
import sys
import tempfile
import threading
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=Path(os.environ.get('BROWSER_OUTPUT',str(ROOT/'work'/'browser-evidence')))
OUT.mkdir(parents=True,exist_ok=True)
tmp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ['DATABASE_URL']='sqlite:///'+str(Path(tmp.name)/'browser.sqlite')
os.environ['ADMIN_PASSWORD']='local-qa-only'
os.environ['BARON_DEMO_STOCK']='1'
from app import app
server=make_server('127.0.0.1',0,app,threaded=True)
threading.Thread(target=server.serve_forever,daemon=True).start()
BASE='http://127.0.0.1:'+str(server.server_port)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel=os.environ.get('BROWSER_CHANNEL') or None)
    context=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1)
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE+'/admin/login')
    page.locator('input[name=password]').fill('local-qa-only')
    page.get_by_role('button',name='Ingresar',exact=False).click()
    page.wait_for_selector('.group')
    csrf=page.locator('meta[name="csrf-token"]').get_attribute('content')
    def owner_post(path,data):
        r=page.request.post(BASE+'/admin/interno/api'+path,data=data,headers={'X-CSRF-Token':csrf})
        assert r.status==200,r.text()
        return r.json()
    base=dict(material_id='excel-screen',color_id='blanco',width_cm=150,height_cm=180,tube='32',room='Living')
    first=owner_post('/orders',dict(customer='Pedido A',groups=[dict(quantity=2,base=base,customize=True,attributes=['material_id'],units=[{},dict(material_id='excel-blackout')])]))['order']
    second=owner_post('/orders',dict(customer='Pedido B',groups=[dict(quantity=1,base=base|{'room':'Dormitorio'})]))['order']
    pending=owner_post('/orders',dict(customer='Borrador oculto',groups=[dict(quantity=1,base=base)]))['order']
    for o in (first,second):owner_post('/orders/'+o['id']+'/status',dict(status='aprobado',revision=o['revision'],confirm=True))
    owner_post('/users',dict(username='operador',password='clave-operativa-123',permissions=['orders','bom','bom_export','stock','stock_add','stock_edit','manufacturing'],enabled=True))
    context2=browser.new_context(viewport={'width':390,'height':844});op=context2.new_page()
    op.on('pageerror',lambda e:errors.append(str(e)))
    op.goto(BASE+'/admin/login');op.locator('input[name=username]').fill('operador');op.locator('input[name=password]').fill('clave-operativa-123');op.get_by_role('button',name='Ingresar',exact=False).click()
    op.locator('#op-order-selector select').wait_for()
    selector=op.locator('#op-order-selector').get_by_label('Seleccionar presupuesto aprobado',exact=True)
    assert selector.locator('option').count()==3
    assert 'Borrador oculto' not in selector.inner_text()
    assert op.locator('#op-order-list article').count()==0
    def isolated(id):
        assert op.locator('.op-panel:visible').count()==1
        assert op.locator('#'+id).is_visible()
    isolated('op-orders')
    selector.select_option(first['id'])
    op.locator('#op-order-selector').get_by_label('Seleccionar cortina',exact=True).select_option('1')
    op.get_by_role('tab',name='Despiece',exact=True).click();isolated('op-bom')
    assert op.locator('#op-bom-content .selected-curtain').count()==1
    assert op.locator('#op-bom-content .bom-line').count()==3
    assert op.locator('#op-bom-content .bom-line[data-curtain="2"]').count()==0
    check=op.locator('#op-bom-content').get_by_label('Realizada',exact=True)
    with op.expect_response(lambda r:'/curtains/1/completion' in r.url) as finished:check.check()
    assert finished.value.status==200
    op.locator('#op-bom-content').get_by_text('YA REALIZADA',exact=False).wait_for()
    op.get_by_role('button',name='Actualizar',exact=True).click()
    op.locator('#op-bom-content').get_by_text('YA REALIZADA',exact=False).wait_for()
    op.locator('#op-bom-selector').get_by_label('Seleccionar cortina',exact=True).select_option('2')
    assert not op.locator('#op-bom-content').get_by_label('Realizada',exact=True).is_checked()
    assert op.locator('#op-bom-content .bom-line[data-curtain="1"]').count()==0
    assert op.locator('#op-bom-content .bom-line[data-curtain="2"]').count()==3
    with op.expect_download() as download:
        op.get_by_role('link',name='Exportar despiece Excel',exact=True).click()
    from openpyxl import load_workbook
    excel=Path(tmp.name)/'cortina.xlsx';download.value.save_as(excel);book=load_workbook(excel)
    assert all(row[0]==2 for row in list(book['Despiece'].values)[2:])
    assert len(list(book['Cortinas'].values))==2
    op.locator('#op-bom-selector').get_by_label('Seleccionar cortina',exact=True).select_option('1')
    op.once('dialog',lambda d:d.dismiss())
    op.locator('#op-bom-content').get_by_label('Realizada',exact=True).click()
    assert op.locator('#op-bom-content').get_by_label('Realizada',exact=True).is_checked()
    for title,id in [('Stock','op-stock'),('Alertas','op-alerts'),('Pedidos aprobados','op-orders')]:
        op.get_by_role('tab',name=title,exact=True).click();isolated(id)
    op.get_by_role('tab',name='Despiece',exact=True).click()
    op.locator('#op-bom-selector').get_by_label('Seleccionar presupuesto aprobado',exact=True).select_option(second['id'])
    assert op.locator('#op-bom-content .selected-curtain').count()==0
    op.locator('#op-bom-selector').get_by_label('Seleccionar cortina',exact=True).select_option('1')
    assert not op.locator('#op-bom-content').get_by_label('Realizada',exact=True).is_checked()
    assert op.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    op.screenshot(path=str(OUT/'operativo-selectores-mobile.png'),full_page=True)
    op.set_viewport_size({'width':1440,'height':1000})
    op.screenshot(path=str(OUT/'operativo-selectores-desktop.png'),full_page=True)
    assert op.locator('#notice').inner_text()==''
    assert errors==[],errors
    browser.close()
server.shutdown()
from private_store import _engines
for engine in _engines.values():engine.dispose()
tmp.cleanup()
print('PASS: isolated operational tabs; order/curtain selection; per-curtain completion; scoped Excel')
