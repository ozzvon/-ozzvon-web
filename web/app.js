const registrationDialog=document.querySelector('#registration-dialog');
const registrationForm=document.querySelector('#registration-form');
const registrationFeedback=document.querySelector('#mensaje-respuesta');
const accountControl=document.querySelector('#open-login-dialog');
const loginDialog=document.querySelector('#login-dialog');
const accountDialog=document.querySelector('#account-dialog');
const forgotDialog=document.querySelector('#forgot-dialog');
const resetDialog=document.querySelector('#reset-dialog');
const loginForm=document.querySelector('#login-form');
const forgotForm=document.querySelector('#forgot-form');
const resetForm=document.querySelector('#reset-form');
let accountData=null;

function feedback(element,message,error=false){
  element.textContent=message;
  element.classList.toggle('is-error',error);
  element.setAttribute('role',error?'alert':'status');
  element.hidden=false;
}

async function api(url,options={}){
  const response=await fetch(url,{
    headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{})},
    ...options
  });
  let result;
  try{
    result=await response.json();
  }catch{
    throw new Error('El servicio devolvió una respuesta no válida. Inténtalo de nuevo.');
  }
  if(!response.ok)throw new Error(result?.mensaje||'No se pudo completar la solicitud.');
  return result;
}

function updateAccountButton(){
  if(!accountControl)return;
  accountControl.textContent=accountData?'Mi cuenta':'Iniciar sesión';
  accountControl.setAttribute(
    'aria-label',
    accountData?`Ver la cuenta de ${accountData.nombre_negocio}`:'Iniciar sesión'
  );
}

function renderAccount(){
  if(!accountData)return;
  document.querySelector('#account-business').textContent=accountData.nombre_negocio;
  document.querySelector('#account-email').textContent=accountData.email;
  const created=new Date(accountData.fecha_creacion);
  document.querySelector('#account-created').textContent=Number.isNaN(created.getTime())
    ?accountData.fecha_creacion
    :new Intl.DateTimeFormat('es-MX',{dateStyle:'medium'}).format(created);
  const license=document.querySelector('#account-license');
  license.textContent={activa:'Activa',suspendida:'Suspendida',baja:'De baja'}[accountData.licencia_estado]||'Sin estado';
  license.classList.toggle('is-suspended',accountData.licencia_estado==='suspendida');
  license.classList.toggle('is-cancelled',accountData.licencia_estado==='baja');
  const softwareList=document.querySelector('#account-software');
  softwareList.replaceChildren(...(accountData.software||[]).map(product=>{
    const item=document.createElement('li');
    const name=document.createElement('strong');
    const status=document.createElement('span');
    const stores=document.createElement('small');
    name.textContent=product.nombre;
    status.textContent=product.activo?'Acceso activo':'Acceso desactivado';
    stores.textContent=`Límite: ${product.sucursales_max} ${product.sucursales_max===1?'sucursal':'sucursales'}`;
    const branchNames=(product.sucursales||[])
      .filter(branch=>branch.activa)
      .map(branch=>branch.nombre);
    if(branchNames.length)stores.textContent+=` · ${branchNames.join(', ')}`;
    else if(product.activo)stores.textContent+=' · Se crean al ingresar al POS';
    item.append(name,status,stores);
    return item;
  }));
}

async function refreshAccount(){
  const result=await api('/api/cuenta');
  accountData=result.cuenta;
  updateAccountButton();
  renderAccount();
  return accountData;
}

document.querySelector('#open-registration-form')?.addEventListener('click',()=>{
  registrationDialog?.showModal();
});

registrationForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!registrationForm.reportValidity())return;
  const data=new FormData(registrationForm);
  if(data.get('password')!==data.get('confirmar_password')){
    feedback(registrationFeedback,'Las contraseñas no coinciden.',true);
    return;
  }
  const submit=registrationForm.querySelector('[type="submit"]');
  const label=registrationForm.querySelector('.registration-submit-label');
  submit.disabled=true;
  label.textContent='Creando cuenta…';
  registrationFeedback.hidden=true;
  try{
    const response=await fetch('/api/registro',{
      method:'POST',
      headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({
        nombre_negocio:data.get('nombre_negocio'),
        email:data.get('email'),
        password:data.get('password')
      })
    });
    const result=await response.json();
    if(response.status!==201)throw new Error(result?.mensaje||'No se pudo crear la cuenta.');
    registrationForm.reset();
    feedback(registrationFeedback,result.mensaje||'¡Tu cuenta fue creada correctamente!');
    await refreshAccount().catch(error=>{
      console.error('La cuenta se creó, pero no se pudo actualizar el perfil en pantalla:',error);
    });
  }catch(error){
    feedback(registrationFeedback,error instanceof TypeError
      ?'No pudimos conectar con el servicio. Inténtalo de nuevo.'
      :error.message,true);
  }finally{
    submit.disabled=false;
    label.textContent='Crear mi cuenta POS';
  }
});

async function openAccountOrLogin(){
  if(!accountData){
    loginDialog?.showModal();
    return;
  }
  try{
    await refreshAccount();
    accountDialog.showModal();
  }catch(error){
    if(error.message.includes('Inicia sesión')){
      accountData=null;
      updateAccountButton();
      loginDialog.showModal();
    }else{
      feedback(document.querySelector('#account-feedback'),error.message,true);
      accountDialog.showModal();
    }
  }
}
accountControl?.addEventListener('click',openAccountOrLogin);

loginForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!loginForm.reportValidity())return;
  const data=new FormData(loginForm);
  const submit=loginForm.querySelector('[type="submit"]');
  const label=loginForm.querySelector('.login-submit-label');
  const message=document.querySelector('#login-feedback');
  submit.disabled=true;
  label.textContent='Iniciando sesión…';
  message.hidden=true;
  try{
    await api('/api/auth/login',{
      method:'POST',
      body:JSON.stringify({email:data.get('email'),password:data.get('password')})
    });
    loginForm.reset();
    await refreshAccount();
    loginDialog.close();
    accountDialog.showModal();
  }catch(error){
    feedback(message,error instanceof TypeError
      ?'No pudimos conectar con el servicio. Inténtalo de nuevo.'
      :error.message,true);
  }finally{
    submit.disabled=false;
    label.textContent='Iniciar sesión';
  }
});

document.querySelector('#open-registration-from-login')?.addEventListener('click',()=>{
  loginDialog.close();
  registrationDialog.showModal();
});
document.querySelector('#open-forgot-dialog')?.addEventListener('click',()=>{
  forgotForm.elements.email.value=loginForm.elements.email.value;
  loginDialog.close();
  forgotDialog.showModal();
});
document.querySelector('#account-reset-password')?.addEventListener('click',()=>{
  forgotForm.elements.email.value=accountData?.email||'';
  accountDialog.close();
  forgotDialog.showModal();
});

forgotForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!forgotForm.reportValidity())return;
  const submit=forgotForm.querySelector('[type="submit"]');
  const label=forgotForm.querySelector('.forgot-submit-label');
  const message=document.querySelector('#forgot-feedback');
  submit.disabled=true;
  label.textContent='Enviando…';
  message.hidden=true;
  try{
    const data=new FormData(forgotForm);
    const result=await api('/api/auth/forgot-password',{
      method:'POST',body:JSON.stringify({email:data.get('email')})
    });
    feedback(message,result.mensaje);
  }catch(error){
    feedback(message,error instanceof TypeError
      ?'No pudimos conectar con el servicio. Inténtalo de nuevo.'
      :error.message,true);
  }finally{
    submit.disabled=false;
    label.textContent='Enviar enlace';
  }
});

resetForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!resetForm.reportValidity())return;
  const data=new FormData(resetForm);
  const message=document.querySelector('#reset-feedback');
  if(data.get('password')!==data.get('confirmar_password')){
    feedback(message,'Las contraseñas no coinciden.',true);
    return;
  }
  const submit=resetForm.querySelector('[type="submit"]');
  const label=resetForm.querySelector('.reset-submit-label');
  submit.disabled=true;
  label.textContent='Actualizando…';
  message.hidden=true;
  try{
    const result=await api('/api/auth/reset-password',{
      method:'POST',
      body:JSON.stringify({
        token:new URLSearchParams(location.hash.slice(1)).get('restablecer'),
        password:data.get('password')
      })
    });
    await refreshAccount();
    history.replaceState({},'',location.pathname+location.search);
    resetDialog.close();
    accountDialog.showModal();
    feedback(document.querySelector('#account-feedback'),result.mensaje);
  }catch(error){
    feedback(message,error instanceof TypeError
      ?'No pudimos conectar con el servicio. Inténtalo de nuevo.'
      :error.message,true);
  }finally{
    submit.disabled=false;
    label.textContent='Actualizar contraseña';
  }
});

document.querySelector('#logout-button')?.addEventListener('click',async()=>{
  const button=document.querySelector('#logout-button');
  button.disabled=true;
  try{
    await api('/api/auth/logout',{method:'POST'});
    accountData=null;
    updateAccountButton();
    accountDialog.close();
    loginDialog.showModal();
  }catch(error){
    feedback(document.querySelector('#account-feedback'),error.message,true);
  }finally{
    button.disabled=false;
  }
});

[
  ['#registration-dialog','[data-close-registration]'],
  ['#login-dialog','[data-close-login]'],
  ['#account-dialog','[data-close-account]'],
  ['#forgot-dialog','[data-close-forgot]'],
  ['#reset-dialog','[data-close-reset]']
].forEach(([dialogSelector,buttonSelector])=>{
  const dialog=document.querySelector(dialogSelector);
  dialog?.querySelector(buttonSelector)?.addEventListener('click',()=>dialog.close());
  dialog?.addEventListener('click',event=>{
    if(event.target===dialog)dialog.close();
  });
});

async function googleCredential(response){
  const fromRegistration=registrationDialog?.open;
  const message=document.querySelector(fromRegistration?'#mensaje-respuesta':'#login-feedback');
  const name=document.querySelector(fromRegistration?'#google-business-name':'#google-login-business-name')?.value.trim();
  try{
    await api('/api/auth/google',{
      method:'POST',
      body:JSON.stringify({
        credential:response.credential,
        ...(name?{nombre_negocio:name}:{})
      })
    });
    await refreshAccount();
    registrationDialog?.close();
    loginDialog?.close();
    accountDialog?.showModal();
  }catch(error){
    feedback(message,error instanceof TypeError
      ?'No pudimos conectar con el servicio. Inténtalo de nuevo.'
      :error.message,true);
  }
}

async function configureGoogle(){
  try{
    const {google_client_id:clientId}=await api('/api/auth/config');
    if(!clientId)return;
    const script=document.createElement('script');
    script.src='https://accounts.google.com/gsi/client';
    script.async=true;
    script.defer=true;
    script.onload=()=>{
      if(!window.google?.accounts?.id)return;
      window.google.accounts.id.initialize({client_id:clientId,callback:googleCredential});
      [['#google-login-option','#google-login-button'],['#google-register-option','#google-register-button']].forEach(([optionSelector,buttonSelector])=>{
        document.querySelector(optionSelector).hidden=false;
        window.google.accounts.id.renderButton(document.querySelector(buttonSelector),{
          theme:'filled_black',size:'large',text:'continue_with',shape:'rectangular',width:320
        });
      });
    };
    script.onerror=()=>console.error('No se pudo cargar Google Identity Services.');
    document.head.append(script);
  }catch(error){
    if(!(error instanceof TypeError))console.error('No se pudo configurar el inicio con Google:',error);
  }
}

refreshAccount().catch(error=>{
  if(!(error instanceof TypeError)&&!error.message.includes('Inicia sesión')){
    console.error('No se pudo consultar la sesión actual:',error);
  }
}).finally(updateAccountButton);
configureGoogle();
if(location.hash==='#registro')registrationDialog?.showModal();
if(new URLSearchParams(location.hash.slice(1)).has('restablecer'))resetDialog?.showModal();
