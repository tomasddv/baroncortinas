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
from quoting import COLUMNS, commercial_rows, client_measurement_note
from storage import read_image

BLUE='#244574'


def currency(value):
    return f'{value:,.2f}'.replace(',','_').replace('.',',').replace('_','.')


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
    sheet.append(['Medidas',client_measurement_note(order)] if not bom and order.get('mentirita') else [])
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
            keys=['lot_id','line_id','length_m','status','at']
            rs.append(['Lote','Línea','Largo m','Estado','Fecha'])
            for r in reservations:
                rs.append([safe(r[k]) for k in keys])
    else:
        sheet.append([COLUMNS[k]+(' (cm)' if k.endswith('_cm') else '') for k in columns])
        for row in commercial_rows(order):
            sheet.append([safe(row[k]) for k in columns])
        sheet.append([])
        sheet.append(['Subtotal',order['subtotal']])
        sheet.append(['Descuento %',order['discount_pct']])
        if order.get('happy_adjustment_pct'):
            sheet.append(['Ajuste comercial incluido %',order['happy_adjustment_pct']])
        sheet.append(['Total',order['total']])
        for k,v in order['payments'].items():
            sheet.append([k,v])
        sheet.append(['Observaciones',safe(order['notes'])])
        brand=order['price_snapshot']['brand']
        sheet.append(['Contacto',safe(brand.get('whatsapp','')),safe(brand.get('email',''))])
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
    output=BytesIO();book.save(output)
    return output.getvalue()


def pdf(order,columns):
    output=BytesIO()
    brand=order['price_snapshot']['brand']
    logo=None
    if brand.get('brand_logo'):
        try:
            logo=ImageReader(BytesIO(read_image(brand['brand_logo'])))
        except (OSError,ValueError,RuntimeError):
            pass
    page_width,page_height=A4
    def decorate(canvas,doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(BLUE))
        canvas.rect(page_width-240,page_height-48,240,48,fill=1,stroke=0)
        canvas.setFillColor(colors.white);canvas.setFont('Helvetica-Bold',17)
        canvas.drawString(page_width-222,page_height-31,'PRESUPUESTO')
        if logo:
            canvas.drawImage(logo,35,page_height-112,width=100,height=70,preserveAspectRatio=True,mask='auto')
            canvas.saveState();canvas.setFillAlpha(.045)
            canvas.drawImage(logo,page_width-220,75,width=180,height=180,preserveAspectRatio=True,mask='auto')
            canvas.restoreState()
        else:
            canvas.setFillColor(colors.HexColor(BLUE));canvas.drawString(35,page_height-80,brand.get('brand','BARÓN'))
        canvas.setFillColor(colors.HexColor(BLUE));canvas.rect(0,0,page_width,47,fill=1,stroke=0)
        canvas.setFillColor(colors.white);canvas.setFont('Helvetica',9)
        contact=' · '.join(str(brand[k]) for k in ('whatsapp','email','address') if brand.get(k))
        canvas.drawString(35,27,contact[:100])
        canvas.drawString(35,12,brand.get('brand','BARÓN'))
        canvas.drawRightString(page_width-30,12,f'Página {doc.page}')
        canvas.restoreState()
    style=ParagraphStyle('cell',fontName='Helvetica',fontSize=8,leading=11,textColor=colors.HexColor('#162334'),wordWrap='CJK')
    heading=ParagraphStyle('head',parent=style,fontName='Helvetica-Bold',fontSize=11,leading=15)
    white=ParagraphStyle('white',parent=style,textColor=colors.white,fontName='Helvetica-Bold')
    def para(value,sty=style):
        return Paragraph(escape(str(value)).replace('\n','<br/>'),sty)
    story=[para(order['number'],heading),para('Fecha: '+order['date']+' · Válido hasta: '+order['valid_until']),
           para('Cliente: '+order['customer']+' · '+order['city']),Spacer(1,18)]
    if order.get('mentirita'):
        story.extend([para(client_measurement_note(order)),Spacer(1,10)])
    data=[[para(COLUMNS[k]+(' cm' if k.endswith('_cm') else ''),white) for k in columns]]
    for row in commercial_rows(order):
        data.append([para(currency(row[k]) if k in ('unit_price','subtotal') else row[k]) for k in columns])
    weights={'detail':2.5,'material':1.5,'room':1.2,'quantity':.65,'width_cm':.9,'height_cm':.9,'color':1.1,'unit_price':1.25,'subtotal':1.25}
    total=sum(weights[k] for k in columns)
    table=Table(data,colWidths=[(page_width-60)*weights[k]/total for k in columns],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor(BLUE)),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cbd4de')),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.extend([table,Spacer(1,18),para(f'Subtotal: $ {currency(order["subtotal"])} · Descuento: {order["discount_pct"]:g}%')])
    if order.get('happy_adjustment_pct'):
        story.append(para(f'Ajuste comercial incluido: {order["happy_adjustment_pct"]:g}%'))
    for name,value in order['payments'].items():
        story.append(para(f'{name}: $ {currency(value)}',heading))
    if order['notes']:
        story.extend([Spacer(1,12),para(order['notes'])])
    SimpleDocTemplate(output,pagesize=A4,leftMargin=30,rightMargin=30,topMargin=130,bottomMargin=70).build(story,onFirstPage=decorate,onLaterPages=decorate)
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
        pix=p.get_pixmap(matrix=pymupdf.Matrix(1.7,1.7),alpha=False)
        pages.append(pix.tobytes('jpeg' if kind=='jpg' else 'png'))
    doc.close()
    if len(pages)==1:
        return pages[0],('image/jpeg' if kind=='jpg' else 'image/png'),kind
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as bundle:
        for i,page in enumerate(pages,1):
            bundle.writestr(f'{order["number"]}-{i}.{kind}',page)
    return output.getvalue(),'application/zip',kind+'.zip'
