/**
 * Relie l'application « Mes candidatures » à ce Google Sheets.
 * Colonnes attendues (ligne 1 = en-têtes) :
 *   A N | B Poste | C Nom de l'entreprise | D Lien | E Date | F Retour | G Commentaire
 *
 * Installation : Extensions > Apps Script, remplace tout le code par ce fichier,
 * mets ton code secret dans TOKEN (le même que SHEETS_TOKEN dans le fichier .env),
 * puis Déployer > Nouveau déploiement > Application Web
 *   (Exécuter en tant que : moi, Qui a accès : Tout le monde) et copie l'URL.
 */
const TOKEN = 'COLLE_ICI_TON_CODE_SECRET';
// Onglet à utiliser : le nombre après "gid=" dans l'adresse de l'onglet (0 = premier onglet)
const SHEET_GID = 0;

function sheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheets().find(function (s) { return s.getSheetId() === SHEET_GID; });
  if (!sh) throw new Error('Onglet gid=' + SHEET_GID + ' introuvable');
  // Sheets tout neuf : écrit les en-têtes de la ligne 1
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, 7).setValues([['N', 'Poste', "Nom de l'entreprise", 'Lien', 'Date', 'Retour', 'Commentaire']])
      .setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function norm_(url) {
  return String(url || '').trim().replace(/[?#].*$/, '').replace(/\/+$/, '').toLowerCase();
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// GET ?token=... : toutes les candidatures, pour les afficher dans l'application
// et repérer les offres où tu as déjà postulé
function doGet(e) {
  if (!e || !e.parameter || e.parameter.token !== TOKEN) return json_({ ok: false, error: 'token' });
  const sh = sheet_();
  const values = sh.getDataRange().getValues();
  const tz = Session.getScriptTimeZone();
  const fmt = function (v) {
    return (v instanceof Date) ? Utilities.formatDate(v, tz, 'dd/MM/yyyy') : String(v || '').trim();
  };
  const rows = [];
  for (let i = 1; i < values.length; i++) {
    const r = values[i];
    if (String(r[1]).trim() || String(r[3]).trim()) {
      rows.push({
        row: i + 1, n: fmt(r[0]), poste: fmt(r[1]), entreprise: fmt(r[2]),
        lien: norm_(r[3]), url: String(r[3] || '').trim(),
        date: fmt(r[4]), retour: fmt(r[5]), commentaire: fmt(r[6])
      });
    }
  }
  const url = SpreadsheetApp.getActiveSpreadsheet().getUrl() + '#gid=' + sh.getSheetId();
  return json_({ ok: true, version: 3, sheet_url: url, rows: rows });
}

// POST {token, lien, poste, entreprise, date, retour, commentaire} : ajoute ou met à jour la ligne
// POST {token, row, expect_poste, fields: {poste, entreprise, url, date, retour, commentaire}} :
//   modifie la ligne numéro `row` (depuis l'application), si son poste est toujours `expect_poste`
function doPost(e) {
  const data = JSON.parse(e.postData.contents);
  if (data.token !== TOKEN) return json_({ ok: false, error: 'token' });
  const sh = sheet_();
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    if (data.row) {
      const r = Number(data.row);
      if (!(r >= 2) || r > sh.getLastRow()) return json_({ ok: false, error: 'row_not_found' });
      const current = String(sh.getRange(r, 2).getValue()).trim();
      if (data.expect_poste !== undefined && current !== String(data.expect_poste).trim()) {
        return json_({ ok: false, error: 'row_changed' });
      }
      const cols = { poste: 2, entreprise: 3, url: 4, date: 5, retour: 6, commentaire: 7 };
      const f = data.fields || {};
      Object.keys(cols).forEach(function (k) {
        if (f[k] !== undefined && f[k] !== null) sh.getRange(r, cols[k]).setValue(f[k]);
      });
      return json_({ ok: true, updated: true, row: r });
    }
    const values = sh.getDataRange().getValues();
    const link = norm_(data.lien);
    let row = -1, last = 1, maxN = 0;
    for (let i = 1; i < values.length; i++) {
      if (link && norm_(values[i][3]) === link) row = i + 1;
      if (String(values[i][1]).trim()) last = i + 1;
      const n = Number(values[i][0]);
      if (!isNaN(n) && n > maxN) maxN = n;
    }
    if (row === -1) {
      if (!data.retour) return json_({ ok: false, error: 'not_found' });  // simple mise à jour d'une ligne absente
      row = last + 1;
      sh.getRange(row, 1, 1, 7).setValues([[maxN + 1, data.poste || '', data.entreprise || '', data.lien || '',
        data.date || '', data.retour || 'En attente', data.commentaire || '']]);
      return json_({ ok: true, created: true, row: row });
    }
    if (data.retour) sh.getRange(row, 6).setValue(data.retour);
    if (data.commentaire !== undefined && data.commentaire !== null) sh.getRange(row, 7).setValue(data.commentaire);
    return json_({ ok: true, created: false, row: row });
  } finally {
    lock.releaseLock();
  }
}

/**
 * Couleurs du suivi : à lancer UNE fois depuis l'éditeur (choisir « miseEnCouleur » puis Exécuter).
 * - ligne verte si Retour = Positif, rouge si Negatif, jaune si En attente ;
 * - en-tête foncé, figé en haut ;
 * - nettoie les espaces en trop dans la colonne Retour (« En attente » au lieu de « En attente »).
 * Les nouvelles lignes ajoutées par l'application prennent automatiquement les couleurs.
 */
function miseEnCouleur() {
  const sh = sheet_();
  const lastRow = Math.max(sh.getMaxRows(), 2);

  // 1. Retour sans espaces superflus (pour que les règles reconnaissent les valeurs)
  const retour = sh.getRange(2, 6, lastRow - 1, 1);
  retour.setValues(retour.getValues().map(function (r) { return [String(r[0]).trim()]; }));

  // 2. Règles de couleur sur toute la largeur du tableau (A:G), en gardant les autres règles existantes
  const range = sh.getRange(2, 1, lastRow - 1, 7);
  const a1 = range.getA1Notation();
  const keep = sh.getConditionalFormatRules().filter(function (rule) {
    return !rule.getRanges().some(function (g) { return g.getA1Notation() === a1; });
  });
  const rule = function (formula, bg, fg) {
    return SpreadsheetApp.newConditionalFormatRule().whenFormulaSatisfied(formula)
      .setBackground(bg).setFontColor(fg).setRanges([range]).build();
  };
  keep.push(
    rule('=$F2="Positif"', '#d9ead3', '#1e5631'),
    rule('=$F2="Negatif"', '#f4cccc', '#7f1d1d'),
    rule('=$F2="Négatif"', '#f4cccc', '#7f1d1d'),
    rule('=$F2="En attente"', '#fff2cc', '#6b5200')
  );
  sh.setConditionalFormatRules(keep);

  // 3. En-tête lisible et figé
  sh.getRange(1, 1, 1, 7).setFontWeight('bold').setBackground('#1f3864').setFontColor('#ffffff');
  sh.setFrozenRows(1);
}
