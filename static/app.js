'use strict';
(() => {
  const $=(q, root=document)=>root.querySelector(q);
  const $$=(q,root=document)=>Array.from(root.querySelectorAll(q));
  const parseJSON=id=>{try{return JSON.parse(document.getElementById(id)?.textContent||'{}')}catch{return {}}};
  const money=n=>new Intl.NumberFormat('es-AR',{style:'currency',currency:'ARS',maximumFractionDigits:0}).format(n||0);
  const CART='baron_cart_v1';
  const getCart=()=>{try{let v=JSON.parse(localStorage.getItem(CART)||'[]');return Array.isArray(v)?v.slice(0,40):[]}catch{return []}};
  const putCart=v=>{localStorage.setItem(CART,JSON.stringify(v));updateCartCount()};
  const updateCartCount=()=>{$$('#cart-count').forEach(el=>el.textContent=getCart().reduce((s,x)=>s+Number(x.quantity||0),0))};
  updateCartCount();
  $$('[data-confirm]').forEach(btn=>btn.addEventListener('click',ev=>{if(!confirm(btn.dataset.confirm))ev.preventDefault()}));
  if(document.body.dataset.page==='configurator') setupConfigurator();
  if(document.body.dataset.page==='cart') setupCart();
  if(document.body.dataset.page==='option-rules') setupOptionRules();
  function setupConfigurator(){
    const frm=$('#quote-form'),kind=frm.dataset.kind, mats=parseJSON('material-data');
    const families=kind==='doble'?['blackout','sunscreen']:[kind==='tela'?'tela':kind];
    let latestQuote=null, seq=0, timer=0;
    const err=$('#quote-error'), total=$('#quote-total'), mobile=$('#mobile-total'), add=$('#add-to-cart');
    const selected=(name)=>$( `input[name="${name}"]:checked`,frm)?.value;
    function renderColors(family){
      const mid=selected('material_'+family), mat=mats.find(m=>m.id===mid), box=$(`[data-color-for="${family}"]`,frm);
      if(!box)return;
      const previous=box.querySelector('input:checked')?.value;
      box.replaceChildren();
      if(!mat)return;
      const validPrevious=mat.colors.some(c=>c.id===previous)?previous:null;
      for(let i=0;i<mat.colors.length;i++){
        const col=mat.colors[i], lab=document.createElement('label');lab.className='color-choice';
        const inp=document.createElement('input');inp.type='radio';inp.name='color_'+family;inp.value=col.id;inp.checked=(validPrevious===col.id)||(!validPrevious&&i===0);
        const span=document.createElement('span'), sw=document.createElement('i');sw.className='color-swatch';sw.style.backgroundColor=col.hex;
        span.append(sw);
        if(col.photo){const img=document.createElement('img');img.className='color-thumbnail';img.loading='lazy';img.alt='';img.src='/media/'+encodeURIComponent(col.photo);span.append(img)}
        span.append(document.createTextNode(col.name));lab.append(inp,span);box.append(lab);
      }
      updateFabricPreview(family);
    }
    function updateFabricPreview(family){
      const mat=mats.find(m=>m.id===selected('material_'+family));
      const col=mat?.colors.find(c=>c.id===selected('color_'+family));
      const target=$(`[data-preview-for="${family}"]`,frm);
      if(!target)return;
      target.replaceChildren();
      const image=col?.photo||mat?.photo;
      if(image){
        const img=document.createElement('img');img.src='/media/'+encodeURIComponent(image);img.alt=`Tela ${mat.name}, color ${col?.name||''}`;img.loading='lazy';
        const caption=document.createElement('span');caption.textContent=`Vista real: ${mat.name} · ${col?.name||''}`;
        target.append(img,caption);
      }else{
        const note=document.createElement('span');note.textContent='Este color todavía no tiene una fotografía cargada.';target.append(note);
      }
    }
    function gather(){const selections={};families.forEach(f=>{selections[f]={material_id:selected('material_'+f),color_id:selected('color_'+f)}});
      return {kind,selections,width_cm:Number($('#width_cm').value),height_cm:Number($('#height_cm').value),quantity:Number($('#quantity').value),mount:selected('mount'),drop:selected('drop'),side:selected('side'),chain:selected('chain'),pleat:selected('pleat')};}
    async function quote(){const id=++seq;latestQuote=null;add.disabled=true;err.textContent='';total.textContent='Calculando…';mobile.textContent='Calculando…';
      if(!$('#width_cm').checkValidity()||!$('#height_cm').checkValidity()){total.textContent='Revisá las medidas';mobile.textContent='Revisá las medidas';return}
      try{const r=await fetch('/api/cotizar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(gather())});let v=await r.json();if(id!==seq)return;if(!r.ok)throw Error(v.error||'No se pudo cotizar');latestQuote=v;total.textContent=money(v.total);mobile.textContent=money(v.total);$('#quote-description').textContent=v.width_cm+' × '+v.height_cm+' cm · '+v.selections.map(x=>x.material+' / '+x.color).join(' · ');add.disabled=false;
      }catch(e){if(id!==seq)return;err.textContent=e.message;total.textContent='Sin precio';mobile.textContent='Sin precio'}}
    function queueQuote(){clearTimeout(timer);timer=setTimeout(quote,240)}
    families.forEach(f=>renderColors(f));
    frm.addEventListener('change',ev=>{if(ev.target.name?.startsWith('material_'))renderColors(ev.target.name.replace('material_',''));if(ev.target.name?.startsWith('color_'))updateFabricPreview(ev.target.name.replace('color_',''));queueQuote()});
    frm.addEventListener('input',queueQuote);
    $$('[data-qty]').forEach(btn=>btn.addEventListener('click',()=>{let inp=$('#quantity');inp.value=Math.max(1,Math.min(30,Number(inp.value||1)+Number(btn.dataset.qty)));queueQuote()}));
    $('#quantity').addEventListener('input',queueQuote);
    add.addEventListener('click',()=>{if(!latestQuote)return;const cart=getCart();cart.push(latestQuote);putCart(cart);window.location.href='/carrito'});
    quote();
  }
  function setupOptionRules(){
    const allRules=parseJSON('option-rules-data');
    const allOptions=parseJSON('option-choices-data');
    const allComponents=parseJSON('option-components-data');
    const modes=parseJSON('option-modes-data');
    const makeSelect=(name,options,selected)=>{
      const el=document.createElement('select');el.name=name;el.required=true;
      Object.entries(options).forEach(([value,label])=>{
        const op=document.createElement('option');op.value=value;op.textContent=label;
        if(value===selected)op.selected=true;el.append(op);
      });return el;
    };
    const td=(el)=>{const cell=document.createElement('td');cell.append(el);return cell};
    $$('[data-option-model]').forEach(form=>{
      const kind=form.dataset.optionModel, choices=allOptions[kind]||{}, tbody=$('[data-option-rows]',form);
      function addRow(row={}){
        const tr=document.createElement('tr'), keySelect=makeSelect('option_key',Object.fromEntries(Object.keys(choices).map(k=>[k,({mount:'Colocación',drop:'Caída',side:'Mando',chain:'Cadena',pleat:'Confección'})[k]||k])),row.option_key);
        const valueSelect=document.createElement('select');valueSelect.name='option_value';valueSelect.required=true;
        function fillValues(preferred){valueSelect.replaceChildren();(choices[keySelect.value]||[]).forEach(v=>{const opt=document.createElement('option');opt.value=v;opt.textContent=v;if(v===preferred)opt.selected=true;valueSelect.append(opt)})}
        fillValues(row.option_value);keySelect.addEventListener('change',()=>fillValues());
        const compSelect=makeSelect('component_id',Object.fromEntries(allComponents.map(c=>[c.id,c.name+' · $'+Number(c.unit_cost).toLocaleString('es-AR')+'/'+c.unit])),row.component_id);
        const modeSelect=makeSelect('mode',modes,row.mode||'fijo');
        function numberInput(name,value,min,max,step){const el=document.createElement('input');el.type='number';el.name=name;el.min=min;el.max=max;el.step=step;el.value=value;el.required=true;return el}
        const factor=numberInput('factor',row.factor??1,0.001,100000,0.001);
        const waste=numberInput('waste_pct',row.waste_pct??0,0,80,0.1);
        const del=document.createElement('button');del.type='button';del.textContent='Quitar';del.addEventListener('click',()=>tr.remove());
        [keySelect,valueSelect,compSelect,modeSelect,factor,waste,del].forEach(x=>tr.append(td(x)));
        tbody.append(tr);
      }
      (allRules[kind]||[]).forEach(addRow);
      $('[data-add-option]',form)?.addEventListener('click',()=>addRow());
    });
  }
  function setupCart(){
    const store=parseJSON('store-data'), el=$('#cart-items'),total=$('#cart-total'), error=$('#cart-error');
    function render(){const cart=getCart();el.replaceChildren();let sum=0;
      if(!cart.length){const empty=document.createElement('div');empty.className='cart-empty';empty.textContent='Tu pedido está vacío. Elegí una cortina y personalizala.';el.append(empty)}
      cart.forEach((x,i)=>{
        sum+=Number(x.total)||0;const card=document.createElement('div');card.className='cart-item';const left=document.createElement('div'),title=document.createElement('h3'),info=document.createElement('p'),desc=document.createElement('p');
        title.textContent=x.product;info.textContent=`${x.width_cm} × ${x.height_cm} cm · ${x.quantity} unidad(es) · ${x.mount}`;desc.textContent=(x.selections||[]).map(y=>y.material+' / '+y.color).join(' · ');left.append(title,info,desc);
        const right=document.createElement('div');const price=document.createElement('strong');price.textContent=money(x.total);const spacer=document.createElement('div');spacer.style.height='9px';const remove=document.createElement('button');remove.textContent='Quitar';remove.type='button';remove.addEventListener('click',()=>{const c=getCart();c.splice(i,1);putCart(c);render()});right.append(price,spacer,remove);card.append(left,right);el.append(card)
      });total.textContent=money(sum)
    }
    $('#whatsapp-checkout').addEventListener('click',async ()=>{const cart=getCart();
      if(!cart.length){error.textContent='Primero agregá una cortina.';return}
      const name=$('#customer-name').value.trim(),city=$('#customer-city').value.trim();
      if(!name||!city){error.textContent='Completá tu nombre y localidad.';return}
      error.textContent='Preparando tu pedido…';
      try{
        const res=await fetch('/api/armar-pedido',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,city,tokens:cart.map(x=>x.token)})});
        const out=await res.json();if(!res.ok)throw Error(out.error||'No fue posible preparar tu pedido');
        error.textContent='';window.open(out.url,'_blank','noopener,noreferrer');
      }catch(e){error.textContent=e.message||'Revisá los datos y probá nuevamente'}
    });render();
  }
})();
