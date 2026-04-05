#!/usr/bin/env node
/**
 * uninstall.js - Clean up agents-memory from system
 * 
 * Usage: node uninstall.js
 * 
 * WARNING: This removes ALL agents-memory data including memory entries!
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const HOME = process.env.HOME || require('os').homedir();
const MEMORY_DIR = path.join(HOME, '.memory', 'agents-memory');
const OPENCLAW_HOOKS_DIR = path.join(HOME, '.openclaw', 'hooks', 'agents-memory');
const OPENCLAW_CONFIG = path.join(HOME, '.openclaw', 'openclaw.json');

function confirm(msg) {
    process.stdout.write(msg + ' [y/N] ');
    const answer = process.stdin.read();
    return answer && answer.trim().toLowerCase() === 'y';
}

function deleteDirectory(dir) {
    if (fs.existsSync(dir)) {
        console.log(`  🗑️  Deleting: ${dir}`);
        fs.rmSync(dir, { recursive: true, force: true });
        return true;
    }
    console.log(`  ✅ Already gone: ${dir}`);
    return false;
}

console.log('╔═══════════════════════════════════════════════════════════╗');
console.log('║         agents-memory UNINSTALLER                      ║');
console.log('╚═══════════════════════════════════════════════════════════╝');
console.log('\nThis will remove:');
console.log('  - Memory data (~/.memory/agents-memory/)');
console.log('  - ChromaDB database (~/.memory/chroma/)');
console.log('  - OpenClaw hooks (~/.openclaw/hooks/agents-memory/)');
console.log('  - Systemd services (agents-memory-daemon, memory-gc, memory-trash)');
console.log('  - NPM package (agents-memory)');
console.log('  - Config entries in openclaw.json');
console.log('');

if (!confirm('⚠️  Are you sure you want to uninstall agents-memory?')) {
    console.log('Cancelled.');
    process.exit(0);
}

// 1. Stop and disable systemd services
console.log('\n[1/6] Stopping systemd services...');
const services = [
    'agents-memory-daemon.service',
    'memory-gc.service',
    'memory-gc.timer',
    'memory-trash.service',
    'memory-trash.timer'
];

for (const svc of services) {
    try {
        execSync(`systemctl --user stop ${svc} 2>/dev/null`, { stdio: 'pipe' });
        execSync(`systemctl --user disable ${svc} 2>/dev/null`, { stdio: 'pipe' });
        console.log(`  ✅ Stopped: ${svc}`);
    } catch (e) {
        console.log(`  ⚠️  Could not stop: ${svc}`);
    }
}

// 2. Delete memory directories
console.log('\n[2/6] Deleting memory directories...');
deleteDirectory(MEMORY_DIR);
deleteDirectory(path.join(HOME, '.memory', 'chroma'));

// 3. Delete OpenClaw hooks
console.log('\n[3/6] Deleting OpenClaw hooks...');
deleteDirectory(OPENCLAW_HOOKS_DIR);

// 4. Clean systemd unit files
console.log('\n[4/6] Cleaning systemd unit files...');
const systemdDir = path.join(HOME, '.config', 'systemd', 'user');
for (const svc of services) {
    const unitFile = path.join(systemdDir, svc);
    if (fs.existsSync(unitFile)) {
        fs.unlinkSync(unitFile);
        console.log(`  🗑️  Deleted: ${unitFile}`);
    }
}

// 5. Remove NPM package
console.log('\n[5/6] Removing NPM package...');
try {
    execSync('npm rm -g agents-memory', { stdio: 'pipe' });
    console.log('  ✅ NPM package removed');
} catch (e) {
    console.log('  ⚠️  NPM package not found or already removed');
}

// 6. Update openclaw.json
console.log('\n[6/6] Updating openclaw.json...');
if (fs.existsSync(OPENCLAW_CONFIG)) {
    try {
        const config = JSON.parse(fs.readFileSync(OPENCLAW_CONFIG, 'utf8'));
        
        // Remove agents-memory from hooks.internal.entries
        if (config.hooks?.internal?.entries?.['agents-memory']) {
            delete config.hooks.internal.entries['agents-memory'];
            console.log('  ✅ Removed: hooks.internal.entries.agents-memory');
        }
        
        // Remove agents-memory from plugins.entries
        if (config.plugins?.entries?.['agents-memory']) {
            delete config.plugins.entries['agents-memory'];
            console.log('  ✅ Removed: plugins.entries.agents-memory');
        }
        
        // Remove plugins.installs.agents-memory
        if (config.plugins?.installs?.['agents-memory']) {
            delete config.plugins.installs['agents-memory'];
            console.log('  ✅ Removed: plugins.installs.agents-memory');
        }
        
        fs.writeFileSync(OPENCLAW_CONFIG, JSON.stringify(config, null, 2));
        console.log('  ✅ openclaw.json updated');
    } catch (e) {
        console.log(`  ⚠️  Could not update openclaw.json: ${e.message}`);
        console.log('  ℹ️  Manual edit required - remove these entries manually:');
        console.log('     - hooks.internal.entries.agents-memory');
        console.log('     - plugins.entries.agents-memory');
        console.log('     - plugins.installs.agents-memory');
    }
} else {
    console.log('  ⚠️  openclaw.json not found');
}

console.log('\n╔═══════════════════════════════════════════════════════════╗');
console.log('║         UNINSTALL COMPLETE                             ║');
console.log('╚═══════════════════════════════════════════════════════════╝');
console.log('\nTo reinstall fresh:');
console.log('  1. npm install -g /path/to/agents-memory');
console.log('  2. agents-memory init');
console.log('  3. Follow the MANUAL CONFIGURATION instructions');
