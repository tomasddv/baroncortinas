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
    page.get_by_role('button',name='Usuarios y permisos',exact=True).click()
    form=page.locator('#users-fields form').first
    form.get_by_label('Usuario',exact=True).fill('colaborador-ui')
    form.get_by_label('Nombre',exact=True).fill('Colaborador UI')
    form.get_by_label('Contraseña inicial',exact=True).fill('clave-ui-colaborador')
    form.get_by_label('Visualizar despiece',exact=True).check()
    form.get_by_label('Actualizar estados de fabricación',exact=True).check()
    form.get_by_label('Exportar despiece a Excel sin precios',exact=True).check()
    form.get_by_role('button',name='Crear colaborador',exact=True).click()
    page.get_by_text('Usuario guardado. Las sesiones anteriores fueron revocadas.',exact=True).wait_for()
    page.get_by_role('button',name='Cotizador',exact=True).click()
    page.locator('input[name=customer]').fill('Organismo UI')
    page.get_by_label('Modelo / producto',exact=True).select_option('manual')
    page.get_by_label('Detalle del artículo',exact=True).fill('Caño de aluminio')
    page.get_by_label('Precio unitario',exact=True).fill('2000')
    page.get_by_label('Cantidad',exact=True).fill('2')
    page.get_by_label('Cantidad',exact=True).press('Tab')
    page.get_by_label('Organismo gubernamental',exact=True).check()
    page.get_by_label('Importe final aplicable',exact=True).fill('5000')
    page.get_by_label('Observaciones',exact=True).fill('Entrega en 15 días.\nGarantía incluida.')
    with page.expect_response(lambda r:r.url.endswith('/api/orders') and r.request.method=='POST') as saved:
        page.get_by_role('button',name='Guardar presupuesto',exact=True).click()
    assert saved.value.status==200
    assert saved.value.json()['order']['payments']=={'TOTAL PRESUPUESTO':5000}
    assert not page.locator('#price-choice-dialog').is_visible()
    page.get_by_role('button',name='Presupuesto cliente',exact=True).click()
    frame=page.frame_locator('#client-preview iframe')
    frame.locator('img').first.wait_for()
    assert frame.locator('img').first.evaluate('(img)=>img.complete && img.naturalWidth>0')
    page.screenshot(path=str(OUT/'oficial-gobierno-mobile.png'),full_page=True)
    csrf=page.locator('meta[name="csrf-token"]').get_attribute('content')
    o=saved.value.json()['order']
    r=page.request.post(BASE+'/admin/interno/api/orders/'+o['id']+'/status',data={'status':'aprobado','revision':o['revision'],'confirm':True},headers={'X-CSRF-Token':csrf});assert r.status==200
    staff=browser.new_context(viewport={'width':390,'height':844})
    op=staff.new_page();op.on('pageerror',lambda e:errors.append(str(e)))
    op.goto(BASE+'/admin/login');op.locator('input[name=username]').fill('colaborador-ui');op.locator('input[name=password]').fill('clave-ui-colaborador');op.get_by_role('button',name='Ingresar',exact=False).click()
    op.goto(BASE+'/')
    op.get_by_role('heading',name='Tablero de trabajo',exact=True).wait_for()
    op.locator('#op-order-selector').get_by_label('Seleccionar presupuesto aprobado',exact=True).select_option(o['id'])
    op.locator('#op-order-selector').get_by_label('Seleccionar cortina',exact=True).select_option('1')
    op.get_by_role('heading',name=o['number']+' · Organismo UI',exact=True).wait_for()
    assert '5000' not in op.locator('body').inner_text()
    assert op.request.get(BASE+'/admin/interno/api/state').status==403
    op.get_by_role('tab',name='Despiece',exact=True).click()
    assert op.get_by_role('link',name='Exportar despiece Excel',exact=True).count()==1
    assert op.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    op.get_by_role('tab',name='Stock',exact=True).click()
    entry=op.locator('form').filter(has=op.get_by_role('heading',name='Entrada de artículos',exact=True))
    entry.get_by_label('Cantidad',exact=True).fill('5')
    with op.expect_response(lambda r:r.url.endswith('/admin/operativo/api/component-lots') and r.request.method=='POST') as stock_entry:
        entry.get_by_role('button',name='Agregar stock',exact=True).click()
    assert stock_entry.value.status==200
    op.get_by_role('tab',name='Pedidos aprobados',exact=True).click()
    op.get_by_label('Estado de fabricación',exact=True).select_option('en fabricación')
    with op.expect_response(lambda r:r.url.endswith('/manufacturing') and r.request.method=='POST') as stage:
        op.get_by_role('button',name='Guardar estado',exact=True).click()
    assert stage.value.status==200
    assert op.locator('#notice').inner_text()==''
    op.screenshot(path=str(OUT/'colaborador-mobile.png'),full_page=True)
    page.get_by_role('button',name='Usuarios y permisos',exact=True).click()
    form=page.locator('#users-fields form').filter(has=page.get_by_role('heading',name='colaborador-ui · staff',exact=True))
    form.get_by_label('Cuenta habilitada',exact=True).uncheck()
    form.get_by_role('button',name='Guardar usuario / Revocar sesiones',exact=True).click()
    page.get_by_text('Usuario guardado. Las sesiones anteriores fueron revocadas.',exact=True).wait_for()
    op.reload();op.locator('input[name=password]').wait_for()
    assert errors==[],errors
    browser.close()
server.shutdown()
from private_store import _engines
for engine in _engines.values():engine.dispose()
tmp.cleanup()
print('PASS: users UI, manual governmental quote, official preview, mobile operations, revocation')
