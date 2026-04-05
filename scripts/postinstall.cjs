#!/usr/bin/env node

/**
 * postinstall.js - Post-install hook for agents-memory npm package
 * 
 * Handles:
 * 1. Python dependencies installation
 * 2. Seamless installation (daemon + OpenClaw plugin)
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = process.env.HOME || os.homedir();

console.log('\n╔═══════════════════════════════════════════════════════════╗');
console.log('║              agents-memory postinstall                    ║');
console.log('╚═══════════════════════════════════════════════════════════╝\n');

// ═══════════════════════════════════════════════════════════════════
// SECTION 1: Python Dependencies
// ═══════════════════════════════════════════════════════════════════

let pythonCmd = '/usr/bin/python3';
let pipCmd = '/usr/bin/pip3';

try {
  execSync(`${pythonCmd} --version`, { stdio: 'pipe' });
} catch (e) {
  pythonCmd = 'python3';
  try {
    execSync(`${pythonCmd} --version`, { stdio: 'pipe' });
  } catch (e2) {
    console.error('❌ Python 3 not found. Please install Python 3.8+');
    process.exit(1);
  }
}

try {
  execSync(`${pipCmd} --version`, { stdio: 'pipe' });
} catch (e) {
  pipCmd = pythonCmd.replace('python3', 'pip3');
  try {
    execSync(`${pipCmd} --version`, { stdio: 'pipe' });
  } catch (e2) {
    console.error('❌ pip not found. Please install pip');
    process.exit(1);
  }
}

const deps = [
  { pkg: 'chromadb',              imp: 'chromadb' },
  { pkg: 'sentence-transformers', imp: 'sentence_transformers' },
  { pkg: 'python-dateutil',       imp: 'dateutil' },
  { pkg: 'pyyaml',                imp: 'yaml' }
];

console.log('[1/2] Installing Python dependencies...\n');

let allInstalled = true;
for (const dep of deps) {
  process.stdout.write(`  ${dep.pkg}... `);
  let installed = false;
  const flagsList = ['--break-system-packages', '--user', ''];

  for (const flags of flagsList) {
    try {
      const cmd = `${pipCmd} install ${flags} ${dep.pkg} 2>&1`.trim();
      execSync(cmd, {
        stdio: 'pipe',
        env: { ...process.env, PIP_DISABLE_PIP_VERSION_CHECK: '1' }
      });
      try {
        execSync(`${pythonCmd} -c "import ${dep.imp}"`, { stdio: 'pipe' });
      } catch (e2) {
        continue;
      }
      installed = true;
      break;
    } catch (e) {}
  }

  if (installed) {
    console.log('✅');
  } else {
    console.log('❌');
    allInstalled = false;
  }
}

if (!allInstalled) {
  console.error('\n❌ Failed to install some Python dependencies');
  process.exit(1);
}

// Create memory directory
const memDir = path.join(HOME, '.memory', 'chroma');
fs.mkdirSync(memDir, { recursive: true });
console.log(`\n  Memory directory: ${memDir}`);

// ═══════════════════════════════════════════════════════════════════
// SECTION 2: Seamless Installation (Daemon + OpenClaw Plugin)
// ═══════════════════════════════════════════════════════════════════

console.log('\n[2/2] Running seamless installer...\n');

const pkgRoot = path.dirname(path.dirname(path.resolve(__filename)));
const installScript = path.join(pkgRoot, 'scripts', 'install-seamless.cjs');

if (fs.existsSync(installScript)) {
  try {
    execSync(`node "${installScript}"`, {
      stdio: 'inherit',
      cwd: pkgRoot,
      env: { ...process.env, npm_config_ignore_scripts: '' }
    });
  } catch (e) {
    console.log('\n⚠️  Seamless installer had issues, but core setup is complete.');
    console.log('   You can run the installer manually:');
    console.log('   node scripts/install-seamless.cjs');
  }
} else {
  console.log('  ℹ️  install-seamless.cjs not found, skipping daemon/plugin setup');
}

console.log('\n═══════════════════════════════════════════════════════════\n');
