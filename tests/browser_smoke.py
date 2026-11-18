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
    page.screenshot(path=str(OUT/'despiece-mobile.png'),full_page=True)
    page.get_by_role('button',name='Presupuesto cliente',exact=True).click()
    assert page.locator('#client-preview .client-row').count()==2
    page.screenshot(path=str(OUT/'presupuesto-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('button',name='Cotizador',exact=True).click()
    page.screenshot(path=str(OUT/'cotizador-desktop.png'),full_page=True)
    # Default and deselection confirmations actually discard exceptions.
    page.on('dialog',lambda d:d.accept())
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
