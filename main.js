const menuToggle=document.querySelector('.menu-toggle');const nav=document.querySelector('.desktop-nav');
menuToggle?.addEventListener('click',()=>{const open=menuToggle.getAttribute('aria-expanded')==='true';menuToggle.setAttribute('aria-expanded',String(!open));nav.classList.toggle('open',!open)});
document.querySelectorAll('.desktop-nav a').forEach(a=>a.addEventListener('click',()=>{menuToggle?.setAttribute('aria-expanded','false');nav?.classList.remove('open')}));
const demoData={
  commerce:[
    {id:'a-104',code:'A-104',name:'Audífonos inalámbricos',category:'Accesorios',price:449,stock:12},
    {id:'c-208',code:'C-208',name:'Cable USB-C',category:'Accesorios',price:129,stock:28},
    {id:'t-316',code:'T-316',name:'Teclado compacto',category:'Periféricos',price:589,stock:7},
    {id:'m-422',code:'M-422',name:'Mouse óptico',category:'Periféricos',price:249,stock:15}
  ],
  restaurant:[
    {id:'pepperoni',category:'pz',icon:'🍕',name:'Pepperoni',sizes:[['Chica',89],['Mediana',129],['Grande',169],['Familiar',219]]},
    {id:'hawaiana',category:'pz',icon:'🍍',name:'Hawaiana',sizes:[['Chica',89],['Mediana',129],['Grande',169],['Familiar',219]]},
    {id:'mexicana',category:'pz',icon:'🌶️',name:'Mexicana',sizes:[['Chica',99],['Mediana',139],['Grande',179],['Familiar',229]]},
    {id:'cuatro-quesos',category:'pz',icon:'🧀',name:'Cuatro quesos',sizes:[['Chica',99],['Mediana',145],['Grande',189],['Familiar',239]]},
    {id:'margarita',category:'pz',icon:'🍅',name:'Margarita',sizes:[['Chica',79],['Mediana',115],['Grande',155],['Familiar',199]]},
    {id:'papas',category:'sn',icon:'🍟',name:'Papas a la francesa',sizes:[['Chicas',39],['Grandes',59]]},
    {id:'alitas',category:'sn',icon:'🍗',name:'Alitas',sizes:[['6 pzas',89],['12 pzas',159]]},
    {id:'pan-ajo',category:'sn',icon:'🥖',name:'Pan de ajo',sizes:[['Único',45]]},
    {id:'nuggets',category:'sn',icon:'🧆',name:'Nuggets',sizes:[['8 pzas',69]]},
    {id:'refresco',category:'bb',icon:'🥤',name:'Refresco',sizes:[['Chico',25],['Grande',35]]},
    {id:'agua',category:'bb',icon:'💧',name:'Agua',sizes:[['Único',20]]},
    {id:'cerveza',category:'bb',icon:'🍺',name:'Cerveza',sizes:[['Único',40]]},
    {id:'brownie',category:'ps',icon:'🍫',name:'Brownie',sizes:[['Único',45]]},
    {id:'helado',category:'ps',icon:'🍦',name:'Helado',sizes:[['Único',35]]}
  ]
};
const restaurantCategories=[
  {id:'pz',icon:'🍕',name:'Pizzas'},
  {id:'sn',icon:'🍟',name:'Snacks'},
  {id:'bb',icon:'🥤',name:'Bebidas'},
  {id:'ps',icon:'🍰',name:'Postres'}
];
const demoMoney=new Intl.NumberFormat('es-MX',{style:'currency',currency:'MXN'});
const demoTabs=document.querySelectorAll('.demo-tab');
const demoProductGrid=document.querySelector('#demo-product-grid');
const demoCartItems=document.querySelector('#demo-cart-items');
const demoToast=document.querySelector('#demo-toast');
const demoState={
  product:'commerce',
  view:'sale',
  category:'pz',
  search:'',
  cart:[],
  service:'mesa',
  table:null,
  customer:'',
  phone:'',
  address:'',
  notes:'',
  discount:0,
  payment:'Efectivo',
  received:'',
  paying:false,
  orders:[],
  completed:false,
  selectedSize:null
};
let demoSizeTrigger=null;
const demoDescriptions={
  commerce:{brand:'OZZVON POS',kind:'COMERCIO',icon:'▰',nav:[['Ventas','sale'],['Inventario','inventory'],['Compras',null],['Clientes y créditos',null],['Reportes',null],['Corte de caja',null],['Usuarios',null],['Ajustes',null]]},
  restaurant:{brand:'Mi Pizzería',kind:'OZZVAN POS',icon:'🍕',nav:[['Nuevo pedido','sale'],['Pedidos','orders'],['Ventas',null],['Menú',null],['Configuración',null]]}
};
function demoNotice(message){
  demoToast.textContent=message;
}
function demoButton(label,className,dataset={}){
  const button=document.createElement('button');
  button.type='button';
  button.className=className;
  button.textContent=label;
  Object.entries(dataset).forEach(([key,value])=>button.dataset[key]=value);
  return button;
}
function demoAdd(product,size=product.sizes?.[0]){
  if(demoState.product==='commerce'&&product.stock<=0){
    demoNotice(`${product.name} está agotado en el inventario de muestra.`);
    return;
  }
  const key=product.id+(size?'|'+size[0]:'');
  const line=demoState.cart.find(item=>item.key===key);
  if(line)line.quantity++;
  else demoState.cart.push({key,product,size,quantity:1});
  demoState.completed=false;
  demoState.paying=false;
  demoNotice('');
  renderDemo();
}
function demoTotal(){
  const gross=demoState.cart.reduce((sum,item)=>sum+item.quantity*(item.size?item.size[1]:item.product.price),0);
  return gross*(1-Math.min(100,Math.max(0,demoState.discount))/100);
}
function renderDemoNav(){
  const restaurant=demoState.product==='restaurant';
  const config=demoDescriptions[demoState.product];
  const icons=restaurant?['＋','▤','▥','☰','⚙']:['⌂','▣','▤','↗','♙','▥','◷','♙','⚙'];
  document.querySelector('#demo-app-name').textContent=restaurant?'OZZVAN POS · RESTAURANTE':'OZZVON POS · COMERCIO';
  document.querySelector('#demo-brand-icon').textContent=config.icon;
  document.querySelector('#demo-brand-name').textContent=config.brand;
  document.querySelector('#demo-brand-kind').textContent=config.kind;
  const nav=document.querySelector('#demo-side-nav');
  nav.replaceChildren(...config.nav.map(([label,view],index)=>{
    const button=demoButton('','demo-nav-item',{
      demoNav:view||'unavailable'
    });
    const icon=document.createElement('span');
    icon.className='demo-nav-icon';
    icon.textContent=icons[index];
    icon.setAttribute('aria-hidden','true');
    const text=document.createElement('span');
    text.className='demo-nav-label';
    text.textContent=label;
    button.append(icon,text);
    button.setAttribute('aria-label',label);
    if(view===demoState.view)button.classList.add('active');
    if(!view){
      button.disabled=true;
      button.title='Esta sección está fuera de la demostración';
    }
    return button;
  }));
}
function renderDemoCategories(){
  const container=document.querySelector('#demo-categories');
  container.replaceChildren(...restaurantCategories.map(category=>{
    const button=demoButton(`${category.icon} ${category.name}`,'demo-category',{
      demoCategory:category.id
    });
    if(category.id===demoState.category)button.classList.add('active');
    button.setAttribute('aria-pressed',String(category.id===demoState.category));
    return button;
  }));
}
function renderDemoProducts(){
  const commerce=demoState.product==='commerce';
  const products=demoData[demoState.product];
  const matches=products.filter(product=>{
    if(commerce){
      const query=demoState.search.trim().toLowerCase();
      return query&&`${product.code} ${product.name}`.toLowerCase().includes(query);
    }
    return product.category===demoState.category;
  });
  if(commerce&&!demoState.search.trim()){
    demoProductGrid.innerHTML='<p class="demo-empty-result">Escanea el código o escribe el nombre del producto para empezar.</p>';
  }else if(!matches.length){
    demoProductGrid.innerHTML='<p class="demo-empty-result">No hay coincidencias en el catálogo de muestra.</p>';
  }else{
    demoProductGrid.replaceChildren(...matches.map(product=>{
      const button=demoButton('',commerce?'demo-search-result':'demo-product',{productId:product.id});
      if(commerce){
        const details=document.createElement('span');
        details.className='demo-result-name';
        const name=document.createElement('b');
        name.textContent=product.name;
        const code=document.createElement('small');
        code.textContent=`${product.code} · ${product.stock} en existencia`;
        details.append(name,code);
        const price=document.createElement('b');
        price.textContent=demoMoney.format(product.price);
        button.append(details,price);
        button.disabled=product.stock<=0;
        button.setAttribute('aria-label',`Agregar ${product.name}, código ${product.code}, ${demoMoney.format(product.price)}`);
      }else{
        const icon=document.createElement('i');
        icon.textContent=product.icon;
        icon.setAttribute('aria-hidden','true');
        const name=document.createElement('b');
        name.textContent=product.name;
        const price=document.createElement('small');
        price.textContent=`desde ${demoMoney.format(Math.min(...product.sizes.map(size=>size[1])))}`;
        button.append(icon,name,price);
        button.setAttribute('aria-label',`Agregar ${product.name}`);
      }
      return button;
    }));
  }
}
function renderDemoOrderOptions(){
  const container=document.querySelector('#demo-order-options');
  container.replaceChildren();
  if(demoState.product==='commerce'){
    const discount=document.createElement('label');
    discount.className='demo-discount';
    discount.textContent='Descuento (%)';
    const input=document.createElement('input');
    input.type='number';
    input.min='0';
    input.max='100';
    input.value=demoState.discount;
    input.setAttribute('aria-label','Descuento de muestra en porcentaje');
    discount.append(input);
    container.append(discount);
    return;
  }
  const service=document.createElement('div');
  service.className='demo-service';
  [['mesa','🪑 Mesa'],['llevar','🥡 Para llevar'],['domicilio','🛵 Domicilio']].forEach(([id,label])=>{
    const button=demoButton(label,'demo-service-button',{demoService:id});
    if(demoState.service===id)button.classList.add('active');
    button.setAttribute('aria-pressed',String(demoState.service===id));
    service.append(button);
  });
  container.append(service);
  if(demoState.service==='mesa'){
    const tableLabel=document.createElement('span');
    tableLabel.className='demo-field-label';
    tableLabel.textContent='Selecciona mesa';
    const tables=document.createElement('div');
    tables.className='demo-tables';
    for(let table=1;table<=12;table++){
      const button=demoButton(String(table),'demo-table',{demoTable:String(table)});
      if(table===demoState.table)button.classList.add('active');
      button.setAttribute('aria-pressed',String(table===demoState.table));
      tables.append(button);
    }
    container.append(tableLabel,tables);
  }
  const customer=demoInput('Nombre del cliente (opcional)','customer');
  container.append(customer);
  if(demoState.service==='domicilio'){
    container.append(demoInput('Teléfono','phone','tel'),demoInput('Dirección de entrega *','address'));
  }
  const notes=document.createElement('textarea');
  notes.placeholder='Notas (sin cebolla, extra queso…)';
  notes.value=demoState.notes;
  notes.dataset.demoField='notes';
  notes.setAttribute('aria-label','Notas del pedido de muestra');
  container.append(notes);
}
function demoInput(placeholder,field,type='text'){
  const input=document.createElement('input');
  input.placeholder=placeholder;
  input.value=demoState[field];
  input.type=type;
  input.dataset.demoField=field;
  input.setAttribute('aria-label',placeholder);
  return input;
}
function renderDemoCart(){
  const restaurant=demoState.product==='restaurant';
  const quantity=demoState.cart.reduce((sum,item)=>sum+item.quantity,0);
  const total=demoTotal();
  document.querySelector('#demo-cart-count').textContent=quantity;
  document.querySelector('#demo-total').textContent=demoMoney.format(total);
  const taxes=document.querySelector('#demo-taxes');
  taxes.hidden=restaurant||!quantity;
  document.querySelector('#demo-subtotal').textContent=demoMoney.format(total/1.16);
  document.querySelector('#demo-tax').textContent=demoMoney.format(total-total/1.16);
  document.querySelector('#demo-cart-context').textContent=restaurant
    ?`${demoState.service==='mesa'?'Mesa '+(demoState.table||'—'):demoState.service==='llevar'?'Para llevar':'Domicilio'} · CLIENTE DE MUESTRA`
    :'Mostrador (sin registrar)';
  document.querySelector('#demo-cart-title').textContent=restaurant?'Pedido actual':'Venta actual';
  document.querySelector('#demo-total-label').textContent=restaurant?'Total':'Total a cobrar';
  document.querySelector('#demo-cart-empty').hidden=demoState.cart.length>0;
  document.querySelector('#demo-reset').textContent=restaurant?'Vaciar pedido':'Cancelar venta';
  document.querySelector('#demo-checkout-label').textContent=restaurant
    ?'Confirmar pedido'
    :demoState.paying?'Finalizar venta':'Cobrar';
  document.querySelector('#demo-checkout').disabled=!quantity||demoState.completed;
  const items=demoState.cart.map(item=>{
    const product=item.product;
    const price=item.size?item.size[1]:product.price;
    const name=item.size?`${product.name} · ${item.size[0]}`:product.name;
    const row=document.createElement('div');
    row.className='demo-cart-item';
    const info=document.createElement('div');
    info.className='demo-cart-item-info';
    const label=document.createElement('strong');
    label.textContent=name;
    const detail=document.createElement('small');
    detail.textContent=restaurant?demoMoney.format(price):`${product.code} · ${demoMoney.format(price)}`;
    info.append(label,detail);
    const controls=document.createElement('div');
    controls.className='demo-quantity';
    const decrement=demoButton('−','',{demoChange:-1,demoKey:item.key});
    decrement.setAttribute('aria-label',`Quitar una unidad de ${name}`);
    const amount=document.createElement('span');
    amount.textContent=item.quantity;
    const increment=demoButton('+','',{demoChange:1,demoKey:item.key});
    increment.setAttribute('aria-label',`Agregar una unidad de ${name}`);
    controls.append(decrement,amount,increment);
    const subtotal=document.createElement('b');
    subtotal.className='demo-line-total';
    subtotal.textContent=demoMoney.format(price*item.quantity);
    row.append(info,controls,subtotal);
    return row;
  });
  demoCartItems.replaceChildren(...items);
  const paymentFields=document.querySelector('#demo-payment-fields');
  paymentFields.hidden=!demoState.paying;
  if(demoState.paying&&!restaurant)renderDemoPaymentFields(paymentFields,total);
}
function renderDemoPaymentFields(container,total){
  container.replaceChildren();
  const methods=document.createElement('div');
  methods.className='demo-payment-methods';
  ['Efectivo','Tarjeta','Transferencia'].forEach(method=>{
    const button=demoButton(method,'demo-payment-method');
    if(method===demoState.payment)button.classList.add('active');
    button.setAttribute('aria-pressed',String(method===demoState.payment));
    button.addEventListener('click',()=>{
      demoState.payment=method;
      demoState.received='';
      renderDemoCart();
    });
    methods.append(button);
  });
  container.append(methods);
  if(demoState.payment==='Efectivo'){
    const label=document.createElement('label');
    label.className='demo-cash-label';
    label.textContent='Efectivo recibido';
    const input=document.createElement('input');
    input.type='number';
    input.min=String(total);
    input.step='0.01';
    input.placeholder=demoMoney.format(total);
    input.value=demoState.received;
    input.setAttribute('aria-label','Efectivo recibido');
    const change=document.createElement('small');
    const received=Number(demoState.received)||0;
    change.textContent=`Cambio: ${demoMoney.format(Math.max(0,received-total))}`;
    input.addEventListener('input',()=>{
      demoState.received=input.value;
      const amount=Number(input.value)||0;
      change.textContent=`Cambio: ${demoMoney.format(Math.max(0,amount-total))}`;
    });
    label.append(input,change);
    container.append(label);
  }else{
    const note=document.createElement('p');
    note.className='demo-payment-note';
    note.textContent='Método de pago de muestra; no se procesa ninguna transacción.';
    container.append(note);
  }
}
function renderDemoOrders(){
  const section=document.querySelector('#demo-orders-view');
  section.replaceChildren();
  if(!demoState.orders.length){
    const empty=document.createElement('p');
    empty.className='demo-orders-empty';
    empty.textContent='No hay pedidos de muestra. Crea uno en “Nuevo pedido” para verlo aquí.';
    section.append(empty);
    return;
  }
  section.append(...demoState.orders.map(order=>{
    const card=document.createElement('article');
    card.className='demo-order-card';
    const heading=document.createElement('div');
    heading.className='demo-order-heading';
    const number=document.createElement('b');
    number.textContent=`Pedido #${String(order.id).padStart(3,'0')}`;
    const status=document.createElement('span');
    status.className=`demo-order-status ${order.status}`;
    status.textContent=order.status==='pendiente'?'Pendiente':order.status==='envio'?(order.service==='mesa'?'Listo para servir':'En envío'):'Concluido';
    heading.append(number,status);
    const type=document.createElement('p');
    type.textContent=`${order.service==='mesa'?'Mesa '+order.table:order.service==='llevar'?'Para llevar':'Domicilio'}${order.customer?' · '+order.customer:''}`;
    const details=document.createElement('p');
    details.textContent=[order.phone,order.address,order.notes].filter(Boolean).join(' · ');
    const lines=document.createElement('ul');
    order.items.forEach(item=>{
      const line=document.createElement('li');
      line.textContent=`${item.quantity} × ${item.size?item.product.name+' · '+item.size[0]:item.product.name}`;
      lines.append(line);
    });
    const footer=document.createElement('div');
    footer.className='demo-order-footer';
    const total=document.createElement('b');
    total.textContent=demoMoney.format(order.total);
    footer.append(total);
    if(order.status!=='concluido'){
      const actionLabel=order.status==='pendiente'?(order.service==='domicilio'?'Iniciar envío':order.service==='mesa'?'Marcar listo para servir':'Simular cobro'):'Concluir · simular cobro';
      const payment=document.createElement('select');
      payment.className='demo-order-payment';
      payment.setAttribute('aria-label','Método de pago de muestra');
      ['Efectivo','Tarjeta','Transferencia'].forEach(method=>{
        const option=document.createElement('option');
        option.value=method;
        option.textContent=method;
        payment.append(option);
      });
      payment.value=order.payment||'Efectivo';
      payment.addEventListener('change',()=>order.payment=payment.value);
      footer.append(payment);
      const action=demoButton(actionLabel,'demo-order-action',{demoOrderId:String(order.id)});
      footer.append(action);
    }
    card.append(heading,type,details);
    card.append(lines,footer);
    return card;
  }));
}
function renderDemoInventory(){
  const table=document.querySelector('#demo-inventory-table');
  const head=document.createElement('div');
  head.className='demo-inventory-row heading';
  ['Código','Producto','Precio','Stock','Estado'].forEach(label=>{
    const cell=document.createElement('b');
    cell.textContent=label;
    head.append(cell);
  });
  table.replaceChildren(head,...demoData.commerce.map(product=>{
    const row=document.createElement('div');
    row.className='demo-inventory-row';
    [product.code,product.name,demoMoney.format(product.price),String(product.stock),product.stock?'Normal':'Agotado'].forEach((value,index)=>{
      const cell=document.createElement('span');
      cell.textContent=value;
      if(index===4)cell.className=product.stock?'demo-stock-normal':'demo-stock-empty';
      row.append(cell);
    });
    return row;
  }));
}
function renderDemo(){
  const restaurant=demoState.product==='restaurant';
  const config=demoDescriptions[demoState.product];
  const quantity=demoState.cart.reduce((sum,item)=>sum+item.quantity,0);
  const progress=demoState.completed?3:Math.min(quantity,2);
  document.querySelector('#demo-app').dataset.demoProduct=demoState.product;
  demoTabs.forEach(tab=>{
    const active=tab.dataset.demoProduct===demoState.product;
    tab.classList.toggle('active',active);
    tab.setAttribute('aria-selected',String(active));
  });
  renderDemoNav();
  document.querySelector('#demo-screen-label').textContent=restaurant?'NUEVO PEDIDO':'VENTAS';
  document.querySelector('#demo-screen-title').textContent=restaurant
    ?demoState.view==='orders'?'Pedidos de hoy':'Nuevo pedido'
    :demoState.view==='inventory'?'Inventario':'Ventas';
  document.querySelector('#demo-register-label').textContent=restaurant?'En línea · modo muestra':'Caja abierta';
  document.querySelector('#demo-brand-kind').textContent=restaurant?'OZZVAN POS':'COMERCIO';
  document.querySelector('#demo-catalog-label').textContent=restaurant?'MENÚ':'BUSCAR PRODUCTOS';
  document.querySelector('#demo-catalog-title').textContent=restaurant?'Elige productos':'Nueva venta';
  document.querySelector('#demo-commerce-tools').hidden=restaurant;
  document.querySelector('#demo-restaurant-tools').hidden=!restaurant;
  document.querySelector('#demo-sale-layout').hidden=(restaurant&&demoState.view==='orders')||(!restaurant&&demoState.view==='inventory');
  document.querySelector('#demo-inventory-view').hidden=restaurant||demoState.view!=='inventory';
  document.querySelector('#demo-orders-view').hidden=!restaurant||demoState.view!=='orders';
  document.querySelector('#demo-progress-bar').style.width=`${progress/3*100}%`;
  document.querySelector('#demo-progress-label').textContent=demoState.completed
    ?'¡Reto completado! Cambia de POS para probar el otro.'
    :progress===0?'Reto exprés: agrega 2 productos'
    :progress===1?'¡Vas bien! Agrega un producto más'
    :'¡Listo! Completa la operación para terminar';
  document.querySelector('#demo-search').value=demoState.search;
  document.querySelectorAll('.demo-frequent-code').forEach(button=>{
    const product=demoData.commerce.find(item=>item.id===button.dataset.productId);
    button.disabled=!product||product.stock<=0;
  });
  renderDemoCategories();
  renderDemoProducts();
  renderDemoOrderOptions();
  renderDemoCart();
  renderDemoOrders();
  document.querySelector('#demo-cart').hidden=(restaurant&&demoState.view==='orders')||(!restaurant&&demoState.view==='inventory');
  renderDemoInventory();
}
function resetDemoForProduct(product){
  demoState.product=product;
  demoState.view='sale';
  demoState.category='pz';
  demoState.search='';
  demoState.cart=[];
  demoState.table=null;
  demoState.discount=0;
  demoState.paying=false;
  demoState.completed=false;
  demoState.selectedSize=null;
  demoState.service='mesa';
  demoState.customer='';
  demoState.phone='';
  demoState.address='';
  demoState.notes='';
  demoState.payment='Efectivo';
  demoState.received='';
  demoNotice('Carrito de muestra reiniciado. Nada se guarda.');
  renderDemo();
}
function addDemoProduct(id,trigger){
  const product=demoData[demoState.product].find(item=>item.id===id);
  if(!product)return;
  if(demoState.product==='commerce'){
    demoAdd(product);
    return;
  }
  if(product.sizes.length===1){
    demoAdd(product,product.sizes[0]);
    return;
  }
  const modal=document.querySelector('#demo-size-modal');
  const content=document.querySelector('#demo-size-options');
  demoSizeTrigger=trigger;
  document.querySelector('#demo-size-title').textContent=`${product.icon} ${product.name}`;
  content.replaceChildren(...product.sizes.map(size=>{
    const button=demoButton(`${size[0]} · ${demoMoney.format(size[1])}`,'demo-size-option');
    button.addEventListener('click',()=>{
      closeDemoSizeModal(false);
      demoAdd(product,size);
      document.querySelector(`[data-product-id="${product.id}"]`)?.focus();
    });
    return button;
  }));
  modal.hidden=false;
  document.querySelector('#demo-size-close').focus();
}
function closeDemoSizeModal(restoreFocus=true){
  document.querySelector('#demo-size-modal').hidden=true;
  if(restoreFocus)demoSizeTrigger?.focus();
  demoSizeTrigger=null;
}
function handleDemoCheckout(){
  if(!demoState.cart.length)return;
  if(demoState.product==='restaurant'){
    if(demoState.service==='mesa'&&!demoState.table){
      demoNotice('Selecciona una mesa para continuar con este pedido de muestra.');
      return;
    }
    if(demoState.service==='domicilio'&&!demoState.address.trim()){
      demoNotice('Escribe una dirección de entrega para este pedido de muestra.');
      document.querySelector('[data-demo-field="address"]').focus();
      return;
    }
    demoState.orders.unshift({
      id:demoState.orders.length+1,
      service:demoState.service,
      table:demoState.table,
      customer:demoState.customer.trim(),
      phone:demoState.phone.trim(),
      address:demoState.address.trim(),
      notes:demoState.notes.trim(),
      items:demoState.cart.map(item=>({...item})),
      total:demoTotal(),
      status:'pendiente'
    });
    demoState.cart=[];
    demoState.notes='';
    demoState.phone='';
    demoState.address='';
    demoState.table=null;
    demoState.completed=true;
    demoState.view='orders';
    demoNotice('Pedido de muestra enviado a cocina. Solo existe durante esta visita.');
    renderDemo();
    return;
  }
  if(!demoState.paying){
    demoState.paying=true;
    demoState.received='';
    document.querySelector('#demo-checkout-label').textContent='Finalizar venta';
    renderDemoCart();
    return;
  }
  if(demoState.payment==='Efectivo'&&Number(demoState.received)<demoTotal()){
    demoNotice('El efectivo recibido debe cubrir el total de muestra.');
    return;
  }
  const total=demoTotal();
  demoState.cart.forEach(item=>{
    item.product.stock=Math.max(0,item.product.stock-item.quantity);
  });
  demoState.cart=[];
  demoState.paying=false;
  demoState.completed=true;
  demoState.discount=0;
  demoState.payment='Efectivo';
  demoNotice(`Venta de muestra finalizada · ${demoMoney.format(total)}. No se realizó ningún cargo ni se guardaron datos.`);
  renderDemo();
}
demoTabs.forEach(tab=>tab.addEventListener('click',()=>{
  if(tab.dataset.demoProduct!==demoState.product)resetDemoForProduct(tab.dataset.demoProduct);
}));
document.querySelectorAll('[data-demo-link]').forEach(link=>link.addEventListener('click',()=>{
  const tab=document.querySelector(`[data-demo-product="${link.dataset.demoLink}"]`);
  if(tab&&link.dataset.demoLink!==demoState.product)tab.click();
}));
document.querySelector('#demo-side-nav').addEventListener('click',event=>{
  const button=event.target.closest('[data-demo-nav]');
  if(!button||button.disabled)return;
  demoState.view=button.dataset.demoNav;
  renderDemo();
});
document.querySelector('#demo-search').addEventListener('input',event=>{
  demoState.search=event.target.value;
  renderDemoProducts();
});
document.querySelector('#demo-frequent-products').replaceChildren(...demoData.commerce.slice(0,4).map(product=>{
  const button=demoButton(product.code,'demo-frequent-code',{productId:product.id});
  button.title=`Agregar ${product.name}`;
  return button;
}));
document.querySelector('#demo-product-grid').addEventListener('click',event=>{
  const button=event.target.closest('[data-product-id]');
  if(button)addDemoProduct(button.dataset.productId,button);
});
document.querySelector('#demo-categories').addEventListener('click',event=>{
  const button=event.target.closest('[data-demo-category]');
  if(!button)return;
  demoState.category=button.dataset.demoCategory;
  renderDemoCategories();
  renderDemoProducts();
});
document.querySelector('#demo-frequent-products').addEventListener('click',event=>{
  const button=event.target.closest('[data-product-id]');
  if(button)addDemoProduct(button.dataset.productId,button);
});
document.querySelector('#demo-cart-items').addEventListener('click',event=>{
  const button=event.target.closest('[data-demo-change]');
  if(!button)return;
  const item=demoState.cart.find(line=>line.key===button.dataset.demoKey);
  if(!item)return;
  item.quantity+=Number(button.dataset.demoChange);
  if(item.quantity<=0)demoState.cart=demoState.cart.filter(line=>line!==item);
  demoState.completed=false;
  renderDemo();
});
document.querySelector('#demo-order-options').addEventListener('input',event=>{
  const field=event.target.dataset.demoField;
  if(field)demoState[field]=event.target.value;
  if(event.target.matches('.demo-discount input')){
    demoState.discount=Math.min(100,Math.max(0,Number(event.target.value)||0));
    const total=demoTotal();
    document.querySelector('#demo-total').textContent=demoMoney.format(total);
    document.querySelector('#demo-subtotal').textContent=demoMoney.format(total/1.16);
    document.querySelector('#demo-tax').textContent=demoMoney.format(total-total/1.16);
  }
});
document.querySelector('#demo-payment-fields').addEventListener('input',event=>{
  if(!event.target.matches('input[type="number"]'))return;
  demoState.received=event.target.value;
  const change=event.target.parentElement.querySelector('small');
  const total=demoTotal();
  change.textContent=`Cambio: ${demoMoney.format(Math.max(0,(Number(demoState.received)||0)-total))}`;
});
document.querySelector('#demo-order-options').addEventListener('click',event=>{
  const service=event.target.closest('[data-demo-service]');
  if(service){
    demoState.service=service.dataset.demoService;
    demoState.table=null;
    renderDemo();
    return;
  }
  const table=event.target.closest('[data-demo-table]');
  if(table){
    demoState.table=Number(table.dataset.demoTable);
    renderDemoOrderOptions();
    renderDemoCart();
  }
});
document.querySelector('#demo-checkout').addEventListener('click',handleDemoCheckout);
document.querySelector('#demo-reset').addEventListener('click',()=>{
  demoState.cart=[];
  demoState.discount=0;
  demoState.paying=false;
  demoState.completed=false;
  demoState.customer='';
  demoState.phone='';
  demoState.address='';
  demoState.notes='';
  demoState.table=null;
  demoNotice('Listo para empezar de nuevo. No se guardó nada.');
  renderDemo();
});
document.querySelector('#demo-size-close').addEventListener('click',()=>{
  closeDemoSizeModal();
});
document.querySelector('#demo-size-modal').addEventListener('click',event=>{
  if(event.target===event.currentTarget)closeDemoSizeModal();
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!document.querySelector('#demo-size-modal').hidden)closeDemoSizeModal();
});
document.querySelector('#demo-orders-view').addEventListener('click',event=>{
  const button=event.target.closest('[data-demo-order-id]');
  if(!button)return;
  const order=demoState.orders.find(item=>item.id===Number(button.dataset.demoOrderId));
  if(!order)return;
  order.status=order.status==='pendiente'&&order.service!=='llevar'?'envio':'concluido';
  if(order.status==='concluido')order.payment=order.payment||'Efectivo';
  demoNotice(order.status==='concluido'?`Pedido concluido · cobro de muestra con ${order.payment||'Efectivo'}. No se procesó ningún pago.`:'Pedido de muestra listo para continuar.');
  renderDemoOrders();
});
renderDemo();
document.querySelectorAll('details').forEach(detail=>detail.addEventListener('toggle',()=>{if(detail.open)document.querySelectorAll('details').forEach(other=>{if(other!==detail)other.open=false})}));
const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-visible');observer.unobserve(entry.target)}}),{threshold:.12});document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));
const header=document.querySelector('.site-header');window.addEventListener('scroll',()=>header.classList.toggle('scrolled',window.scrollY>24),{passive:true});

const contactDialog=document.querySelector('#contact-dialog');
const openContactForm=document.querySelector('#open-contact-form');
const contactForm=document.querySelector('#contact-form');
const contactFormFeedback=document.querySelector('#contact-form-feedback');
const contactFormSubmit=contactForm.querySelector('[type="submit"]');
const contactFormSubmitLabel=contactFormSubmit.querySelector('.form-submit-label');

openContactForm?.addEventListener('click',()=>{
  contactDialog.showModal();
});

contactForm.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!contactForm.reportValidity())return;

  contactFormFeedback.hidden=true;
  contactFormFeedback.textContent='';
  contactFormSubmit.disabled=true;
  contactFormSubmitLabel.textContent='Enviando…';
  contactForm.setAttribute('aria-busy','true');

  try{
    const response=await fetch(contactForm.action,{
      method:'POST',
      body:new FormData(contactForm),
      headers:{Accept:'application/json'}
    });
    const result=await response.json().catch(()=>null);

    if(!response.ok){
      const details=Array.isArray(result?.errors)
        ?result.errors.map(error=>error.message).filter(Boolean).join(' ')
        :'';
      throw new Error(details||'Formspree no pudo recibir tu consulta. Inténtalo de nuevo.');
    }

    contactForm.reset();
    contactFormFeedback.setAttribute('role','status');
    contactFormFeedback.classList.remove('is-error');
    contactFormFeedback.textContent='¡Gracias! Recibimos tu consulta. Nos pondremos en contacto contigo pronto.';
  }catch(error){
    contactFormFeedback.setAttribute('role','alert');
    contactFormFeedback.classList.add('is-error');
    contactFormFeedback.textContent=error instanceof TypeError
      ?'No pudimos conectar con el servicio de contacto. Revisa tu conexión e inténtalo de nuevo.'
      :error.message;
  }finally{
    contactFormFeedback.hidden=false;
    contactFormSubmit.disabled=false;
    contactFormSubmitLabel.textContent='Enviar consulta';
    contactForm.removeAttribute('aria-busy');
  }
});

contactDialog?.querySelectorAll('[data-close-dialog]').forEach(button=>{
  button.addEventListener('click',()=>contactDialog.close());
});

contactDialog?.addEventListener('click',event=>{
  if(event.target===contactDialog)contactDialog.close();
});
