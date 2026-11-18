'use strict';
let settingsDraft=null,configDirty=false,extraDraft=null;
function settingsChanged(){configDirty=true;const status=$('#settings-save-status');if(status)status.textContent='Cambios sin guardar';}
function configField(label,object,key,type='number',options=null,extra={}){
 return field(label,object[key],value=>{object[key]=value;settingsChanged();},options,type,{step:'any',min:0,...extra});
}
function renderSettings(){
 const root=$('#settings-fields');if(!root)return;
 if(!configDirty||!settingsDraft){settingsDraft=clone(state.config);configOriginal=clone(state.config);extraDraft=Object.fromEntries(['zocalo','chain','mount'].map(k=>[k,Object.entries(settingsDraft.extras[k]).map(([name,price])=>({name,price,existing:true}))]));}
 root.replaceChildren();const cfg=settingsDraft;
 function section(title,description,open=false){const details=el('details',{class:'card settings-section',open},[el('summary',{text:title}),el('p',{text:description})]);root.append(details);return details;}
 const general=section('Precios y formas de pago','Importes en pesos argentinos. Los ajustes de pago se expresan como porcentaje.',true),grid=el('div',{class:'grid'});
 for(const [key,label]of [['markup_pct','Recargo comercial %'],['tax_pct','Impuestos %']])grid.append(configField(label,cfg,key,'number',null,{max:1000,required:true}));
 for(const name of ['Transferencia','Efectivo','Tarjeta'])grid.append(configField(name+' ajuste %',cfg.payments,name,'number',null,{min:-100,max:1000,required:true}));
 grid.append(check('Reglas comerciales revisadas por el dueño',cfg.confirmed,c=>{cfg.confirmed=c.checked;settingsChanged();}));general.append(grid);
 const rules=section('Medidas, consumo y stock','Las medidas de corte se calculan a partir de las medidas solicitadas y estas reglas.'),rulesGrid=el('div',{class:'grid'});
 for(const [key,label,max]of [['min_billable_m2','Mínimo facturable m²',100000],['min_linear_m','Mínimo facturable metros lineales',100000],['width_reduction_cm','Descuento de ancho de tela cm',20],['stock_min_m','Alerta mínima de stock m',100000],['guides_price_m','Precio de guías por metro de alto',100000000]])rulesGrid.append(configField(label,cfg,key,'number',null,{max,required:true}));
 rules.append(rulesGrid);
 const tubes=section('Caños y sistemas','Precio del caño por metro, sistema por cortina y tela adicional en centímetros.');
 for(const size of ['32','42','45','58']){const box=el('div',{class:'settings-item settings-tube','data-tube':size},[el('h3',{text:'Caño '+size+' mm'})]),fields=el('div',{class:'grid'});for(const[key,label]of [['price_m','Precio del caño por metro'],['system_price','Precio del sistema por cortina'],['extra_cm','Tela adicional de alto cm']])fields.append(configField(label,cfg.tubes[size],key,'number',null,{required:true,max:100000000}));box.append(fields);tubes.append(box);}
 const fabrics=section('Telas y colores','Editá precios, anchos y colores. Desactivar una tela conserva su registro y los presupuestos anteriores.');
 const materialList=el('div');fabrics.append(materialList);
 function drawMaterials(){materialList.replaceChildren();for(const m of cfg.materials){
  const summary=el('summary',{text:m.name+(m.active===false?' · Inactiva':'')}),box=el('details',{class:'settings-material settings-item','data-material-id':m.id},[summary]),fields=el('div',{class:'grid'});
  fields.append(field('Nombre de tela',m.name,v=>{m.name=v;summary.textContent=v+(m.active===false?' · Inactiva':'');settingsChanged();},null,'text',{required:true,maxLength:100}));
  fields.append(configField('Tipo de tela',m,'family','text',[['sunscreen','Screen'],['blackout','Blackout'],['traslucida','Traslúcida'],['tela','Tela tradicional']],{required:true}));
  fields.append(configField('Precio de tela',m,'price','number',null,{required:true}));
  fields.append(configField('Unidad de precio',m,'price_unit','text',[['m2','Metro cuadrado (m²)'],['metro_lineal','Metro lineal']],{required:true}));
  fields.append(configField('Ancho nominal del rollo cm',m,'roll_width_cm','number',null,{min:20,max:600,required:true}));
  fields.append(check('Tela activa',m.active!==false,c=>{m.active=c.checked;summary.textContent=m.name+(m.active===false?' · Inactiva':'');settingsChanged();}));box.append(fields);
  const colors=el('div',{class:'settings-colors'});box.append(el('h4',{text:'Colores disponibles'}),colors);
  function drawColors(){colors.replaceChildren();for(const c of m.colors){
   const row=el('div',{class:'settings-color grid'});row.append(configField('Nombre del color',c,'name','text',null,{required:true,maxLength:100}));
   const hex=/^#[a-fA-F0-9]{6}$/.test(c.hex||'')?c.hex:'#f6f4ee';row.append(field('Muestra de color',hex,v=>{c.hex=v;settingsChanged();},null,'color'));
   const special=el('input',{type:'number',min:0,step:'any',value:c.price_override??'','aria-label':'Precio especial del color',placeholder:'Usar precio de tela',oninput:()=>{if(special.value==='')delete c.price_override;else c.price_override=Number(special.value);settingsChanged();}});
   row.append(el('label',{},[document.createTextNode('Precio especial del color'),special,el('small',{class:'muted',text:'Vacío: usa el precio de la tela.'})]));colors.append(row);
  }}drawColors();
  box.append(el('button',{type:'button',class:'secondary',text:'＋ Agregar color',onclick:()=>{m.colors.push({id:'color-'+crypto.randomUUID().slice(0,12),name:'Nuevo color',hex:'#f6f4ee'});settingsChanged();drawColors();}}));materialList.append(box);
 }}drawMaterials();
 fabrics.append(el('button',{type:'button',class:'secondary',text:'＋ Agregar tela',onclick:()=>{cfg.materials.push({id:'mat-'+crypto.randomUUID().slice(0,12),name:'Nueva tela',family:'sunscreen',price:0,price_unit:'m2',roll_width_cm:280,colors:[],active:true});settingsChanged();drawMaterials();materialList.lastElementChild.open=true;}}));
 const extras=section('Zócalos, cadenas y soportes','Los zócalos se cobran por metro de ancho; cadenas y soportes, por cortina. Los nombres guardados se conservan para los pedidos existentes.');
 for(const[key,label]of [['zocalo','Zócalos'],['chain','Cadenas'],['mount','Soportes']]){
  const box=el('div',{class:'settings-item','data-extra-kind':key},[el('h3',{text:label})]),rows=el('div');
  function drawExtras(){rows.replaceChildren();if(!extraDraft[key].length)rows.append(el('p',{class:'muted',text:'No hay adicionales configurados.'}));for(const item of extraDraft[key]){const row=el('div',{class:'settings-extra grid'});row.append(configField('Nombre del adicional',item,'name','text',null,{required:true,maxLength:100,readOnly:item.existing}));row.append(configField('Precio del adicional',item,'price','number',null,{required:true}));if(!item.existing)row.append(el('button',{type:'button',class:'danger',text:'Quitar nuevo adicional',onclick:()=>{extraDraft[key]=extraDraft[key].filter(x=>x!==item);settingsChanged();drawExtras();}}));rows.append(row);}}
  drawExtras();box.append(rows,el('button',{type:'button',class:'secondary',text:'＋ Agregar '+label.toLowerCase(),onclick:()=>{extraDraft[key].push({name:'',price:0,existing:false});settingsChanged();drawExtras();}}));extras.append(box);
 }
 const brand=section('Datos de BARÓN','Estos datos aparecen en el presupuesto del cliente.'),brandGrid=el('div',{class:'grid'});
 for(const[key,label]of [['brand','Nombre del comercio'],['tagline','Descripción del comercio'],['whatsapp','Teléfono / WhatsApp'],['email','Email'],['address','Dirección']])brandGrid.append(configField(label,cfg.brand,key,'text',null,{maxLength:500}));brand.append(brandGrid);
}
async function saveSettings(){
 const form=$('#settings-form');if(!form.reportValidity())return;
 const config=clone(settingsDraft);
 for(const kind of ['zocalo','chain','mount']){const values={};for(const row of extraDraft[kind]){const name=row.name.trim();if(!name)throw Error('Ingresá el nombre de cada adicional.');if(Object.hasOwn(values,name))throw Error('El adicional «'+name+'» está repetido.');values[name]=row.price;}config.extras[kind]=values;}
 await api('/config','POST',{config,previous:configOriginal});configDirty=false;await refresh();renderGroups();$('#settings-save-status').textContent='Configuración guardada';notice('Configuración guardada. Los presupuestos anteriores conservan sus precios.');
}
