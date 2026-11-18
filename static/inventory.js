'use strict';
let inventoryImportToken=null;
const componentCategories=['caño','cadena','sistema','zócalo','guía','soporte','accesorio','otro'];
const componentUnits=['m','m²','unidad','par'];
const recipeModes=[['fijo','Cantidad fija'],['ancho_m','Por metro de ancho'],['alto_m','Por metro de alto'],['area_m2','Por m²'],['perimetro_m','Por metro de perímetro']];
function renderInventoryCatalogue(cfg,section){
 const components=section('Insumos y artículos de stock','Agregá caños, cadenas, sistemas, accesorios y otros artículos. Al registrar una entrada se activa su control de stock.');
 let deletedComponents=false;const list=el('div');components.append(check('Mostrar insumos eliminados',false,c=>{deletedComponents=c.checked;drawComponents();}),list);
 function drawComponents(){list.replaceChildren();for(const item of cfg.stock_components.filter(c=>deletedComponents||!c.deleted)){
  const summary=el('summary',{text:item.name+(item.deleted?' · Eliminado':'')}),box=el('details',{class:'settings-item settings-material','data-component-id':item.id},[summary]),grid=el('div',{class:'grid'});
  grid.append(field('Nombre del insumo',item.name,v=>{item.name=v;summary.textContent=v;settingsChanged();},null,'text',{required:true,maxLength:100}));
  grid.append(configField('Categoría',item,'category','text',componentCategories.map(x=>[x,x])));
  grid.append(configField('Unidad del insumo',item,'unit','text',componentUnits.map(x=>[x,x])));
  grid.append(configField('Costo unitario del insumo',item,'unit_cost','number',null,{required:true}));
  grid.append(configField('Stock mínimo del insumo',item,'minimum_qty','number',null,{required:true}));
  grid.append(check('Insumo activo',item.active!==false,c=>{item.active=c.checked;settingsChanged();}),check('Controlar stock al aprobar',!!item.track_stock,c=>{item.track_stock=c.checked;settingsChanged();}));
  box.append(grid);
  if(item.pricing_key)box.append(el('p',{class:'muted',text:'Vinculado a la regla del cotizador: editar este costo actualiza su tarifa para nuevos presupuestos.'}));
  box.append(el('button',{type:'button',class:item.deleted?'secondary':'danger',text:item.deleted?'Recuperar insumo':'Eliminar insumo',onclick:()=>{if(!item.deleted&&!confirm('¿Eliminar del catálogo? Los movimientos y presupuestos anteriores se conservan.'))return;item.deleted=!item.deleted;item.active=!item.deleted;settingsChanged();drawComponents();}}));list.append(box);
 }}drawComponents();
 components.append(el('button',{type:'button',class:'secondary',text:'＋ Agregar insumo al catálogo',onclick:()=>{cfg.stock_components.push({id:'ins-'+crypto.randomUUID().slice(0,12),name:'Nuevo insumo',category:'otro',unit:'unidad',unit_cost:0,minimum_qty:0,active:true,track_stock:false});settingsChanged();drawComponents();list.lastElementChild.open=true;}}));
 const products=section('Productos y modelos para cotizar','Creá modelos con una regla de precio explícita. Por materiales suma tela y receta; las demás reglas usan el valor base indicado. Los recargos e impuestos generales se aplican al resultado.');
 let deletedProducts=false;const productList=el('div');products.append(check('Mostrar productos eliminados',false,c=>{deletedProducts=c.checked;drawProducts();}),productList);
 function drawProducts(){productList.replaceChildren();for(const product of cfg.products.filter(p=>deletedProducts||!p.deleted)){
  const summary=el('summary',{text:product.name+(product.deleted?' · Eliminado':'')}),box=el('details',{class:'settings-item settings-material','data-product-id':product.id},[summary]),grid=el('div',{class:'grid'});
  grid.append(field('Nombre del producto',product.name,v=>{product.name=v;summary.textContent=v;settingsChanged();},null,'text',{required:true,maxLength:100}));
  grid.append(check('Producto activo',product.active!==false,c=>{product.active=c.checked;settingsChanged();}));
  if(product.id==='roller'){box.append(grid,el('p',{class:'muted',text:'Usa las reglas existentes de Roller. Podés cambiar telas, caños y sistemas en sus secciones.'}));productList.append(box);continue;}
  grid.append(configField('Regla de precio',product,'calculation','text',[['materiales','Por materiales y receta'],['m2','Precio por m²'],['metro_ancho','Precio por metro de ancho'],['fijo','Precio fijo']]));
  grid.append(configField('Valor base de la regla',product,'price_value','number',null,{required:true}));
  grid.append(check('Requiere tela y color',product.requires_fabric!==false,c=>{product.requires_fabric=c.checked;settingsChanged();}));
  grid.append(configField('Tela adicional de alto cm',product,'extra_height_cm','number',null,{required:true,max:300}));
  grid.append(configField('Multiplicador del ancho de tela',product,'fabric_width_multiplier','number',null,{required:true,min:.01,max:10}));
  box.append(grid,el('h4',{text:'Insumos del producto'}));const recipes=el('div');box.append(recipes);
  function drawRecipes(){recipes.replaceChildren();for(const r of product.recipes){const row=el('div',{class:'settings-extra grid'});row.append(configField('Insumo de la receta',r,'component_id','text',[['','Elegí un insumo'],...cfg.stock_components.filter(c=>c.active!==false&&!c.deleted).map(c=>[c.id,c.name])]));row.append(configField('Regla de cantidad',r,'mode','text',recipeModes),configField('Factor de cantidad',r,'factor','number',null,{required:true}));row.append(el('button',{type:'button',class:'danger',text:'Quitar de receta',onclick:()=>{product.recipes=product.recipes.filter(x=>x!==r);settingsChanged();drawRecipes();}}));recipes.append(row);}}
  drawRecipes();box.append(el('button',{type:'button',class:'secondary',text:'＋ Agregar insumo a la receta',onclick:()=>{product.recipes.push({component_id:cfg.stock_components.find(c=>c.active!==false&&!c.deleted)?.id||'',mode:'fijo',factor:1});settingsChanged();drawRecipes();}}));
  box.append(el('button',{type:'button',class:product.deleted?'secondary':'danger',text:product.deleted?'Recuperar producto':'Eliminar producto',onclick:()=>{if(!product.deleted&&!confirm('¿Eliminar este producto del catálogo? Los presupuestos guardados se conservan.'))return;product.deleted=!product.deleted;product.active=!product.deleted;settingsChanged();drawProducts();}}));productList.append(box);
 }}drawProducts();
 products.append(el('button',{type:'button',class:'secondary',text:'＋ Agregar producto o modelo',onclick:()=>{cfg.products.push({id:'prod-'+crypto.randomUUID().slice(0,12),name:'Nuevo producto',calculation:'fijo',price_value:0,requires_fabric:true,extra_height_cm:0,fabric_width_multiplier:1,recipes:[],active:true});settingsChanged();drawProducts();productList.lastElementChild.open=true;}}));
}

function renderComponentStock(){
 const root=$('#component-entry');if(!root||!state)return;
 const components=state.config.stock_components.filter(c=>c.active!==false&&!c.deleted),data={component_id:components[0]?.id||'',quantity:1,location:'',origin:''};
 const form=el('form',{class:'card'},[el('h3',{text:'Entrada de insumos'})]),grid=el('div',{class:'grid'}),unit=el('p',{class:'muted'});
 function showUnit(){unit.textContent='Unidad: '+(state.config.stock_components.find(c=>c.id===data.component_id)?.unit||'—');}
 grid.append(field('Insumo a ingresar',data.component_id,v=>{data.component_id=v;showUnit();},[['','Elegí un insumo'],...components.map(c=>[c.id,c.name])]));
 for(const[k,label,type]of [['quantity','Cantidad de entrada','number'],['location','Ubicación del insumo','text'],['origin','Origen de la entrada','text']])grid.append(field(label,data[k],v=>data[k]=v,null,type,{min:.000001,step:'any',required:k==='quantity'}));
 showUnit();form.append(grid,unit,el('button',{type:'submit',text:'Registrar entrada de insumo'}));form.addEventListener('submit',task(async()=>{await api('/component-lots','POST',data);await refresh();notice('Entrada de insumo guardada.');}));root.replaceChildren(form);renderComponentRows();
}
function renderComponentRows(){
 const root=$('#component-stock-list');if(!root||!state)return;const query=$('#component-stock-search').value.toLowerCase();
 const components=state.config.stock_components.filter(c=>!c.deleted&&(c.name+' '+c.category).toLowerCase().includes(query));root.replaceChildren();
 for(const c of components){const lots=state.component_lots.filter(l=>l.component_id===c.id),qty=lots.reduce((s,l)=>s+l.quantity,0),free=lots.reduce((s,l)=>s+l.available_qty,0),box=el('article',{class:'card stock-component','data-stock-component':c.id});
  box.append(el('h3',{text:c.name}),el('p',{text:c.category+' · Total '+qty+' '+c.unit+' · Reservado '+Math.round((qty-free)*1e6)/1e6+' · Disponible '+Math.round(free*1e6)/1e6}));
  if(c.track_stock&&free<=c.minimum_qty)box.append(el('p',{class:'warning',text:'Poco stock · mínimo '+c.minimum_qty+' '+c.unit}));
  if(!lots.length)box.append(el('p',{class:'muted',text:'Sin existencias registradas.'}));
  for(const lot of lots){const row=el('div',{class:'list-row'},[el('div',{},[el('strong',{text:lot.quantity+' '+lot.unit+' · '+lot.location}),el('p',{class:'muted',text:lot.id+' · '+lot.origin})]),el('button',{class:'secondary',text:'Ajustar insumo',onclick:()=>{
    const data={revision:lot.revision,quantity:lot.quantity,location:lot.location,reason:''},editor=el('form',{class:'card grid'});
    for(const[k,label,type]of [['quantity','Cantidad total del lote','number'],['location','Ubicación del insumo','text'],['reason','Motivo del ajuste','text']])editor.append(field(label,data[k],v=>data[k]=v,null,type,{min:0,step:'any',required:true}));
    editor.append(el('button',{type:'submit',text:'Guardar ajuste de insumo'}));editor.addEventListener('submit',task(async()=>{await api('/component-lots/'+lot.id,'POST',data);await refresh();notice('Ajuste de insumo registrado.');}));row.append(editor);
   }})]);box.append(row);}
  root.append(box);
 }
 if(!components.length)root.append(el('p',{text:'No hay insumos que coincidan con la búsqueda.'}));
}
async function inventoryPreview(event){
 event.preventDefault();const file=$('#inventory-import-file').files[0];if(!file)throw Error('Seleccioná un Excel .xlsx');
 const data=new FormData();data.append('file',file);data.append('scope',$('#inventory-import-scope').value);
 const response=await fetch(API+'/inventory/import/preview',{method:'POST',headers:{'X-CSRF-Token':$('meta[name="csrf-token"]').content},body:data});
 let result;try{result=await response.json();}catch{throw Error('No se pudo revisar el archivo. Verificá el acceso y el tamaño.');}
 if(!response.ok)throw Error(result.error||'No se pudo importar el Excel');
 inventoryImportToken=result.token;const root=$('#inventory-import-preview');root.hidden=false;root.replaceChildren(el('h3',{text:'Vista previa: '+result.count+' cambio(s)'}));
 if(!result.count)root.append(el('p',{text:'El archivo coincide con los datos guardados. No hay cambios para aplicar.'}));
 for(const change of result.changes)root.append(el('div',{class:'list-row'},[el('strong',{text:change.accion+' · '+change.tipo+' · '+change.codigo}),el('div',{},[el('p',{text:'Antes: '+change.antes}),el('p',{text:'Después: '+change.despues})])]));
 if(result.truncated)root.append(el('p',{text:'Se muestran los primeros 200 cambios. Se aplicarán '+result.count+' en total.'}));
 $('#inventory-import-commit').hidden=!result.count;$('#inventory-import-cancel').hidden=false;
}
function clearInventoryPreview(){inventoryImportToken=null;$('#inventory-import-preview').hidden=true;$('#inventory-import-preview').replaceChildren();$('#inventory-import-commit').hidden=true;$('#inventory-import-cancel').hidden=true;}
function initInventoryUI(){
 $('#show-fabric-stock').addEventListener('click',()=>{$('#fabric-stock-panel').hidden=false;$('#component-stock-panel').hidden=true;});
 $('#show-component-stock').addEventListener('click',()=>{$('#fabric-stock-panel').hidden=true;$('#component-stock-panel').hidden=false;});
 $('#component-stock-search').addEventListener('input',renderComponentRows);
 $('#edit-catalogue')?.addEventListener('click',()=>{showTab('settings');for(const section of document.querySelectorAll('.settings-section'))if(['Telas y colores','Insumos y artículos de stock','Productos y modelos para cotizar'].includes(section.querySelector('summary')?.textContent))section.open=true;});
 $('#inventory-import-form')?.addEventListener('submit',task(inventoryPreview));
 $('#inventory-import-scope')?.addEventListener('change',()=>{clearInventoryPreview();$('#inventory-template').href=API+'/inventory/export?template=1&scope='+$('#inventory-import-scope').value;});
 $('#inventory-import-file')?.addEventListener('change',clearInventoryPreview);
 $('#inventory-import-cancel')?.addEventListener('click',clearInventoryPreview);
 $('#inventory-import-commit')?.addEventListener('click',task(async()=>{if(!inventoryImportToken)throw Error('Primero revisá el Excel');const result=await api('/inventory/import/commit','POST',{token:inventoryImportToken});clearInventoryPreview();await refresh();renderGroups();notice('Importación completada: '+result.count+' cambio(s).');}));
}
