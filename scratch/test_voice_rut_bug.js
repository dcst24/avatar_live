const _currentAccounts = [
    {
        id_cuenta: "CTA-101",
        rut_titular: "18.765.432-1",
        nombre_titular: "Juan Pérez",
        categoria: "luz",
        empresa_id: "enel",
        empresa_nombre: "Enel Distribución",
        monto: 28990
    },
    {
        id_cuenta: "CTA-102",
        rut_titular: "18.765.432-1",
        nombre_titular: "Juan Pérez",
        categoria: "agua",
        empresa_id: "aguas_andinas",
        empresa_nombre: "Aguas Andinas",
        monto: 14500
    }
];

function hasCompleteRut(text) {
    if (!text) return false;
    return /(?:(?:[1-9]\d?\.?\d{3}\.?\d{3}|[1-9]\d{6,7})[-–—][0-9kK]|\b\d{7,8}[0-9kK]\b)/i.test(text);
}

function normalizeUserInput(text) {
    return text.trim();
}

function selectAccountByVoice_IMPROVED(voiceText) {
    if (!_currentAccounts || _currentAccounts.length === 0) return null;
    if (hasCompleteRut(voiceText) || /\b\d{6,}\b/.test(voiceText)) {
        // Si el texto contiene un RUT o identificador largo, NO interpretarlo como selección por número
        return null;
    }
    const norm = normalizeUserInput(voiceText).toLowerCase();

    // 1. Detección prioritaria por nombre de empresa (ej: "enel", "chilectra", "aguas andinas", "vtr", "cge")
    for (let i = 0; i < _currentAccounts.length; i++) {
        const acc = _currentAccounts[i];
        const empName = (acc.empresa_nombre || '').toLowerCase();
        const empId = (acc.empresa_id || '').toLowerCase();
        if (norm.includes(empName) || (empId && norm.includes(empId)) || (empId === 'enel' && norm.includes('chilectra'))) {
            return { matched: 'empresa', targetIdx: i, acc: acc.empresa_nombre, categoria: acc.categoria };
        }
    }

    // 2. Detección prioritaria por categoría (ej: "la luz", "el agua", "el gas", "el tag", "internet")
    for (let i = 0; i < _currentAccounts.length; i++) {
        const acc = _currentAccounts[i];
        const cat = (acc.categoria || '').toLowerCase();
        if (cat && norm.includes(cat)) {
            return { matched: 'categoria', targetIdx: i, acc: acc.empresa_nombre, categoria: acc.categoria };
        }
    }

    // 3. Detección por número (ej: "la 1", "uno", "cuenta 2", "el dos", "opción 2")
    // Solo debe coincidir si es una opción explícita (aislada o precedida por indicador de selección)
    const numWords = {
        '1': 1, 'uno': 1, 'primera': 1, 'primero': 1,
        '2': 2, 'dos': 2, 'segunda': 2, 'segundo': 2,
        '3': 3, 'tres': 3, 'tercera': 3, 'tercero': 3,
        '4': 4, 'cuatro': 4, 'cuarta': 4, 'cuarto': 4,
        '5': 5, 'cinco': 5, 'quinta': 5, 'quinto': 5
    };
    const matchExplicitNum = norm.match(
        /^(?:(?:la|el|opci[oó]n|cuenta|n[uú]mero)\s+)?(1|2|3|4|5|uno|dos|tres|cuatro|cinco|primera|primero|segunda|segundo|tercera|tercero|cuarta|quinta)$/i
    ) || norm.match(
        /\b(?:la\s+|el\s+|opci[oó]n\s+|cuenta\s+|n[uú]mero\s+|fila\s+|quiero\s+la\s+|quiero\s+el\s+|pagar\s+la\s+|pagar\s+el\s+)(1|2|3|4|5|uno|dos|tres|cuatro|cinco|primera|primero|segunda|segundo|tercera|tercero|cuarta|quinta)\b/i
    );

    if (matchExplicitNum) {
        const w = matchExplicitNum[1].toLowerCase();
        const targetIdx = (numWords[w] || parseInt(w, 10)) - 1;
        if (targetIdx >= 0 && targetIdx < _currentAccounts.length) {
            const acc = _currentAccounts[targetIdx];
            return { matched: 'number', targetIdx, acc: acc.empresa_nombre, categoria: acc.categoria };
        }
    }

    return null;
}

const tests = [
    "18.765.432-1 quiero pagar el agua",
    "quiero pagar el agua 18.765.432-1",
    "18765432-1 el agua",
    "18.765.432-1",
    "el agua",
    "quiero pagar el agua",
    "aguas andinas",
    "la luz",
    "la 2",
    "opcion 2",
    "la 1",
    "el uno",
    "uno",
    "dos",
    "tengo 1 duda",
    "pagar"
];

for (const t of tests) {
    console.log(`Input: "${t.padEnd(35)}" ->`, selectAccountByVoice_IMPROVED(t));
}
