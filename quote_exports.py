"""All client formats share the same commercial rows and stored payment totals."""
from io import BytesIO
from xml.sax.saxutils import escape
import zipfile
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.utils import ImageReader
from quoting import COLUMNS, commercial_rows
from storage import read_image

BLUE='#244574'


def currency(value):
    return f'{value:,.2f}'.replace(',','_').replace('.',',').replace('_','.')


def measurement(value):
    if not isinstance(value,(int,float)):
        return value
    from decimal import Decimal
    result=format(Decimal(str(value)),'f')
    if '.' in result:
        result=result.rstrip('0').rstrip('.')
    return result.replace('.',',')


def safe(value):
    # Excel text must never execute a customer-supplied formula.
    return "'"+value if isinstance(value,str) and value.startswith(('=','+','-','@')) else value


def xlsx(order,columns,bom=False,reservations=()):
    book=Workbook()
    sheet=book.active
    sheet.title='Despiece' if bom else 'Presupuesto'
    sheet.append([order['price_snapshot']['brand'].get('brand','BARÓN'),order['number']])
    sheet.append(['Cliente',safe(order['customer']),'Localidad',safe(order['city'])])
    sheet.append(['Fecha',order['date'],'Vigencia',order['valid_until']])
    sheet.append([])
    if bom:
        keys=['curtain','name','quantity','unit','unit_cost','subtotal','cut_width_cm','cut_height_cm','billable_quantity','price_unit','remnant_id']
        sheet.append(['Cortina','Material','Cantidad física','Unidad','Costo unitario','Subtotal costo','Ancho corte cm','Alto corte cm','Cantidad facturable','Unidad precio','Retazo elegido'])
        for l in order['bom']:
            sheet.append([safe(l.get(k,'')) for k in keys])
        curtains=book.create_sheet('Cortinas')
        curtains.append(['Cortina']+list(COLUMNS.values()))
        for i,u in enumerate(order['units'],1):
            curtains.append([i]+[safe(u[k]) for k in COLUMNS])
        summary=book.create_sheet('Resumen')
        summary.append(['Concepto','Importe'])
        summary.append(['Costo despiece',sum(l['subtotal'] for l in order['bom'])])
        summary.append(['Precio comercial',order['total']])
        if reservations:
            rs=book.create_sheet('Reservas')
            keys=['lot_id','line_id','length_m','quantity','unit','status','at']
            rs.append(['Lote','Línea','Largo m','Cantidad insumo','Unidad','Estado','Fecha'])
            for r in reservations:
                rs.append([safe(r.get(k,'')) for k in keys])
    else:
        sheet.append([COLUMNS[k]+(' (cm)' if k.endswith('_cm') else '') for k in columns])
        for row in commercial_rows(order):
            sheet.append([safe(row[k]) for k in columns])
        sheet.append([])
        if not order.get('government'):
            sheet.append(['Subtotal',order['subtotal']])
            sheet.append(['Descuento %',order['discount_pct']])
        if order.get('happy_adjustment_pct'):
            sheet.append(['Ajuste comercial incluido %',order['happy_adjustment_pct']])
        if not order.get('government'):sheet.append(['Total',order['total']])
        for k,v in order['payments'].items():
            sheet.append([k,v])
        if order.get('notes'):sheet.append(['Observaciones',safe(order['notes'])])
        brand=order['price_snapshot']['brand']
        sheet.append(['Ventas','280 50 111 99','Administración','280 49 713 41','ventas@barondeco.com.ar'])
    for ws in book:
        ws.freeze_panes='A6' if ws==sheet else 'A2'
        ws.sheet_view.showGridLines=False
        ws.print_options.horizontalCentered=True
        ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.page_setup.orientation='landscape'
        ws.page_setup.paperSize=ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth=1
        ws.page_setup.fitToHeight=0
        ws.print_title_rows='1:5' if ws==sheet else '1:1'
        for row in ws:
            for cell in row:
                cell.alignment=Alignment(vertical='top',wrap_text=True)
                if isinstance(cell.value,(int,float)):
                    cell.number_format='#,##0.00'
        header=5 if ws==sheet else 1
        for cell in ws[header]:
            cell.fill=PatternFill('solid',fgColor='244574')
            cell.font=Font(color='FFFFFF',bold=True)
        for col in ws.columns:
            length=max((len(str(c.value or '')) for c in col),default=12)
            ws.column_dimensions[get_column_letter(col[0].column)].width=min(45,max(13,length+2))
        ws.print_area=ws.dimensions
    if not bom:
        for row in sheet.iter_rows(min_row=6,max_row=5+len(commercial_rows(order))):
            for index,key in enumerate(columns):
                cell=row[index]
                if key in ('width_cm','height_cm') and isinstance(cell.value,(int,float)):
                    cell.number_format='0' if float(cell.value).is_integer() else '0.##########'
    output=BytesIO();book.save(output)
    return output.getvalue()


def pdf(order,columns):
    from pathlib import Path
    output=BytesIO();page_width,page_height=A4
    background=ImageReader(str(Path(__file__).parent/'static'/'brand'/'presupuesto-oficial.png'))
    def date_label(value):
        from datetime import date
        return date.fromisoformat(value).strftime('%d/%m/%Y') if value else ''
    def decorate(canvas,doc):
        canvas.saveState();canvas.drawImage(background,0,0,width=page_width,height=page_height)
        accessible=canvas.beginText(page_width-145,page_height-25);accessible.setFont('Helvetica-Bold',16);accessible.setTextRenderMode(3);accessible.textLine('PRESUPUESTO');accessible.setTextRenderMode(0);canvas.drawText(accessible)
        canvas.setFillColor(colors.black);canvas.setFont('Helvetica-Bold',9)
        canvas.drawString(377,page_height-133,'N° Presupuesto:')
        canvas.drawString(377,page_height-145,'Fecha desde:')
        canvas.drawString(377,page_height-157,'Válido hasta:')
        canvas.setFont('Helvetica',9)
        canvas.drawString(452,page_height-133,order['number'])
        canvas.drawString(444,page_height-145,date_label(order['date']))
        canvas.drawString(448,page_height-157,date_label(order['valid_until']))
        canvas.setFont('Helvetica',7);canvas.drawString(72,76,f'Página {doc.page}')
        canvas.restoreState()
    style=ParagraphStyle('cell',fontName='Helvetica',fontSize=7.5,leading=10,textColor=colors.black,wordWrap='LTR')
    heading=ParagraphStyle('head',parent=style,fontName='Helvetica-Bold',fontSize=10,leading=14)
    def para(value,sty=style):return Paragraph(escape(str(value)).replace('\n','<br/>'),sty)
    story=[para('Cliente: '+order['customer']+' · '+order['city']),Spacer(1,7)]
    data=[[para(COLUMNS[k],ParagraphStyle('th',parent=style,fontName='Helvetica-Bold')) for k in columns]]
    for row in commercial_rows(order):data.append([para(currency(row[k]) if k in ('unit_price','subtotal') else measurement(row[k]) if k in ('width_cm','height_cm') else row[k]) for k in columns])
    weights={'detail':2.5,'material':1.5,'room':1.2,'quantity':1.0,'width_cm':.9,'height_cm':.9,'color':1.1,'unit_price':1.25,'subtotal':1.25}
    total=sum(weights[k] for k in columns)
    table=Table(data,colWidths=[(page_width-144)*weights[k]/total for k in columns],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#d3d3d3')),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('GRID',(0,0),(-1,-1),.55,colors.HexColor('#555555')),('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.extend([table,Spacer(1,18)])
    labels={'Transferencia':'Total transferencia','Efectivo':'Pago Efectivo','Tarjeta':'Pago con Tarjeta','TOTAL PRESUPUESTO':'TOTAL PRESUPUESTO'}
    for payment_index,(name,value) in enumerate(order['payments'].items()):
        t=Table([[para(labels.get(name,name)+':',heading),para('$ '+currency(value),heading)]],colWidths=[140,80],hAlign='RIGHT')
        t.setStyle(TableStyle([('ALIGN',(1,0),(1,0),'RIGHT'),*(([('LINEABOVE',(0,0),(-1,0),.6,colors.black)]) if payment_index==0 else []),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.append(t)
    if order.get('notes'):story.extend([Spacer(1,12),para('Observaciones',heading),para(order['notes'])])
    SimpleDocTemplate(output,pagesize=A4,leftMargin=72,rightMargin=72,topMargin=190,bottomMargin=185).build(story,onFirstPage=decorate,onLaterPages=decorate)
    return output.getvalue()


def export_file(order,columns,kind,reservations=()):
    if kind in ('xlsx','bom'):
        return xlsx(order,columns,kind=='bom',reservations),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',('despiece.xlsx' if kind=='bom' else 'xlsx')
    if kind not in ('pdf','png','jpg'):
        raise ValueError('Formato de exportación no válido')
    raw=pdf(order,columns)
    if kind=='pdf':
        return raw,'application/pdf','pdf'
    import pymupdf
    doc=pymupdf.open(stream=raw,filetype='pdf')
    pages=[]
    for p in doc:
        pix=p.get_pixmap(matrix=pymupdf.Matrix(300/72,300/72),alpha=False)
        pages.append(pix.tobytes('jpeg' if kind=='jpg' else 'png'))
    doc.close()
    if len(pages)==1:
        return pages[0],('image/jpeg' if kind=='jpg' else 'image/png'),kind
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as bundle:
        for i,page in enumerate(pages,1):
            bundle.writestr(f'{order["number"]}-{i}.{kind}',page)
    return output.getvalue(),'application/zip',kind+'.zip'
