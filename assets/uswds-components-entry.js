// Bundle the maintained USWDS modules themselves; no network runtime dependency.
const accordion = require('@uswds/uswds/js/usa-accordion');
const fileInput = require('@uswds/uswds/js/usa-file-input');
const navigation = require('@uswds/uswds/js/usa-header');
const button = require('@uswds/uswds/js/usa-button');
const skipnav = require('@uswds/uswds/js/usa-skipnav');
window.HubUSWDS = {accordion, fileInput, navigation, button, skipnav};
window.uswdsPresent = true;
const start = () => {
  navigation.on(document.body);
  button.on(document.body);
  skipnav.on(document.body);
  accordion.on(document.body);
};
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
else start();
