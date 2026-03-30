#!/usr/bin/env node

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

console.log('Setting up semantic-clawmemory...');

// Check Python
try {
  execSync('python3 --version', { stdio: 'pipe' });
} catch (e) {
  console.error('Python 3 not found. Please install Python 3.8+');
  process.exit(1);
}

// Check pip
try {
  execSync('pip3 --version', { stdio: 'pipe' });
} catch (e) {
  console.log('pip3 not found, trying pip...');
  try {
    execSync('pip --version', { stdio: 'pipe' });
  } catch (e2) {
    console.error('pip not found. Please install pip');
    process.exit(1);
  }
}

// Install Python dependencies
const deps = [
  'chromadb',
  'sentence-transformers',
  'python-dateutil',
  'pyyaml'
];

console.log('Installing Python dependencies...');

for (const dep of deps) {
  try {
    execSync(`pip3 install ${dep}`, { stdio: 'inherit' });
  } catch (e) {
    console.error(`Failed to install ${dep}`);
    process.exit(1);
  }
}

// Create memory directory
const memDir = path.join(process.env.HOME || os.homedir(), '.memory', 'chroma');
fs.mkdirSync(memDir, { recursive: true });
console.log(`Memory directory: ${memDir}`);

console.log('Done! Run: semantic-clawmemory --help');
