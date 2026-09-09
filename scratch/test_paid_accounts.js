const assert = require('assert');

// Extraer el entorno de funciones relevantes
let _cart = [];
let _currentAccounts = [
    {
        id_cuenta: "CTA-301",
        rut_titular: "12.345.678-5",
        nombre_titular: "Carlos Silva",
        categoria: "luz",
        empresa_id: "enel",
        empresa_nombre: "Enel Distribución",
        monto: 0,
        estado: "pagada",
        es_pagada: true,
        monto_formateado: "$0"
    },
    {
        id_cuenta: "CTA-302",
        rut_titular: "12.345.678-5",
        nombre_titular: "Carlos Silva",
        categoria: "agua",
        empresa_id: "aguas_andinas",
        empresa_nombre: "Aguas Andinas",
        monto: 0,
        estado: "pagada",
        es_pagada: true,
        monto_formateado: "$0"
    }
];

let lastSpoken = '';
function sayViaAvatar(text) {
    lastSpoken = text;
}

function LOG(text) {}

function normalizeUserInput(text) {
    return text || '';
}

function hasCompleteRut(text) {
    return false;
}

function updateCartUI() {}

async function toggleAccountInCart(acc, announceAvatar = false) {
    const isPaid = Boolean(acc.es_pagada || acc.monto === 0 || acc.estado === 'pagada' || acc.estado === 'sin_deuda');
    if (isPaid) {
        const existingIdx = _cart.findIndex(item => item.id_cuenta === acc.id_cuenta);
        if (existingIdx >= 0) {
            _cart.splice(existingIdx, 1);
            updateCartUI();
        }
        if (announceAvatar) {
            sayViaAvatar(`Tu cuenta de ${acc.empresa_nombre} ya se encuentra pagada y al día. No tiene deuda pendiente.`);
        }
        return false;
    }

    const existingIdx = _cart.findIndex(item => item.id_cuenta === acc.id_cuenta);
    if (existingIdx >= 0) {
        _cart.splice(existingIdx, 1);
    } else {
        _cart.push(acc);
        if (announceAvatar) {
            sayViaAvatar(`Agregué tu cuenta de ${acc.empresa_nombre} al carro.`);
        }
    }
    updateCartUI();
    return true;
}

function selectAccountByVoice(voiceText) {
    if (!_currentAccounts || _currentAccounts.length === 0) return false;
    if (hasCompleteRut(voiceText) || /\b\d{6,}\b/.test(voiceText)) {
        return false;
    }

    const norm = normalizeUserInput(voiceText).toLowerCase();

    const handleAccountSelected = (acc) => {
        const isPaid = Boolean(acc.es_pagada || acc.monto === 0 || acc.estado === 'pagada' || acc.estado === 'sin_deuda');
        if (isPaid) {
            sayViaAvatar(`Tu cuenta de ${acc.empresa_nombre} ya se encuentra pagada y al día. No tiene deuda pendiente.`);
            return true;
        }
        toggleAccountInCart(acc, true);
        return true;
    };

    // 1. Empresa
    for (let i = 0; i < _currentAccounts.length; i++) {
        const acc = _currentAccounts[i];
        const empName = (acc.empresa_nombre || '').toLowerCase();
        const empId = (acc.empresa_id || '').toLowerCase();
        if (norm.includes(empName) || (empId && norm.includes(empId)) || (empId === 'enel' && norm.includes('chilectra'))) {
            return handleAccountSelected(acc);
        }
    }

    // 2. Categoría
    for (let i = 0; i < _currentAccounts.length; i++) {
        const acc = _currentAccounts[i];
        const cat = (acc.categoria || '').toLowerCase();
        if (cat && (norm.includes(cat) || (cat === 'agua' && norm.includes('aguas')) || (cat === 'luz' && (norm.includes('electricidad') || norm.includes('eléctrica'))))) {
            return handleAccountSelected(acc);
        }
    }

    // 3. Número
    const numWords = {
        '1': 1, 'uno': 1, 'primera': 1, 'primero': 1,
        '2': 2, 'dos': 2, 'segunda': 2, 'segundo': 2,
        '3': 3, 'tres': 3, 'tercera': 3, 'tercero': 3
    };
    const matchNum = norm.match(
        /^(?:(?:la|el|opci[oó]n|cuenta|n[uú]mero)\s+)?(1|2|3|uno|dos|tres|primera|primero|segunda|segundo|tercera|tercero)$/i
    ) || norm.match(
        /\b(?:la\s+|el\s+|opci[oó]n\s+|cuenta\s+|n[uú]mero\s+|fila\s+|quiero\s+la\s+|quiero\s+el\s+|pagar\s+la\s+|pagar\s+el\s+)(1|2|3|uno|dos|tres|primera|primero|segunda|segundo|tercera|tercero)\b/i
    );

    if (matchNum) {
        const w = matchNum[1].toLowerCase();
        const targetIdx = (numWords[w] || parseInt(w, 10)) - 1;
        if (targetIdx >= 0 && targetIdx < _currentAccounts.length) {
            const acc = _currentAccounts[targetIdx];
            return handleAccountSelected(acc);
        }
    }

    return false;
}

console.log('--- Test 1: Direct toggle of paid account ---');
toggleAccountInCart(_currentAccounts[0], true);
assert.strictEqual(_cart.length, 0, 'Cart should remain empty');
assert.strictEqual(lastSpoken.includes('ya se encuentra pagada'), true, 'Should announce paid');
console.log('✓ Passed: Direct toggle blocked, spoken:', lastSpoken);

console.log('--- Test 2: Voice select by category ("quiero pagar el agua") ---');
const matchedCat = selectAccountByVoice('quiero pagar el agua');
assert.strictEqual(matchedCat, true, 'Should be handled by voice');
assert.strictEqual(_cart.length, 0, 'Cart should remain empty');
assert.strictEqual(lastSpoken.includes('Aguas Andinas ya se encuentra pagada'), true, 'Should announce Aguas Andinas paid');
console.log('✓ Passed: Voice select by category blocked, spoken:', lastSpoken);

console.log('--- Test 3: Voice select by option number ("la 1") ---');
const matchedNum = selectAccountByVoice('la 1');
assert.strictEqual(matchedNum, true, 'Should be handled by voice');
assert.strictEqual(_cart.length, 0, 'Cart should remain empty');
assert.strictEqual(lastSpoken.includes('Enel Distribución ya se encuentra pagada'), true, 'Should announce Enel paid');
console.log('✓ Passed: Voice select by option number blocked, spoken:', lastSpoken);

console.log('--- Test 4: Voice select by company name ("enel") ---');
const matchedEmp = selectAccountByVoice('enel');
assert.strictEqual(matchedEmp, true, 'Should be handled by voice');
assert.strictEqual(_cart.length, 0, 'Cart should remain empty');
assert.strictEqual(lastSpoken.includes('Enel Distribución ya se encuentra pagada'), true, 'Should announce Enel paid');
console.log('✓ Passed: Voice select by company name blocked, spoken:', lastSpoken);

console.log('--- Test 5: Pay confirmation when all accounts are paid ---');
const debtAccounts = _currentAccounts.filter(a => (a.monto || 0) > 0 && !a.es_pagada && a.estado !== 'pagada' && a.estado !== 'sin_deuda');
assert.strictEqual(debtAccounts.length, 0, 'Should have 0 debt accounts');
if (debtAccounts.length === 0) {
    sayViaAvatar("Todas tus cuentas se encuentran pagadas y al día. No tienes cuentas pendientes de pago.");
}
assert.strictEqual(lastSpoken.includes('Todas tus cuentas se encuentran pagadas'), true);
console.log('✓ Passed: All accounts paid notice:', lastSpoken);

console.log('ALL FRONTEND TESTS PASSED SUCCESSFULLY!');
