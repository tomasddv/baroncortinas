"""Bounded XLSX exchange with an authenticated, signed preview before applying."""
from copy import deepcopy
from datetime import date,datetime
from io import BytesIO
import hashlib
import json
import re
import uuid
import zipfile
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
from quoting import num,text,now,available,validate_config,audit
from inventory import validate_inventory_catalogue,reconcile_prices,component_available
from quote_exports import safe

HEADERS={
 'Telas':['Código','Nombre','Familia','Precio','Unidad precio','Ancho rollo cm','Activa','Eliminada'],
 'Colores':['Código tela','Código color','Color','Hex','Precio especial'],
 'Insumos':['Código','Nombre','Categoría','Unidad','Costo unitario','Stock mínimo','Activo','Control stock','Eliminado'],
 'Productos':['Código','Nombre','Regla precio','Valor regla','Requiere tela','Extra alto cm','Multiplicador ancho tela','Activo','Eliminado'],
 'Recetas':['Código producto','Código insumo','Regla cantidad','Factor'],
 'Stock telas':['Código lote','Código tela','Código color','Tipo','Ancho cm','Largo m','Ubicación','Origen','Mínimo m','Revisión','Reservado m','Disponible m'],
 'Stock insumos':['Código lote','Código insumo','Cantidad','Unidad','Ubicación','Origen','Revisión','Reservado','Disponible']}
CATALOGUE=['Telas','Colores','Insumos','Productos','Recetas']


def scope_sheets(scope):
    if scope not in ('todo','catalogo','stock'):raise ValueError('Elegí catálogo, stock o todo')
    return list(HEADERS) if scope=='todo' else CATALOGUE if scope=='catalogo' else ['Stock telas','Stock insumos']


def export_inventory(state,scope='todo',template=False):
    cfg=state['config'];data={k:[] for k in HEADERS}
    yes=lambda v:'sí' if v else 'no'
    for m in cfg['materials']:
        data['Telas'].append([m['id'],m['name'],m['family'],m['price'],m['price_unit'],m['roll_width_cm'],yes(m.get('active',True)),yes(m.get('deleted',False))])
        for c in m['colors']:data['Colores'].append([m['id'],c['id'],c['name'],c.get('hex',''),c.get('price_override','')])
    for c in cfg['stock_components']:
        data['Insumos'].append([c['id'],c['name'],c['category'],c['unit'],c['unit_cost'],c.get('minimum_qty',0),yes(c.get('active',True)),yes(c.get('track_stock',False)),yes(c.get('deleted',False))])
    for p in cfg['products']:
        data['Productos'].append([p['id'],p['name'],p['calculation'],p.get('price_value',0),yes(p.get('requires_fabric',True)),p.get('extra_height_cm',0),p.get('fabric_width_multiplier',1),yes(p.get('active',True)),yes(p.get('deleted',False))])
        for r in p.get('recipes',[]):data['Recetas'].append([p['id'],r['component_id'],r['mode'],r['factor']])
    for l in state['lots'].values():
        free=available(state,l)
        data['Stock telas'].append([l['id'],l['material_id'],l['color_id'],l['kind'],l['width_cm'],l['length_m'],l['location'],l['origin'],l.get('minimum_m',0),l.get('revision',1),round(l['length_m']-free,6),free])
    for l in state['component_lots'].values():
        free=component_available(state,l)
        data['Stock insumos'].append([l['id'],l['component_id'],l['quantity'],l['unit'],l['location'],l['origin'],l['revision'],round(l['quantity']-free,6),free])
    book=Workbook();book.remove(book.active)
    for name in scope_sheets(scope):
        ws=book.create_sheet(name);ws.append(HEADERS[name])
        if not template:
            for row in data[name]:ws.append([safe(v) for v in row])
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions;ws.sheet_view.showGridLines=False
        for c in ws[1]:c.fill=PatternFill('solid',fgColor='244574');c.font=Font(color='FFFFFF',bold=True)
        for col in range(1,len(HEADERS[name])+1):
            ws.column_dimensions[get_column_letter(col)].width=24 if 'Nombre' not in HEADERS[name][col-1] else 35
        for row in ws:
            for c in row:
                c.alignment=Alignment(vertical='top',wrap_text=True)
                if isinstance(c.value,(int,float)):c.number_format='#,##0.00'
                elif 'Código' in HEADERS[name][c.column-1]:c.number_format='@'
        ws.page_setup.orientation='landscape';ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0;ws.print_title_rows='1:1'
    guide=book.create_sheet('Instrucciones')
    instructions=[['Carga por lote BARÓN'],['1. Conservá encabezados y códigos existentes. Los códigos vacíos crean registros nuevos.'],
      ['2. Las cantidades de stock son existencias totales del lote, no entradas que se suman.'],
      ['3. Para modificar un lote existente conservá su Revisión. No se pisa stock reservado.'],
      ['4. Reservado y Disponible se calculan en la app; no se importan.'],
      ['5. No borres filas para eliminar registros: usá Eliminada/Eliminado = sí. Se conservan referencias.'],
      ['6. Para unir hojas usá códigos de tela, color, insumo y producto. No uses fórmulas.'],
      ['Familias de tela','sunscreen, blackout, traslucida, tela'],['Unidades tela','m2, metro_lineal'],
      ['Categorías insumos','caño, cadena, sistema, zócalo, guía, soporte, accesorio, otro'],['Unidades insumos','m, m², unidad, par'],
      ['Reglas de precio','materiales, m2, metro_ancho, fijo; roller es el modelo existente'],
      ['Reglas de cantidad en recetas','fijo, ancho_m, alto_m, area_m2, perimetro_m'],
      ['Booleanos','sí / no'],['Colores','Precio especial vacío hereda el precio de tela.'],
      ['Recetas','Se agregan o actualizan por producto + insumo + regla. Para quitar una línea usá la app.'],
      ['Datos existentes','Las hojas o filas omitidas se conservan. Siempre revisá la vista previa antes de aplicar.']]
    for row in instructions:guide.append(row)
    guide.column_dimensions['A'].width=100;guide.column_dimensions['B'].width=75
    out=BytesIO();book.save(out);return out.getvalue()


def read_inventory(raw,filename,scope):
    if not filename.lower().endswith('.xlsx') or not raw.startswith(b'PK') or len(raw)>3_000_000:raise ValueError('Subí un Excel .xlsx de hasta 3 MB')
    try:
        with zipfile.ZipFile(BytesIO(raw)) as z:
            if len(z.infolist())>3000 or sum(i.file_size for i in z.infolist())>25_000_000 or any('vbaproject' in i.filename.lower() for i in z.infolist()):raise ValueError('El Excel es demasiado grande o contiene macros')
        book=load_workbook(BytesIO(raw),read_only=True,data_only=False,keep_links=False)
        rows={};count=0
        for name in scope_sheets(scope):
            if name not in book.sheetnames:continue
            ws=book[name]
            if ws.max_row>5001 or ws.max_column>30:raise ValueError(name+': máximo 5000 filas y 30 columnas')
            it=ws.iter_rows();header=[str(c.value or '').strip() for c in next(it)]
            if len(header)!=len(set(header)):raise ValueError(name+': encabezados repetidos')
            required=HEADERS[name][:2]
            if not set(required).issubset(header):raise ValueError(name+': usá los encabezados de la plantilla BARÓN')
            records=[]
            for index,cells in enumerate(it,2):
                if all(c.value is None for c in cells):continue
                record={'_fila':index}
                for key,c in zip(header,cells):
                    if c.data_type=='f':raise ValueError(f'{name} fila {index}: reemplazá las fórmulas por valores')
                    v=c.value
                    if isinstance(v,(date,datetime)):v=v.isoformat()
                    if key in HEADERS[name]:record[key]=v
                records.append(record);count+=1
                if count>5000:raise ValueError('Máximo 5000 filas en total por importación')
            rows[name]=records
        book.close()
        if not count:raise ValueError('No hay filas para importar en las hojas seleccionadas')
        return rows
    except ValueError:raise
    except Exception as exc:raise ValueError('No se pudo leer el Excel. Usá la plantilla .xlsx de BARÓN') from exc


def fingerprint(state):
    relevant={k:state.get(k) for k in ['config','lots','component_lots','reservations']}
    return hashlib.sha256(json.dumps(relevant,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def code(value,prefix):
    value=text(str(value if value is not None else ''),100)
    if not value:return prefix+'-'+uuid.uuid4().hex[:12]
    if not re.fullmatch(r'[\w.-]+',value):raise ValueError('Los códigos admiten letras, números, guión y punto, sin espacios')
    return value


def boolean(value,default):
    if value is None or value=='':return default
    v=str(value).lower().strip()
    if v in ('sí','si','true','1','yes'):return True
    if v in ('no','false','0'):return False
    raise ValueError('Usá sí o no en las columnas de activación')


def apply_inventory(state,rows,actor):
    previous=deepcopy(state['config']);cfg=state['config'];changes=[]
    def record(kind,ident,before,after):
        if before==after:return
        def summary(x):
            if not x:return '—'
            labels={'name':'Nombre','family':'Familia','price':'Precio','price_unit':'Unidad precio',
                'roll_width_cm':'Ancho rollo cm','active':'Activo','deleted':'Eliminado','hex':'Color HEX',
                'price_override':'Precio especial','category':'Categoría','unit':'Unidad','unit_cost':'Costo',
                'minimum_qty':'Mínimo','track_stock':'Control stock','calculation':'Regla precio',
                'price_value':'Valor regla','requires_fabric':'Requiere tela','extra_height_cm':'Extra alto cm',
                'fabric_width_multiplier':'Multiplicador ancho','component_id':'Código insumo','mode':'Regla cantidad',
                'factor':'Factor','material_id':'Código tela','color_id':'Código color','kind':'Tipo',
                'width_cm':'Ancho cm','length_m':'Largo m','quantity':'Cantidad','location':'Ubicación','origin':'Origen'}
            return ' · '.join(labels[k]+': '+str(v) for k,v in x.items() if k in labels)
        changes.append(dict(tipo=kind,codigo=ident,accion='Crear' if before is None else 'Actualizar',antes=summary(before),despues=summary(after)))
    def numeric(row,key,old,default=0):return num(row[key] if row.get(key) is not None else old.get(key,default),key)
    seen=set()
    for sheet in HEADERS:
      for row in rows.get(sheet,[]):
        try:
            if sheet in ('Telas','Insumos','Productos'):
                container=cfg['materials' if sheet=='Telas' else 'stock_components' if sheet=='Insumos' else 'products']
                ident=code(row.get('Código'),'mat' if sheet=='Telas' else 'ins' if sheet=='Insumos' else 'prod')
                row['Código']=ident
                if (sheet,ident) in seen:raise ValueError('Código repetido en el archivo')
                seen.add((sheet,ident));old=next((x for x in container if x['id']==ident),None);item=deepcopy(old or {'id':ident})
                item['name']=text(str(row.get('Nombre') or ''),100)
                if not item['name']:raise ValueError('Falta el nombre')
                if sheet=='Telas':
                    item.update(family=row.get('Familia') or item.get('family','sunscreen'),price=num(row.get('Precio',item.get('price',0)),'Precio'),
                        price_unit=row.get('Unidad precio') or item.get('price_unit','m2'),roll_width_cm=num(row.get('Ancho rollo cm') or item.get('roll_width_cm',280),'Ancho',20,600),
                        active=boolean(row.get('Activa'),item.get('active',True)),deleted=boolean(row.get('Eliminada'),item.get('deleted',False)))
                    item.setdefault('colors',[])
                elif sheet=='Insumos':
                    item.update(category=row.get('Categoría') or item.get('category','otro'),unit=row.get('Unidad') or item.get('unit','unidad'),
                        unit_cost=num(row.get('Costo unitario',item.get('unit_cost',0)),'Costo'),minimum_qty=num(row.get('Stock mínimo',item.get('minimum_qty',0)),'Mínimo'),
                        active=boolean(row.get('Activo'),item.get('active',True)),track_stock=boolean(row.get('Control stock'),item.get('track_stock',False)),deleted=boolean(row.get('Eliminado'),item.get('deleted',False)))
                    if old and item['unit']!=old['unit'] and any(l['component_id']==ident for l in state['component_lots'].values()):raise ValueError('El insumo tiene stock; no cambies su unidad')
                else:
                    item.update(calculation=row.get('Regla precio') or item.get('calculation','fijo'),price_value=num(row.get('Valor regla',item.get('price_value',0)),'Valor'),
                        requires_fabric=boolean(row.get('Requiere tela'),item.get('requires_fabric',True)),extra_height_cm=num(row.get('Extra alto cm',item.get('extra_height_cm',0)),'Extra alto',0,300),
                        fabric_width_multiplier=num(row.get('Multiplicador ancho tela',item.get('fabric_width_multiplier',1)),'Multiplicador',0.01,10),
                        active=boolean(row.get('Activo'),item.get('active',True)),deleted=boolean(row.get('Eliminado'),item.get('deleted',False)))
                    item.setdefault('recipes',[])
                if item.get('deleted'):item['active']=False
                record(sheet,ident,old,item)
                if old:container[container.index(old)]=item
                else:container.append(item)
            elif sheet=='Colores':
                m=next((m for m in cfg['materials'] if m['id']==str(row.get('Código tela'))),None)
                if not m:raise ValueError('Código de tela inexistente')
                ident=code(row.get('Código color'),'color');row['Código color']=ident
                if (sheet,m['id'],ident) in seen:raise ValueError('Color repetido')
                seen.add((sheet,m['id'],ident));old=next((c for c in m['colors'] if c['id']==ident),None);c=deepcopy(old or {'id':ident})
                c.update(name=text(str(row.get('Color') or ''),100),hex=row.get('Hex') or c.get('hex','#f6f4ee'))
                if 'Precio especial' in row:
                    if row['Precio especial'] is None or row['Precio especial']=='':c.pop('price_override',None)
                    else:c['price_override']=num(row['Precio especial'],'Precio especial')
                record(sheet,m['id']+'/'+ident,old,c)
                if old:m['colors'][m['colors'].index(old)]=c
                else:m['colors'].append(c)
            elif sheet=='Recetas':
                p=next((p for p in cfg['products'] if p['id']==str(row.get('Código producto'))),None)
                if not p:raise ValueError('Código de producto inexistente')
                r=dict(component_id=str(row.get('Código insumo') or ''),mode=row.get('Regla cantidad') or 'fijo',factor=num(row.get('Factor',1),'Factor'))
                key=(sheet,p['id'],r['component_id'],r['mode'])
                if key in seen:raise ValueError('Línea de receta repetida')
                seen.add(key);old=next((x for x in p['recipes'] if x['component_id']==r['component_id'] and x['mode']==r['mode']),None)
                record(sheet,p['id']+'/'+r['component_id'],old,r)
                if old:p['recipes'][p['recipes'].index(old)]=r
                else:p['recipes'].append(r)
            else:
                fabric=sheet=='Stock telas';container=state['lots'] if fabric else state['component_lots']
                ident=code(row.get('Código lote'),'lote' if fabric else 'ins-lote');row['Código lote']=ident
                if (sheet,ident) in seen:raise ValueError('Lote repetido')
                seen.add((sheet,ident));old=container.get(ident);item=deepcopy(old or {'id':ident,'revision':1})
                if old and num(row.get('Revisión'),'Revisión',1,1e9)!=old.get('revision',1):raise ValueError('Revisión desactualizada; exportá el stock actual antes de modificarlo')
                if fabric:
                    m=next((m for m in cfg['materials'] if m['id']==str(row.get('Código tela'))),None)
                    if not m or str(row.get('Código color')) not in [c['id'] for c in m['colors']]:raise ValueError('Tela o color inexistentes')
                    kind=row.get('Tipo') or item.get('kind','rollo')
                    if kind not in ('rollo','retazo'):raise ValueError('Tipo debe ser rollo o retazo')
                    item.update(material_id=m['id'],color_id=str(row['Código color']),kind=kind,width_cm=num(row.get('Ancho cm'),'Ancho',1,600),length_m=num(row.get('Largo m'),'Largo',0,10000),minimum_m=num(row.get('Mínimo m',item.get('minimum_m',0)) or 0,'Mínimo'))
                    item.setdefault('status','disponible')
                    if not old or item['length_m']!=old['length_m']:item['status']='disponible' if item['length_m'] else 'consumido'
                    if old and any(item[k]!=old[k] for k in ['material_id','color_id','kind']):raise ValueError('No cambies la identidad del lote existente; creá otro código')
                else:
                    c=next((c for c in cfg['stock_components'] if c['id']==str(row.get('Código insumo'))),None)
                    if not c:raise ValueError('Insumo inexistente')
                    unit=row.get('Unidad') or c['unit']
                    if unit!=c['unit']:raise ValueError('La unidad no coincide con el insumo')
                    item.update(component_id=c['id'],quantity=num(row.get('Cantidad'),'Cantidad',0,1e8),unit=unit)
                    if old and item['component_id']!=old['component_id']:raise ValueError('No cambies el insumo de un lote existente')
                    c['track_stock']=True
                item.update(location=text(str(row.get('Ubicación',item.get('location','')) or ''),150),origin=text(str(row.get('Origen',item.get('origin','')) or ''),200))
                if old and item!=old:
                    reserved=old['length_m']-available(state,old) if fabric else old['quantity']-component_available(state,old)
                    if fabric and reserved>0:raise ValueError('El lote tiene reservas; liberá el pedido antes de ajustarlo')
                    if not fabric and item['quantity']<reserved:raise ValueError('La cantidad no alcanza a cubrir las reservas')
                    item['revision']=old.get('revision',1)+1
                record(sheet,ident,old,item)
                if old!=item:
                    delta=item['length_m']-(old['length_m'] if old else 0) if fabric else item['quantity']-(old['quantity'] if old else 0)
                    state['movements'].append(dict(at=now(),actor=actor,event='importación Excel',lot_id=ident,**({'length_m':delta} if fabric else {'quantity':delta,'unit':item['unit']})))
                container[ident]=item
        except (ValueError,KeyError,TypeError) as exc:
            raise ValueError(f'{sheet}, fila {row.get("_fila","?")}: {exc}') from exc
    validate_config(cfg);validate_inventory_catalogue(cfg);reconcile_prices(previous,cfg)
    return changes
