const registrationDialog=document.querySelector('#registration-dialog');
const openRegistrationForm=document.querySelector('#open-registration-form');
const registrationForm=document.querySelector('#registration-form');
const registrationFeedback=document.querySelector('#mensaje-respuesta');
const registrationSubmit=registrationForm?.querySelector('[type="submit"]');
const registrationSubmitLabel=registrationForm?.querySelector('.registration-submit-label');
const accountControl=document.querySelector('#open-login-dialog');
const loginDialog=document.querySelector('#login-dialog');
const accountDialog=document.querySelector('#account-dialog');
const forgotDialog=document.querySelector('#forgot-dialog');
const resetDialog=document.querySelector('#reset-dialog');
const loginForm=document.querySelector('#login-form');
const forgotForm=document.querySelector('#forgot-form');
const resetForm=document.querySelector('#reset-form');
let accountData=null;

openRegistrationForm?.addEventListener('click',()=>{
  registrationDialog?.showModal();
});

registrationForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!registrationForm.reportValidity())return;

  const formData=new FormData(registrationForm);
  const password=formData.get('password');
  if(password!==formData.get('confirmar_password')){
    registrationFeedback.textContent='Las contraseñas no coinciden.';
    registrationFeedback.classList.add('is-error');
    registrationFeedback.setAttribute('role','alert');
    registrationFeedback.hidden=false;
    return;
  }

  registrationFeedback.hidden=true;
  registrationFeedback.textContent='';
  registrationFeedback.classList.remove('is-error');
  registrationSubmit.disabled=true;
  registrationSubmitLabel.textContent='Creando cuenta…';
  registrationForm.setAttribute('aria-busy','true');

  try{
    const response=await fetch(registrationForm.dataset.apiUrl||'/api/registro',{
      method:'POST',
      headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({
        nombre_negocio:formData.get('nombre_negocio'),
        email:formData.get('email'),
        password
      })
    });
    let result;
    try{
      result=await response.json();
    }catch{
      throw new Error('El servicio devolvió una respuesta no válida. Inténtalo de nuevo.');
    }

    if(response.status!==201){
      throw new Error(result?.mensaje||'No se pudo crear la cuenta. Inténtalo de nuevo.');
    }

    registrationForm.reset();
    registrationFeedback.textContent=result?.mensaje||'¡Tu cuenta fue creada correctamente!';
    registrationFeedback.setAttribute('role','status');
    await refreshAccount().catch(error=>{
      console.error('La cuenta se creó, pero no se pudo actualizar el perfil en pantalla:',error);
    });
  }catch(error){
    registrationFeedback.textContent=error instanceof TypeError
      ?'No pudimos conectar con el servicio de registro. Revisa tu conexión e inténtalo de nuevo.'
      :error.message;
    registrationFeedback.setAttribute('role','alert');
    registrationFeedback.classList.add('is-error');
  }finally{
    registrationFeedback.hidden=false;
    registrationSubmit.disabled=false;
    registrationSubmitLabel.textContent='Crear mi cuenta POS';
    registrationForm.removeAttribute('aria-busy');
  }
});

registrationDialog?.querySelectorAll('[data-close-registration]').forEach(button=>{
  button.addEventListener('click',()=>registrationDialog.close());
});

registrationDialog?.addEventListener('click',event=>{
  if(event.target===registrationDialog)registrationDialog.close();
});

async function apiRequest(url,options={}){
  const response=await fetch(url,{headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{})},...options});
  let result=null;
  try{
    result=await response.json();
  }catch{
    throw new Error('El servicio devolvió una respuesta no válida. Inténtalo de nuevo.');
  }
  if(!response.ok)throw new Error(result?.mensaje||'No se pudo completar la solicitud.');
  return result;
}

function showFeedback(element,message,isError=false){
  element.textContent=message;
  element.classList.toggle('is-error',isError);
  element.setAttribute('role',isError?'alert':'status');
  element.hidden=false;
}

function setAccountControl(){
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
  const licenseLabels={activa:'Activa',suspendida:'Suspendida',baja:'De baja'};
  license.textContent=licenseLabels[accountData.licencia_estado]||'Sin estado';
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
  const result=await apiRequest('/api/cuenta');
  accountData=result.cuenta;
  setAccountControl();
  renderAccount();
  return accountData;
}

accountControl?.addEventListener('click',async()=>{
  if(!accountData){
    loginDialog?.showModal();
    return;
  }
  const feedback=document.querySelector('#account-feedback');
  feedback.hidden=true;
  try{
    await refreshAccount();
    accountDialog?.showModal();
  }catch(error){
    if(error.message.includes('Inicia sesión')){
      accountData=null;
      setAccountControl();
      loginDialog?.showModal();
      return;
    }
    showFeedback(feedback,error.message,true);
    accountDialog?.showModal();
  }
});

loginForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!loginForm.reportValidity())return;
  const feedback=document.querySelector('#login-feedback');
  const submit=loginForm.querySelector('[type="submit"]');
  const label=loginForm.querySelector('.login-submit-label');
  const formData=new FormData(loginForm);
  feedback.hidden=true;
  submit.disabled=true;
  label.textContent='Iniciando sesión…';
  try{
    await apiRequest('/api/auth/login',{
      method:'POST',
      body:JSON.stringify({email:formData.get('email'),password:formData.get('password')})
    });
    loginForm.reset();
    await refreshAccount();
    loginDialog.close();
    accountDialog.showModal();
  }catch(error){
    showFeedback(feedback,error instanceof TypeError
      ?'No pudimos conectar con el servicio. Inténtalo de nuevo.'
      :error.message,true);
  }finally{
    submit.disabled=false;
    label.textContent='Iniciar sesión';
  }
});

document.querySelector('#open-registration-from-login')?.addEventListener('click',()=>{
  loginDialog.close();
  registrationDialog?.showModal();
});

document.querySelector('#open-forgot-dialog')?.addEventListener('click',()=>{
  const loginEmail=loginForm.elements.email.value;
  forgotForm.elements.email.value=loginEmail;
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
  const feedback=document.querySelector('#forgot-feedback');
  const submit=forgotForm.querySelector('[type="submit"]');
  const label=forgotForm.querySelector('.forgot-submit-label');
  feedback.hidden=true;
  submit.disabled=true;
  label.textContent='Enviando…';
  try{
    const formData=new FormData(forgotForm);
    const result=await apiRequest('/api/auth/forgot-password',{
      method:'POST',
      body:JSON.stringify({email:formData.get('email')})
    });
    showFeedback(feedback,result.mensaje);
  }catch(error){
    showFeedback(feedback,error instanceof TypeError
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
  const feedback=document.querySelector('#reset-feedback');
  const submit=resetForm.querySelector('[type="submit"]');
  const label=resetForm.querySelector('.reset-submit-label');
  const formData=new FormData(resetForm);
  if(formData.get('password')!==formData.get('confirmar_password')){
    showFeedback(feedback,'Las contraseñas no coinciden.',true);
    return;
  }
  submit.disabled=true;
  label.textContent='Actualizando…';
  feedback.hidden=true;
  try{
    const result=await apiRequest('/api/auth/reset-password',{
      method:'POST',
      body:JSON.stringify({
        token:new URLSearchParams(window.location.hash.slice(1)).get('restablecer'),
        password:formData.get('password')
      })
    });
    await refreshAccount();
    window.history.replaceState({},'',window.location.pathname+window.location.search);
    resetDialog.close();
    accountDialog.showModal();
    showFeedback(document.querySelector('#account-feedback'),result.mensaje);
  }catch(error){
    showFeedback(feedback,error instanceof TypeError
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
    await apiRequest('/api/auth/logout',{method:'POST'});
    accountData=null;
    setAccountControl();
    accountDialog.close();
    loginDialog.showModal();
  }catch(error){
    showFeedback(document.querySelector('#account-feedback'),error.message,true);
  }finally{
    button.disabled=false;
  }
});

const dialogCloseSelectors=[
  ['#login-dialog','[data-close-login]'],
  ['#account-dialog','[data-close-account]'],
  ['#forgot-dialog','[data-close-forgot]'],
  ['#reset-dialog','[data-close-reset]']
];
dialogCloseSelectors.forEach(([dialogSelector,buttonSelector])=>{
  const dialog=document.querySelector(dialogSelector);
  dialog?.querySelector(buttonSelector)?.addEventListener('click',()=>dialog.close());
  dialog?.addEventListener('click',event=>{
    if(event.target===dialog)dialog.close();
  });
});

async function handleGoogleCredential(response){
  const feedback=document.querySelector(
    registrationDialog?.open?'#mensaje-respuesta':'#login-feedback'
  );
  const businessName=document.querySelector(
    registrationDialog?.open?'#google-business-name':'#google-login-business-name'
  )?.value.trim();
  try{
    const result=await apiRequest('/api/auth/google',{
      method:'POST',
      body:JSON.stringify({
        credential:response.credential,
        ...(businessName?{nombre_negocio:businessName}:{})
      })
    });
    await refreshAccount();
    registrationDialog?.close();
    loginDialog?.close();
    accountDialog?.showModal();
    if(feedback)feedback.hidden=true;
    return result;
  }catch(error){
    if(feedback)showFeedback(feedback,error instanceof TypeError
      ?'No pudimos conectar con el servicio. Inténtalo de nuevo.'
      :error.message,true);
  }
}

async function configureGoogleSignIn(){
  try{
    const {google_client_id:clientId}=await apiRequest('/api/auth/config');
    if(!clientId)return;
    const script=document.createElement('script');
    script.src='https://accounts.google.com/gsi/client';
    script.async=true;
    script.defer=true;
    script.onload=()=>{
      if(!window.google?.accounts?.id)return;
      window.google.accounts.id.initialize({client_id:clientId,callback:handleGoogleCredential});
      [['#google-login-option','#google-login-button'],['#google-register-option','#google-register-button']].forEach(([optionSelector,buttonSelector])=>{
        const option=document.querySelector(optionSelector);
        const button=document.querySelector(buttonSelector);
        option.hidden=false;
        window.google.accounts.id.renderButton(button,{
          theme:'filled_black',
          size:'large',
          text:'continue_with',
          shape:'rectangular',
          width:320
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
}).finally(setAccountControl);
configureGoogleSignIn();

const resetToken=new URLSearchParams(window.location.hash.slice(1)).get('restablecer');
if(resetToken)resetDialog?.showModal();

document.querySelectorAll('[data-close-registration]').forEach(button=>{
  button.addEventListener('click',()=>registrationDialog?.close());
});
