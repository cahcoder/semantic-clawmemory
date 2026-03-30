#!/usr/bin/env node

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

console.log('Setting up agents-memory...');

// Find Python and pip with absolute paths
let pythonCmd = '/usr/bin/python3';
let pipCmd = '/usr/bin/pip3';

try {
  execSync(`${pythonCmd} --version`, { stdio: 'pipe' });
} catch (e) {
  // Try python
  pythonCmd = 'python3';
  try {
    execSync(`${pythonCmd} --version`, { stdio: 'pipe' });
  } catch (e2) {
    console.error('Python 3 not found. Please install Python 3.8+');
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
    console.error('pip not found. Please install pip');
    process.exit(1);
  }
}

// Install Python dependencies - package name → import name mapping
const deps = [
  { pkg: 'chromadb',          imp: 'chromadb' },
  { pkg: 'sentence-transformers', imp: 'sentence_transformers' },
  { pkg: 'python-dateutil',   imp: 'dateutil' },
  { pkg: 'pyyaml',            imp: 'yaml' }
];

console.log('Installing Python dependencies...');

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
      // Verify actually installed - check if importable
      const importName = dep.imp;
      try {
        execSync(`${pythonCmd} -c "import ${importName}"`, { stdio: 'pipe' });
      } catch (e2) {
        continue; // not really installed, try next flags option
      }
      installed = true;
      break;
    } catch (e) {
      // Try next option
    }
  }

  if (installed) {
    console.log('✅');
  } else {
    console.log('❌');
    console.error(`  Failed to install ${dep.pkg}`);
    process.exit(1);
  }
}

// Create memory directory
const memDir = path.join(process.env.HOME || os.homedir(), '.memory', 'chroma');
fs.mkdirSync(memDir, { recursive: true });
console.log(`Memory directory: ${memDir}`);

console.log('Done! Run: agents-memory --help');
