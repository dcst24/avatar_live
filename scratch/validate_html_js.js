const fs = require('fs');

const content = fs.readFileSync('web/avatar-experimental.html', 'utf-8');

// Extract all script tags that have inline JavaScript (not external src)
const scriptRegex = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
let match;
let count = 0;
while ((match = scriptRegex.exec(content)) !== null) {
    count++;
    const js = match[1];
    try {
        new Function(js);
        console.log(`Script #${count} syntax is VALID (${js.length} chars)`);
    } catch (e) {
        console.error(`Script #${count} syntax ERROR:`, e.message);
        // Find line number
        const lines = js.split('\n');
        console.error(`Snippet around error:`);
        process.exit(1);
    }
}
console.log(`All ${count} inline scripts validated successfully!`);
