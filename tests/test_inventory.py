from copy import deepcopy
from io import BytesIO
from openpyxl import load_workbook,Workbook
from test_internal import client,draft,post,save
from private_store import transaction
from inventory import component_available


def update_cfg(client,edit):
    cfg=client.get('/admin/interno/api/state').json['config'];new=deepcopy(cfg);edit(new)
    r=post(client,'/config',dict(config=new,previous=cfg));assert r.status_code==200,r.data


def upload(client,raw,scope='todo'):
    return client.post('/admin/interno/api/inventory/import/preview',data={'scope':scope,'file':(BytesIO(raw),'stock.xlsx')},headers={'X-CSRF-Token':'test-csrf'})


def workbook_bytes(sheets):
    book=Workbook();book.remove(book.active)
    for name,rows in sheets.items():
        ws=book.create_sheet(name)
        for row in rows:ws.append(row)
    out=BytesIO();book.save(out);return out.getvalue()


def test_hardware_reservations_split_and_release(client):
    client.get('/admin/interno/api/state')
    post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco'))
    first=post(client,'/component-lots',dict(component_id='tubo-32',quantity=3,location='A')).json['lot']
    o=save(client)
    change=lambda order,target:post(client,'/orders/'+order['id']+'/status',dict(status=target,revision=order['revision'],confirm=True))
    assert change(o,'aprobado').status_code==400
    with transaction() as s:assert s['reservations']==[]
    second=post(client,'/component-lots',dict(component_id='tubo-32',quantity=2,location='B')).json['lot']
    r=change(o,'aprobado');assert r.status_code==200,r.data;o=r.json['order']
    with transaction() as s:
        free=sum(component_available(s,l) for l in s['component_lots'].values())
        assert free==.5
        count=len(s['reservations'])
        current=deepcopy(s['component_lots'][first['id']])
    assert change(o,'aprobado').json['unchanged']
    with transaction() as s:assert len(s['reservations'])==count
    assert post(client,'/component-lots/'+first['id'],dict(revision=current['revision'],quantity=1,location='A',reason='prueba')).status_code==400
    assert change(o,'presupuesto').status_code==200
    with transaction() as s:assert sum(component_available(s,l) for l in s['component_lots'].values())==5


def test_archive_material_preserves_orders_and_stock(client):
    lot=post(client,'/lots',dict(kind='rollo',material_id='excel-screen',color_id='blanco')).json['lot']
    old=save(client,draft(1))
    def archive(cfg):
        m=next(m for m in cfg['materials'] if m['id']=='excel-screen');m.update(deleted=True,active=False)
    update_cfg(client,archive)
    assert post(client,'/preview',draft(1)).status_code==400
    assert client.get('/admin/interno/api/orders/'+old['id']).json['order']['total']==old['total']
    with transaction() as s:assert s['lots'][lot['id']]['length_m']==50
    def restore(cfg):
        m=next(m for m in cfg['materials'] if m['id']=='excel-screen');m.update(deleted=False,active=True,name='Screen editado')
    update_cfg(client,restore)
    assert post(client,'/preview',draft(1)).json['order']['units'][0]['material']=='Screen editado'


def test_custom_product_recipe_and_price_modes(client):
    def setup(cfg):
        next(c for c in cfg['stock_components'] if c['id']=='cadena-plastica')['unit_cost']=100
        cfg['products'].append(dict(id='modelo-nuevo',name='Modelo nuevo',calculation='fijo',price_value=25000,requires_fabric=False,extra_height_cm=0,fabric_width_multiplier=1,active=True,recipes=[dict(component_id='cadena-plastica',mode='alto_m',factor=2)]))
    update_cfg(client,setup)
    post(client,'/component-lots',dict(component_id='cadena-plastica',quantity=5))
    body=draft(1);body['groups'][0]['base']['product_id']='modelo-nuevo'
    o=save(client,body)
    assert o['total']==25000 and not o['units'][0]['material_id']
    assert o['bom'][0]['quantity']==3.6 and o['bom'][0]['subtotal']==360
    assert post(client,'/orders/'+o['id']+'/status',dict(status='aprobado',revision=o['revision'],confirm=True)).status_code==200
    def area(cfg):next(p for p in cfg['products'] if p['id']=='modelo-nuevo').update(calculation='m2',price_value=10000)
    update_cfg(client,area)
    assert post(client,'/preview',body).json['order']['total']==27000
    assert client.get('/admin/interno/api/orders/'+o['id']).json['order']['total']==25000


def test_excel_roundtrip_and_bulk_new_catalogue_stock(client):
    client.get('/admin/interno/api/state')
    raw=client.get('/admin/interno/api/inventory/export').data
    assert load_workbook(BytesIO(raw)).sheetnames==['Telas','Colores','Insumos','Productos','Recetas','Stock telas','Stock insumos','Instrucciones']
    preview=upload(client,raw);assert preview.status_code==200,preview.data
    assert preview.json['count']==0
    raw=workbook_bytes({
      'Telas':[['Código','Nombre','Familia','Precio','Unidad precio','Ancho rollo cm'],['nueva-tela','Nueva tela','blackout',12345,'m2',280]],
      'Colores':[['Código tela','Código color','Color','Hex','Precio especial'],['nueva-tela','azul','Azul','#123456',None]],
      'Insumos':[['Código','Nombre','Categoría','Unidad','Costo unitario'],['cadena-nueva','Cadena nueva','cadena','m',500]],
      'Productos':[['Código','Nombre','Regla precio','Valor regla','Requiere tela'],['nuevo-modelo','Nuevo modelo','fijo',17000,'no']],
      'Recetas':[['Código producto','Código insumo','Regla cantidad','Factor'],['nuevo-modelo','cadena-nueva','alto_m',2]],
      'Stock telas':[['Código lote','Código tela','Código color','Tipo','Ancho cm','Largo m'],['lote-azul','nueva-tela','azul','rollo',280,50]],
      'Stock insumos':[['Código lote','Código insumo','Cantidad','Unidad'],['lote-cadena','cadena-nueva',80,'m']]})
    preview=upload(client,raw);assert preview.status_code==200,preview.data
    with transaction() as s:assert 'lote-azul' not in s['lots']
    commit=post(client,'/inventory/import/commit',dict(token=preview.json['token']));assert commit.status_code==200,commit.data
    with transaction() as s:
        assert s['lots']['lote-azul']['length_m']==50
        assert s['component_lots']['lote-cadena']['quantity']==80
        assert any(p['id']=='nuevo-modelo' for p in s['config']['products'])
    assert post(client,'/inventory/import/commit',dict(token=preview.json['token'])).status_code==409
    assert post(client,'/inventory/import/commit',dict(token='alterado')).status_code==400


def test_excel_rejects_formula_bad_reference_and_stale_revision(client):
    client.get('/admin/interno/api/state')
    bad=workbook_bytes({'Telas':[['Código','Nombre','Precio'],['mala','=1+2',1000]]})
    assert upload(client,bad).status_code==400
    unknown=workbook_bytes({'Stock insumos':[['Código lote','Código insumo','Cantidad','Unidad'],['x','inexistente',5,'m']]})
    assert upload(client,unknown).status_code==400
    lot=post(client,'/component-lots',dict(component_id='tubo-32',quantity=10)).json['lot']
    raw=client.get('/admin/interno/api/inventory/export?scope=stock').data
    book=load_workbook(BytesIO(raw));book['Stock insumos']['C2']=15
    out=BytesIO();book.save(out)
    preview=upload(client,out.getvalue(),'stock');assert preview.status_code==200,preview.data
    assert post(client,'/component-lots/'+lot['id'],dict(revision=1,quantity=11,location='',reason='conteo')).status_code==200
    assert post(client,'/inventory/import/commit',dict(token=preview.json['token'])).status_code==409
    assert upload(client,out.getvalue(),'stock').status_code==400
    with transaction() as s:assert s['component_lots'][lot['id']]['quantity']==11
