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
  themes:{commerce:'system',restaurant:'auto'},
  accent:'ember',
  tableCount:12,
  category:'pz',
  search:'',
  cart:[],
  service:'mesa',
  table:null,
  customer:'',
  phone:'',
  address:'',
  notes:'',
  sales:[],
  customers:[
    {id:'ana',name:'Ana Torres',phone:'55 1234 5678',balance:250},
    {id:'carlos',name:'Carlos Ruiz',phone:'55 2345 6789',balance:0},
    {id:'laura',name:'Laura Méndez',phone:'55 3456 7890',balance:680}
  ],
  cashCounted:'',
  cashClosed:false,
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
  commerce:{brand:'OZZVON POS',kind:'COMERCIO',icon:'▰',nav:[['Ventas','sale'],['Inventario','inventory'],['Clientes y créditos','customers'],['Reportes','reports'],['Corte de caja','cash'],['Ajustes','settings']]},
  restaurant:{brand:'Mi Pizzería',kind:'OZZVAN POS',icon:'🍕',nav:[['Nuevo pedido','sale'],['Pedidos','orders'],['Menú','menu'],['Configuración','settings']]}
};
const demoThemeOptions={
  commerce:[['system','Sistema'],['light','Claro'],['dark','Oscuro'],['mint','Menta'],['forest','Bosque'],['contrast','Alto contraste']],
  restaurant:[['auto','Auto'],['light','Claro'],['dark','Oscuro']]
};
const demoAccentOptions=[
  ['ember','Mandarina','#e4462a'],['esmeralda','Esmeralda','#0f9d6b'],
  ['oceano','Océano','#2563eb'],['violeta','Violeta','#7c3aed'],
  ['oro','Oro','#b7791f'],['rosa','Rosa','#db2777'],['grafito','Grafito','#3f3f46']
];
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
  const icons=restaurant?['＋','▤','☰','⚙']:['⌂','▣','♙','▥','◷','⚙'];
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
    for(let table=1;table<=demoState.tableCount;table++){
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
function renderDemoDataView(){
  const section=document.querySelector('#demo-data-view');
  section.replaceChildren();
  const heading=document.createElement('div');
  heading.className='demo-inventory-heading';
  const title=document.createElement('div');
  const overline=document.createElement('span');
  overline.className='demo-overline';
  overline.textContent='MODO DE MUESTRA';
  const titleText=document.createElement('h4');
  title.append(overline);
  const subheading=document.createElement('span');
  subheading.textContent='Datos temporales de esta visita';
  title.append(titleText);
  heading.append(title,subheading);
  section.append(heading);
  const cards=document.createElement('div');
  cards.className='demo-data-cards';
  if(demoState.view==='customers'){
    titleText.textContent='Clientes y créditos';
    const description=document.createElement('p');
    description.className='demo-data-intro';
    description.textContent='Consulta saldos y simula un abono. Los cambios solo viven en esta sesión.';
    section.append(description);
    demoState.customers.forEach(customer=>{
      const card=document.createElement('article');
      card.className='demo-data-card demo-customer-card';
      const identity=document.createElement('div');
      const name=document.createElement('b');
      name.textContent=customer.name;
      const phone=document.createElement('small');
      phone.textContent=customer.phone;
      identity.append(name,phone);
      const balance=document.createElement('strong');
      balance.textContent=demoMoney.format(customer.balance);
      const label=document.createElement('small');
      label.textContent='Saldo pendiente';
      const action=demoButton(customer.balance?'Simular abono de $100':'Sin saldo pendiente','demo-credit-payment',{demoCustomer:customer.id});
      action.disabled=!customer.balance;
      card.append(identity,document.createElement('span'));
      const details=document.createElement('div');
      details.className='demo-credit-balance';
      details.append(label,balance);
      card.replaceChildren(identity,details,action);
      cards.append(card);
    });
    section.append(cards);
    return;
  }
  if(demoState.view==='reports'){
    titleText.textContent='Resumen de ventas';
    const total=demoState.sales.reduce((sum,sale)=>sum+sale.total,0);
    const cash=demoState.sales.filter(sale=>sale.payment==='Efectivo').reduce((sum,sale)=>sum+sale.total,0);
    const cardPayments=demoState.sales.filter(sale=>sale.payment==='Tarjeta').reduce((sum,sale)=>sum+sale.total,0);
    const transfers=demoState.sales.filter(sale=>sale.payment==='Transferencia').reduce((sum,sale)=>sum+sale.total,0);
    const metrics=[['Ventas de muestra',demoState.sales.length],['Ingresos simulados',demoMoney.format(total)],['Efectivo',demoMoney.format(cash)],['Tarjeta',demoMoney.format(cardPayments)],['Transferencia',demoMoney.format(transfers)]];
    metrics.forEach(([label,value])=>{
      const card=document.createElement('article');
      card.className='demo-data-card demo-metric-card';
      const metricLabel=document.createElement('small');
      metricLabel.textContent=label;
      const metricValue=document.createElement('strong');
      metricValue.textContent=String(value);
      card.append(metricLabel,metricValue);
      cards.append(card);
    });
    const recent=document.createElement('div');
    recent.className='demo-recent-sales';
    const recentTitle=document.createElement('h5');
    recentTitle.textContent='Actividad reciente';
    recent.append(recentTitle);
    if(!demoState.sales.length){
      const empty=document.createElement('p');
      empty.className='demo-empty-result';
      empty.textContent='Completa una venta de muestra para ver aquí la actividad.';
      recent.append(empty);
    }else{
      demoState.sales.slice(0,5).forEach(sale=>{
        const row=document.createElement('div');
        row.className='demo-report-row';
        const description=document.createElement('span');
        description.textContent=`Venta #${String(sale.id).padStart(3,'0')} · ${sale.items} artículo(s) · ${sale.payment}`;
        const amount=document.createElement('b');
        amount.textContent=demoMoney.format(sale.total);
        row.append(description,amount);
        recent.append(row);
      });
    }
    section.append(cards,recent);
    return;
  }
  if(demoState.view==='cash'){
    titleText.textContent=demoState.cashClosed?'Corte de caja simulado':'Corte de caja';
    const opening=1000;
    const cashSales=demoState.sales.filter(sale=>sale.payment==='Efectivo').reduce((sum,sale)=>sum+sale.total,0);
    const expected=opening+cashSales;
    const counted=Number(demoState.cashCounted)||0;
    const summary=document.createElement('div');
    summary.className='demo-cash-summary';
    [['Fondo de apertura',demoMoney.format(opening)],['Ventas en efectivo',demoMoney.format(cashSales)],['Efectivo esperado',demoMoney.format(expected)]].forEach(([label,value])=>{
      const row=document.createElement('div');
      row.className='demo-report-row';
      const name=document.createElement('span');
      name.textContent=label;
      const amount=document.createElement('b');
      amount.textContent=value;
      row.append(name,amount);
      summary.append(row);
    });
    const form=document.createElement('label');
    form.className='demo-cash-count';
    form.textContent='Efectivo contado';
    const input=document.createElement('input');
    input.type='number';
    input.min='0';
    input.step='0.01';
    input.placeholder=demoMoney.format(expected);
    input.value=demoState.cashCounted;
    input.dataset.demoCashCount='true';
    input.setAttribute('aria-label','Efectivo contado en el corte de muestra');
    form.append(input);
    const difference=document.createElement('p');
    difference.className='demo-cash-difference';
    difference.textContent=`Diferencia: ${demoMoney.format(demoState.cashCounted===''?0:counted-expected)}`;
    const close=demoButton(demoState.cashClosed?'Corte de muestra realizado':'Simular corte de caja','demo-cash-close',{demoCashClose:'true'});
    close.disabled=demoState.cashClosed;
    section.append(summary,form,difference,close);
    return;
  }
  if(demoState.view==='menu'){
    titleText.textContent='Menú de muestra';
    const products=demoData.restaurant;
    products.forEach(product=>{
      const card=document.createElement('article');
      card.className='demo-data-card demo-menu-card';
      const icon=document.createElement('span');
      icon.textContent=product.icon;
      icon.setAttribute('aria-hidden','true');
      const name=document.createElement('b');
      name.textContent=product.name;
      const price=document.createElement('small');
      price.textContent=`Desde ${demoMoney.format(Math.min(...product.sizes.map(size=>size[1])))}`;
      card.append(icon,name,price);
      cards.append(card);
    });
    section.append(cards);
  }
}
function renderDemoSettings(){
  const restaurant=demoState.product==='restaurant';
  const themeContainer=document.querySelector('#demo-theme-options');
  const selectedTheme=demoState.themes[demoState.product];
  themeContainer.replaceChildren(...demoThemeOptions[demoState.product].map(([id,label])=>{
    const button=demoButton(label,'demo-setting-option',{demoThemeOption:id});
    button.setAttribute('role','radio');
    button.setAttribute('aria-checked',String(id===selectedTheme));
    if(id===selectedTheme)button.classList.add('selected');
    return button;
  }));
  const accentContainer=document.querySelector('#demo-accent-options');
  accentContainer.replaceChildren(...demoAccentOptions.map(([id,label,color])=>{
    const button=demoButton(label,'demo-setting-option',{demoAccent:id});
    button.setAttribute('role','radio');
    button.setAttribute('aria-checked',String(id===demoState.accent));
    if(id===demoState.accent)button.classList.add('selected');
    const swatch=document.createElement('i');
    swatch.style.setProperty('--demo-swatch-color',color);
    button.prepend(swatch);
    return button;
  }));
  document.querySelector('#demo-accent-setting').hidden=!restaurant;
  document.querySelector('#demo-tables-setting').hidden=!restaurant;
  document.querySelector('#demo-table-count').value=demoState.tableCount;
}
function renderDemo(){
  const restaurant=demoState.product==='restaurant';
  const quantity=demoState.cart.reduce((sum,item)=>sum+item.quantity,0);
  const progress=demoState.completed?3:Math.min(quantity,2);
  const screenLabels=restaurant
    ?{sale:'NUEVO PEDIDO',orders:'PEDIDOS',menu:'MENÚ',settings:'AJUSTES'}
    :{sale:'VENTAS',inventory:'INVENTARIO',customers:'CLIENTES',reports:'REPORTES',cash:'CORTE DE CAJA',settings:'AJUSTES'};
  const screenTitles=restaurant
    ?{sale:'Nuevo pedido',orders:'Pedidos de hoy',menu:'Menú de muestra',settings:'Apariencia y preferencias'}
    :{sale:'Ventas',inventory:'Inventario',customers:'Clientes y créditos',reports:'Resumen de ventas',cash:'Corte de caja',settings:'Apariencia y preferencias'};
  const app=document.querySelector('#demo-app');
  app.dataset.demoProduct=demoState.product;
  const theme=demoState.themes[demoState.product];
  const followsSystem=theme==='system'||theme==='auto';
  app.dataset.demoTheme=followsSystem
    ?window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'
    :theme;
  app.dataset.demoAccent=demoState.accent;
  demoTabs.forEach(tab=>{
    const active=tab.dataset.demoProduct===demoState.product;
    tab.classList.toggle('active',active);
    tab.setAttribute('aria-selected',String(active));
  });
  renderDemoNav();
  document.querySelector('#demo-screen-label').textContent=screenLabels[demoState.view];
  document.querySelector('#demo-screen-title').textContent=screenTitles[demoState.view];
  document.querySelector('#demo-register-label').textContent=restaurant?'En línea · modo muestra':'Caja abierta';
  document.querySelector('#demo-brand-kind').textContent=restaurant?'OZZVAN POS':'COMERCIO';
  document.querySelector('#demo-catalog-label').textContent=restaurant?'MENÚ':'BUSCAR PRODUCTOS';
  document.querySelector('#demo-catalog-title').textContent=restaurant?'Elige productos':'Nueva venta';
  document.querySelector('#demo-commerce-tools').hidden=restaurant;
  document.querySelector('#demo-restaurant-tools').hidden=!restaurant;
  document.querySelector('#demo-sale-layout').hidden=demoState.view!=='sale';
  document.querySelector('#demo-inventory-view').hidden=restaurant||demoState.view!=='inventory';
  document.querySelector('#demo-orders-view').hidden=!restaurant||demoState.view!=='orders';
  document.querySelector('#demo-data-view').hidden=demoState.view==='sale'||demoState.view==='inventory'||demoState.view==='orders'||demoState.view==='settings';
  document.querySelector('#demo-settings-view').hidden=demoState.view!=='settings';
  document.querySelector('.demo-challenge').hidden=demoState.view!=='sale';
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
  document.querySelector('#demo-cart').hidden=demoState.view!=='sale';
  renderDemoInventory();
  renderDemoDataView();
  renderDemoSettings();
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
  demoState.sales.unshift({
    id:demoState.sales.length+1,
    total,
    payment:demoState.payment,
    items:demoState.cart.reduce((sum,item)=>sum+item.quantity,0)
  });
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
document.querySelector('#demo-settings-view').addEventListener('click',event=>{
  const theme=event.target.closest('[data-demo-theme-option]');
  if(theme){
    demoState.themes[demoState.product]=theme.dataset.demoThemeOption;
    renderDemo();
    return;
  }
  const accent=event.target.closest('[data-demo-accent]');
  if(accent){
    demoState.accent=accent.dataset.demoAccent;
    renderDemo();
  }
});
document.querySelector('#demo-data-view').addEventListener('click',event=>{
  const payment=event.target.closest('[data-demo-customer]');
  if(payment){
    const customer=demoState.customers.find(item=>item.id===payment.dataset.demoCustomer);
    if(!customer)return;
    customer.balance=Math.max(0,customer.balance-100);
    demoNotice(`Abono de muestra registrado. Nuevo saldo: ${demoMoney.format(customer.balance)}. No se guardó.`);
    renderDemoDataView();
    return;
  }
  if(event.target.closest('[data-demo-cash-close]')){
    demoState.cashClosed=true;
    demoNotice('Corte de caja de muestra realizado. No se guardó ningún dato.');
    renderDemoDataView();
  }
});
document.querySelector('#demo-data-view').addEventListener('input',event=>{
  if(!event.target.matches('[data-demo-cash-count]'))return;
  demoState.cashCounted=event.target.value;
  const sales=demoState.sales.filter(sale=>sale.payment==='Efectivo').reduce((sum,sale)=>sum+sale.total,0);
  const expected=1000+sales;
  const difference=Number(demoState.cashCounted||0)-expected;
  document.querySelector('.demo-cash-difference').textContent=`Diferencia: ${demoMoney.format(difference)}`;
});
document.querySelector('#demo-table-count').addEventListener('input',event=>{
  const parsed=Number(event.target.value);
  if(Number.isInteger(parsed)&&parsed>=1&&parsed<=24)demoState.tableCount=parsed;
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
