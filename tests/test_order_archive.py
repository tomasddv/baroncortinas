from copy import deepcopy
from test_internal import client, post, save
from private_store import transaction


def test_archive_restore_preserves_budget(client):
    order=save(client)
    base='/orders/'+order['id']
    assert post(client,base+'/archive',dict(revision=order['revision'])).status_code==400
    assert post(client,base+'/archive',dict(revision=0,confirm=True)).status_code==409
    assert post(client,base+'/archive',dict(revision=order['revision'],confirm=True)).status_code==200
    state=client.get('/admin/interno/api/state').json
    assert not state['orders']
    archived=state['archived_orders'][0]
    for suffix in ('','/export/pdf','/export/xlsx','/preview'):
        assert client.get('/admin/interno/api'+base+suffix).status_code==404
    assert post(client,base+'/duplicate',{}).status_code==404
    assert post(client,base+'/restore',dict(revision=0,confirm=True)).status_code==409
    assert post(client,base+'/restore',dict(revision=archived['revision'],confirm=True)).status_code==200
    restored=client.get('/admin/interno/api'+base).json['order']
    for key in ('id','number','total','groups','bom','price_snapshot'):
        assert restored[key]==order[key]
    assert restored['status']=='presupuesto'
    assert not client.get('/admin/interno/api/state').json['archived_orders']


def test_archive_approved_releases_reservations_preserves_progress(client):
    from test_upgrade import approve
    order=approve(client)
    with transaction() as state:
        saved=state['orders'][order['id']]
        saved['curtain_progress']={'1':dict(done=True,revision=1)}
        physical=deepcopy(state['lots'])
    assert post(client,'/orders/'+order['id']+'/archive',dict(revision=order['revision'],confirm=True)).status_code==200
    with transaction() as state:
        saved=state['orders'][order['id']]
        assert saved['curtain_progress']['1']['done']
        assert not any(r['order_id']==order['id'] and r['status']=='reservado' for r in state['reservations'])
        assert {k:v['length_m'] for k,v in state['lots'].items()}=={k:v['length_m'] for k,v in physical.items()}
    assert not client.get('/admin/operativo/api/state').json['orders']

def test_staff_cannot_archive_or_restore(client):
    from test_upgrade import collaborator
    order=save(client)
    staff=collaborator(client)
    for action in ('archive','restore'):
        assert post(staff,'/orders/'+order['id']+'/'+action,dict(revision=order['revision'],confirm=True)).status_code==403
