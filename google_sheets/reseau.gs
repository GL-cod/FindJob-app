/**
 * Relie l'onglet « 🤝 Réseau » de l'application « Mes candidatures » à ce Google Sheets.
 * Le script crée lui-même deux onglets s'ils n'existent pas :
 *   - « Entreprises » : les entreprises que tu vises ;
 *   - « Contacts »    : les personnes que tu ajoutes toi-même depuis l'application.
 * Tu peux aussi écrire directement dans ces onglets : l'application relit tout.
 *
 * Installation : Extensions > Apps Script, remplace tout le code par ce fichier
 * (l'application te le donne avec ton code secret déjà rempli), puis
 * Déployer > Nouveau déploiement > Application Web
 *   (Exécuter en tant que : moi, Qui a accès : Tout le monde) et colle l'URL dans l'application.
 */
const TOKEN = 'COLLE_ICI_TON_CODE_SECRET';

const CONTACTS = 'Contacts';
const COMPANIES = 'Entreprises';
// en-tête de colonne -> nom du champ dans l'application
const CONTACT_COLS = {
  'ID': 'id', 'Nom': 'nom', 'Poste': 'poste', 'Entreprise': 'entreprise', 'LinkedIn': 'linkedin',
  'Email': 'email', 'Statut': 'statut', 'Contacté le': 'contacte_le', 'Relance le': 'relance_le',
  'Notes': 'notes', 'Message': 'message'
};
const COMPANY_COLS = {
  'Entreprise': 'entreprise', 'Secteur': 'secteur', 'Recherche LinkedIn': 'recherche',
  'Priorité': 'priorite', 'Notes': 'notes'
};

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function key_(s) {
  return String(s || '').trim().toLowerCase();
}

// Onglet `name`, créé avec ses en-têtes s'il n'existe pas ; colonnes manquantes ajoutées à droite.
function tab_(name, cols) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  const created = !sh;
  if (!sh) sh = ss.insertSheet(name);
  const headers = Object.keys(cols);
  const lastCol = Math.max(sh.getLastColumn(), 1);
  const current = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(function (h) { return String(h).trim(); });
  const missing = headers.filter(function (h) { return current.indexOf(h) === -1; });
  if (missing.length) {
    const start = current.filter(String).length ? current.filter(String).length + 1 : 1;
    sh.getRange(1, start, 1, missing.length).setValues([missing]);
  }
  if (created || missing.length) {
    const width = sh.getLastColumn();
    sh.getRange(1, 1, 1, width).setFontWeight('bold').setBackground('#1f3864').setFontColor('#ffffff');
    sh.setFrozenRows(1);
    if (name === CONTACTS) colors_(sh);
  }
  return sh;
}

function colors_(sh) {
  const col = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].indexOf('Statut') + 1;
  if (col < 1) return;
  const letter = String.fromCharCode(64 + col);
  const range = sh.getRange(2, 1, Math.max(sh.getMaxRows() - 1, 1), sh.getLastColumn());
  const rule = function (value, bg, fg) {
    return SpreadsheetApp.newConditionalFormatRule().whenFormulaSatisfied('=$' + letter + '2="' + value + '"')
      .setBackground(bg).setFontColor(fg).setRanges([range]).build();
  };
  sh.setConditionalFormatRules([
    rule('Contacté', '#fff2cc', '#6b5200'),
    rule('Relancé', '#fce5cd', '#7a3e00'),
    rule('A répondu', '#d9ead3', '#1e5631'),
    rule('Entretien', '#b6d7a8', '#123d1f'),
    rule('Pas de réponse', '#eeeeee', '#666666')
  ]);
}

function headerIndex_(sh) {
  const h = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  const idx = {};
  h.forEach(function (name, i) { idx[String(name).trim()] = i; });
  return idx;
}

function read_(sh, cols) {
  const values = sh.getDataRange().getValues();
  const idx = headerIndex_(sh);
  const tz = Session.getScriptTimeZone();
  const fmt = function (v) {
    return (v instanceof Date) ? Utilities.formatDate(v, tz, 'dd/MM/yyyy') : String(v === null ? '' : v).trim();
  };
  const rows = [];
  for (let i = 1; i < values.length; i++) {
    const o = { row: i + 1 };
    let empty = true;
    Object.keys(cols).forEach(function (h) {
      const v = idx[h] === undefined ? '' : fmt(values[i][idx[h]]);
      if (v) empty = false;
      o[cols[h]] = v;
    });
    if (!empty) rows.push(o);
  }
  return rows;
}

// Écrit les champs `fields` (noms côté application) dans la ligne `row`
function write_(sh, cols, row, fields) {
  const idx = headerIndex_(sh);
  Object.keys(cols).forEach(function (h) {
    const k = cols[h];
    if (fields[k] !== undefined && fields[k] !== null && idx[h] !== undefined) {
      sh.getRange(row, idx[h] + 1).setNumberFormat('@').setValue(String(fields[k]));
    }
  });
}

function findRow_(sh, header, value) {
  const idx = headerIndex_(sh);
  if (idx[header] === undefined) return -1;
  const values = sh.getDataRange().getValues();
  for (let i = 1; i < values.length; i++) {
    if (key_(values[i][idx[header]]) === key_(value)) return i + 1;
  }
  return -1;
}

const VERSION = 2;

// Les autres onglets du fichier (tes données d'avant), bruts, pour les importer depuis l'application
function otherTabs_() {
  const tz = Session.getScriptTimeZone();
  return SpreadsheetApp.getActiveSpreadsheet().getSheets()
    .filter(function (sh) { return [CONTACTS, COMPANIES].indexOf(sh.getName()) === -1 && sh.getLastRow() > 0; })
    .map(function (sh) {
      const values = sh.getDataRange().getValues().map(function (r) {
        return r.map(function (v) {
          return (v instanceof Date) ? Utilities.formatDate(v, tz, 'dd/MM/yyyy') : String(v === null ? '' : v).trim();
        });
      });
      return { name: sh.getName(), values: values.slice(0, 2000) };
    });
}

// GET ?token=... : tout le réseau ; &tabs=1 : en plus, le contenu des autres onglets
function doGet(e) {
  if (!e || !e.parameter || e.parameter.token !== TOKEN) return json_({ ok: false, error: 'token' });
  const contacts = tab_(CONTACTS, CONTACT_COLS);
  const companies = tab_(COMPANIES, COMPANY_COLS);
  const out = {
    ok: true, version: VERSION, sheet_url: SpreadsheetApp.getActiveSpreadsheet().getUrl(),
    contacts: read_(contacts, CONTACT_COLS), companies: read_(companies, COMPANY_COLS)
  };
  if (e.parameter.tabs) out.tabs = otherTabs_();
  return json_(out);
}

// POST {token, action, ...}
//   add_contact {fields}            -> {id}
//   update_contact {id, fields}
//   delete_contact {id}
//   add_companies {items: [fields]}  (les entreprises déjà présentes sont ignorées)
//   update_company {name, fields}
//   delete_company {name}
function doPost(e) {
  const data = JSON.parse(e.postData.contents);
  if (data.token !== TOKEN) return json_({ ok: false, error: 'token' });
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const contacts = tab_(CONTACTS, CONTACT_COLS);
    const companies = tab_(COMPANIES, COMPANY_COLS);
    const a = data.action;
    if (a === 'add_contact') {
      let maxId = 0;
      read_(contacts, CONTACT_COLS).forEach(function (c) { maxId = Math.max(maxId, Number(c.id) || 0); });
      const row = contacts.getLastRow() + 1;
      const fields = Object.assign({ statut: 'À contacter' }, data.fields || {}, { id: maxId + 1 });
      write_(contacts, CONTACT_COLS, row, fields);
      return json_({ ok: true, id: maxId + 1, row: row });
    }
    if (a === 'add_contacts') {
      let maxId = 0;
      const seen = {};
      read_(contacts, CONTACT_COLS).forEach(function (c) {
        maxId = Math.max(maxId, Number(c.id) || 0);
        seen[key_(c.nom) + '|' + key_(c.entreprise)] = true;
      });
      const rows = [];
      (data.items || []).forEach(function (f) {
        const k = key_(f.nom) + '|' + key_(f.entreprise);
        if (!f.nom || seen[k]) return;
        seen[k] = true;
        maxId++;
        rows.push(Object.assign({ statut: 'À contacter' }, f, { id: maxId }));
      });
      if (rows.length) {
        const idx = headerIndex_(contacts);
        const width = contacts.getLastColumn();
        const values = rows.map(function (f) {
          const line = new Array(width).fill('');
          Object.keys(CONTACT_COLS).forEach(function (h) {
            const v = f[CONTACT_COLS[h]];
            if (idx[h] !== undefined && v !== undefined && v !== null) line[idx[h]] = String(v);
          });
          return line;
        });
        const range = contacts.getRange(contacts.getLastRow() + 1, 1, values.length, width);
        range.setNumberFormat('@').setValues(values);
      }
      return json_({ ok: true, added: rows.length });
    }
    if (a === 'update_contact' || a === 'delete_contact') {
      const row = findRow_(contacts, 'ID', data.id);
      if (row < 0) return json_({ ok: false, error: 'contact_not_found' });
      if (a === 'delete_contact') contacts.deleteRow(row);
      else write_(contacts, CONTACT_COLS, row, data.fields || {});
      return json_({ ok: true, row: row });
    }
    if (a === 'add_companies') {
      let added = 0;
      (data.items || []).forEach(function (f) {
        if (!f.entreprise || findRow_(companies, 'Entreprise', f.entreprise) > 0) return;
        write_(companies, COMPANY_COLS, companies.getLastRow() + 1, f);
        added++;
      });
      return json_({ ok: true, added: added });
    }
    if (a === 'update_company' || a === 'delete_company') {
      const row = findRow_(companies, 'Entreprise', data.name);
      if (row < 0) return json_({ ok: false, error: 'company_not_found' });
      if (a === 'delete_company') companies.deleteRow(row);
      else write_(companies, COMPANY_COLS, row, data.fields || {});
      return json_({ ok: true, row: row });
    }
    return json_({ ok: false, error: 'unknown_action' });
  } finally {
    lock.releaseLock();
  }
}
