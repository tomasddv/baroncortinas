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
    page.get_by_label('Mentirita',exact=True).check()
    page.get_by_role('button',name='Calcular',exact=True).click()
    page.wait_for_selector('#totals .total')
    page.screenshot(path=str(OUT/'cotizador-mobile-variante-color.png'),full_page=True)
    page.get_by_role('button',name='Guardar presupuesto',exact=True).click()
    page.locator('#order-title').filter(has_text='BAR-').wait_for()
    page.locator('#price-choice-dialog').wait_for()
    page.screenshot(path=str(OUT/'eleccion-caritas.png'),full_page=True)
    page.locator('#choose-normal').click()
    page.locator('#price-choice-dialog').wait_for(state='hidden')
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
    frame=page.frame_locator('#client-preview iframe')
    frame.locator('img').first.wait_for()
    assert frame.locator('img').count()>=1
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
    assert page.locator('#change-status').is_disabled()
    original_id=saved_bom.value.json()['order']['id']
    csrf=page.locator('meta[name="csrf-token"]').get_attribute('content')
    extra_body={'customer':'Segundo aprobado','groups':saved_bom.value.json()['order']['groups']}
    extra=page.request.post(BASE+'/admin/interno/api/orders',data=extra_body,headers={'X-CSRF-Token':csrf}).json()['order']
    approved=page.request.post(BASE+'/admin/interno/api/orders/'+extra['id']+'/status',data={'status':'aprobado','revision':extra['revision'],'confirm':True},headers={'X-CSRF-Token':csrf})
    assert approved.status==200
    page.get_by_role('button',name='Despiece',exact=True).click()
    page.locator('#bom-order-select option').filter(has_text='Segundo aprobado').wait_for(state='attached')
    assert page.locator('#bom-order-select option').count()==3
    page.locator('#bom-order-select').select_option(extra['id'])
    page.locator('#bom-content h3').first.filter(has_text='Segundo aprobado').wait_for()
    assert page.locator('#save-bom').is_disabled()
    page.screenshot(path=str(OUT/'despiece-aprobados.png'),full_page=True)
    page.locator('#bom-order-select').select_option(original_id)
    page.locator('#bom-content h3').first.filter(has_text='Cliente de prueba').wait_for()
    page.get_by_role('button',name='Cotizador',exact=True).click()
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
    # Resaving with the happy choice must never multiply the previous uplift.
    for choice in ['happy','happy','normal']:
        page.get_by_role('button',name='Guardar presupuesto',exact=True).click()
        page.locator('#price-choice-dialog').wait_for()
        page.locator('#choose-'+choice).click()
        page.locator('#price-choice-dialog').wait_for(state='hidden')
        stored_choice=page.request.get(BASE+'/admin/interno/api/orders/'+original_id).json()['order']
        if choice=='happy':
            assert stored_choice['happy_adjustment_pct']==10
            if 'previous_happy' in locals():assert previous_happy==stored_choice['total']
            previous_happy=stored_choice['total']
        else:
            assert stored_choice['happy_adjustment_pct']==0 and stored_choice['total']==stored_choice['normal_total']
    page.set_viewport_size({'width':390,'height':844})
    page.locator('#add-group').click()
    assert page.locator('.group').count()==2
    page.locator('#add-group').scroll_into_view_if_needed()
    assert page.locator('#add-group').bounding_box()['y']>=page.locator('.group').last.bounding_box()['y']+page.locator('.group').last.bounding_box()['height']
    # Export the selected historical record without replacing the unsaved quote.
    page.get_by_role('button',name='Historial',exact=True).click()
    historical=page.locator('#history-list .list-row').filter(has_text='Segundo aprobado')
    assert historical.get_by_role('button',name='Abrir',exact=True).count()==1
    historical.get_by_role('button',name='Presupuesto cliente',exact=True).click()
    popup=page.locator('#history-export-dialog')
    popup.wait_for()
    assert 'Segundo aprobado' in popup.inner_text()
    assert popup.locator('a').count()==4
    assert page.locator('.group').count()==2
    assert popup.bounding_box()['width']<=390
    page.screenshot(path=str(OUT/'historial-formatos-mobile.png'),full_page=True)
    with page.expect_download() as downloaded:
        popup.get_by_role('link',name='Descargar PDF',exact=True).click()
    assert downloaded.value.suggested_filename==extra['number']+'.pdf'
    popup.wait_for(state='hidden')
    assert page.locator('.group').count()==2
    historical.get_by_role('button',name='Presupuesto cliente',exact=True).click()
    assert popup.get_by_role('link',name='Descargar Excel',exact=True).get_attribute('href').endswith('/'+extra['id']+'/export/xlsx')
    popup.get_by_role('button',name='Cerrar formatos',exact=True).click()
    # Catalogue administration, generic model and hardware stock on a phone.
    page.get_by_role('button',name='Configuración',exact=True).click()
    page.get_by_text('Telas y colores',exact=True).click()
    screen=page.locator('[data-material-id="excel-screen"]')
    screen.locator('summary').click()
    screen.get_by_role('button',name='Eliminar tela',exact=True).click()
    assert screen.count()==0
    page.get_by_role('button',name='Guardar configuración',exact=True).click()
    page.get_by_text('Configuración guardada',exact=True).wait_for()
    page.get_by_text('Telas y colores',exact=True).click()
    page.get_by_label('Mostrar telas eliminadas',exact=True).check()
    screen.locator('summary').click()
    screen.get_by_role('button',name='Recuperar tela',exact=True).click()
    page.get_by_text('Insumos y artículos de stock',exact=True).click()
    page.get_by_role('button',name='＋ Agregar insumo al catálogo',exact=True).click()
    component=page.locator('[data-component-id]').last
    component.get_by_label('Nombre del insumo',exact=True).fill('Cadena UI')
    component.get_by_label('Unidad del insumo',exact=True).select_option('m')
    component.get_by_label('Costo unitario del insumo',exact=True).fill('200')
    component_id=component.get_attribute('data-component-id')
    page.get_by_text('Productos y modelos para cotizar',exact=True).click()
    page.get_by_role('button',name='＋ Agregar producto o modelo',exact=True).click()
    product=page.locator('[data-product-id]').last
    product.get_by_label('Nombre del producto',exact=True).fill('Modelo UI')
    product.get_by_label('Valor base de la regla',exact=True).fill('25000')
    product.get_by_label('Requiere tela y color',exact=True).uncheck()
    product_id=product.get_attribute('data-product-id')
    product.get_by_role('button',name='＋ Agregar insumo a la receta',exact=True).click()
    product.get_by_label('Insumo de la receta',exact=True).select_option(component_id)
    product.get_by_label('Regla de cantidad',exact=True).select_option('alto_m')
    product.get_by_label('Factor de cantidad',exact=True).fill('2')
    page.get_by_role('button',name='Guardar configuración',exact=True).click()
    page.get_by_text('Configuración guardada',exact=True).wait_for()
    page.get_by_role('button',name='Stock e insumos',exact=True).click()
    page.locator('#show-component-stock').click()
    page.get_by_label('Insumo a ingresar',exact=True).select_option(component_id)
    page.get_by_label('Cantidad de entrada',exact=True).fill('100')
    with page.expect_response(lambda r:'/api/component-lots' in r.url and r.request.method=='POST') as entry:
        page.get_by_role('button',name='Registrar entrada de insumo',exact=True).click()
    assert entry.value.status==200
    page.locator('[data-stock-component="'+component_id+'"]').filter(has_text='Total 100 m').wait_for()
    assert page.locator('body').evaluate('(e)=>e.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT/'insumos-mobile.png'),full_page=True)
    # An actual downloaded workbook is reviewed and committed through the form.
    from openpyxl import load_workbook
    with page.expect_download() as exported:
        page.get_by_role('link',name='Exportar todo',exact=True).click()
    excel_path=Path(tmp.name)/'carga.xlsx'
    exported.value.save_as(excel_path)
    book=load_workbook(excel_path)
    book['Insumos'].append(['import-ui','Accesorio Excel UI','accesorio','unidad',123,5,'sí','no','no'])
    book.save(excel_path)
    page.locator('#inventory-import-file').set_input_files(excel_path)
    page.get_by_role('button',name='Revisar Excel',exact=True).click()
    page.locator('#inventory-import-preview').filter(has_text='import-ui').wait_for()
    assert not any(c['id']=='import-ui' for c in page.request.get(BASE+'/admin/interno/api/state').json()['config']['stock_components'])
    page.get_by_role('button',name='Confirmar importación',exact=True).click()
    page.get_by_text('Importación completada: 1 cambio(s).',exact=True).wait_for()
    assert any(c['id']=='import-ui' for c in page.request.get(BASE+'/admin/interno/api/state').json()['config']['stock_components'])
    page.get_by_role('button',name='Cotizador',exact=True).click()
    for group in page.locator('.group').all():
        group.get_by_label('Modelo / producto',exact=True).select_option(product_id)
    page.get_by_role('button',name='Calcular',exact=True).click()
    page.locator('#totals .total').wait_for()
    assert 'Modelo UI' in page.locator('#groups').inner_text()
    assert errors==[],errors
    print('PASS: mobile/desktop; no horizontal overflow; variants A/B/C; confirmations; separate BOM; catalogue, hardware, custom products and Excel import; no JavaScript errors')
    browser.close()

server.shutdown()
from private_store import _engines
for engine in _engines.values(): engine.dispose()
tmp.cleanup()
