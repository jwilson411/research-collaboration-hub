'use strict';
// Dynamic application views use the pinned, locally bundled USWDS component APIs.
// Nodes are moved, never cloned: form/session bindings and selected File objects survive.
(() => {
  let serial = 0;
  const unique = prefix => `${prefix}-${++serial}`;
  const describe = (input, id) => input.setAttribute('aria-describedby', [...new Set((input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean).concat(id))].join(' '));
  function headingLevel(node) {
    for (let ancestor = node.parentElement; ancestor; ancestor = ancestor.parentElement) {
      const heading = Array.from(ancestor.children).map(child => /^H[1-6]$/.test(child.tagName) ? child : child.matches('.family-heading,.row-head,.content-heading,.page-heading') ? child.querySelector('h1,h2,h3,h4,h5,h6') : null).find(Boolean);
      if (heading) return Math.min(6, Number(heading.tagName.slice(1)) + 1);
      if (ancestor.classList.contains('usa-accordion')) {
        const buttonHeading = ancestor.querySelector(':scope > .usa-accordion__heading');
        if (buttonHeading) return Math.min(6, Number(buttonHeading.tagName.slice(1)) + 1);
      }
    }
    return 2;
  }
  function accordions(root) {
    if(!window.HubUSWDS?.accordion)return;
    root.querySelectorAll('details').forEach(details => {
      const summary = details.querySelector(':scope > summary');
      if (!summary) return;
      const group = document.createElement('div');
      for (const attribute of details.attributes) if (attribute.name !== 'open') group.setAttribute(attribute.name, attribute.value);
      group.classList.add('usa-accordion');
      group.setAttribute('data-allow-multiple', '');
      const heading = document.createElement(`h${headingLevel(details)}`);
      heading.className = 'usa-accordion__heading';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'usa-accordion__button';
      button.setAttribute('aria-expanded', String(details.open));
      const content = document.createElement('div');
      content.className = 'usa-accordion__content usa-prose';
      content.id = unique('hub-accordion');
      button.setAttribute('aria-controls', content.id);
      button.append(...summary.childNodes);
      summary.remove();
      content.append(...details.childNodes);
      heading.append(button);
      group.append(heading, content);
      details.replaceWith(group);
      window.HubUSWDS?.accordion.init(group);
    });
  }
  function checkboxes(root) {
    root.querySelectorAll('input[type="checkbox"]').forEach(input => {
      if (input.closest('.usa-checkbox')) return;
      const label = input.closest('label') || (input.id && Array.from(root.querySelectorAll('label')).find(label => label.htmlFor === input.id));
      if (!label) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'usa-checkbox';
      label.before(wrapper);
      input.id ||= unique('hub-checkbox');
      input.classList.add('usa-checkbox__input');
      label.htmlFor = input.id;
      label.classList.add('usa-checkbox__label');
      wrapper.append(input, label);
    });
  }
  function forms(root) {
    root.querySelectorAll('form:not(.usa-search)').forEach(form => {
      form.classList.add('usa-form');
      if (!form.querySelector(':scope > .usa-fieldset')) {
        const fieldset = document.createElement('fieldset');
        fieldset.className = 'usa-fieldset';
        const legend = document.createElement('legend');
        legend.className = 'usa-legend usa-sr-only';
        legend.textContent = form.closest('section')?.querySelector('h2,h3,h4')?.textContent || form.id.replaceAll('-', ' ');
        fieldset.append(legend, ...form.childNodes);
        form.append(fieldset);
      }
      form.querySelectorAll('fieldset').forEach(fieldset => fieldset.classList.add('usa-fieldset'));
      form.querySelectorAll('legend').forEach(legend => legend.classList.add('usa-legend'));
      form.querySelectorAll('.form-hint').forEach(hint => hint.classList.add(hint.matches('[role="alert"]') ? 'usa-error-message' : 'usa-hint'));
      form.querySelectorAll('input:not([type="checkbox"]):not([type="hidden"]),select,textarea').forEach(input => {
        if (input.classList.contains('usa-file-input__input')) return;
        const label = input.labels?.[0];
        if (!label) return;
        label.classList.add('usa-label');
        if (input.matches('input:not([type="file"]),textarea')) input.classList.add(input.tagName === 'TEXTAREA' ? 'usa-textarea' : 'usa-input');
        if (input.tagName === 'SELECT') input.classList.add('usa-select');
        if (!input.closest('.usa-form-group') && label.parentElement === input.parentElement) {
          const hint = input.nextElementSibling?.matches('.usa-hint,.form-hint') ? input.nextElementSibling : null;
          const group = document.createElement('div');
          group.className = 'usa-form-group';
          label.before(group);
          group.append(label, input);
          if (hint) {hint.id ||= unique('hub-hint');group.append(hint);describe(input, hint.id);}
        }
      });
    });
  }
  function alerts(root) {
    root.querySelectorAll('.notice').forEach(original => {
      let node=original;
      if(['P','SPAN'].includes(node.tagName)){const container=document.createElement('div');for(const attribute of node.attributes)container.setAttribute(attribute.name,attribute.value);container.append(...node.childNodes);node.replaceWith(container);node=container;}
      node.classList.add('usa-alert', node.classList.contains('error') ? 'usa-alert--error' : 'usa-alert--info');
      if (node.querySelector(':scope > .usa-alert__body')) return;
      const body = document.createElement('div');body.className = 'usa-alert__body';
      const text = document.createElement('div');text.className = 'usa-alert__text';
      text.append(...node.childNodes);body.append(text);node.append(body);
    });
  }
  function ideaCards(root) {
    root.querySelectorAll('.board-idea-card:not(.usa-card)').forEach(card => {
      card.classList.add('usa-card');
      card.parentElement.classList.add('usa-card-group');
      const container=document.createElement('div');container.className='usa-card__container';
      const header=document.createElement('div');header.className='usa-card__header';
      const body=document.createElement('div');body.className='usa-card__body';
      const footer=document.createElement('div');footer.className='usa-card__footer';
      const title=card.querySelector('h3');title.classList.add('usa-card__heading');
      const position=card.querySelector('.board-position');if(position)header.append(position);
      header.append(title);
      const meta=card.querySelector('.record-meta');if(meta)body.append(meta);
      const content=card.querySelector('.board-idea-content');if(content)body.append(content);
      const actions=card.querySelector('.record-actions');if(actions)footer.append(actions);
      const history=card.querySelector('details,.usa-accordion');if(history)body.append(history);
      container.append(header,body,footer);card.replaceChildren(container);
    });
  }
  function enhance(root=document) {
    const focused=document.activeElement;
    ideaCards(root);checkboxes(root);forms(root);alerts(root);accordions(root);
    root.querySelectorAll('button.text-button').forEach(button=>button.classList.add('usa-button','usa-button--unstyled'));
    root.querySelectorAll('button.board-move').forEach(button=>button.classList.add('usa-button','usa-button--outline'));
    window.HubUSWDS?.fileInput.init(root);
    root.querySelectorAll('input.usa-file-input__input').forEach(input=>{
      const label=input.labels?.[0];if(label){label.id ||= unique('hub-file-label');input.setAttribute('aria-labelledby',label.id);}
      const instructions=input.closest('.usa-file-input')?.querySelector('.usa-file-input__instructions');
      if(instructions){instructions.id ||= unique('hub-file-instructions');describe(input,instructions.id);}
    });
    if(focused&&focused!==document.body&&focused!==document.documentElement&&focused.isConnected&&!focused.closest('[hidden]')&&document.activeElement!==focused)focused.focus({preventScroll:true});
  }
  function reveal(target) {
    for(let parent=target?.parentElement;parent;parent=parent.parentElement){
      if(parent.tagName==='DETAILS')parent.open=true;
      if(parent.classList.contains('usa-accordion__content')){
        const button=parent.parentElement.querySelector(':scope > .usa-accordion__heading > .usa-accordion__button');
        if(button)window.HubUSWDS?.accordion.show(button);
      }
    }
  }
  function validate(input) {
    if(!input.id||!input.validity)return;
    const id=`${input.id}-validation-error`;
    let error=document.getElementById(id);
    const invalid=!input.validity.valid;
    input.classList.toggle('usa-input--error',invalid);
    input.closest('.usa-form-group')?.classList.toggle('usa-form-group--error',invalid);
    if(invalid){
      input.setAttribute('aria-invalid','true');
      if(!error){error=document.createElement('span');error.id=id;error.className='usa-error-message';input.before(error);}
      error.textContent=input.validationMessage;describe(input,id);
    }else{
      input.removeAttribute('aria-invalid');error?.remove();
      const ids=(input.getAttribute('aria-describedby')||'').split(/\s+/).filter(value=>value&&value!==id);
      ids.length?input.setAttribute('aria-describedby',ids.join(' ')):input.removeAttribute('aria-describedby');
    }
  }
  const queuedForms=new WeakSet();
  function validationSummary(form,focus=false){
    if(!form)return;
    const invalid=Array.from(form.elements).filter(input=>input.willValidate&&!input.validity.valid&&input.id);
    let summary=form.querySelector(':scope > .hub-validation-summary');
    if(!invalid.length){summary?.remove();return;}
    if(!summary){summary=document.createElement('div');summary.className='hub-validation-summary usa-alert usa-alert--error';summary.tabIndex=-1;summary.setAttribute('role','alert');form.prepend(summary);}
    const body=document.createElement('div');body.className='usa-alert__body';
    const title=document.createElement('p');title.className='usa-alert__heading';title.textContent='Check the following fields';
    const list=document.createElement('ul');list.className='usa-list';
    for(const input of invalid){const item=document.createElement('li');const link=document.createElement('a');link.href='#'+input.id;link.textContent=(input.labels?.[0]?.textContent?.trim()||input.name||input.id)+': '+input.validationMessage;link.addEventListener('click',event=>{event.preventDefault();reveal(input);input.focus();});item.append(link);list.append(item);}
    body.append(title,list);summary.replaceChildren(body);if(focus)summary.focus();
  }
  document.addEventListener('invalid',event=>{event.preventDefault();validate(event.target);const form=event.target.form;if(form&&!queuedForms.has(form)){queuedForms.add(form);queueMicrotask(()=>{queuedForms.delete(form);if(form.isConnected)validationSummary(form,true);});}},true);
  document.addEventListener('input',event=>{if(event.target.hasAttribute('aria-invalid')){validate(event.target);validationSummary(event.target.form);}},true);
  new MutationObserver(records=>{
    records.forEach(record=>record.removedNodes.forEach(node=>{
      if(node.nodeType!==1||node.isConnected)return;
      const inputs=[...(node.matches('input.usa-file-input__input')?[node]:[]),...node.querySelectorAll('input.usa-file-input__input')];
      inputs.forEach(input=>{
        const wrapper=input.parentElement?.parentElement;
        if(!wrapper?.classList.contains('usa-file-input'))return;
        // USWDS teardown expects a parent for its wrapper. A detached host gives
        // removed trees that structure without reintroducing any private UI.
        const detachedHost=!wrapper.parentElement?document.createElement('div'):null;
        if(detachedHost)detachedHost.append(wrapper);
        window.HubUSWDS?.fileInput.off(input);
        detachedHost?.replaceChildren();
      });
    }));
    enhance();
  }).observe(document.documentElement,{childList:true,subtree:true});
  window.HubComponents={enhance,reveal};
  enhance();
})();
