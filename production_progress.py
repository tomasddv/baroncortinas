"""Per-curtain production completion, independent of prices and physical stock."""
from copy import deepcopy

UNIT_FIELDS=('detail','room','width_cm','height_cm','material_id','color_id','material','color','tube','side','drop','zocalo','chain','mount','guides','product_id')
LINE_FIELDS=('name','curtain','quantity','unit','fabric','material_id','color_id','cut_width_cm','cut_height_cm','component_id','remnant_id')


def progress(order,curtain):
    value=order.get('curtain_progress',{}).get(str(curtain),{})
    return {k:value.get(k,default) for k,default in [('done',False),('revision',0),('at',''),('actor','')]}


def protect_completed(before,after):
    """Keep completed positions tied to the same technical unit until reopened."""
    for index,unit in enumerate(before['units'],1):
        if not progress(before,index)['done']:continue
        candidate=after['units'][index-1] if index<=len(after['units']) else {}
        same_unit=all(unit.get(k)==candidate.get(k) for k in UNIT_FIELDS)
        def lines(order):
            return [{k:l.get(k) for k in LINE_FIELDS} for l in order['bom'] if l['curtain']==index]
        if not same_unit or lines(before)!=lines(after):
            raise ValueError(f'La cortina {index} ya está realizada. Reabrila con confirmación antes de modificar su fabricación.')
    after['curtain_progress']=deepcopy(before.get('curtain_progress',{}))
