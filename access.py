"""Persistent credentials and live session authorization; no financial serializers here."""
import os,json,re,uuid
from flask import session,abort
from werkzeug.security import generate_password_hash,check_password_hash
from private_store import transaction
from quoting import audit,now,text
PERMISSIONS={
 'orders':'Visualizar pedidos aprobados','stock':'Visualizar stock','stock_add':'Agregar stock',
 'stock_edit':'Modificar stock','bom':'Visualizar despiece',
 'remnants':'Consultar retazos','remnants_edit':'Agregar y modificar retazos',
 'bom_export':'Exportar despiece a Excel sin precios','manufacturing':'Actualizar estados de fabricación',
 'contacts':'Visualizar datos de contacto de clientes'}
DEFAULTS=['orders','stock','stock_add','stock_edit']
def initialize(state):
    users=state.setdefault('users',{})
    # One-time import of existing hashed collaborators; environment remains compatible.
    if not state.get('legacy_users_imported'):
        for name,record in json.loads(os.environ.get('STAFF_USERS_JSON','{}')).items():
            if name not in users and record.get('password_hash'):
                users[name]=dict(id=uuid.uuid4().hex,username=name,role='staff',name=name,password_hash=record['password_hash'],enabled=True,version=1,permissions=list(DEFAULTS))
        state['legacy_users_imported']=now()
    desired=os.environ.get('ADMIN_USERNAME','LUCAS')
    if desired=='LUCAS' and 'dueno' in users and users['dueno']['role']=='owner':
        if 'LUCAS' in users:raise ValueError('Ya existe un usuario LUCAS; no se sobrescribe ninguna cuenta')
        user=users.pop('dueno');user.update(username='LUCAS',name='Lucas',version=user.get('version',0)+1)
        users['LUCAS']=user
        audit(state,'renombrar dueño','sistema',before_username='dueno',username='LUCAS')
    return users

def authenticate(username,password):
    with transaction() as state:
        users=initialize(state)
        record=users.get(username)
        # Bootstrap a named owner once, without keeping the environment password in DB.
        if not any(u['role']=='owner' for u in users.values()):
            expected=os.environ.get('ADMIN_PASSWORD','')
            import hmac
            ownername=os.environ.get('ADMIN_USERNAME','LUCAS')
            if ownername not in users and username in ('',ownername) and expected and hmac.compare_digest(password.encode(),expected.encode()):
                record=dict(id=uuid.uuid4().hex,username=ownername,name='Dueño',role='owner',enabled=True,version=1,permissions=list(PERMISSIONS),password_hash=generate_password_hash(password))
                users[ownername]=record;audit(state,'crear dueño inicial',ownername)
        if not record or not record['enabled'] or not check_password_hash(record['password_hash'],password):return None
        return {k:record[k] for k in ('username','role','version')}

def live_session():
    if not session.get('admin_auth'):return
    with transaction() as state:
        users=initialize(state)
        record=users.get(session.get('user'))
        # Older owner sessions remain usable until a named owner has been created.
        if not record and session.get('role','owner')=='owner' and not any(u['role']=='owner' for u in users.values()):return
        if not record or not record['enabled'] or record['version']!=session.get('version'):
            session.clear();return
        session['role']=record['role']

def allowed(key):
    if session.get('role')=='owner':return True
    with transaction() as state:
        u=initialize(state).get(session.get('user'),{})
        return bool(u.get('enabled') and u.get('version')==session.get('version') and key in u.get('permissions',[]))
def require(key):
    if not allowed(key):abort(403)
def public_user(u):
    return {k:([p for p in v if p in PERMISSIONS] if k=='permissions' else v) for k,v in u.items() if k!='password_hash'}

def write_user(state,data,actor):
    users=initialize(state);name=text(data.get('username',''),60)
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,60}',name):raise ValueError('Usuario: 3 a 60 letras, números, punto, guión o guión bajo')
    old=users.get(name)
    if data.get('create') and old:raise ValueError('Ese nombre de usuario ya existe')
    role=old['role'] if old else 'staff'
    perms=data.get('permissions',[p for p in old.get('permissions',DEFAULTS) if p in PERMISSIONS] if old else DEFAULTS)
    if not isinstance(perms,list) or set(perms)-PERMISSIONS.keys():raise ValueError('Permisos inválidos')
    password=data.get('password','')
    if password and (not isinstance(password,str) or not 10<=len(password)<=200):raise ValueError('Contraseña: entre 10 y 200 caracteres')
    if not old and not password:raise ValueError('Establecé una contraseña')
    enabled=data.get('enabled',True) is True
    if role=='owner' and not enabled and sum(u['role']=='owner' and u['enabled'] for u in users.values())<=1:raise ValueError('Conservá al menos un dueño habilitado')
    record=dict(old or {},id=old['id'] if old else uuid.uuid4().hex,username=name,name=text(data.get('name',name),100),role=role,enabled=enabled,
        permissions=list(PERMISSIONS) if role=='owner' else perms,version=(old.get('version',0) if old else 0)+1)
    if password:record['password_hash']=generate_password_hash(password)
    users[name]=record
    audit(state,'actualizar usuario' if old else 'crear usuario',actor,username=name,enabled=enabled,permissions=perms,password_reset=bool(password))
    return public_user(record)
