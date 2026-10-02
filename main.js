const menuToggle=document.querySelector('.menu-toggle');const nav=document.querySelector('.desktop-nav');
menuToggle?.addEventListener('click',()=>{const open=menuToggle.getAttribute('aria-expanded')==='true';menuToggle.setAttribute('aria-expanded',String(!open));nav.classList.toggle('open',!open)});
document.querySelectorAll('.desktop-nav a').forEach(a=>a.addEventListener('click',()=>{menuToggle?.setAttribute('aria-expanded','false');nav?.classList.remove('open')}));
const tabs=document.querySelectorAll('.product-tab');const shots=document.querySelectorAll('.product-shot');tabs.forEach(tab=>tab.addEventListener('click',()=>{const product=tab.dataset.product;tabs.forEach(t=>{const active=t===tab;t.classList.toggle('active',active);t.setAttribute('aria-selected',String(active))});shots.forEach(shot=>shot.classList.toggle('active',shot.dataset.shot===product))}));
document.querySelectorAll('details').forEach(detail=>detail.addEventListener('toggle',()=>{if(detail.open)document.querySelectorAll('details').forEach(other=>{if(other!==detail)other.open=false})}));
const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-visible');observer.unobserve(entry.target)}}),{threshold:.12});document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));
const header=document.querySelector('.site-header');window.addEventListener('scroll',()=>header.classList.toggle('scrolled',window.scrollY>24),{passive:true});

const contactDialog=document.querySelector('#contact-dialog');
const contactForm=document.querySelector('#contact-form');
const formStatus=document.querySelector('#form-status');
const openContactForm=document.querySelector('#open-contact-form');

openContactForm?.addEventListener('click',()=>{
  formStatus.textContent='';
  contactDialog.showModal();
});

contactDialog?.querySelectorAll('[data-close-dialog]').forEach(button=>{
  button.addEventListener('click',()=>contactDialog.close());
});

contactDialog?.addEventListener('click',event=>{
  if(event.target===contactDialog)contactDialog.close();
});

contactForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  const submitButton=contactForm.querySelector('[type="submit"]');
  submitButton.disabled=true;
  formStatus.classList.remove('success','error');
  formStatus.textContent='Enviando tu consulta…';

  try{
    const response=await fetch(contactForm.action,{
      method:'POST',
      body:new FormData(contactForm),
      headers:{Accept:'application/json'}
    });
    const result=await response.json();

    if(!response.ok||!result.success||result.success==='false'){
      throw new Error(result.message||'No fue posible enviar el formulario.');
    }

    contactForm.reset();
    formStatus.classList.add('success');
    formStatus.textContent='¡Listo! Recibimos tu consulta y nos pondremos en contacto contigo.';
  }catch(error){
    console.error('Error al enviar el formulario de contacto:',error);
    formStatus.classList.add('error');
    formStatus.textContent='No se pudo enviar tu consulta. Inténtalo de nuevo más tarde o escríbenos a contacto@ozzvon.com.';
  }finally{
    submitButton.disabled=false;
  }
});
