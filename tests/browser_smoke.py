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
    assert page.get_by_text('ENTORNO DE PRUEBA · STOCK FICTICIO',exact=True).count()==1
    assert page.locator('#status-select option').evaluate_all('(items)=>items.map(e=>e.value)')==['presupuesto','aprobado']
    quantity=page.locator('#groups').get_by_label('Cantidad',exact=True)
    quantity.fill('3');quantity.press('Tab')
    assert page.locator('.unit').count()==0
    assert page.get_by_text('¿Qué querés personalizar?',exact=False).count()==0
    page.screenshot(path=str(OUT/'cotizador-mobile-grupo.png'),full_page=True)
    page.get_by_label('Personalizar unidades de este grupo').check()
    assert page.locator('.unit').count()==0
    page.locator('.attributes').get_by_role('checkbox',name='Color',exact=True).check()
    assert page.locator('.unit').count()==3
    assert page.locator('.unit select').count()==3
    assert page.locator('.unit input').count()==0
    page.locator('.unit').nth(1).locator('select').select_option('beige')
    page.locator('input[name=customer]').fill('Cliente de prueba')
    page.locator('input[name=city]').fill('Trelew')
    page.get_by_role('button',name='Calcular',exact=True).click()
    page.wait_for_selector('#totals .total')
    page.screenshot(path=str(OUT/'cotizador-mobile-variante-color.png'),full_page=True)
    page.get_by_role('button',name='Guardar presupuesto',exact=True).click()
    page.locator('#order-title').filter(has_text='BAR-').wait_for()
    assert page.locator('body').evaluate('(e)=>e.scrollWidth <= innerWidth')
    page.get_by_role('button',name='Despiece',exact=True).click()
    assert not page.locator('#find-remnants').is_checked()
    assert not page.locator('#remnant-results').is_visible()
    assert page.locator('.bom-curtain').count()==3
    assert page.locator('.bom-curtain').nth(0).locator('.bom-line').count()==3
    second=page.locator('.bom-curtain').nth(1)
    second.get_by_role('button',name='＋ Agregar insumo',exact=True).click()
    added=second.locator('.bom-line').last
    added.get_by_label('Insumo',exact=True).fill('Accesorio de prueba')
    added.get_by_label('Cantidad física',exact=True).fill('2')
    added.get_by_label('Costo unitario',exact=True).fill('1234')
    with page.expect_response(lambda r:'/bom' in r.url and r.request.method=='POST') as saved_bom:
        page.get_by_role('button',name='Guardar despiece',exact=True).click()
    assert saved_bom.value.status==200
    assert page.locator('.bom-curtain').nth(1).locator('.bom-line').count()==4
    assert page.locator('body').evaluate('(e)=>e.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT/'despiece-mobile.png'),full_page=True)
    page.get_by_role('button',name='Presupuesto cliente',exact=True).click()
    assert page.locator('#client-preview .client-row').count()==2
    page.screenshot(path=str(OUT/'presupuesto-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('button',name='Despiece',exact=True).click()
    page.screenshot(path=str(OUT/'despiece-desktop.png'),full_page=True)
    page.get_by_role('button',name='Cotizador',exact=True).click()
    page.screenshot(path=str(OUT/'cotizador-desktop.png'),full_page=True)
    page.on('dialog',lambda d:d.accept())
    page.locator('#status-select').select_option('aprobado')
    page.get_by_role('button',name='Confirmar estado',exact=True).click()
    page.locator('#order-status').filter(has_text='aprobado').wait_for()
    page.locator('#status-select').select_option('presupuesto')
    page.get_by_role('button',name='Confirmar estado',exact=True).click()
    page.locator('#order-status').filter(has_text='presupuesto').wait_for()
    # Configuration uses forms and preserves the prices of the stored order.
    page.get_by_role('button',name='Configuración',exact=True).click()
    assert page.locator('#config-json').count()==0
    before=page.request.get(BASE+'/admin/interno/api/state').json()['config']
    page.get_by_text('Telas y colores',exact=True).click()
    screen=page.locator('[data-material-id="excel-screen"]')
    screen.locator('summary').click()
    screen.get_by_label('Precio de tela',exact=True).fill('24000')
    screen.locator('.settings-color').first.get_by_label('Precio especial del color',exact=True).fill('26000')
    screen.get_by_role('button',name='＋ Agregar color',exact=True).click()
    screen.locator('.settings-color').last.get_by_label('Nombre del color',exact=True).fill('Azul de prueba')
    page.get_by_text('Caños y sistemas',exact=True).click()
    page.locator('[data-tube="32"]').get_by_label('Precio del caño por metro',exact=True).fill('38000')
    page.get_by_text('Zócalos, cadenas y soportes',exact=True).click()
    chain=page.locator('[data-extra-kind="chain"]')
    chain.get_by_role('button',name='＋ Agregar cadenas',exact=True).click()
    chain.get_by_label('Nombre del adicional',exact=True).fill('Cadena de prueba')
    chain.get_by_label('Precio del adicional',exact=True).fill('1500')
    with page.expect_response(lambda r:'/api/config' in r.url and r.request.method=='POST') as settings_saved:
        page.get_by_role('button',name='Guardar configuración',exact=True).click()
    assert settings_saved.value.status==200
    page.get_by_text('Configuración guardada',exact=True).wait_for()
    after=page.request.get(BASE+'/admin/interno/api/state').json()['config']
    m=next(m for m in after['materials'] if m['id']=='excel-screen')
    assert m['price']==24000 and m['colors'][0]['price_override']==26000
    assert any(c['name']=='Azul de prueba' for c in m['colors'])
    assert m['source']==next(m for m in before['materials'] if m['id']=='excel-screen')['source']
    assert after['tubes']['32']['price_m']==38000
    assert after['extras']['chain']['Cadena de prueba']==1500
    stored=page.request.get(BASE+'/admin/interno/api/orders/'+saved_bom.value.json()['order']['id']).json()['order']
    assert stored['total']==saved_bom.value.json()['order']['total']
    page.get_by_text('Telas y colores',exact=True).click()
    screen.locator('summary').click()
    screen.locator('.settings-color').first.get_by_label('Precio especial del color',exact=True).fill('')
    with page.expect_response(lambda r:'/api/config' in r.url and r.request.method=='POST') as cleared:
        page.get_by_role('button',name='Guardar configuración',exact=True).click()
    assert cleared.value.status==200
    page.get_by_text('Configuración guardada',exact=True).wait_for()
    cleared_cfg=page.request.get(BASE+'/admin/interno/api/state').json()['config']
    assert 'price_override' not in next(m for m in cleared_cfg['materials'] if m['id']=='excel-screen')['colors'][0]
    page.screenshot(path=str(OUT/'configuracion-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('body').evaluate('(e)=>e.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT/'configuracion-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('button',name='Cotizador',exact=True).click()
    # Default and deselection confirmations actually discard exceptions.
    page.locator('.attributes').get_by_role('checkbox',name='Color',exact=True).uncheck()
    assert page.locator('.unit').count()==0
    page.get_by_label('Personalizar unidades de este grupo').uncheck()
    assert page.locator('.attributes').count()==0
    assert errors==[],errors
    print('PASS: mobile/desktop; no horizontal overflow; variants A/B/C; confirmations; separate BOM; no JavaScript errors')
    browser.close()

server.shutdown()
from private_store import _engines
for engine in _engines.values(): engine.dispose()
tmp.cleanup()
